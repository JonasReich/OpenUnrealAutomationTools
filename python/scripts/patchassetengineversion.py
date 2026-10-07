"""
Patch the engine version stored in the package file summary of uasset/umap files.

Useful to load assets that were saved with a newer engine version (or a licensee build of the engine)
in an older/different engine, which otherwise fails with an error like this:
    Current EngineVersion: 5.7.1-48512491+++UE5+Release-5.7 (Licensee=0). Package EngineVersion: 5.7.4-122084+++TQ2S+tq2-main (Licensee=1)

Both the SavedByEngineVersion and CompatibleWithEngineVersion are overwritten in place.
Only the fixed size fields (major, minor, patch, changelist + licensee flag) are patched. The branch name is only
replaced if the new name has the exact same serialized length, because changing the size of the header would require
fixing up all offsets stored in the package.

This does NOT convert any serialized data. It only makes sense if the asset data is actually compatible with the target engine
(e.g. same object/custom versions), so use with care and keep a backup / version control around.
"""

import argparse
import os
import shutil
import struct
from typing import List, Optional, Tuple

from openunrealautomation.environment import UnrealEnvironment
from openunrealautomation.version import UnrealVersion, UnrealVersionComparison

PACKAGE_FILE_TAG = 0x9E2A83C1
LICENSEE_BIT = 0x80000000
ASSET_EXTENSIONS = [".uasset", ".umap"]
# Directories that are skipped when searching directories recursively.
# They mostly contain cooked or temporary packages that can't be patched and would only add error spam.
SKIPPED_DIRS = {"saved", "intermediate"}
# The engine versions are always located in the package summary at the beginning of the file.
# Limit the search range so we don't accidentally match any export data.
MAX_SEARCH_RANGE = 0x10000


class SerializedEngineVersion():
    """FEngineVersion as serialized in a package file summary"""

    offset: int
    version: UnrealVersion
    # Offset and serialized size of the branch name FString (including length prefix)
    branch_offset: int
    branch_size: int

    @staticmethod
    def try_parse(data: bytes, offset: int) -> Optional['SerializedEngineVersion']:
        # uint16 Major, uint16 Minor, uint16 Patch, uint32 Changelist, FString Branch
        if offset + 14 > len(data):
            return None
        major, minor, patch, changelist, branch_len = struct.unpack_from("<HHHIi", data, offset)
        if not (1 <= major <= 10 and minor < 100 and patch < 100):
            return None

        branch_offset = offset + 10
        string_start = branch_offset + 4
        if branch_len > 0:
            if branch_len > 512 or string_start + branch_len > len(data):
                return None
            raw = data[string_start:string_start + branch_len]
            if raw[-1] != 0 or not all(0x20 <= c < 0x7F for c in raw[:-1]):
                return None
            branch = raw[:-1].decode("ascii")
            branch_size = 4 + branch_len
        elif branch_len < 0:
            # Negative length -> UTF-16 string
            num_chars = -branch_len
            if num_chars > 512 or string_start + num_chars * 2 > len(data):
                return None
            raw = data[string_start:string_start + num_chars * 2]
            if raw[-2:] != b"\0\0":
                return None
            try:
                branch = raw[:-2].decode("utf-16-le")
            except UnicodeDecodeError:
                return None
            if not branch.isprintable():
                return None
            branch_size = 4 + num_chars * 2
        else:
            branch = ""
            branch_size = 4

        result = SerializedEngineVersion()
        result.offset = offset
        result.version = UnrealVersion(major_version=major,
                                       minor_version=minor,
                                       patch_version=patch,
                                       changelist=changelist & ~LICENSEE_BIT,
                                       is_licensee_version=bool(changelist & LICENSEE_BIT),
                                       branch_name=branch)
        result.branch_offset = branch_offset
        result.branch_size = branch_size
        return result

    @property
    def end_offset(self) -> int:
        return self.branch_offset + self.branch_size

    def __str__(self) -> str:
        return f"{self.version} (Licensee={int(self.version.is_licensee_version)})"


