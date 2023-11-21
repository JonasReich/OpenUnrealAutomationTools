
import glob
import json
import os
import subprocess
import re
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree

from openunrealautomation.util import run_subprocess
from openunrealautomation.environment import UnrealEnvironment
from openunrealautomation.unrealengine import UnrealEngine
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
        "error": ouu_sa.StaticAnalysisSeverity.ERROR,
        "warning": ouu_sa.StaticAnalysisSeverity.WARNING,
        "style": ouu_sa.StaticAnalysisSeverity.SUGGESTION,
        "performance": ouu_sa.StaticAnalysisSeverity.SUGGESTION,
        "portability": ouu_sa.StaticAnalysisSeverity.SUGGESTION,
        "information": ouu_sa.StaticAnalysisSeverity.IGNORE,
        "debug": ouu_sa.StaticAnalysisSeverity.IGNORE
    }
    if severity_str in severity_dict:
        return severity_dict[severity_str]
    else:
        return ouu_sa.StaticAnalysisSeverity.IGNORE

def crate_analysis_results_from_cppcheck_xml(cppcheck_output_str):
    cppcheck_xml_results = ElementTree.fromstring(cppcheck_output_str)

    results = ouu_sa.StaticAnalysisResults()
    cppcheck_cat = results.find_or_add_category(
        "cppcheck", "Issues from cppcheck", None)

    results.find_or_add_category(
        "cppcheck-grim", "Custom Grimlore Rules", cppcheck_cat)
    for error_node in cppcheck_xml_results.findall(".//error"):
        error_full_id = str(error_node.get("id"))
        last_cat = cppcheck_cat
            
        id_parts = error_full_id.split("-")
        if len(id_parts) > 0:
            for id_part in id_parts[0:-2]:
                last_cat = results.find_or_add_category(
                    last_cat.id + "-" + id_part, "", last_cat)

            rule_id = last_cat.id + "-" + id_parts[-1]
        else:
            rule_id = last_cat.id + error_full_id

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


def run_cppcheck(target_paths, output_path="./cppcheck.xml", addon_rules_file: Optional[str] = None, include_dirs = [], force_includes = []) -> ouu_sa.StaticAnalysisResults:
    suppression_file = os.path.join(
        _resources_folder, "all_issues.suppress.cppcheck")
    if addon_rules_file is None:
        addon_rules_file = os.path.join(
            _script_folder, "cppcheck_grimlore_rules.py")

    output_path = os.path.normpath(output_path)
    suppression_file = os.path.normpath(suppression_file)
    addon_rules_file = os.path.normpath(addon_rules_file)
    input_args = [
        "cppcheck",
        "--xml",
        "--quiet",
        # f"--output-file={output_path}",
        #f"--suppressions-list={suppression_file}",
        f"--addon={addon_rules_file}",
        "--enable=all",
        #"--disable=information",
        "--language=c++",
        "--platform=native",
        # explicitly suppress missing include files (this can be done, but might be a cuase of unknownMacros)
        "--suppress=missingInclude",
        # DO NOT explicitly suppress missing macro errors -> this hides why no other errors are reported
        #"--suppress=unknownMacro",
        #"--check-config"

        # TEMP
        # "-DPRAGMA_DISABLE_DEPRECATION_WARNINGS",
        # "-DOUURUNTIME_API"
    ]

    print("Arguments (without includes):", input_args)

    for include_dir in include_dirs:
        input_args += [f"-I", include_dir]

    input_args += [f"--include={force_include}" for force_include in force_includes]
    input_args += target_paths
    args = input_args

    while True:
        cppcheck_output_str = bytes.decode(subprocess.run(
            args, shell=True, check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout, "utf-8")
        #print(cppcheck_output_str)
        if "unknownMacro" in cppcheck_output_str:
            match = re.search(r"If (?P<macro>.*?) is a macro then please configure it", cppcheck_output_str)
            if match:
                macro = match.group("macro")
                print("macro " + macro)
                args += [f"-D{macro}"]
            else:
                # print("no macro")
                break
        else:
            break

    print(cppcheck_output_str)
    
    return crate_analysis_results_from_cppcheck_xml(cppcheck_output_str)


def _run_test():
    ue = UnrealEngine.create_from_parent_tree(str(Path(__file__).parent))
    env = ue.environment
    env.project_root
    test_source_files = []# [os.path.join(_resources_folder, "Test.cpp")]
    ouu_path = "D:\\projects\\OUU_SampleProject\\Plugins\\OUUCodingStandard\\Source\\OUUCodingStandard\\Private\\OUUCodingStandard.cpp"
    solution_dir = env.engine_root if env.is_source_engine else env.project_root
    
    
    for module_path in ue.get_all_module_dirs(skip_export=True):
        # I know this name doesn't always match, but please let me keep my sanity while I try to wrestle this demon
        module_name = Path(module_path).name 
        src_path, _ = env.find_source_dir_for_file(module_path)
        intermediate_path = os.path.join(Path(src_path).parent, "Intermediate")

        json_path_glob = os.path.abspath(os.path.join(
            intermediate_path, f"Build/Win64/x64/UnrealEditor/Development/{module_name}/*.dep.json"))
        print(json_path_glob)

        for json_path in glob.glob(json_path_glob):
            print("match", json_path)

            with open(json_path, "r") as json_file:
                compile_info = json.load(json_file)["Data"]
            includes:list = compile_info["Includes"]
            # includes.append(compile_info["PCH"])
            # includes = [str(Path(include).resolve()) if os.path.exists(include) else "" for include in includes]
            real_includes = []
            for include in includes:
                include = str(Path(include).resolve())
                if os.path.exists(include):
                    real_includes.append(include)
                else:
                    print("WARN: not file", include)
            includes = real_includes

            #print(includes)

            test_source_files = [compile_info["Source"]]

            # if os.path.exists(ouu_path):
                # test_source_files.append(ouu_path)


            # we already exported before
            target_dict = ue.get_target_json_dict(skip_export=True)

            include_dirs = []
            modules_dict = target_dict["Modules"]
            module_attrs = modules_dict[module_name]
            include_dirs += module_attrs["InternalIncludePaths"]
            include_dirs += module_attrs["PrivateIncludePaths"]

            # filter unique entries
            include_dirs = list(set(include_dirs))

            results = run_cppcheck(test_source_files, include_dirs=include_dirs,force_includes=includes)
            ouu_sa._generate_html_report(env, results, "./cppcheck_report.html", test_source_files)

            exit()

if __name__ == "__main__":
    _run_test()
