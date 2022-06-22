from enum import Enum
from re import search

from openunrealautomation.core import OUAException
from openunrealautomation.descriptor import UnrealDescriptor


class UnrealVersionComparison(Enum):
    NEITHER = 1
    FIRST = 2
    SECOND = 3


class UnrealVersionDescriptor(UnrealDescriptor):
    """
    Descriptor helper to read version file
    """

    @classmethod
    def get_extension(cls) -> str:
        return ".version"


class UnrealVersion():
    """
    Python wrapper for Unreal Engine Build.version (see C++ class FEngineVersionBase)
    """

    major_version: int = 0
    minor_version: int = 0
    patch_version: int = 0
    changelist: int = 0
    compatible_changelist: int = 0
    is_licensee_version: bool = False
    is_promoted_build: bool = False
    branch_name: str = ""

    def __init__(self):
        pass

    @staticmethod
    def create_from_file(version_file_path: str) -> 'UnrealVersion':
        version_json = UnrealVersionDescriptor(version_file_path).read()
        version = UnrealVersion()
        version.major_version = version_json["MajorVersion"]
        version.minor_version = version_json["MinorVersion"]
        version.patch_version = version_json["PatchVersion"]
        version.changelist = version_json["Changelist"]
        version.compatible_changelist = version_json["CompatibleChangelist"]
        version.is_licensee_version = version_json["IsLicenseeVersion"]
        version.is_promoted_build = version_json["IsPromotedBuild"]
        version.branch_name = version_json["BranchName"]
        return version

    @staticmethod
    def create_from_string(version_string: str) -> 'UnrealVersion':
        version = UnrealVersion()
        regex = "^(?P<MajorVersion>\\d+)(\\.(?P<MinorVersion>\\d+)(\\.(?P<PatchVersion>\\d+)(-(?P<Changelist>\\d+)(\\+(?P<BranchName>.+))?)?)?)?$"
        match = search(regex, version_string)
        if match is None:
            raise OUAException(
                f"Failed to parse UnrealVersion from string '{version_string}'")
        version.major_version = match.group("MajorVersion")
        version.minor_version = match.group("MinorVersion")
        if version.minor_version is None:
            version.minor_version = 0
        version.patch_version = match.group("PatchVersion")
        if version.patch_version is None:
            version.patch_version = 0
        version.changelist = match.group("Changelist")
        if version.changelist is None:
            version.changelist = 0
        version.branch_name = match.group("BranchName")
        if version.branch_name is None:
            version.branch_name = ""

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
        return UnrealVersion.get_newest(self, other) is not UnrealVersionComparison.SECOND

    @staticmethod
    def get_newest(first, second) -> UnrealVersionComparison:
        if not first.major_version == second.major_version:
            return UnrealVersionComparison.FIRST if first.major_version > second.major_version else UnrealVersionComparison.SECOND
        if not first.minor_version == second.minor_version:
            return UnrealVersionComparison.FIRST if first.minor_version > second.minor_version else UnrealVersionComparison.SECOND
        if not first.patch_version == second.patch_version:
            return UnrealVersionComparison.FIRST if first.patch_version > second.patch_version else UnrealVersionComparison.SECOND
        if first.is_licensee_version == second.is_licensee_version and first.has_changelist() and second.has_changelist() and not first.changelist != second.changelist:
            return UnrealVersionComparison.FIRST if first.changelist > second.changelist else UnrealVersionComparison.SECOND
        return UnrealVersionComparison.NEITHER


def _test_version_string_conversion(test_string, expected_result) -> None:
    result = str(UnrealVersion.create_from_string(test_string))
    if not expected_result == result:
        raise OUAException(
            f"Conversion of {test_string} to UnrealVersion returned invalid result {result}; expected {expected_result}")


def _test_version_string_conversion_SAME(test_string) -> None:
    _test_version_string_conversion(test_string, test_string)


# Check that version string conversion works at module startup
_test_version_string_conversion_SAME("5.0.2-0+++UE5+Release-5.0")
_test_version_string_conversion_SAME("5.0.2-0")
_test_version_string_conversion("5.0.2", "5.0.2-0")
_test_version_string_conversion("5.0", "5.0.0-0")
_test_version_string_conversion("5", "5.0.0-0")
