"""
Utils for plain-old automation tests.
Does not support gauntlet testing yet, but it's planned in the future.
"""

import glob
import json
import os
from pathlib import Path
from typing import Optional
from xml.etree.ElementTree import Element as XmlNode
from xml.etree.ElementTree import ElementTree as XmlTree

from openunrealautomation.core import UnrealProgram
from openunrealautomation.environment import UnrealEnvironment
from openunrealautomation.unrealengine import UnrealEngine
from openunrealautomation.util import (ouu_temp_file, run_subprocess,
                                       which_checked, write_text_file)


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
            test_node.set("classname", test["fullTestPath"])
            test_node.set("status", test["state"])
            test_node.set("time", str(test["duration"]))

            for entry in test["entries"]:
                if entry["event"]["type"] == "Info":
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


def automation_test_html_report(json_path: str) -> str:
    with open(json_path, "r", encoding="utf-8-sig") as json_file:
        json_results = json.loads(json_file.read())
        results = ""

        test_platform = json_results['devices'][0]['platform']
        report_created_on = json_results['reportCreatedOn']
        testsuite_id = f"Automation Tests {test_platform} @ {report_created_on}"
        num_failures = str(json_results["failed"])
        num_tests = str(int(json_results["succeeded"]) + int(num_failures))
        testsuite_time = str(json_results["totalDuration"])

        for test in json_results["tests"]:
            if test["state"] == "Fail":
                # not really a display name in most cases, but just the last name after the dot
                display_name = test["testDisplayName"]
                test_path = test["fullTestPath"]
                str(test["duration"])

                error_lines = ""
                for entry in test["entries"]:
                    event = entry["event"]
                    event_type = event["type"].lower()
                    if event_type in ["error", "warning"]:
                        message = event["message"]
                        error_lines += f"<code class='{event_type}'>{message}</code><br>"
                if len(error_lines) > 0:
                    results += f"<div class='error'>{test_path}<br/><div class='code-container text-nowrap p-3'><code>{error_lines}</code></div></div>"
        return f"<div class='p-3'><h5>{testsuite_id}</h5>Tests: <code>{num_tests}</code> Failed: <code>{num_failures}</code> Duration: <code>{testsuite_time}s</code><div>{results}</div></div>"


def get_root_report_directory(environment: UnrealEnvironment) -> str:
    return f"{environment.project_root}/Saved/Automation/Reports/"


def get_default_test_report_directory(environment: UnrealEnvironment) -> str:
    return os.path.join(get_root_report_directory(environment), f"TestReport-{environment.creation_time_str}")


def run_tests(engine: UnrealEngine, test_filter: Optional[str] = None,
              game_test_target: bool = True,
              arguments: "list[str]" = [],
              generate_report_file: bool = False,
              report_directory: Optional[str] = None,
              convert_junit: bool = True,
              setup_report_viewer: bool = False,
              generate_coverage_reports: bool = False):
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

    if test_filter is None:
        optional_ouu_tests = "+OpenUnrealUtilities" if engine.environment.has_open_unreal_utilities() else ""
        test_filter = f"{engine.environment.project_name}+Project.Functional{optional_ouu_tests}"

    all_args = ["-game", "-gametest"] if game_test_target \
        else ["-editor", "-editortest"]
    all_args.append(
        f"-ExecCmds=Automation RunTests Now {test_filter};Quit")
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
                                  generate_coverage_reports=generate_coverage_reports)

    if generate_report_file and convert_junit:
        json_path = os.path.join(report_directory, "index.json")
        junit_path = os.path.join(report_directory, "JUnitTestResults.xml")
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

    search_path = f"{report_directory}/**/index.json"
    found_files = glob.glob(search_path, recursive=True)
    found_files = [os.path.normpath(file) for file in found_files]
    found_files.sort(key=os.path.getctime)
    return found_files[0] if len(found_files) > 0 else None


if __name__ == "__main__":
    ue = UnrealEngine.create_from_parent_tree(str(Path(__file__).parent))

    json_report_path = find_last_test_report(ue)
    if json_report_path is None:
        run_tests(ue, generate_coverage_reports=True,
                  generate_report_file=True, setup_report_viewer=True)
        json_report_path = find_last_test_report(ue)

    assert json_report_path
    report_str = automation_test_html_report(json_report_path)
    write_text_file(ouu_temp_file(f"automationTestReport.html"), report_str)
