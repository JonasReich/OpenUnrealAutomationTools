from enum import Enum
from locale import atoi
from re import search

from openunrealautomation.core import OUAException
from openunrealautomation.descriptor import UnrealDescriptor
from openunrealautomation.p4 import UnrealPerforce


def _try_atoi(str) -> int:
    if not str is None:
        return atoi(str)
    else:
        return 0


class UnrealVersionComparison(Enum):
    NEITHER = 1
    FIRST = 2
    SECOND = 3


class UnrealVersion():
    """
    Python wrapper for Unreal Engine Build.version (see C++ class FEngineVersionBase)
    """

    major_version: int = 0
    minor_version: int = 0
    patch_version: int = 0
    changelist: int = 0
    is_licensee_version: bool = False
    is_promoted_build: bool = False
    branch_name: str = ""

    def __init__(self):
        pass

    @staticmethod
    def create_from_string(version_string: str, is_licensee_version: bool = False) -> 'UnrealVersion':
        version = UnrealVersion()
        regex = "^(?P<MajorVersion>\\d+)(\\.(?P<MinorVersion>\\d+)(\\.(?P<PatchVersion>\\d+)(-(?P<Changelist>\\d+)(\\+(?P<BranchName>.+))?)?)?)?$"
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
    def get_newest(first, second) -> UnrealVersionComparison:
        if not first.major_version == second.major_version:
            return UnrealVersionComparison.FIRST if first.major_version > second.major_version else UnrealVersionComparison.SECOND
        if not first.minor_version == second.minor_version:
            return UnrealVersionComparison.FIRST if first.minor_version > second.minor_version else UnrealVersionComparison.SECOND
        if not first.patch_version == second.patch_version:
            return UnrealVersionComparison.FIRST if first.patch_version > second.patch_version else UnrealVersionComparison.SECOND
        if first.is_licensee_version == second.is_licensee_version and first.has_changelist() and second.has_changelist() and not first.changelist == second.changelist:
            return UnrealVersionComparison.FIRST if first.changelist > second.changelist else UnrealVersionComparison.SECOND
        return UnrealVersionComparison.NEITHER


class UnrealVersionDescriptor(UnrealDescriptor):
    """
    Descriptor helper to read version file
    """

    @classmethod
    def get_extension(cls) -> str:
        return ".version"

    def update_local_version(self,
                             cl: int = None,
                             compatible_cl: int = None,
                             build_id: str = None,
                             promoted: bool = False,
                             branch: str = None,
                             licensee: bool = True) -> None:
        """
        Update the local version file (equivalent to UpdateLocalVersion UAT script).
        """
        if cl is None:
            cl = UnrealPerforce.get_current_cl()

        UnrealPerforce.sync(self.file_path, cl=cl, force=True)
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
            branch = UnrealPerforce.get_current_stream()
        branch = branch.replace("/", "+")
        version_json["BranchName"] = branch

        if build_id:
            version_json["BuildId"] = build_id

        UnrealPerforce.sync(self.file_path, cl=0)
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
