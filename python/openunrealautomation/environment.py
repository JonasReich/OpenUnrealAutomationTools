"""
Environment (engine + project) utilities.
"""

import glob
import inspect
import os
import pathlib
import platform
import winreg
from datetime import datetime
from typing import List, Optional, Tuple

import semver
from openunrealautomation.config import UnrealConfig, UnrealConfigValue
from openunrealautomation.core import OUAException, UnrealProgram
from openunrealautomation.descriptor import (UnrealPluginDescriptor,
                                             UnrealProjectDescriptor)
from openunrealautomation.p4 import UnrealPerforce
from openunrealautomation.util import walk_level, walk_parents
from openunrealautomation.version import UnrealVersionDescriptor


class UnrealEnvironment:
    """
    Environment required for an Unreal automation job.
    It's assumed that only one engine and game project are used at a time.

    This class is not meant to be subclassed.

    Use the create_from_* factory methods instead of creating an UnrealPaths object directly.
    """

    creation_time: datetime
    creation_time_str: str

    # Unreal string for the platform that this script is running on
    host_platform: str

    # Path to the engine root directory. This is the directory containing the 'Engine' folder:
    # <Engine Root>/
    #    Engine/
    #       Binaries/
    #       Build/
    #       ...
    #    .uprojectdirs
    #    ...
    engine_root: str = ""

    is_source_engine: bool = False
    is_installed_engine: bool = False

    build_version: UnrealVersionDescriptor

    # Path to the project root directory
    project_root: str = ""

    # Path to the project file
    project_file: Optional[UnrealProjectDescriptor] = None
    project_file_auto_detected: bool

    project_name: Optional[str]

    def __init__(self, engine_root: str, project_file: Optional[UnrealProjectDescriptor] = None) -> None:
        # Cache the creation time once so it can be used by various processes as timestamp
        # The format string is adopted from the way UE formats the timestamps for log file backups.
        self.creation_time = datetime.now()
        self.creation_time_str = datetime.strftime(
            self.creation_time, "%Y.%m.%d-%H.%M.%S")

        if platform.system() != "Windows":
            raise NotImplementedError(
                "UnrealEnvironment is only implemented on Windows")

        self.host_platform = "Win64"

        self.engine_root = os.path.abspath(engine_root)
        if not os.path.exists(self.engine_root):
            raise OUAException(f"Invalid engine path at {self.engine_root}")

        self.is_source_engine = os.path.exists(
            f"{engine_root}/Engine/Build/SourceDistribution.txt")
        self.is_installed_engine = os.path.exists(
            f"{engine_root}/Engine/Build/InstalledBuild.txt")

        self.build_version = UnrealVersionDescriptor(
            f"{self.engine_root}/Engine/Build/Build.version")

        auto_detect = False
        if project_file is None:
            native_projects = self.get_native_projects()
            if len(native_projects) > 0:
                project_file = native_projects[0]
                auto_detect = True
        # Always do this last. It includes path validation!
        self._set_project(project_file=project_file, auto_detect=auto_detect)

        # Do not initialize the P4 connection. Downstream scripts might want to customize
        # P4 environment / sync changes, before we can use this.
        self._p4 = None

    def __str__(self) -> str:
        has_project_bool = self.has_project()

        if self.is_source_engine:
            distribution_type = "Source"
        elif self.is_installed_engine:
            distribution_type = "Installed"
        else:
            distribution_type = "Unknown"

        version_str = ""
        if has_project_bool:
            project_version = self.get_project_version()
            if project_version is not None:
                version_str = f"    -> Version:          {project_version.value} (source: {project_version.file})\n"
            else:
                version_str = f"    -> Version:          not detected\n"

        ouu = self.find_open_unreal_utilities()

        native_projects_str = '\n'.join(
            [f'    -> {project}' for project in self.get_native_projects()])
        return \
            f"Creation Time:   {self.creation_time_str}\n"\
            f"Engine Root:     {self.engine_root}\n"\
            f"Engine Version:  {self.engine_version}\n"\
            f"Distribution:    {distribution_type}\n"\
            f"Has Project:     {has_project_bool}\n" + (
                (f"    -> Project Name:     {self.project_name}\n"
                 f"    -> Is Auto Detected: {self.project_file_auto_detected}\n"
                 f"    -> Project Root:     {self.project_root}\n"
                 f"    -> Project File:     {self.project_file}\n"
                 f"    -> Is Native:        {self.is_native_project()}\n"
                 + version_str)
                if has_project_bool else ""
            ) +\
            f"Has OUU:         {bool(ouu)}\n" + (
                f"    -> Version:          {ouu.read()['VersionName']}\n" if ouu else ""
            ) +\
            f"Native Projects:\n"\
            f"{(native_projects_str if len(native_projects_str) > 0 else '    -> None')}"

    # Factory methods

    @staticmethod
    def create_from_engine_root(engine_root) -> 'UnrealEnvironment':
        return UnrealEnvironment(engine_root=engine_root, project_file=None)

    @staticmethod
    def create_from_project_root(project_root: str) -> 'UnrealEnvironment':
        project_file = UnrealProjectDescriptor.try_find(project_root)
        return UnrealEnvironment.create_from_project_file(project_file=project_file)

    @staticmethod
    def create_from_project_file(project_file: UnrealProjectDescriptor) -> 'UnrealEnvironment':
        return UnrealEnvironment(engine_root=UnrealEnvironment.engine_root_from_project(project_file),
                                 project_file=project_file)

    @staticmethod
    def create_from_parent_tree(folder: str) -> 'UnrealEnvironment':
        """Recursively search through parents in the directory tree until either a project or engine root is found (project root is preferred)"""

        # Resolve the folder so inconsistent drive letter casing is corrected.
        # Casing is sometimes wrong in __file__ which we often use with this function.
        folder = str(pathlib.Path(folder).resolve())

        def try_create(dir: str) -> Optional['UnrealEnvironment']:
            # Any folder with a uproject file can be reasonably considered an Unreal project directory
            if UnrealEnvironment.is_project_root(dir):
                print(f"    -> found a project root at '{dir}'")
                return UnrealEnvironment.create_from_project_root(
                    project_root=dir)

            elif UnrealEnvironment.is_engine_root(dir):
                print(f"    -> found an engine root at '{dir}'")
                return UnrealEnvironment.create_from_engine_root(
                    engine_root=dir)
            return None

        environment: Optional[UnrealEnvironment] = None
        print(f"Searching for project or engine root in '{folder}'...")

        # Try create the environment directly
        environment = try_create(folder)
        if not environment is None:
            return environment

        for pardir in walk_parents(folder):
            environment = try_create(pardir)
            if not environment is None:
                return environment

        raise OUAException(
            f"Failed to find project or engine root in any parent directory of '{folder}'")

    @staticmethod
    def create_from_invoking_file_parent_tree() -> 'UnrealEnvironment':
        stack_frame = inspect.stack()[1]
        stack_module = inspect.getmodule(stack_frame[0])
        assert stack_module is not None and stack_module.__file__ is not None
        module_dir = pathlib.Path(stack_module.__file__).parent
        return UnrealEnvironment.create_from_parent_tree(str(module_dir))

    # Member functions

    def has_project(self) -> bool:
        return self.project_file is not None

    def is_native_project(self) -> bool:
        return self.project_root.startswith(self.engine_root)

    @property
    def engine_version(self) -> str:
        """For backwards compatibility"""
        return str(self.build_version.get_current())

    def find_plugin(self, plugin_name) -> Optional[UnrealPluginDescriptor]:
        if os.path.isdir(f"{self.engine_root}/Engine/Plugins"):
            engine_plugin = self.find_plugin_in_dir(
                dir=f"{self.engine_root}/Engine/Plugins", plugin_name=plugin_name)
            if engine_plugin:
                return engine_plugin
        if self.has_project() and os.path.isdir(f"{self.project_root}/Plugins"):
            project_plugin = self.find_plugin_in_dir(
                dir=f"{self.project_root}/Plugins", plugin_name=plugin_name)
            if project_plugin:
                return project_plugin
        return None

    def find_open_unreal_utilities(self) -> Optional[UnrealPluginDescriptor]:
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
        if program == UnrealProgram.VERSION_SELECTOR:
            if self.is_source_engine:
                return self.get_program_path(UnrealProgram.PROGRAM, "UnrealVersionSelector")
            else:
                return self._find_global_version_selector()
        raise OUAException(
            f"Invalid program {program} - can't find program path")

    def get_native_projects(self) -> List[UnrealProjectDescriptor]:
        """Returns a list of all native projects within the engine root as specified by .uprojectdirs files"""
        projectdirs_files = glob.glob(
            os.path.join(self.engine_root, "*.uprojectdirs"))

        result_list = []
        for file in projectdirs_files:
            with open(file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith(";"):
                        continue
                    line = line.removesuffix("\n")
                    scan_dir = os.path.join(self.engine_root, line)
                    if not os.path.exists(scan_dir):
                        continue
                    for item in os.scandir(scan_dir):
                        if item.is_dir() and UnrealEnvironment.is_project_root(item.path):
                            project_file = UnrealProjectDescriptor.try_find(
                                item.path)
                            if project_file is not None:
                                result_list.append(project_file)

        return result_list

    def set_project_by_native_name(self, project_name: str) -> None:
        """Set the project by name. Only works for native projects contained within the engine root searchable via .uprojectdirs."""
        for project_file in self.get_native_projects():
            if project_file.get_name() == project_name:
                self.set_project(project_file)
                return

    def set_project(self, project_file: UnrealProjectDescriptor) -> None:
        """Set the project by path. This works both for native and foreign projects."""
        self._set_project(project_file, False)

    def config(self) -> UnrealConfig:
        return UnrealConfig(engine_root=self.engine_root, project_root=self.project_root)

    def get_project_version(self) -> Optional[UnrealConfigValue]:
        return self.config().read(category="Game", section="/Script/EngineSettings.GeneralProjectSettings", key="ProjectVersion")

    def get_project_version_semver(self) -> semver.VersionInfo:
        build_version = self.get_project_version()
        return semver.VersionInfo.parse(
            build_version.value) if build_version else semver.VersionInfo(0, 1, 0, "unknown")

    def get_engine_solution(self) -> str:
        # assume UE5
        return os.path.join(self.engine_root, "UE5.sln")

    def get_project_solution(self) -> str:
        return os.path.join(self.project_root, f"{self.project_name}.sln")

    def p4(self) -> UnrealPerforce:
        if not self._p4:
            self._p4 = UnrealPerforce()
        return self._p4

    def _get_generate_project_files_path(self) -> Tuple[str, bool]:
        """
        Returns a tuple of
        - A) the path to a script file/application that can be used to generate project files.
        - B) bool: whether A) is a generate script or the version selector executable.
        """
        if self.is_source_engine:
            return (self.engine_root +
                    "\\Engine\\Build\\BatchFiles\\GenerateProjectFiles.bat", True)
        else:
            global_version_selector = self._find_global_version_selector()
            if global_version_selector:
                return global_version_selector

        raise OUAException(
            "Failed to determine GenerateProjectFiles script/command")

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
    def engine_root_from_association(engine_association_key) -> Optional[str]:
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
    def find_engine_parent_dir(dir: str) -> Optional[str]:
        for pardir in walk_parents(dir):
            if os.path.exists(f"{pardir}/Engine/Build/Build.version"):
                # It's reasonable to expect that this is an Engine directory
                return pardir
        return None

    @staticmethod
    def find_plugin_in_dir(dir: str, plugin_name: str) -> Optional[UnrealPluginDescriptor]:
        for root, dirs, _files in walk_level(dir, level=2):
            for dirname in dirs:
                subdir = os.path.join(root, dirname)
                try:
                    descriptor = UnrealPluginDescriptor.try_find(subdir)
                    if descriptor and descriptor.get_name() == plugin_name:
                        return descriptor
                except OUAException as e:
                    pass
        return None

    @staticmethod
    def find_source_dir_for_file(search_path: str) -> Tuple[str, str]:
        """
        Find the encompassing Source/ directory for a source file - and the name of the corresponding module (folder).
        Works for .cpp, .h and .cs files - anything that is inside Source/.
        """
        search_path = os.path.abspath(search_path)
        module_name = ""
        for _ in range(20):  # max 30 iterations
            if search_path.endswith("\\Private") or search_path.endswith("\\Public"):
                module_name = pathlib.Path(search_path).parent.name
            break_now = search_path.endswith("\\Source")
            if break_now:
                break
            search_path = os.path.abspath(pathlib.Path(search_path).parent)
        return search_path, module_name

    @staticmethod
    def _find_global_version_selector() -> Optional[str]:
        # For versions of the engine installed using the launcher, we need to query the shell integration
        # to determine the location of the Unreal Version Selector executable, which generates VS project files
        try:
            key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,
                                 "Unreal.ProjectFile\\shell\\rungenproj\\command")
            if key:
                command = winreg.QueryValue(key, None)
                command = command.replace(' /projectfiles "%1"', "")
                command = command.replace('"', '')
                return command
        except:
            pass
        return None

    def _set_project(self, project_file: Optional[UnrealProjectDescriptor], auto_detect: bool) -> None:
        self.project_file = project_file
        self.project_file_auto_detected = auto_detect
        if project_file is not None:
            self.project_root = os.path.abspath(pathlib.Path(
                project_file.file_path).parent)
        else:
            self.project_root = ""
        self.project_name = self.project_file.get_name(
        ) if self.project_file is not None else None
        self._validate_paths()

    def _validate_paths(self) -> None:
        if len(self.engine_root) == 0 or not os.path.exists(self.engine_root):
            raise OUAException(
                f"Engine root directory {self.engine_root} does not exist")
        if len(self.project_root) > 0 and not os.path.exists(self.project_root):
            raise OUAException(
                f"Project root directory {self.project_root} does not exist")
        if self.project_file is not None and (len(self.project_file.file_path) == 0 or not os.path.exists(self.project_file.file_path)):
            raise OUAException(
                f"Project root directory does not contain a valid project file")


if __name__ == "__main__":
    module_path = os.path.realpath(os.path.dirname(__file__))
    environment = UnrealEnvironment.create_from_parent_tree(module_path)

    print(str(environment))
