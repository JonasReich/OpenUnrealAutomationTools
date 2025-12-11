"""
Utils for plain-old automation tests.
Does not support gauntlet testing yet, but it's planned in the future.
"""

import glob
import json
import os
import shutil
import time
from pathlib import Path
from typing import List, Optional, Tuple
from xml.etree.ElementTree import Element as XmlNode
from xml.etree.ElementTree import ElementTree as XmlTree

from openunrealautomation.core import OUAException, UnrealProgram
from openunrealautomation.environment import UnrealEnvironment
from openunrealautomation.logfile import UnrealLogFile
from openunrealautomation.unrealengine import UnrealEngine
from openunrealautomation.util import (glob_latest, ouu_temp_file,
                                       run_subprocess, which_checked,
                                       write_text_file)
from openunrealautomation.version import UnrealVersion


def _convert_test_results_to_junit(json_path: str, junit_path: str) -> None:
    print(f"Converting {json_path} to {junit_path}...")
    with open(json_path, "r", encoding="utf-8-sig") as json_file:
        json_results = json.loads(json_file.read())

        test_platform = json_results['devices'][0]['platform']
        report_created_on = json_results['reportCreatedOn']
        testsuite_id = f"UnrealTest {test_platform} @ {report_created_on}"
        num_failures = str(json_results["failed"])
        num_tests = str(int(json_results["succeeded"]) + int(num_failures))
        testsuite_time = str(json_results["totalDuration"])

        testsuite_node = XmlNode("testsuite")
        testsuite_node.set("id", testsuite_id)
        testsuite_node.set("tests", num_tests)
        testsuite_node.set("failures", num_failures)
        testsuite_node.set("time", testsuite_time)

        for test in json_results["tests"]:
            test_node = XmlNode("testcase")
            test_node.set("name", test["testDisplayName"])
            # make sure class names do not contain any spaces - otherwise TeamCity etc won't detect other groupings by dot separator
            test_node.set("classname", str(
                test["fullTestPath"]).replace(" ", "_"))
            test_node.set("status", test["state"])
            test_node.set("time", str(test["duration"]))

            for entry in test["entries"]:
                # entries may contain info logs and warnings. Only errors should fail JUnit tests
                if not entry["event"]["type"] == "Error":
                    continue

                event_node = XmlNode("failure")
                event_node.set("message", entry["event"]["message"])
                event_type = entry["event"]["type"]
                event_node.set("type", event_type)
                event_node.text = event_type
                event_node.text += "\n" + entry["event"]["message"]
                event_node.text += "\n" + entry["filename"]
                event_node.text += "\n" + str(entry["lineNumber"])

                test_node.append(event_node)

            testsuite_node.append(test_node)

        # Use the same data as from the first testsuite
        root_node = XmlNode("testsuites")
        root_node.set("id", testsuite_id)
        root_node.set("tests", num_tests)
        root_node.set("failures", num_failures)
        root_node.set("time", testsuite_time)
        root_node.append(testsuite_node)

        xml_tree = XmlTree(root_node)
        xml_tree.write(junit_path, encoding="utf-8", xml_declaration=True)

        # Always report tets back to TeamCity.
        # This is not necessarily required, but should never hurt.
        # See https://www.jetbrains.com/help/teamcity/service-messages.html#Importing+XML+Reports
        print(f"##teamcity[importData type='junit' path='{junit_path}']")


