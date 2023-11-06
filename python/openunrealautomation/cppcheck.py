
import os
import subprocess
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree

from openunrealautomation.util import run_subprocess
from openunrealautomation.environment import UnrealEnvironment
import openunrealautomation.staticanalysis_common as ouu_sa

# TODOs
# Semi-important:
# - Combine results of runs?
# - gather UE include lists, run cppcheck per file and pass include list + generated macros
# Nice-to-have:
# - Allow building library file for UE source


_script_folder = Path(__file__).parent
_resources_folder = os.path.join(_script_folder, "resources", "cppcheck")

def parse_cppcheck_serverity(severity_str: str) -> ouu_sa.StaticAnalysisSeverity:
    severity_str = severity_str.lower()
    severity_dict = {
        "error" : ouu_sa.StaticAnalysisSeverity.ERROR,
        "warning" : ouu_sa.StaticAnalysisSeverity.WARNING,
        "style":ouu_sa.StaticAnalysisSeverity.SUGGESTION,
        "performance" : ouu_sa.StaticAnalysisSeverity.SUGGESTION,
        "portability": ouu_sa.StaticAnalysisSeverity.SUGGESTION,
        "information": ouu_sa.StaticAnalysisSeverity.IGNORE,
        "debug": ouu_sa.StaticAnalysisSeverity.IGNORE
    }
    if severity_str in severity_dict:
        return severity_dict[severity_str]
    else:
        return ouu_sa.StaticAnalysisSeverity.IGNORE


def run_cppcheck(target_paths, output_path="./cppcheck.xml", addon_rules_file: Optional[str] = None) -> ouu_sa.StaticAnalysisResults:
    suppression_file = os.path.join(
        _resources_folder, "all_issues.suppress.cppcheck")
    if addon_rules_file is None:
        addon_rules_file = os.path.join(
            _script_folder, "cppcheck_grimlore_rules.py")

    output_path = os.path.normpath(output_path)
    suppression_file = os.path.normpath(suppression_file)
    addon_rules_file = os.path.normpath(addon_rules_file)
    args = [
        "cppcheck",
        "--xml",
        "--quiet",
        # f"--output-file={output_path}",
        f"--suppressions-list={suppression_file}",
        f"--addon={addon_rules_file}",
        "--enable=all",
        "--disable=information",
        "--language=c++",
        "--platform=native",
        # explicitly suppress missing include files until we implemented UE include gathering
        "--suppress=missingInclude"
    ]
    args += target_paths

    cppcheck_output_str = bytes.decode(subprocess.run(
        args, shell=True, check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout, "utf-8")

    cppcheck_xml_results = ElementTree.fromstring(cppcheck_output_str)

    results = ouu_sa.StaticAnalysisResults()
    cppcheck_cat = results.find_or_add_category(
        "cppcheck", "Issues from cppcheck", None)

    results.find_or_add_category(
        "cppcheck-grim", "Custom Grimlore Rules", cppcheck_cat)
    for error_node in cppcheck_xml_results.findall(".//error"):
        error_full_id = str(error_node.get("id"))
        id_parts = error_full_id.split("-")
        if len(id_parts) < 2:
            raise Exception("Unexcpected number of components in ID")
        last_cat = cppcheck_cat
        for id_part in id_parts[0:-2]:
            last_cat = results.find_or_add_category(
                last_cat.id + "-" + id_part, "", last_cat)

        rule_id = last_cat.id + "-" + id_parts[-1]

        severity = parse_cppcheck_serverity(str(error_node.get("severity")))
        results.find_or_add_rule(rule_id, "", severity, last_cat.id)

        location_node = error_node.find("location")
        assert location_node is not None
        symbol = ""
        results.new_issue(location_node.get("file"),
                          int(str(location_node.get("line"))),
                          # The reported column number is weird. Always either lower or higher than expected.
                          int(str(location_node.get("column"))),
                          symbol,
                          error_node.get("msg"),
                          rule_id)

    return results


def _run_test():
    env = UnrealEnvironment.create_from_parent_tree(str(Path(__file__).parent))
    env.project_root
    test_source_files = [os.path.join(_resources_folder, "Test.cpp")]
    ouu_path = "D:\\projects\\OUU_SampleProject\\Plugins\\OUUCodingStandard\\Source\\OUUCodingStandard\\Private\\OUUCodingStandard.cpp"
    if os.path.exists(ouu_path):
        test_source_files.append(ouu_path)
    results = run_cppcheck(test_source_files)
    ouu_sa._generate_html_report(env, results, "./cppcheck_report.html", test_source_files)


if __name__ == "__main__":
    _run_test()
