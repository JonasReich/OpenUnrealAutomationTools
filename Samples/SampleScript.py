"""
This sample shows how to use the python tools.
It assumes the package located in ../python/* (relative to this file)
is installed in your python environment under its default name (i.e. openunrealautomation).

The python tools don't have any dependencies to the Powershell tools.
"""

import argparse
import os

from openunrealautomation.automationtest import run_tests
from openunrealautomation.core import (UnrealBuildConfiguration,
                                       UnrealBuildTarget)
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

    step_header("Build")
    ue.build(target=UnrealBuildTarget.EDITOR,
             build_configuration=UnrealBuildConfiguration.DEVELOPMENT)

    step_header("Automation Tests")
    run_tests(ue, generate_coverage_reports=True)

    exit()

    step_header("Blueprint Compile")
    # ue5 has a bp that fails to compile in this folder
    ignore_folder_arg = "-IgnoreFolder=/Engine/Tutorial/InWorldBlueprintEditing"
    ue.run_commandlet("CompileAllBlueprints", arguments=[ignore_folder_arg])

    step_header("Fix Redirectors")
    # Other useful flags:
    # -SKIPMAPS, -MAPSONLY -SkipDeveloperFolders -NODEV -OnlyDeveloperFolders
    ue.run_commandlet("ResavePackages", arguments=[
                      "-fixupredirects", "-autocheckout", "-PROJECTONLY"])
