import glob
import os
import pathlib
import platform
import winreg
from datetime import datetime

from openunrealautomation.config import UnrealConfig, UnrealConfigValue
from openunrealautomation.core import *
from openunrealautomation.descriptor import (UnrealPluginDescriptor,
                                             UnrealProjectDescriptor)
from openunrealautomation.util import *
from openunrealautomation.version import UnrealVersion


class UnrealEnvironment:
    """
    Environment paths required for an automation job.
    It's assumed that only one engine and game project are used at a time.

    This class is not meant to be subclassed.

    Use the create_from_* factory methods instead of creating an UnrealPaths object directly.
    """

    creation_time: datetime = None
    creation_time_str: str = ""

    # Unreal string for the platform that this script is running on
    host_platform: str

    # Path to the engine root directory
    engine_root: str = ""

    is_source_engine: bool = False
    is_installed_engine: bool = False

    engine_version: UnrealVersion = None

    # Path to the project root directory
    project_root: str = ""

    # Path to the project file
    project_file: UnrealProjectDescriptor = ""

    project_name: str = ""

    def __init__(self, engine_root: str, project_root: str = "", project_file: UnrealProjectDescriptor = "") -> None:
        # Cache the creation time once so it can be used by various processes as timestamp
        # The format string is adopted from the way UE formats the timestamps for log file backups.
        self.creation_time = datetime.now()
        self.creation_time_str = datetime.strftime(
            self.creation_time, "%Y.%m.%d-%H.%M.%S")

        if platform.system() != "Windows":
            raise NotImplementedError("UnrealEnvironment is only implemented on Windows")

        self.host_platform = "Win64"

        self.engine_root = os.path.abspath(engine_root)
        if not os.path.exists(self.engine_root):
            raise OUAException(f"Invalid engine path at {self.engine_root}")
            return
        else:
            self.is_source_engine = os.path.exists(
                f"{engine_root}/Engine/Build/SourceDistribution.txt")
            self.is_installed_engine = os.path.exists(
                f"{engine_root}/Engine/Build/InstalledBuild.txt")

            self.engine_version = UnrealVersion.create_from_file(
                f"{self.engine_root}/Engine/Build/Build.version")

            self.project_root = os.path.abspath(project_root)
            if self.has_project():
                self.project_file = os.path.abspath(str(project_file))
                self.project_name = project_file.get_name()

            self._validate_paths()
            print(f"Created Unreal Environment:\n{self}")

    def __str__(self) -> str:
        has_project_bool = self.has_project()

        if self.is_source_engine:
            distribution_type = "Source"
        elif self.is_installed_engine:
            distribution_type = "Installed"
        else:
            distribution_type = "Unknown"

        if has_project_bool:
            project_version = self.get_project_version()

        ouu = self.find_open_unreal_utilities()
        return \
            f"Creation Time:   {self.creation_time_str}\n"\
            f"Engine Root:     {self.engine_root}\n"\
            f"Engine Version:  {self.engine_version}\n"\
            f"Distribution:    {distribution_type}\n"\
            f"Has Project?:    {has_project_bool}\n" + (
                f"    -> Project Name:   {self.project_name}\n"
                f"    -> Project Root:   {self.project_root}\n" +
                (f"    -> Project File:   {self.project_file}\n" if has_project_bool else "") +
                f"    -> Version:        {project_version.value} (source: {project_version.file})\n"
            ) + \
            f"Has OUU?:        {bool(ouu)}\n" + (
                f"    -> Version:        {ouu.read()['VersionName'] if ouu else ''}"
            )

    # Factory methods

    @staticmethod
    def create_from_engine_root(engine_root) -> 'UnrealEnvironment':
        return UnrealEnvironment(engine_root=engine_root)

    @staticmethod
    def create_from_project_root(project_root: str) -> 'UnrealEnvironment':
        project_file = UnrealProjectDescriptor.try_find(project_root)
        return UnrealEnvironment.create_from_project_file(project_file=project_file)

    @staticmethod
    def create_from_project_file(project_file: UnrealProjectDescriptor) -> 'UnrealEnvironment':
        return UnrealEnvironment(engine_root=UnrealEnvironment.engine_root_from_project(project_file),
                                 project_root=str(pathlib.Path(
                                     str(project_file)).parent),
                                 project_file=project_file)

    @staticmethod
    def create_from_parent_tree(folder: str) -> 'UnrealEnvironment':
        """Recursively search through parents in the directory tree until either a project or engine root is found (project root is preferred)"""
        print(f"Searching for project or engine root in '{folder}'...")
        environment: UnrealEnvironment = None
        for pardir in walkparents(folder):
            # Any folder with a uproject file can be reasonably considered an Unreal project directory
            if UnrealEnvironment.is_project_root(pardir):
                print(f"    -> found a project root at '{pardir}'")
                environment = UnrealEnvironment.create_from_project_root(
                    project_root=pardir)

            elif UnrealEnvironment.is_engine_root(pardir):
                print(f"    -> found an engine root at '{pardir}'")
                environment = UnrealEnvironment.create_from_engine_root(
                    engine_root=pardir)
        if environment is None:
            raise OUAException(
                f"Failed to find project or engine root in any parent directory of '{folder}'")
        return environment

    # Member functions

    def has_project(self) -> bool:
        return len(self.project_root) > 0

    def is_native_project(self) -> bool:
        return self.project_root.startswith(self.engine_root)

    def find_plugin(self, plugin_name) -> UnrealPluginDescriptor:
        engine_plugin = self.find_plugin_in_dir(
            dir=f"{self.engine_root}/Engine/Plugins", plugin_name=plugin_name)
        if engine_plugin:
            return engine_plugin
        if self.has_project():
            project_plugin = self.find_plugin_in_dir(
                dir=f"{self.project_root}/Plugins", plugin_name=plugin_name)
            if project_plugin:
                return project_plugin
        return None

    def find_open_unreal_utilities(self) -> UnrealPluginDescriptor:
        return self.find_plugin("OpenUnrealUtilities")

    def has_plugin(self, plugin_name) -> bool:
        """Is the plugin with the given name installed?"""
        return bool(self.find_plugin(plugin_name))

    def has_open_unreal_utilities(self) -> bool:
        """Is the OpenUnrealUtilities plugin installed?"""
        return bool(self.find_open_unreal_utilities())

    def get_program_path(self, program: UnrealProgram, program_name: str = "") -> str:
        if program == UnrealProgram.UAT:
            return os.path.abspath(f"{self.engine_root}/Engine/Build/BatchFiles/RunUAT.bat")
        if program == UnrealProgram.UBT:
            return os.path.abspath(f"{self.engine_root}/Engine/Build/BatchFiles/Build.bat")
        if program == UnrealProgram.EDITOR:
            return os.path.abspath(f"{self.engine_root}/Engine/Binaries/{self.host_platform}/UnrealEditor.exe")
        if program == UnrealProgram.EDITOR_CMD:
            return os.path.abspath(f"{self.engine_root}/Engine/Binaries/{self.host_platform}/UnrealEditor-Cmd.exe")
        if program == UnrealProgram.PROGRAM:
            return os.path.abspath(f"{self.engine_root}/Engine/Binaries/{self.host_platform}/{program_name}.exe")

    def get_native_projects(self) -> "list[str]":
        """Returns a list of all native projects within the engine root as specified by .uprojectdirs files"""
        # TODO: Implement this!
        raise NotImplementedError

    def set_project_by_native_name(self, project_name) -> None:
        """Set the project by name. Only works for native projects contained within the engine root searchable via .uprojectdirs."""
        # TODO: Implement this!
        # Should call self.set_project_by_path()
        raise NotImplementedError

    def set_project_by_path(self, project_path) -> None:
        """Set the project by path. This works both for native and foreign projects."""
        # TODO: Implement this!
        raise NotImplementedError

    def config(self) -> UnrealConfig:
        return UnrealConfig(engine_root=self.engine_root, project_root=self.project_root)

    def get_project_version(self) -> UnrealConfigValue:
        return self.config().read(category="Game", section="/Script/EngineSettings.GeneralProjectSettings", key="ProjectVersion")

    # Static utility functions

    @staticmethod
    def is_project_root(path: str) -> bool:
        """
        Determine if a path is a project root directory.
        The project root is the folder containing the .uproject file.
        """
        # Any folder with a uproject file can be reasonably considered an Unreal project directory
        return len(glob.glob(f"{path}/*.uproject")) > 0

    @staticmethod
    def is_engine_root(path: str) -> bool:
        """
        Determine if a path is an engine root directory.
        The engine root being the folder containing the Engine/ folder.
        """
        if not all(subdir in os.listdir(path) for subdir in ["Engine"]):
            return False

        # Check some subdirectories. Only check ones that are required for Source without git dependencies (Content, Binaries)
        # or optional (e.g. Extras, Platforms, Documentation, etc)
        return all(subdir in os.listdir(f"{path}/Engine")
                   for subdir in ["Build", "Plugins", "Shaders"])

    @staticmethod
    def engine_root_from_project(project_file: UnrealProjectDescriptor) -> str:
        project_file_json = project_file.read()
        engine_association = project_file_json["EngineAssociation"]
        engine_root = UnrealEnvironment.engine_root_from_association(
            engine_association)
        if not engine_root is None:
            print(
                f"Looked up engine association key: {engine_association} => {engine_root}")
            return engine_root

        engine_root = UnrealEnvironment.find_engine_parent_dir(
            project_file.file_path)
        if engine_root is None:
            raise OUAException(
                f"Failed to find an engine root for project file '{project_file}'")
        return engine_root

    @staticmethod
    def engine_root_from_association(engine_association_key) -> str:
        """
        Search the windows registry for an engine installation key
        """
        if platform.system() != "Windows":
            raise NotImplementedError(
                "engine_root_from_association() is only implemented on Windows")

        # First check for entries of custom builds in HKEY_CURRENT_USER:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 "SOFTWARE\\Epic Games\\Unreal Engine\\Builds")
            if key:
                customBuildPath = winreg.QueryValueEx(
                    key, engine_association_key)[0]
                if os.path.exists(customBuildPath):
                    return customBuildPath
        except:
            pass

        # If the first attempt, also check HKEY_LOCAL_MACHINE for installed engines:
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, f"SOFTWARE\\EpicGames\\Unreal Engine\\{engine_association_key}")
            return winreg.QueryValueEx(key, "InstalledDirectory")[0]
        except:
            pass

        return None

    @staticmethod
    def find_engine_parent_dir(dir) -> str:
        for pardir in walkparents(dir):
            if os.path.exists(f"{pardir}/Engine/Build/Build.version") and os.path.exists(f"{pardir}/Engine/Source"):
                # It's reasonable to expect that this is an Engine directory
                return pardir
        return None

    @staticmethod
    def find_plugin_in_dir(dir, plugin_name) -> UnrealPluginDescriptor:
        for root, dirs, files in walklevel(dir, level=2):
            for dirname in dirs:
                subdir = os.path.join(root, dirname)
                try:
                    descriptor = UnrealPluginDescriptor.try_find(subdir)
                    if descriptor and descriptor.get_name() == plugin_name:
                        return descriptor
                except OUAException as e:
                    pass
        return None

    def _validate_paths(self) -> None:
        if len(self.project_root) == 0 or not os.path.exists(self.engine_root):
            raise OUAException(
                f"Engine root directory {self.engine_root} does not exist")
        if len(self.project_root) > 0 and not os.path.exists(self.project_root):
            raise OUAException(
                f"Project root directory {self.project_root} does not exist")
        if len(self.project_root) > 0 and (len(self.project_file) == 0 or not os.path.exists(self.project_file)):
            raise OUAException(
                f"Project root directory does not contain a valid project file")


if __name__ == "__main__":
    module_path = os.path.realpath(os.path.dirname(__file__))
    enviroment = UnrealEnvironment.create_from_parent_tree(module_path)
