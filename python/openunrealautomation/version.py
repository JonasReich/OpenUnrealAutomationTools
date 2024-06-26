"""
Python implementation of Unreal Engine build versioning
"""

from enum import Enum
from functools import total_ordering
from locale import atoi
from re import search
from typing import Optional

from openunrealautomation.core import OUAException
from openunrealautomation.descriptor import UnrealDescriptor
from openunrealautomation.p4 import UnrealPerforce


def _try_atoi(str) -> int:
    if not str is None:
        return atoi(str)
    else:
        return 0


class UnrealVersionComparison(Enum):
    """
    When comparing two engine versions (A, B), does the result refer to...
    - neither A or B
    - only A (first)
    - only B (second)
    """

    NEITHER = 1
    FIRST = 2
    SECOND = 3


@total_ordering
class UnrealVersion():
    """
    One unique version of the engine. Used for version / compatibility checks.
    This is a python implementation of the FEngineVersionBase C++ class.
    """

    major_version: int
    minor_version: int
    patch_version: int
    changelist: int
    compatible_changelist: int
    is_licensee_version: bool
    is_promoted_build: bool
    branch_name: str

    def __init__(self, major_version=0, minor_version=0, patch_version=0, changelist=0, compatible_changelist=None, is_licensee_version=False, is_promoted_build=False, branch_name=""):
        self.major_version = major_version
        self.minor_version = minor_version
        self.patch_version = patch_version
        self.changelist = changelist
        self.compatible_changelist = compatible_changelist if compatible_changelist else changelist
        self.is_licensee_version = is_licensee_version
        self.is_promoted_build = is_promoted_build
        self.branch_name = branch_name

    @staticmethod
    def create_from_string(version_string: str, is_licensee_version: bool = False) -> 'UnrealVersion':
        version = UnrealVersion()
        regex = r"^(?P<MajorVersion>\d+)(\.(?P<MinorVersion>\d+)(\.(?P<PatchVersion>\d+)(-(?P<Changelist>\d+)(\+(?P<BranchName>.+))?)?)?)?$"
        match = search(regex, version_string)
        if match is None:
            raise OUAException(
                f"Failed to parse UnrealVersion from string '{version_string}'")
        version.major_version = atoi(match.group("MajorVersion"))
        version.minor_version = _try_atoi(match.group("MinorVersion"))
        version.patch_version = _try_atoi(match.group("PatchVersion"))
        version.changelist = _try_atoi(match.group("Changelist"))
        version.branch_name = match.group("BranchName")
        if version.branch_name is None:
            version.branch_name = ""
        version.is_licensee_version = is_licensee_version

        return version

    def __str__(self) -> str:
        base_version = f"{self.major_version}.{self.minor_version}.{self.patch_version}-{self.changelist}"
        if len(self.branch_name) > 0:
            return f"{base_version}+{self.branch_name}"
        return base_version

    def has_changelist(self) -> bool:
        return self.changelist > 0

    def is_compatible_with(self, other: 'UnrealVersion') -> bool:
        if not self.has_changelist() or not other.has_changelist():
            return True
        newest = UnrealVersion.get_newest(self, other)
        return newest is not UnrealVersionComparison.SECOND

    @staticmethod
    def get_newest(first: 'UnrealVersion', second: 'UnrealVersion') -> UnrealVersionComparison:
        if not first.major_version == second.major_version:
            return UnrealVersionComparison.FIRST if first.major_version > second.major_version else UnrealVersionComparison.SECOND
        if not first.minor_version == second.minor_version:
            return UnrealVersionComparison.FIRST if first.minor_version > second.minor_version else UnrealVersionComparison.SECOND
        if not first.patch_version == second.patch_version:
            return UnrealVersionComparison.FIRST if first.patch_version > second.patch_version else UnrealVersionComparison.SECOND
        if first.is_licensee_version == second.is_licensee_version and first.has_changelist() and second.has_changelist() and not first.changelist == second.changelist:
            return UnrealVersionComparison.FIRST if first.changelist > second.changelist else UnrealVersionComparison.SECOND
        return UnrealVersionComparison.NEITHER

    def __lt__(self, other) -> bool:
        newest = UnrealVersion.get_newest(self, other)
        return newest == UnrealVersionComparison.SECOND

    def __eq__(self, other) -> bool:
        newest = UnrealVersion.get_newest(self, other)
        return newest == UnrealVersionComparison.NEITHER


class UnrealVersionDescriptor(UnrealDescriptor):
    """
    Descriptor helper to read version file (Build.version)
    """

    @classmethod
    def get_extension(cls) -> str:
        return ".version"

    def update_local_version(self,
                             cl: Optional[int] = None,
                             compatible_cl: Optional[int] = None,
                             build_id: Optional[str] = None,
                             promoted: bool = False,
                             branch: Optional[str] = None,
                             licensee: bool = True) -> None:
        """
        Update the local version file (equivalent to UpdateLocalVersion UAT script).
        """
        p4 = UnrealPerforce()
        if cl is None:
            cl = p4.get_current_cl()

        p4.sync(self.file_path, cl=cl, force=True)
        version_json = self.read()
        version_json["Changelist"] = cl
        if compatible_cl:
            version_json["CompatibleChangelist"] = compatible_cl
        elif licensee != bool(
                version_json["IsLicenseeVersion"]):
            # Clear out the compatible changelist number; it corresponds to a different P4 server.
            version_json["CompatibleChangelist"] = 0

        # The boolean fields must be encoded as integers
        version_json["IsLicenseeVersion"] = int(licensee)
        version_json["IsPromotedBuild"] = int(promoted)

        if branch is None:
            branch = p4.get_current_stream()
        branch = branch.replace("/", "+")
        version_json["BranchName"] = branch

        if build_id:
            version_json["BuildId"] = build_id

        p4.sync(self.file_path, cl=0)
        self.write(version_json)

    def get_current(self) -> UnrealVersion:
        version_json = self.read()
        current_version = UnrealVersion()
        current_version.major_version = version_json["MajorVersion"]
        current_version.minor_version = version_json["MinorVersion"]
        current_version.patch_version = version_json["PatchVersion"]
        current_version.changelist = version_json["Changelist"]
        current_version.is_licensee_version = bool(
            version_json["IsLicenseeVersion"])
        current_version.is_promoted_build = bool(
            version_json["IsPromotedBuild"])
        current_version.branch_name = version_json["BranchName"]
        return current_version

    def get_compatible(self) -> UnrealVersion:
        compatible_version = self.get_current()
        version_json = self.read()
        compatible_version.compatible_changelist = version_json["CompatibleChangelist"]
        if not compatible_version.is_licensee_version:
            # Official epic engine versions = not licensee versions must always stay compatible with patch 0
            compatible_version.patch_version = 0
        return compatible_version
