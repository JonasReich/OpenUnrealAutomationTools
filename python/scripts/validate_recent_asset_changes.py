"""
Validate the recent uasset changes in this workspace.
Makes some opinionated limitations like no validation of external actor files in the current version.
This is mainly meant to keep it simple - but this version of the script is probably more useful as a sample than the final version to use.
Relies on OpenUnrealUtilities.
"""

import datetime
import json
import os

from openunrealautomation.core import OUAException, UnrealBuildConfiguration, UnrealBuildTarget
from openunrealautomation.p4 import UnrealPerforce
from openunrealautomation.unrealengine import UnrealEngine
from openunrealautomation.util import write_text_file


def generate_assets_list():
    changed_files = p4.get_current_stream_changed_files_since(
        datetime.timedelta(days=4))
    disallowed_patterns = [
        "__ExternalActors__",
    ]
    allowed_patterns = [
        content_dir_local_path,
        ".uasset"
    ]
    filtered_files = [file for file in changed_files
                      if any(pattern in file for pattern in allowed_patterns)]
    print(f"Found {len(filtered_files)} uassets in local Content directory")
    filtered_files = [file for file in filtered_files if not any(
        pattern in file for pattern in disallowed_patterns)]
    print(
        f"Filtered down to {len(filtered_files)} uassets in local Content directory that match restricted path criteria")

    asset_paths = [file.replace(content_dir_depot_location, "/Game",
                                1).removesuffix(".uasset") for file in filtered_files]

    write_text_file(asset_list_path, "\n".join(asset_paths))


def run_validation():
    ue.build(UnrealBuildTarget.EDITOR, UnrealBuildConfiguration.DEVELOPMENT)
    ue.run_commandlet("OUUValidateAssetList", arguments=[
        f"-AssetList={asset_list_path}", f"-ValidationReport={report_path}"],
        raise_on_error=False)


def print_issues():
    print("Reading issues from", report_path, "...")
    with open(report_path, "r", encoding="utf-8") as report_file:
        report = dict(json.load(report_file))
        asset: str
        error: str
        if len(report) == 0:
            print("No errors detected")
        else:
            print(f"{len(report)} errors detected:")

        failed_to_find_user_assets = []
        for asset, error in report.items():
            asset_filename = asset.replace(
                "/Game", content_dir_depot_location) + ".uasset"

            first_error_line = error.splitlines()[0]
            change_user = p4.get_last_change(
                asset_filename, ignore_copies=True)

            if change_user:
                username = change_user[1]
                p4_user_info = p4_user_map.get(username)
                if p4_user_info:
                    p4_user_info.email
                    change_source_str = f"{username} @{change_user[0]}" if change_user else "unknown @?"
                    RED = "\033[1;31m"
                    print(
                        f"{RED}ERROR: {asset_filename} by {change_source_str}:\n       {first_error_line}")

                    continue
            failed_to_find_user_assets.append(asset_filename)

        failed_to_find_asset_list = '\n'.join(failed_to_find_user_assets)
        failed_to_find_error = f"Failed to find users for {len(failed_to_find_user_assets)} assets with errors:\n{failed_to_find_asset_list}"
        print(f"{RED}ERROR: }{failed_to_find_error}")


p4 = UnrealPerforce()
p4_user_map = p4.get_user_map()
ue = UnrealEngine.create_from_parent_tree(os.getcwd())

if not ue.environment.has_open_unreal_utilities():
    raise OUAException("This script requires the OpenUnrealUtilities plugin")

asset_list_path = f"{ue.environment.project_root}/AssetsToValidate.txt"
report_path = os.path.join(ue.environment.project_root,
                           "Saved/ChangelistAssetValidation.json")

content_dir_local_path = os.path.join(
    ue.environment.project_root, "Content")
content_dir_depot_location = p4.get_depot_location(content_dir_local_path)

generate_assets_list()
run_validation()
print_issues()
