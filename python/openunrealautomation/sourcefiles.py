"""
#TODO This is a stub

Manage Unreal C++ source files.
- Based on raw files?
- Based on meta data?
    -> not possible outside of UE -> requires commandlet
    -> only has compiled files as foundation :/
"""

import enum
from typing import Optional


class SourceFileVisibility(enum.Enum):
    PRIVATE = 0
    PUBLIC = 1


class ClassType (enum.Enum):
    OBJECT = 0
    ACTOR = 1
    STRUCT = 2
    ENUM = 3
    INTERFACE = 4
    MODULE = 5
    OTHER = 100


class UnrealSourceFiles:
    @staticmethod
    def create_class_file(class_name: str, class_type: ClassType, module_root: str, visibility: SourceFileVisibility, parent_class_name: Optional[str] = None):
        pass
