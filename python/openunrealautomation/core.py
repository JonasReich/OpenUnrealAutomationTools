
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
