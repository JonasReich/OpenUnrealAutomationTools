from openunrealautomation.version import *

def _test_version_string_conversion(test_string, expected_result) -> None:
    result = str(UnrealVersion.create_from_string(test_string))
    assert expected_result == result


def _test_version_string_conversion_SAME(test_string) -> None:
    _test_version_string_conversion(test_string, test_string)


def _test_version_compatibility_inner(licensee_a, licensee_b, version_a, version_b, expected_result):
    a = UnrealVersion.create_from_string(version_a, licensee_a)
    b = UnrealVersion.create_from_string(version_b, licensee_b)
    result = a.is_compatible_with(b)
    assert result == expected_result


def _test_version_compatibility(matching_licensee, version_a, version_b, expected_result):
    if (matching_licensee):
        _test_version_compatibility_inner(
            True, True, version_a, version_b, expected_result)
        _test_version_compatibility_inner(
            False, False, version_a, version_b, expected_result)
    else:
        _test_version_compatibility_inner(
            True, False, version_a, version_b, expected_result)
        _test_version_compatibility_inner(
            False, True, version_a, version_b, expected_result)


def test_version_string_conversion():
    # Check that version string conversion works at module startup
    _test_version_string_conversion_SAME("5.0.2-0+++UE5+Release-5.0")
    _test_version_string_conversion_SAME("5.0.2-0")
    _test_version_string_conversion("5.0.2", "5.0.2-0")
    _test_version_string_conversion("5.0", "5.0.0-0")
    _test_version_string_conversion("5", "5.0.0-0")

def test_version_compatibilit_matching():
    # test matching licensee version compatibility
    _test_version_compatibility(True, "1.2.3-10", "1.2.3-9", True)
    _test_version_compatibility(True, "1.2.3-10", "1.2.3-11", False)
    _test_version_compatibility(True, "1.2.3-0", "1.2.3-11", True)
    _test_version_compatibility(True, "1.2.3-10", "1.2.3-0", True)
    _test_version_compatibility(True, "1.2.4-10", "1.2.3-10", True)
    _test_version_compatibility(True, "1.2.3-10", "1.2.4-10", False)
    _test_version_compatibility(True, "1.3.3-10", "1.2.3-10", True)
    _test_version_compatibility(True, "1.2.3-10", "1.3.3-10", False)

def test_version_compatibilit_non_matching():
    # test non-matching licensee version compatibility
    # -> Ignore build number mismatches
    _test_version_compatibility(False, "1.2.3-10", "1.2.3-9", True)
    _test_version_compatibility(False, "1.2.3-10", "1.2.3-11", True)
    _test_version_compatibility(False, "1.2.3-0", "1.2.3-11", True)
    _test_version_compatibility(False, "1.2.3-10", "1.2.3-0", True)
    _test_version_compatibility(False, "1.2.4-10", "1.2.3-10", True)
    _test_version_compatibility(False, "1.2.3-10", "1.2.4-10", False)
    _test_version_compatibility(False, "1.3.3-10", "1.2.3-10", True)
    _test_version_compatibility(False, "1.2.3-10", "1.3.3-10", False)
