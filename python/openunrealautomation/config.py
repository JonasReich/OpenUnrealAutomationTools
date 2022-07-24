"""
Helpers for interacting with UE config / ini files.

Because of UE's idiosyncracies with ini file keys, we do not offer any tools to write to ini files, only to read out values.
For writing to ini files, we recommend invoking UE commandlets written in UE C++ instead.

#TODO Add auto array syntax support (+Key=Value)
"""

import configparser
import os
import winreg
import platform
from typing import Any

from openunrealautomation.core import *


class UnrealConfigScope(Enum):
    """
    Scope of the config file. Determines config path.
    Files with higher scope numbers override lower ones.
    See https://docs.unrealengine.com/5.0/en-US/configuration-files-in-unreal-engine/
    """

    # Engine/Config/Base.ini
    # Base.ini is usually empty.
    BASE = 0

    # Engine/Config/BaseEngine.ini
    ENGINE_BASE = 1

    # Engine/Config/[Platform]/Base[Platform]Engine.ini
    ENGINE_PLATFORM_BASE = 2

    # [ProjectDirectory]/Config/DefaultEngine.ini
    PROJECT_DEFAULT = 3

    # Engine/Config/[Platform]/[Platform]Engine.ini
    ENGINE_PLAFORM = 4

    # [ProjectDirectory]/Config/[Platform]/[Platform]Engine.ini
    PROJECT_PLATFORM = 5

    # [ProjectDirectory]/Saved/Config/[Platform]/[Category].ini
    SAVED = 6

    def __int__(self):
        return self.value

    @staticmethod
    def all_scopes() -> 'list[UnrealConfigScope]':
        """Returns a list of all scopes"""
        return [
            UnrealConfigScope.BASE,
            UnrealConfigScope.ENGINE_BASE,
            UnrealConfigScope.ENGINE_PLATFORM_BASE,
            UnrealConfigScope.PROJECT_DEFAULT,
            UnrealConfigScope.ENGINE_PLAFORM,
            UnrealConfigScope.PROJECT_PLATFORM,
            UnrealConfigScope.SAVED
        ]

    @staticmethod
    def parent_scopes(refscope: 'UnrealConfigScope') -> 'list[UnrealConfigScope]':
        """Returns a list of scopes smaller or equal to refscope"""
        return filter(lambda scope: int(scope) <= int(refscope), UnrealConfigScope.all_scopes())


class UnrealConfigValue():
    category: str = ""
    section: str = ""
    key: str = ""
    scope: UnrealConfigScope
    platform: str = ""
    file: str = ""
    value: Any = None

    def __init__(self, category: str, section: str, key: str, scope: UnrealConfigScope, platform: str, file: str) -> None:
        self.category = category
        self.section = section
        self.key = key
        self.scope = scope
        self.platform = platform
        self.file = file

    def __bool__(self) -> bool:
        return not self.value is None

    def __str__(self) -> str:
        return str(self.value)


class UnrealConfig():
    engine_root: str = ""
    project_root: str = ""

    def __init__(self, engine_root: str, project_root: str) -> None:
        self.engine_root = engine_root
        self.project_root = project_root

    def read(self, category: str, section: str, key: str, scope: UnrealConfigScope = UnrealConfigScope.PROJECT_DEFAULT, platform: str = "WindowsEditor", single_scope: bool = False) -> UnrealConfigValue:
        """
        Read a single config value.

        Some types will be auto converted (int, float, bool).
        If the key has multiple values in the same file (e.g. for arrays), the result value is a list of all values.
        If the key is not found, the function returns an invalid ConfigValue.

        @param single_scope if true only the given scope is read. Otherwise also all ini files of lower scope are read.
        """
        if (single_scope):
            return self._read(category=category, section=section, key=key, scope=scope, platform=platform)
        else:
            value = None
            for parscope in UnrealConfigScope.parent_scopes(scope):
                scope_value = self._read(
                    category=category, section=section, key=key, scope=parscope, platform=platform)
                if not scope_value is None:
                    value = scope_value
            return value

    @staticmethod
    def get_config_path(engine_root: str, project_root: str, category: str, scope: UnrealConfigScope = UnrealConfigScope.PROJECT_DEFAULT, platform: str = "WindowsEditor") -> str:
        paths = {
            UnrealConfigScope.BASE: f"{engine_root}/Engine/Config/Base.ini",
            UnrealConfigScope.ENGINE_BASE: f"{engine_root}/Engine/Config/Base{category}.ini",
            UnrealConfigScope.ENGINE_PLATFORM_BASE: f"{engine_root}/Engine/Config/{platform}/Base{platform}{category}.ini",
            UnrealConfigScope.PROJECT_DEFAULT: f"{project_root}/Config/Default{category}.ini",
            UnrealConfigScope.ENGINE_PLAFORM: f"{engine_root}/Engine/Config/{platform}/{platform}{category}.ini",
            UnrealConfigScope.PROJECT_PLATFORM: f"{project_root}/Config/{platform}/{platform}{category}.ini",
            UnrealConfigScope.SAVED: f"{project_root}/Saved/Config/{platform}/{category}.ini"
        }
        return os.path.abspath(paths[scope])

    def _read(self, category: str, section: str, key: str, scope: UnrealConfigScope,  platform: str) -> UnrealConfigValue:
        config = configparser.ConfigParser(
            strict=False, comment_prefixes=(";"), empty_lines_in_values=False)
        config_path = self.get_config_path(
            engine_root=self.engine_root,
            project_root=self.project_root,
            category=category,
            scope=scope,
            platform=platform)
        config.read(config_path)

        result_value = UnrealConfigValue(
            category=category, section=section, key=key, scope=scope, platform=platform, file=config_path)
        if config.has_option(section, key):
            result_value.value = config[section][key]

        return result_value


def set_shared_ddc_path(shared_ddc_path):
    if platform.system() != "Windows":
        raise NotImplementedError(
            "set_shared_ddc_path is only implemented on Windows")

    key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,
                             f"SOFTWARE\\Epic Games\\GlobalDataCachePath")
    winreg.SetValueEx(key, "UE-SharedDataCachePath", 0,
                      winreg.REG_SZ, shared_ddc_path)
    print("Set Global Shared DDC to ", shared_ddc_path)
    return
