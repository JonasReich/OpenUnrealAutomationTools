"""
Small core types (esp. Enums)
"""

from datetime import datetime
from enum import Enum


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
    PROGRAM = 4


class UnrealBuildConfiguration(Enum):
    DEBUG = 0, "Debug"
    DEBUG_GAME = 1, "DebugGame"
    DEVELOPMENT = 2, "Development"
    SHIPPING = 3, "Shipping"
    TEST = 4, "Test"

    def __str__(self) -> str:
        return self.value[1]


class UnrealBuildTarget(Enum):
    GAME = 0, "Game"
    SERVER = 1, "Server"
    CLIENT = 2, "Client"
    EDITOR = 3, "Editor"
    PROGRAM = 4, "Program"

    def __str__(self) -> str:
        return self.value[1]


def get_ue_time_format() -> str:
    return "%Y.%m.%d-%H.%I.%S"


def ue_time_to_string(time: datetime) -> str:
    return time.strftime(get_ue_time_format())


def ue_string_to_time(time_string: str) -> datetime:
    return datetime.strptime(time_string, get_ue_time_format())
