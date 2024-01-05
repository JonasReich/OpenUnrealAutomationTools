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
from openunrealautomation.opencppcoverage import (coverage_html_report,
                                                  find_coverage_file)
from openunrealautomation.unrealengine import UnrealEngine

step_num = 0


def step_header(step_name):
    global step_num
    step_num += 1
    print(
        "\n----------------------------------------"
        f"\nSTEP #{step_num:02d} - {step_name.upper()}"
        "\n----------------------------------------")


def run_step_build():
    bg_options = {
        "ProjectDir": ue.environment.project_root,
        "ProjectName": str(ue.environment.project_name),
    }

    if game_target_name:
        bg_options["GameTargetName"] = game_target_name

    ue.run_buildgraph_nodes_distributed(
        buildgraph_script, "Package Game Win64", bg_options,
        shared_storage_dir=bg_shared_storage,
        log_output_dir=log_dir,
        arguments=["-NoP4"]
    )


def run_step_report():
    parsed_logs = []

    patterns_xml = None  # fallback
    for path in os.scandir(log_dir):
        if path.is_file():
            print("parse", path.path, "...")
            parsed_log = parse_log(
                path.path, patterns_xml, "BuildGraph")
            parsed_logs.append((path, parsed_log))

    embedded_reports = []

    try:
        test_json_path = find_last_test_report(ue, report_dir)
        print("test json", test_json_path)
        test_report_html = automation_test_html_report(test_json_path)
        embedded_reports.append(test_report_html)
    except:
        pass

    coverage_path = find_coverage_file(os.path.join(report_dir, "Coverage"))
    coverage_report = coverage_html_report(coverage_path)
    embedded_reports.append(coverage_report)

    static_analysis_results = inspectcode.load()
    static_analysis_report_html = static_analysis_results.html_report(
        embeddable=True)
    embedded_reports.append(static_analysis_report_html)

    # -----

    html_file = os.path.join(
        report_dir, "BuildReport.html")
    json_file = os.path.join(report_dir, "BuildReport.json")

    # This could be started with additional parameters for build distribution.
    # To make the script more portable we omit those params.
    generate_html_report(None,  # no custom patterns
                         html_report_path=html_file,
                         log_files=parsed_logs,
                         # TODO: Make all following parameters optional!!!
                         embedded_reports=embedded_reports,
                         out_json_path=json_file,
                         report_title=f"{ue.environment.project_name} Build Report",
                         background_image_uri="https://cdn1.epicgames.com/item/ue/LyraEnvironment04_1920x1080-8bc8da7bd84731b4b1b5f7d443c8cdab?resize=1&w=1920",
                         filter_tags_and_labels={"ART": "🎨 Art", "CODE": "🤖 Code", "CONTENT": "📝 Content"})


if __name__ == "__main__":
    step_header("Setup")
    ue = UnrealEngine.create_from_parent_tree(
        os.path.realpath(os.path.dirname(__file__)))

    argparser = argparse.ArgumentParser()
    argparser.add_argument("--dry-run", action="store_true")
    argparser.add_argument("--bg-shared-storage",
                           default="F:\\BuildGraphStorage")
    argparser.add_argument("--bg-network-share",
                           default="F:\\BuildGraphNetworkShare")
    argparser.add_argument("--unique-build-id", default=None)
    argparser.add_argument("--game-target-name", default=None)
    args = argparser.parse_args()
    ue.dry_run = args.dry_run
    bg_shared_storage = args.bg_shared_storage
    bg_network_share = args.bg_network_share
    unique_build_id = args.unique_build_id
    game_target_name = args.game_target_name

    buildgraph_script = os.path.join(
        pathlib.Path(__file__).parent, "Graph.xml")

    if not unique_build_id:
        unique_build_id = ue.environment.project_name + "TestBuild"

    log_dir = os.path.normpath(os.path.join(bg_network_share,
                                            "Builds/Logs",
                                            unique_build_id))

    report_dir = os.path.join(
        bg_network_share, "Builds/Automation/Reports", unique_build_id)
    os.makedirs(report_dir, exist_ok=True)
    inspectcode_xml = os.path.join(report_dir, "InspectCode.xml")
    inspectcode = InspectCode(ue.environment, inspectcode_xml, None)

    # On CI these would be the regular build steps
    try:
        step_header("BuildGraph execution")
        # run_step_build()
    except:
        pass

    # TODO move to BuildGraph sample ??
        ue.generate_project_files()
    try:
        step_header("Static Analysis")
        inspectcode.run(may_skip=True)
    except:
        pass

    # TODO move to BuildGraph sample
    try:
        step_header("Automation Tests")

        if not find_last_test_report(ue, report_dir):
            print("Running tests...")
            run_tests(ue, generate_coverage_reports=True,
                      generate_report_file=True, report_directory=report_dir,
                      setup_report_viewer=False)
        else:
            print("Skipping tests. found results files in", report_dir)
    except:
        pass

    # On CI this should be a separate "run always" build step after all previous steps concluded
    step_header("Report generation (always)")
    run_step_report()
