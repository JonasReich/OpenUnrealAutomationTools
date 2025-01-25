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
import traceback

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


def step_header(step_name, enabled):
    global _step_num
    _step_num += 1
    print(
        "\n----------------------------------------"
        f"\nSTEP #{_step_num:02d} - {step_name.upper()} {'(DISABLED)' if not enabled else ''}"
        "\n----------------------------------------")


def main():
    log_dir = os.path.normpath(os.path.join(bg_network_share,
                                            "Builds/Logs",
                                            unique_build_id))
    report_dir = os.path.join(
        bg_network_share, "Builds/Automation/Reports", unique_build_id)

    run_clean = not ue.dry_run
    step_header(f"Clean {run_clean}", run_clean)
    if run_clean:
        # clean
        force_rmtree(log_dir, no_file_ok=True)
        if clean:
            print("Cleaning", report_dir, "...")
            force_rmtree(report_dir, no_file_ok=True)

    # setup tools
    os.makedirs(report_dir, exist_ok=True)
    inspectcode = InspectCode(ue.environment, os.path.join(
        report_dir, "InspectCode.xml"), None)

    # On CI these would be the regular build steps
    run_buildgraph = not args.skip_bg
    step_header("BuildGraph execution", run_buildgraph)
    if run_buildgraph:
        try:
            bg_options = {
                "ProjectDir": ue.environment.project_root,
                "ProjectName": str(ue.environment.project_name),
                "BuildConfig": "Shipping"
            }

            if game_target_name:
                bg_options["GameTargetName"] = game_target_name

            print("Starting distributed buildgraph...")
            if not args.skip_bg:
                if args.package:
                    bg_target = "AllGamePackages" if args.all else "Package Game Win64"
                else:
                    bg_target = "AllGameCompiles" if args.all else "Compile Game Win64"

                clean_arg = ["-clean"] if clean else []
                ue.run_buildgraph_nodes_distributed(
                    buildgraph_script, bg_target, bg_options,
                    shared_storage_dir=bg_shared_storage,
                    log_output_dir=log_dir,
                    arguments=["-NoP4"] + clean_arg
                )
        except Exception as e:
            print(traceback.format_exc())
            print(e)
            pass

    run_static_analysis = not ue.dry_run and args.static_analysis
    step_header("Static Analysis", run_static_analysis)
    if run_static_analysis:
        try:
            # TODO move to BuildGraph sample ??
            # ue.generate_project_files()
            inspectcode.run(may_skip=True)
        except Exception as e:
            print(traceback.format_exc())
            print(e)
            pass

    # TODO move to BuildGraph sample
    enable_tests = not ue.dry_run
    step_header("Automation Tests", enable_tests)
    if enable_tests:
        try:
            run_tests(ue, generate_coverage_reports=True, generate_report_file=True,
                      report_directory=report_dir, setup_report_viewer=False, may_skip=True)
        except Exception as e:
            print(traceback.format_exc())
            print(e)
            pass

    # On CI this should be a separate "run always" build step after all previous steps concluded
    step_header("Report generation (always)", True)

    # Parse the UAT log files that were copied to log_dir
    patterns_xml = None  # use the default file
    parsed_logs = parse_logs(log_dir, patterns_xml,
                             "BuildGraph") if not args.skip_bg else []

    # Optional embeddable reports
    embedded_reports = []

    # Automation tests
    embedded_reports.append(automation_test_html_report(
        find_last_test_report(ue, report_dir)))

    # Code coverage (from automation tests)
    embedded_reports.append(coverage_html_report(
        find_coverage_file(os.path.join(report_dir, "Coverage"))))

    # Static C++ code analysis
    if args.static_analysis:
        try:
            embedded_reports.append(inspectcode.load().html_report(
                embeddable=True))
        except BaseException as e:
            print(traceback.format_exc())
            print(e)
            embedded_reports.append(
                f"<div>Failed to generate InspectCode report. Exception encountered:<br>\n{e}</div>")

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


if __name__ == "__main__":
    # argparse
    argparser = argparse.ArgumentParser()
    argparser.add_argument("--dry-run", action="store_true",
                           help="Dry-run everything but the report generation.")
    argparser.add_argument("--clean", action="store_true",
                           help="Clean the archive/output directories. If not set, some steps may be skipped if files are present (even if outdated).")
    argparser.add_argument("--package", action="store_true",
                           help="Create full cooked game packages. If not set, the BuildGraph target will be set to only compile C++ code for editor and game.")
    argparser.add_argument("--bg-shared-storage",
                           default="F:\\BuildGraphStorage", help="Shared storage directory for BuildGraph intermediates")
    argparser.add_argument("--bg-network-share",
                           default="F:\\BuildGraphNetworkShare", help="Network directory for BuildGraph artifacts including the generated build reports.")
    argparser.add_argument("--unique-build-id", default=None,
                           help="Unique ID to use for BuildGraph, version numbers, etc.")
    argparser.add_argument("--game-target-name", default=None,
                           help="Name of the game targets. By default the game is autodetected from the current directory tree.")
    argparser.add_argument("--skip-bg", action="store_true",
                           help="Skip the BuildGraph execution. Useful if you want to test static analysis and automation tests only.")
    argparser.add_argument("--all", action="store_true",
                           help="Should game packages for all platforms be built? Default: Only Win64.")
    argparser.add_argument("--static-analysis", action="store_true",
                           help="Run static code analysis on the project. Not reccommended if you're running the build for multiple engine versions / platforms, "
                           "because it significantly increases build times.")
    argparser.add_argument("--engine-versions", default="",
                           help="Semicolon separated engine identifiers. If supplied, the build is ran multiple times, once for each engine version. "
                           "This is useful to confirm if the build succeeds for different engine versions.")
    args = argparser.parse_args()

    print("ARGS:", args)

    step_header("Setup", True)
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

    if len(args.engine_versions) > 0:
        unique_build_without_engine_suffix = unique_build_id
        for engine_version in args.engine_versions.split(";"):
            ue.change_project_engine_association(engine_version)
            unique_build_id = unique_build_without_engine_suffix + "_" + engine_version
            main()
    else:
        main()
