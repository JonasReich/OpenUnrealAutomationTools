"""
This sample shows how to use the python tools.
It assumes the package located in ../python/* (relative to this file)
is installed in your python environment under its default name (i.e. openunrealautomation).

The python tools don't have any dependencies to the Powershell tools.

This example uses BuildGraph for much of the actual script logic.
"""

import argparse
import os
import pathlib
import tempfile

from openunrealautomation.automationtest import (automation_test_html_report,
                                                 find_last_test_report,
                                                 run_tests)
from openunrealautomation.html_report import generate_html_report
from openunrealautomation.inspectcode import InspectCode
from openunrealautomation.logparse import parse_log
from openunrealautomation.unrealengine import UnrealEngine

step_num = 0


def step_header(step_name):
    global step_num
    step_num += 1
    print(
        "\n----------------------------------------"
        f"\nSTEP #{step_num:02d} - {step_name.upper()}"
        "\n----------------------------------------")


if __name__ == "__main__":
    step_header("Setup")
    ue = UnrealEngine.create_from_parent_tree(
        os.path.realpath(os.path.dirname(__file__)))

    argparser = argparse.ArgumentParser()
    argparser.add_argument("--dry-run", action="store_true")
    args = argparser.parse_args()
    ue.dry_run = args.dry_run

    step_header("BuildGraph execution")
    buildgraph_script = os.path.join(
        pathlib.Path(__file__).parent, "Graph.xml")

    log_dir = os.path.join(ue.environment.project_root,
                           "Saved/Logs/OUUBuildGraphLogs")

    ue.run_buildgraph_nodes_distributed(
        buildgraph_script, "Package Game Win64", {
            "ProjectDir": ue.environment.project_root,
            "ProjectName": str(ue.environment.project_name)
        }, log_output_dir=log_dir)

    step_header("Tests + Static Analysis")

    report_dir = os.path.join(
        ue.environment.project_root, "Saved/Automation/BuildGraphTest")
    inspectcode_xml = os.path.join(report_dir, "InspectCode.xml")
    inspectcode = InspectCode(ue.environment, inspectcode_xml, None)
    inspectcode.run(may_skip=True)

    if not find_last_test_report(ue, report_dir):
        run_tests(ue, generate_coverage_reports=True,
                  generate_report_file=True, report_directory=report_dir,
                  setup_report_viewer=False)

    step_header("Report generation")
    temp_dir = os.path.join(tempfile.gettempdir(), "OpenUnrealAutomation")
    os.makedirs(temp_dir, exist_ok=True)

    parsed_logs = []

    patterns_xml = None  # fallback
    for path in os.scandir(log_dir):
        if path.is_file():
            print("parse", path.path, "...")
            parsed_log = parse_log(
                path.path, patterns_xml, "BuildGraph")
            parsed_logs.append((path, parsed_log))

    static_analysis_results = inspectcode.load()
    static_analysis_report_html = static_analysis_results.html_report(
        embeddable=True)

    test_json_path = find_last_test_report(ue, report_dir)
    assert test_json_path
    test_report_html = automation_test_html_report(test_json_path)

    # -----

    html_file = os.path.join(
        temp_dir, "SampleBuildReport.html")
    json_file = os.path.join(temp_dir, "SampleBuildReport.json")

    # This could be started with additional parameters for build distribution.
    # To make the script more portable we omit those params.
    generate_html_report(None,  # no custom patterns
                         html_report_path=html_file,
                         log_files=parsed_logs,
                         # TODO: Make all following parameters optional!!!
                         embedded_reports=[test_report_html,
                                           static_analysis_report_html
                                           ],
                         out_json_path=json_file,
                         report_title="Sample Script Report",
                         background_image_uri="https://cdn1.epicgames.com/salesEvent/salesEvent/Marketplace_S_01_1920x1080-a16ac51ff11b0b5a1f775dd0e932ed61?resize=1&w=1920",
                         filter_tags_and_labels={"ART": "🎨 Art", "CODE": "🤖 Code"})
