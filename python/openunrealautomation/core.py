from enum import Enum
import os
import pathlib
from typing import Generator


class OUAException(Exception):
    """
    Custom exception class for OpenUnrealAutomation
    """
    pass


class UnrealProgram(Enum):
    UAT = 0
    UBT = 1
    EDITOR = 2
    EDITOR_CMD = 3


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

def walkparents(dir:str) -> Generator[str, None, None]:
    """Go through all parent directories of the given dir."""
    path = pathlib.Path(dir)
    while True:
        yield str(path)
        if (path.parent == path):
            break
        path = path.parent
