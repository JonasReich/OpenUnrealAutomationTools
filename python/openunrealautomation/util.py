"""
Utility functions
"""

import os
import pathlib
import platform
import shutil
from typing import Generator

from openunrealautomation.core import *


def walklevel(top, topdown=True, onerror=None, followlinks=False, level=1):
    """
    Copy of os.walk() with additional level parameter.
    @param level    How many sub-directories to traverse
    """
    # From https://stackoverflow.com/a/234329
    top = top.rstrip(os.path.sep)
    assert os.path.isdir(top)
    num_sep = top.count(os.path.sep)
    for root, dirs, files in os.walk(top, topdown=topdown, onerror=onerror, followlinks=followlinks):
        yield root, dirs, files
        num_sep_this = root.count(os.path.sep)
        if num_sep + level <= num_sep_this:
            del dirs[:]


def walkparents(dir: str) -> Generator[str, None, None]:
    """Go through all parent directories of the given dir."""
    path = pathlib.Path(dir)
    while True:
        yield str(path)
        if (path.parent == path):
            break
        path = path.parent


def which_checked(command, display_name) -> str:
    """
    Get the executable path of a CLI command that is on PATH.
    Will raise an exception if the command is not found.

    Example:
    which_checked("powershell") -> "C:\\windows\\System32\\WindowsPowerShell\\v1.0\\powershell.EXE"
    """
    exe_path = shutil.which(command)
    if exe_path is None:
        raise OUAException(
            f"{command} ({display_name}) is not installed or cannot be found via PATH environment.")
    return exe_path


def set_system_env_var(name, value) -> None:
    """
    Set a system wide environment variable (like PATH).
    Does not affect the current environment, but all future commands.
    """
    if platform.system() != "Windows":
        raise NotImplementedError(
            "set_system_env_var() is only implemented on Windows")
    print(f"Setting environment variable: {name}={value}")
    os.system(f"setx {name} {value}")
    return
