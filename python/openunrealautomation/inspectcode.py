"""
Run Resharper's InspectCode static analysis command line and generate html reports from the xml reports.
InspectCode Docs: https://www.jetbrains.com/help/resharper/InspectCode.html
"""

import argparse
import os
import re
from typing import Dict, Generator, List
from xml.etree.ElementTree import Element as XmlNode
from xml.etree.ElementTree import fromstring as xml_fromstring

from openunrealautomation.environment import UnrealEnvironment
from openunrealautomation.staticanalysis_common import (StaticAnalysisResults,
                                                        StaticAnalysisSeverity,
                                                        static_analysis_html_report)
from openunrealautomation.unrealengine import UnrealEngine
from openunrealautomation.util import (read_text_file, run_subprocess,
                                       which_checked, write_text_file)


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


def _generate_analysis_results(xml_report_path: str) -> StaticAnalysisResults:
    results = StaticAnalysisResults()
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


def _run_inspectcode(env: UnrealEnvironment, inspectcode_exe: str, output_path: str):
    # Include / exclude paths have to be relative to the solution directory,
    # which is either the engine root or the project root itself (which means an empty path)
    sln_relative_project_path = os.path.relpath(
        env.project_root, env.engine_root) + "\\" if env.is_source_engine else ""
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

    solution_file = env.get_engine_solution(
    ) if env.is_source_engine else env.get_project_solution()

    command_line = [inspectcode_exe,
                    "--build",
                    f'--project="{env.project_name}"',
                    # This target name is required or otherwise the ENTIRE solution is built. May need to be adjusted for non-game targets or samples, etc that end up in other dirs
                    f'--target="Games\\{env.project_name}"',
                    swea_param,
                    f'--properties="Configuration=Development Editor;Platform=Win64"',
                    f'--include="{includes_str}"',
                    f'--exclude="{excludes_str}"',
                    f'-o="{output_path}"',
                    solution_file
                    ]
    exit_code = run_subprocess(command_line, print_args=True)
    if not exit_code == 0:
        raise Exception(f"Invalid exit code {exit_code} from InspectCode")


def inspectcode(engine: UnrealEngine, may_skip_build: bool) -> StaticAnalysisResults:
    """
    Runs inspectcode on all project and plugin source files.
    """

    # TQ2 specific auto-detection of portable inspectcode folder
    tq2_inspectcode_path = f"{engine.environment.engine_root}/Tools/ReSharperCodeInspect/inspectcode.exe"
    if os.path.exists(tq2_inspectcode_path):
        inspectcode_exe = tq2_inspectcode_path
    else:
        # If the binary is not found, we assume it's on PATH
        inspectcode_exe = "inspectcode.exe"
        which_checked(inspectcode_exe)

    env = engine.environment

    output_path = "./resharperReport.xml"

    if not may_skip_build or not os.path.exists(output_path):
        # InspectCode needs solution for analysis.
        # It should already be present, but we can't be 100% sure in a CI context, so better safe than sorry.
        # engine.generate_project_files(engine_sln=True)

        # Run the main inspectcode exe.
        # This is most likely the most time consuming part, because it may have to rebuild the entire project and then analyze all the source files.
        _run_inspectcode(env, inspectcode_exe, output_path)

    analysis_results = _generate_analysis_results(f"./resharperReport.xml")

    return analysis_results


def inspectcode_report(engine: UnrealEngine, may_skip_build: bool, include_paths: List[str] = [], exclude_paths: List[str] = [], embeddable=False) -> str:
    """
    Runs inspectcode and generates an HTML report filtered by actively used sources
    (active plugins + modules for the editor target).
    """

    analysis_results = inspectcode(engine, may_skip_build)
    return static_analysis_html_report(engine.environment,
                                 analysis_results,
                                 embeddable=embeddable,
                                 include_paths=include_paths,
                                 exclude_paths=exclude_paths)


def write_inspectcode_report(engine: UnrealEngine, may_skip_build: bool, include_paths: List[str] = [], exclude_paths: List[str] = []) -> None:
    report_str = inspectcode_report(engine, may_skip_build, include_paths,
                                    exclude_paths, embeddable=False)
    write_text_file(f"./inspectCodeReport.html", report_str)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--include", default="")
    parser.add_argument("--exclude", default="")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    skip_build = args.skip_build

    def array_arg(parm_str: str):
        result = str.split(parm_str, ";")
        if '' in result and len(result) == 1:
            return []
        return result

    include_paths = array_arg(args.include)
    exclude_paths = array_arg(args.exclude)

    print("skip build:", skip_build)
    print("include:", include_paths)
    print("exclude:", exclude_paths)

    ue = UnrealEngine.create_from_parent_tree(os.getcwd())
    write_inspectcode_report(ue,
                             may_skip_build=skip_build,
                             include_paths=include_paths,
                             exclude_paths=exclude_paths)