def automation_test_html_report(json_path: Optional[str]) -> Optional[str]:
    if not json_path or not os.path.exists(json_path):
        return None

    with open(json_path, "r", encoding="utf-8-sig") as json_file:
        json_results = json.loads(json_file.read())

        test_platform = json_results['devices'][0]['platform']
        report_created_on = json_results['reportCreatedOn']
        testsuite_id = f"Automation Tests {test_platform} @ {report_created_on}"
        num_failures = str(json_results["failed"])
        num_tests = str(int(json_results["succeeded"]) + int(num_failures))
        testsuite_time = "%.2f" % float(json_results["totalDuration"])

        results_dict = {}

        def add_test_result(path_elems: List[str], result_str: str, is_error: bool):
            iter_dict = results_dict
            for idx, elem in zip(range(len(path_elems)), path_elems):
                if idx == len(path_elems) - 1:
                    break
                if elem not in iter_dict:
                    iter_dict[elem] = {}
                iter_dict = iter_dict[elem]
            iter_dict[path_elems[-1]] = (result_str, is_error)

        for test in json_results["tests"]:
            # not really a display name in most cases, but just the last name after the dot
            display_name = test["testDisplayName"]
            test_path = test["fullTestPath"].replace(
                "<", "&lt;").replace(">", "&gt;")
            str(test["duration"])
            if test["state"] == "Fail":
                error_lines = ""
                for entry in test["entries"]:
                    event = entry["event"]
                    event_type = event["type"].lower()
                    if event_type in ["error", "warning"]:
                        message = event["message"]
                        error_lines += f"<code class='{event_type}'>{message}</code><br>\n"
                if len(error_lines) > 0:
                    add_test_result(test_path.split(
                        "."), f"<div><div class='code-container text-nowrap p-3'><code>{error_lines}</code></div></div>\n", True)
                    continue
            add_test_result(test_path.split("."), f"SUCCESS", False)

        def get_results_str(_results_dict: dict) -> Tuple[str, int, int]:
            result_str = ""
            num_total = 0
            num_errors = 0
            for key, value in _results_dict.items():
                if isinstance(value, dict):
                    nested_result_str, nested_result_total, nested_result_errors = get_results_str(
                        value)
                    failure_suffix = f" ❌<div class='error' style='display:inline;'>{nested_result_errors}</div>" if nested_result_errors > 0 else ""
                    result_str += f"<details><summary>{key} - {nested_result_total} {failure_suffix}</summary>\n{nested_result_str}\n</details>\n"
                    num_total += nested_result_total
                    num_errors += nested_result_errors
                else:
                    assert isinstance(value, tuple)
                    message = value[0]
                    is_error = value[1]
                    num_total += 1
                    if is_error:
                        num_errors += 1
                        result_str += f"<details><summary>❌ {key}</summary><div class='box-ouu px-2'>{message}</div>\n</details>\n"
                    else:
                        result_str += f"<ul><li>{key}</li></ul>\n"
            return result_str, num_total, num_errors

        results, _, _ = get_results_str(results_dict)
        summary_table = f"""
<table class="table table-dark table-sm small table-bordered">
<thead>
  <tr>
    <th>Tests</th>
    <th>Failed</th>
    <th>Duration</th>
  </tr>
</thead>
<tbody>
  <tr>
    <td>{num_tests}</td>
    <td>{num_failures}</td>
    <td>{testsuite_time}s</td>
  </tr>
</tbody>
</table>
"""
        test_tree_btns = """
<button class="btn btn-sm btn-secondary" id="expand-all-btn" onclick="$('details').attr('open', true)">🔽 Expand</button>
<button class="btn btn-sm btn-secondary" id="collapse-all-btn" onclick="$('details').attr('open', false)">🔼 Collapse</button>
"""

        return f"<div class='p-3'><h5>{testsuite_id}</h5>{summary_table}<div class='automation-test-results'>\n{test_tree_btns}\n{results}\n</div></div>"


def get_root_report_directory(environment: UnrealEnvironment) -> str:
    return f"{environment.project_root}/Saved/Automation/Reports/"


def get_default_test_report_directory(environment: UnrealEnvironment) -> str:
    return os.path.join(get_root_report_directory(environment), f"TestReport-{environment.creation_time_str}")


