"""
Utility funcs to make TeamCity integration of build scripts written with OpenUnrealAutomation more smooth.
e.g. utility functions / decorators to send service messages.
"""

import os
from functools import wraps
import sys
import argparse
from typing import Callable, Dict, Union

from openunrealautomation.core import OUAException

_TC_MESSAGES_ARG = "--teamcity-messages"

# enable service messages if TEAMCITY_VERSION is set in environment OR
# if "--tc-messages" flag is present on the command line
_enable_service_messages = (os.environ.get(
    "TEAMCITY_VERSION") is not None) or (_TC_MESSAGES_ARG in sys.argv)
if _enable_service_messages:
    print("TeamCity service messages enabled")


def add_service_message_argument(argparser: argparse.ArgumentParser):
    argparser.add_argument(_TC_MESSAGES_ARG, action="store_true",
                           help="If present, TeamCity service messages will be printed for some script steps. "
                           "Automatically deduced when running in a TeamCity build environment.")


def service_message(message_name: str, value_or_named_attributes: Union[None, str, Dict[str, str]]) -> None:
    # TODO check for escaped characters https://www.jetbrains.com/help/teamcity/service-messages.html#Escaped+Values

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
            if "'" in value:
                raise OUAException(
                    "Service message values may not contain single quotes")
            attribute_strings.append(f"{name}='{value}'")
        value_str = " ".join(
            attribute_strings)
    else:
        if "'" in value_or_named_attributes:
            raise OUAException(
                "Service message values may not contain single quotes")
        value_str = f"'{value_or_named_attributes}'"

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
