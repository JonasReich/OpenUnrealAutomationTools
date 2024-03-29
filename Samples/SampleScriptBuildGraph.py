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

from openunrealautomation.automationtest import (automation_test_html_report,
                                                 find_last_test_report,
                                                 run_tests)
from openunrealautomation.html_report import (create_localization_report,
                                              generate_html_report)
from openunrealautomation.inspectcode import InspectCode
from openunrealautomation.logparse import parse_logs
from openunrealautomation.opencppcoverage import (coverage_html_report,
                                                  find_coverage_file)
from openunrealautomation.unrealengine import UnrealEngine
from openunrealautomation.util import force_rmtree

_step_num = 0


def step_header(step_name):
    global _step_num
    _step_num += 1
    print(
        "\n----------------------------------------"
        f"\nSTEP #{_step_num:02d} - {step_name.upper()}"
        "\n----------------------------------------")


if __name__ == "__main__":
    # argparse
    argparser = argparse.ArgumentParser()
    argparser.add_argument("--dry-run", action="store_true")
    argparser.add_argument("--clean", action="store_true")
    argparser.add_argument("--bg-shared-storage",
                           default="F:\\BuildGraphStorage")
    argparser.add_argument("--bg-network-share",
                           default="F:\\BuildGraphNetworkShare")
    argparser.add_argument("--unique-build-id", default=None)
    argparser.add_argument("--game-target-name", default=None)
    args = argparser.parse_args()

    step_header("Setup")
    clean = args.clean
    bg_shared_storage = args.bg_shared_storage
    bg_network_share = args.bg_network_share
    unique_build_id = args.unique_build_id
    game_target_name = args.game_target_name

    # UE environment
    ue = UnrealEngine.create_from_parent_tree(
        os.path.realpath(os.path.dirname(__file__)))
    ue.dry_run = args.dry_run

    # common paths
    buildgraph_script = os.path.join(
        pathlib.Path(__file__).parent, "SampleBuildGraph.xml")

    if not unique_build_id:
        unique_build_id = ue.environment.project_name + "TestBuild"

    log_dir = os.path.normpath(os.path.join(bg_network_share,
                                            "Builds/Logs",
                                            unique_build_id))
    report_dir = os.path.join(
        bg_network_share, "Builds/Automation/Reports", unique_build_id)

    if not ue.dry_run:
        # clean
        force_rmtree(log_dir)
        if clean:
            force_rmtree(report_dir)

    # setup tools
    os.makedirs(report_dir, exist_ok=True)
    inspectcode = InspectCode(ue.environment, os.path.join(
        report_dir, "InspectCode.xml"), None)

    # On CI these would be the regular build steps
    try:
        step_header("BuildGraph execution")
        bg_options = {
            "ProjectDir": ue.environment.project_root,
            "ProjectName": str(ue.environment.project_name),
        }

        if game_target_name:
            bg_options["GameTargetName"] = game_target_name

        print("Starting distributed buildgraph...")
        ue.run_buildgraph_nodes_distributed(
            buildgraph_script, "AllGamePackages", bg_options,
            shared_storage_dir=bg_shared_storage,
            log_output_dir=log_dir,
            arguments=["-NoP4"]
        )
    except Exception as e:
        print(e)
        pass

    try:
        # TODO move to BuildGraph sample ??
        step_header("Static Analysis")
        # ue.generate_project_files()
        inspectcode.run(may_skip=True)
    except Exception as e:
        print(e)
        pass

    # TODO move to BuildGraph sample
    try:
        step_header("Automation Tests")
        run_tests(ue, generate_coverage_reports=True, generate_report_file=True,
                  report_directory=report_dir, setup_report_viewer=False, may_skip=True)
    except Exception as e:
        print(e.with_traceback())
        pass

    # On CI this should be a separate "run always" build step after all previous steps concluded
    step_header("Report generation (always)")

    # Parse the UAT log files that were copied to log_dir
    patterns_xml = None  # use the default file
    parsed_logs = parse_logs(log_dir, patterns_xml, "BuildGraph")

    # Optional embeddable reports
    embedded_reports = []

    # Automation tests
    embedded_reports.append(automation_test_html_report(
        find_last_test_report(ue, report_dir)))

    # Code coverage (from automation tests)
    embedded_reports.append(coverage_html_report(
        find_coverage_file(os.path.join(report_dir, "Coverage"))))

    # Static C++ code analysis
    embedded_reports.append(inspectcode.load().html_report(
        embeddable=True))

    # Localization status
    embedded_reports.append(create_localization_report(
        ue.environment, localization_target="Game"))

    # Combine everything in a report file
    generate_html_report(None,  # no custom patterns
                         html_report_path=os.path.join(
                             report_dir, "BuildReport.html"),
                         log_files=parsed_logs,
                         embedded_reports=embedded_reports,
                         out_json_path=os.path.join(
                             report_dir, "BuildReport.json"),
                         report_title=f"{ue.environment.project_name} Build Report",
                         background_image_uri="https://docs.unrealengine.com/5.0/Images/samples-and-tutorials/sample-games/lyra-game-sample/BannerImage.png",
                         filter_tags_and_labels={"ART": "🎨 Art", "CODE": "🤖 Code", "CONTENT": "📝 Content"})
