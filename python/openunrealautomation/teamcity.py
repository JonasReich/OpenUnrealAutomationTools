"""
Utility funcs to make TeamCity integration of build scripts written with OpenUnrealAutomation more smooth.
e.g. utility functions / decorators to send service messages.
"""

import os
import sys
from functools import wraps
from typing import Callable, Dict, Union

from openunrealautomation.core import OUAException

_TC_MESSAGES_ARG = "--teamcity-messages"

# enable service messages if TEAMCITY_VERSION is set in environment OR
# if "--tc-messages" flag is present on the command line
_enable_service_messages = (os.environ.get(
    "TEAMCITY_VERSION") is not None) or (_TC_MESSAGES_ARG in sys.argv)
if _enable_service_messages:
    print("TeamCity service messages enabled")


def enable_teamcity_service_messages() -> None:
    """
    Enable TeamCity service messages for the current script run.
    This is useful if you want to enable service messages conditionally at runtime.
    """
    global _enable_service_messages
    _enable_service_messages = True


def service_message(message_name: str, value_or_named_attributes: Union[None, str, Dict[str, str]]) -> None:
    def _escape_characters(in_str: str) -> str:
        # Reference  escaped characters https://www.jetbrains.com/help/teamcity/service-messages.html#Escaped+Values
        # The only char missing is
        # \uNNNN (unicode symbol with code 0xNNNN) -> |0xNNNN
        escape_chars = [("|", "||"), ("'", "|'"),
                        ("\n", "|n"), ("[", "|["), ("]", "|]")]
        for from_char, to_char in escape_chars:
            in_str = in_str.replace(from_char, to_char)
        return in_str

    # Do not print service messages if
    if _enable_service_messages == False:
        return
    if value_or_named_attributes is None:
        value_str = ""
    elif isinstance(value_or_named_attributes, dict):
        attribute_strings = []
        if len(value_or_named_attributes) == 0:
            raise OUAException(
                "Service message with attribute list needs at least one key-value-pair.")
        for name, value in value_or_named_attributes.items():
            for char in name:
                if char.isspace():
                    raise OUAException(
                        "Service message attribute keys may not contain any whitespace")
            value = _escape_characters(value)
            attribute_strings.append(f"{name}='{value}'")
        value_str = " ".join(
            attribute_strings)
    else:
        value_str = f"'{_escape_characters(value_or_named_attributes)}'"

    print(f"##teamcity[{message_name} {value_str}]",
          # Flush the lines, so TeamCity is more like to be updated when we ask for stats via RestAPI
          flush=True)


def set_build_parameter(name: str, value: str) -> None:
    """
    Set a build parameter. Values are only published after the build has finished.
    """
    service_message("setParameter", {"name": name, "value": value})


def set_build_number(value: str) -> None:
    """
    Set the build number.
    You can use the existing build number in the string by including '{build.number}' as substring.
    """
    service_message("buildNumber", value)


def report_build_statistic(key: str, value: Union[int, float]) -> None:
    """Report a number for stat tracking (e.g. issue counts, file sizes, etc)"""
    service_message("buildStatisticValue", {"key": key, "value": str(value)})


def publish_artifact(path: str) -> None:
    """
    Publish a build artifact while the build is running.
    The path is a file on disk. May optionally be augmented with wildcards and destination according to Artifact Paths specifications:
    https://www.jetbrains.com/help/teamcity/configuring-general-settings.html#Artifact+Paths
    """
    service_message("publishArtifacts", path)


def disable_service_messages() -> None:
    """
    Use to pause processing of service messages. All future service messages will be ignored
    by TeamCity until enable_service_messages() is called.
    """
    service_message("disableServiceMessages", None)


def enable_service_messages() -> None:
    """
    Use to restore processing of service messages after you disabled them using disable_service_messages().
    """
    service_message("enableServiceMessages", None)


def report_build_problem(description: str) -> None:
    """
    Use to report an actionable build problem to TeamCity.
    This FAILS the build, so only use this for critical issues (like compile errors, critical assets load issues, etc).
    """
    service_message("buildProblem ", {"description": description})


def stop_build(comment: str = "unspecified reason", readd_to_queue: bool = False) -> None:
    """
    Stop a build. Should be used very sparingly, but in conjunction with readding it to the queue might be worth it.
    """
    service_message("buildStatisticValue", {
                    "comment": comment,
                    "readdToQueue": str(readd_to_queue).lower()})


def add_build_tag(tag: str) -> None:
    service_message("addBuildTag", tag)


def remove_build_tag(tag: str) -> None:
    service_message("removeBuildTag", tag)


class TeamCityProgressStep():
    """
    Context manager that reports progress when entering / exiting a scope. Use with 'with' statement:
    ```
    with TeamCityProgressStep("first build step"):
        # execute the first build step...
    ```
    """

    def __init__(self, step_name: str):
        self.step_name = step_name

    def __enter__(self):
        service_message("progressStart", self.step_name)

    def __exit__(self, exc_type, exc_val, exc_tb):
        service_message("progressFinish", self.step_name)


def teamcity_progress_step(step_name: str):
    """Function decorator that reports progress when entering / exiting the function."""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with TeamCityProgressStep(step_name):
                return func(*args, **kwargs)
        return wrapper
    return decorator


@teamcity_progress_step("make some progress")
def __test_progress_marker(some_arg: float, throw: bool):
    if throw:
        raise FileNotFoundError()
    print("some_arg: ", some_arg)


if __name__ == "__main__":
    # Always enable service messages when running this module as script
    _enable_service_messages = True

    # The basics
    service_message("hello", "world")
    service_message("hello", {"key": "value"})

    # Test progress markers
    __test_progress_marker(1.0, False)
    __test_progress_marker(2.0, True)

    print("this should never be executed")