def run_tests(engine: UnrealEngine,
              test_filter: Optional[str] = None,
              game_test_target: bool = True,
              arguments: "list[str]" = [],
              generate_report_file: bool = False,
              report_directory: Optional[str] = None,
              log_directory: Optional[str] = None,
              convert_junit: bool = True,
              setup_report_viewer: bool = False,
              generate_coverage_reports: bool = False,
              may_skip: bool = False) -> int:
    """
    Execute game or editor tests in the editor cmd - Either in game or in editor mode (depending on game_test_target flag).

    test_filter                 Optional string that specifies which test categories shall be executed. Seprated by pluses.
    game_test_target            If true, the editor is launched in game mode (significantly faster). If false in editor mode. The test selection is updated accordingly.
    arguments                   Additional commandline arguments to pass to UE.
    generate_report_file        If true, a test report (json + html) is saved by UE into the project's Saved directory.
    report_directory            Optional path to a directory to place automation reports. By defautl a generated folder in the projects Saved directory is used. 
    convert_junit               If true, the test results json file is converted into a JUnit xml file (e.g. to report test status to Jenkins/TeamCity).
    setup_report_viewer         If true, all bower_components required for Epic's test viewer html page are installed into the report directory. This requires bower to be installed and on PATH.
    generate_coverage_reports   If true, the application is launched via opencppcoverage to generate code coverage reports in the project's Saved directory.
    """

    setup_report_viewer_actual = generate_report_file and setup_report_viewer
    # Already check for requirements at the start, so there are no surprises after running tests.
    bower_path = None
    if setup_report_viewer_actual:
        bower_path = which_checked("bower", "Bower (available via npm)")

    if report_directory is None:
        report_directory = get_default_test_report_directory(
            engine.environment)

    if may_skip:
        last_test_report = find_last_test_report(engine, report_directory)
        if last_test_report is not None:
            last_test_report_time = os.path.getmtime(last_test_report)

            # check the last editor build time by checking editor and plugin DLLs (does not check for engine plugins / dlls at this time)
            editor_dll_path = os.path.join(
                engine.environment.project_root, f"Binaries/Win64/UnrealEditor-{engine.environment.project_name}.dll")
            last_editor_build_time = os.path.getmtime(editor_dll_path)

            for plugin_dll_path in glob.glob(os.path.join(
                    engine.environment.project_root, f"Plugins/*/Binaries/Win64/UnrealEditor-*.dll"), recursive=True):
                last_editor_build_time = max(
                    last_editor_build_time, os.path.getmtime(plugin_dll_path))

            if last_test_report_time > last_editor_build_time:
                print(
                    f"Found test report {last_test_report} (@{time.ctime(last_test_report_time)}) that was newer than last build of editor module {editor_dll_path} (@{time.ctime(last_editor_build_time)})")
                return 0

    json_path = os.path.join(report_directory, "index.json")
    if os.path.exists(json_path):
        os.remove(json_path)

    if test_filter is None:
        optional_ouu_tests = "+OpenUnrealUtilities" if engine.environment.has_open_unreal_utilities() else ""
        test_filter = f"{engine.environment.project_name}+Project{optional_ouu_tests}"

    all_args = ["-game", "-gametest"] if game_test_target \
        else ["-editor", "-editortest"]
    if engine.environment.build_version.get_current() <= UnrealVersion(5, 3, 0):
        optional_now = " Now"
    else:
        # 5.3 has a breaking change in that "RunTests Now" doesn't actually queue the tests anymore
        # "RunTests; Quit" seems to work fine though
        optional_now = ""
    all_args.append(
        f"-ExecCmds=Automation RunTests{optional_now} {test_filter};Quit")
    if generate_report_file:
        os.makedirs(report_directory, exist_ok=True)
        all_args.append(f"-ReportExportPath={report_directory}")
    all_args.append("-nullrhi")
    all_args += arguments

    # run
    unreal_exit_code = engine.run(UnrealProgram.EDITOR_CMD,
                                  arguments=all_args,
                                  map=None,
                                  raise_on_error=False,
                                  add_default_parameters=True,
                                  generate_coverage_reports=generate_coverage_reports,
                                  coverage_report_path=os.path.join(report_directory, "Coverage"))

    if log_directory:
        last_editor_log = UnrealLogFile.EDITOR.find_latest(engine.environment)
        if not last_editor_log:
            raise OUAException("Failed to find editor log file")
        log_target_path = os.path.join(
            log_directory, "EditorAutomationTests.log")
        shutil.copy2(last_editor_log, log_target_path)

    if generate_report_file and convert_junit:
        junit_path = os.path.join(report_directory, "JUnitTestResults.xml")
        if os.path.exists(json_path):
            _convert_test_results_to_junit(
                json_path=json_path, junit_path=junit_path)

    if setup_report_viewer_actual and bower_path is not None:
        bower_json = os.path.join(
            engine.environment.engine_root, "Engine/Content/Automation/bower.json")
        # Install bower components to report directory
        run_subprocess([bower_path, "install", bower_json],
                       cwd=report_directory)

        # Write a super simple batch script that starts python server with results viewer and opens browser.
        host_test_viewer_server_cmd = "start python -m http.server\nstart http:\\\\localhost:8000"
        write_text_file(os.path.join(report_directory,
                        "index.cmd"), host_test_viewer_server_cmd)

    return unreal_exit_code


def find_last_test_report(engine: UnrealEngine,
                          report_directory: Optional[str] = None) -> Optional[str]:
    if report_directory is None:
        report_directory = get_root_report_directory(engine.environment)
    glob_str = f"{report_directory}/**/index.json"
    print(f"Searching for automation report in {glob_str}")
    result = glob_latest(glob_str)
    print(f"  -> {result}")
    return result


if __name__ == "__main__":
    ue = UnrealEngine.create_from_parent_tree(str(Path(__file__).parent))

    json_report_path = find_last_test_report(ue)
    if json_report_path is None:
        run_tests(ue, generate_coverage_reports=True,
                  generate_report_file=True, setup_report_viewer=True)
        json_report_path = find_last_test_report(ue)

    assert json_report_path
    report_str = automation_test_html_report(json_report_path)
    write_text_file(ouu_temp_file(
        f"automationTestReport.html"), str(report_str))
