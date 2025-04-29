# 715 -> 632

import glob
import os
from argparse import ArgumentParser
from pathlib import Path

from alive_progress import alive_bar
from openunrealautomation.unrealengine import UnrealEngine
from openunrealautomation.util import force_rmtree

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    ue = UnrealEngine.create_from_parent_tree(
        os.path.realpath(os.path.dirname(__file__)))

    ue.environment.engine_root
    all_intermediate_dirs = set()
    for glob_line in glob.glob(f"{ue.environment.engine_root}/**/Intermediate/"):
        all_intermediate_dirs.add(glob_line)

    for glob_line in glob.glob(f"{ue.environment.engine_root}/**/Plugins/**/Intermediate/"):
        all_intermediate_dirs.add(glob_line)

    for glob_line in glob.glob(f"{ue.environment.engine_root}/**/Plugins/**/**/Intermediate/"):
        all_intermediate_dirs.add(glob_line)

    print(f"Found {len(all_intermediate_dirs)} intermediate directories")

    dirs_to_clean = set()

    if args.all:
        dirs_to_clean = all_intermediate_dirs
    else:
        platforms_to_clean = ["Linux", "PS5"]
        for platform in platforms_to_clean:
            platform_dirs = set()
            for intermediate_dir in all_intermediate_dirs:
                for glob_line in glob.glob(f"{intermediate_dir}Build\\{platform}"):
                    platform_dirs.add(glob_line)
                    dirs_to_clean.add(glob_line)
            print(
                f"Found {len(platform_dirs)} {platform} intermediate directories")

        targets_to_clean = ["UE4", "UE4Editor"]
        for target in targets_to_clean:
            target_dirs = set()
            for intermediate_dir in all_intermediate_dirs:
                for glob_line in glob.glob(f"{intermediate_dir}Build/Win64/{target}"):
                    target_dirs.add(glob_line)
                    dirs_to_clean.add(glob_line)
            print(
                f"Found {len(target_dirs)} Win64 {target} intermediate directories")

        # "Shipping" is dangerous to include, because most tools are compiled in shipping
        configs_to_clean = ["Debug", "DebugGame"]
        for config in configs_to_clean:
            config_dirs = set()
            for intermediate_dir in all_intermediate_dirs:
                for glob_line in glob.glob(f"{intermediate_dir}Build/Win64/**/{config}"):
                    config_dirs.add(glob_line)
                    dirs_to_clean.add(glob_line)
                for glob_line in glob.glob(f"{intermediate_dir}Build/Win64/**/**/{config}"):
                    config_dirs.add(glob_line)
                    dirs_to_clean.add(glob_line)
            print(
                f"Found {len(config_dirs)} Win64 {config} intermediate directories")

    def dir_size(root_dir):
        root_directory = Path(root_dir)
        return sum(f.stat().st_size for f in root_directory.glob('**/*') if f.is_file())
    bytes_to_clean = sum(dir_size(dir)for dir in dirs_to_clean)
    gb_to_clean = float(bytes_to_clean) / float(1073741824)
    print(
        f"Found {len(dirs_to_clean)} total dirs to clean -> {gb_to_clean} GB")

    if args.clean:
        with alive_bar(len(dirs_to_clean), title="Clean directories") as update_progress_bar:
            for dir in dirs_to_clean:
                update_progress_bar()
                force_rmtree(dir)
