"""
Run Resharper's InspectCode static analysis command line and generate html reports from the xml reports.
InspectCode Docs: https://www.jetbrains.com/help/resharper/InspectCode.html
"""

import argparse
import os
from typing import Optional
from xml.etree.ElementTree import Element as XmlNode
from xml.etree.ElementTree import fromstring as xml_fromstring

from openunrealautomation.environment import UnrealEnvironment
from openunrealautomation.staticanalysis_common import (StaticAnalysisResults,
                                                        StaticAnalysisSeverity)
from openunrealautomation.unrealengine import UnrealEngine
from openunrealautomation.util import (ouu_temp_file, read_text_file,
                                       run_subprocess, strtobool,
                                       which_checked)


def _parse_inspectcode_severity(severity_str: str) -> StaticAnalysisSeverity:
    severity_str = severity_str.lower()
    severity_dict = {
        "error": StaticAnalysisSeverity.ERROR,
        "warning": StaticAnalysisSeverity.WARNING,
        "suggestion": StaticAnalysisSeverity.SUGGESTION,
        "hint": StaticAnalysisSeverity.SUGGESTION,
    }
    if severity_str in severity_dict:
        return severity_dict[severity_str]
    else:
        return StaticAnalysisSeverity.SUGGESTION


def _generate_analysis_results(env: UnrealEnvironment, xml_report_path: str) -> StaticAnalysisResults:
    results = StaticAnalysisResults(env)
    root_category = results.find_or_add_category(
        "inspectCode", "All issues from ReSharper InspectCode", None)

    xml_tree = xml_fromstring(read_text_file(xml_report_path))

    def get_prop(xml_node: XmlNode, prop_name: str) -> str:
        return str(xml_node.get(prop_name))

    for issue_type in xml_tree.findall(".//IssueType"):
        type_id = get_prop(issue_type, "Id")
        type_description = get_prop(issue_type, 'Description').strip()
        severity = _parse_inspectcode_severity(
            get_prop(issue_type, 'Severity'))

        # Rule ID for our tools needs the fully qualified ID including category prefix.
        rule_id = root_category.id + "-" + type_id
        results.find_or_add_rule(
            rule_id, type_description, severity, root_category.id)

        for issue in xml_tree.findall(".//Issue"):
            if get_prop(issue, "TypeId") != type_id:
                continue
            issue_file_path = get_prop(issue, "File")
            message_str = get_prop(issue, "Message")
            line_nr = int(get_prop(issue, "Line"))
            column_nr = 0  # TODO
            symbol_str = ""  # TODO

            results.new_issue(issue_file_path, line_nr,
                              column_nr, symbol_str, message_str, rule_id)

    return results


class InspectCode():
    def __init__(self, env: UnrealEnvironment, output_path: str, inspectcode_exe: Optional[str]) -> None:
        self.env = env
        self.output_path = output_path

        if not inspectcode_exe:
            # TQ2 specific auto-detection of portable inspectcode folder
            tq2_inspectcode_path = f"{self.env.engine_root}/Tools/ReSharperCodeInspect/inspectcode.exe"
            if os.path.exists(tq2_inspectcode_path):
                inspectcode_exe = tq2_inspectcode_path
            else:
                # If the binary is not found, we assume it's on PATH
                inspectcode_exe = "inspectcode.exe"
                which_checked(inspectcode_exe)
        self.inspectcode_exe = inspectcode_exe

    def run(self, may_skip: bool = False) -> None:
        if may_skip and os.path.exists(self.output_path):
            return

        # Include / exclude paths have to be relative to the solution directory,
        # which is either the engine root or the project root itself (which means an empty path)
        sln_relative_project_path = os.path.relpath(
            self.env.project_root, self.env.engine_root) + "\\" if self.env.is_source_engine else ""
        include_paths = [f"{sln_relative_project_path}Source\\**",
                         f"{sln_relative_project_path}Plugins\\**\\Source\\**"]
        includes_str = ";".join(include_paths)
        exclude_paths = ["**\\*.cs",
                         "**\\**.generated.h",
                         "**\\**.gen.cpp"]
        excludes_str = ";".join(exclude_paths)

        # keep turned off for now. we have enough issues as is and times are shorter (I think?)
        solution_wide_analysis = False
        swea_param = "--swea" if solution_wide_analysis else "--no-swea"

        solution_file = self.env.get_engine_solution(
        ) if self.env.is_source_engine else self.env.get_project_solution()

        command_line = [self.inspectcode_exe,
                        "--build",
                        f'--project="{self.env.project_name}"',
                        # This target name is required or otherwise the ENTIRE solution is built. May need to be adjusted for non-game targets or samples, etc that end up in other dirs
                        f'--target="Games\\{self.env.project_name}"',
                        swea_param,
                        f'--properties="Configuration=Development Editor;Platform=Win64"',
                        f'--include="{includes_str}"',
                        f'--exclude="{excludes_str}"',
                        f'-o="{self.output_path}"',
                        solution_file
                        ]
        exit_code = run_subprocess(command_line, print_args=True)
        if not exit_code == 0:
            raise Exception(f"Invalid exit code {exit_code} from InspectCode")

    def load(self) -> StaticAnalysisResults:
        # TODO refactor
        return _generate_analysis_results(self.env, self.output_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--include", default="")
    parser.add_argument("--exclude", default="")
    parser.add_argument("--may-skip", default="true")
    args = parser.parse_args()

    may_skip = strtobool(args.may_skip)

    def array_arg(parm_str: str):
        result = str.split(parm_str, ";")
        if '' in result and len(result) == 1:
            return []
        return result

    include_paths = array_arg(args.include)
    exclude_paths = array_arg(args.exclude)

    print("may skip:", may_skip)
    print("include:", include_paths)
    print("exclude:", exclude_paths)

    ue = UnrealEngine.create_from_parent_tree(os.getcwd())

    inspect = InspectCode(ue.environment, ouu_temp_file(
        "ResharperReport.xml"), None)
    inspect.run(may_skip=may_skip)
    results = inspect.load()
    results.html_report(include_paths=include_paths,
                        exclude_paths=exclude_paths, report_path=ouu_temp_file("ResharperReport.html"))