def serialize_branch_name(branch: str) -> bytes:
    if branch.isascii():
        encoded = branch.encode("ascii") + b"\0"
        return struct.pack("<i", len(encoded)) + encoded
    encoded = branch.encode("utf-16-le") + b"\0\0"
    return struct.pack("<i", -(len(encoded) // 2)) + encoded


def version_to_string(version: UnrealVersion) -> str:
    return f"{version} (Licensee={int(version.is_licensee_version)})"


def find_engine_versions(data: bytes) -> Tuple[SerializedEngineVersion, SerializedEngineVersion]:
    """Find SavedByEngineVersion and CompatibleWithEngineVersion, which are serialized back to back."""
    if len(data) < 8 or struct.unpack_from("<I", data, 0)[0] != PACKAGE_FILE_TAG:
        raise ValueError("Not an uncooked package file (package file tag mismatch)")

    search_end = min(len(data), MAX_SEARCH_RANGE)
    for offset in range(8, search_end):
        saved_by = SerializedEngineVersion.try_parse(data, offset)
        if saved_by is None:
            continue
        compatible_with = SerializedEngineVersion.try_parse(data, saved_by.end_offset)
        if compatible_with is None or compatible_with.version.major_version != saved_by.version.major_version:
            continue
        return saved_by, compatible_with

    raise ValueError("Failed to locate engine versions in package file summary")


def patch_engine_version(data: bytearray, serialized: SerializedEngineVersion, target: UnrealVersion) -> List[str]:
    warnings = []
    changelist = target.changelist & ~LICENSEE_BIT
    if target.is_licensee_version:
        changelist |= LICENSEE_BIT
    struct.pack_into("<HHHI", data, serialized.offset,
                     target.major_version, target.minor_version, target.patch_version, changelist)

    if target.branch_name != serialized.version.branch_name:
        new_branch = serialize_branch_name(target.branch_name)
        if len(new_branch) == serialized.branch_size:
            data[serialized.branch_offset:serialized.end_offset] = new_branch
        else:
            warnings.append(f"Kept branch name '{serialized.version.branch_name}', "
                            f"because '{target.branch_name}' has a different serialized length")
    return warnings


def collect_files(paths: List[str]) -> List[str]:
    result = []
    for path in paths:
        if os.path.isdir(path):
            for dir_path, dir_names, file_names in os.walk(path):
                # Prune in place so os.walk doesn't descend into skipped directories
                dir_names[:] = [name for name in dir_names if name.lower() not in SKIPPED_DIRS]
                result += [os.path.join(dir_path, name) for name in file_names
                           if os.path.splitext(name)[1].lower() in ASSET_EXTENSIONS]
        elif os.path.isfile(path):
            result.append(path)
        else:
            print(f"WARNING: '{path}' does not exist")
    return sorted(set(os.path.normpath(file) for file in result))


def get_target_versions(args, files: List[str]) -> Tuple[UnrealVersion, UnrealVersion]:
    """Returns (saved_by, compatible_with) target versions"""
    if args.version:
        saved_by = UnrealVersion.create_from_string(args.version, is_licensee_version=args.licensee)
        compatible_with = UnrealVersion.create_from_string(args.compatible_version, is_licensee_version=args.licensee) \
            if args.compatible_version else saved_by
        return saved_by, compatible_with

    if args.engine_root:
        env = UnrealEnvironment.create_from_engine_root(args.engine_root)
    elif args.project_root:
        env = UnrealEnvironment.create_from_project_root(args.project_root)
    else:
        # Prefer the first passed path (e.g. a workspace dir containing a uproject) over the first found file
        first_path = os.path.abspath(args.paths[0])
        env = UnrealEnvironment.create_from_parent_tree(first_path if os.path.isdir(first_path) else os.path.dirname(first_path))

    saved_by = env.build_version.get_current()
    compatible_with = env.build_version.get_compatible()
    # The serialized compatible version uses the compatible changelist as its changelist
    compatible_with.changelist = compatible_with.compatible_changelist
    return saved_by, compatible_with


if __name__ == "__main__":
    argparser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    argparser.add_argument("paths", nargs="+",
                           help="uasset/umap files or directories (searched recursively) to patch")
    version_group = argparser.add_argument_group("target version",
                                                 "By default the version of the engine associated with the first file is used "
                                                 "(found by searching the parent directories for a project or engine root).")
    version_group.add_argument("--version",
                               help="Explicit target version, e.g. '5.7.1-48512491+++UE5+Release-5.7' (format as printed in the version mismatch error)")
    version_group.add_argument("--compatible-version",
                               help="Explicit target compatible version. Defaults to --version")
    version_group.add_argument("--licensee", action="store_true",
                               help="Mark the explicit --version as licensee version")
    version_group.add_argument("--engine-root", help="Read the target version from this engine's Build.version")
    version_group.add_argument("--project-root", help="Read the target version from the engine associated with this project")
    argparser.add_argument("--all", action="store_true",
                           help="Also patch files that were saved with an older (or the same) version than the target version. "
                           "By default only files that are not compatible with the target version are patched")
    argparser.add_argument("--dry-run", action="store_true", help="Only print what would be changed")
    argparser.add_argument("--backup", action="store_true", help="Write a <file>.bak copy before patching")
    args = argparser.parse_args()

    files = collect_files(args.paths)
    if len(files) == 0:
        argparser.error("No asset files found")

    target_saved_by, target_compatible_with = get_target_versions(args, files)
    print(f"Target SavedByEngineVersion:        {version_to_string(target_saved_by)}")
    print(f"Target CompatibleWithEngineVersion: {version_to_string(target_compatible_with)}")

    num_patched = 0
    num_failed = 0
    for file in files:
        with open(file, "rb") as f:
            data = bytearray(f.read())
        try:
            saved_by, compatible_with = find_engine_versions(data)
        except ValueError as e:
            print(f"ERROR: {file}: {e}")
            num_failed += 1
            continue

        # Same comparison as the engine: changelists are only compared if the licensee flags match
        is_newer = UnrealVersion.get_newest(compatible_with.version, target_saved_by) == UnrealVersionComparison.FIRST
        if not (args.all or is_newer):
            continue

        warnings =patch_engine_version(data, saved_by, target_saved_by) + \
            patch_engine_version(data, compatible_with, target_compatible_with)

        with open(file, "rb") as f:
            unchanged = f.read() == data
        if unchanged:
            print(f"{file}: already up to date")
            continue

        print(f"{file}:\n"
              f"    SavedBy:        {saved_by}\n"
              f"    CompatibleWith: {compatible_with}")
        for warning in sorted(set(warnings)):
            print(f"    WARNING: {warning}")

        if args.dry_run:
            continue

        try:
            if args.backup:
                shutil.copy2(file, file + ".bak")
            with open(file, "r+b") as f:
                f.write(data)
            num_patched += 1
        except PermissionError:
            print(f"    ERROR: No write access. Is the file read-only or opened by the editor?")
            num_failed += 1

    print(f"\nPatched {num_patched} file(s), {num_failed} failure(s)" + (" (dry run)" if args.dry_run else ""))
    exit(1 if num_failed > 0 else 0)
