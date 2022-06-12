from openunrealautomation.core import OUAException
from openunrealautomation.core import UnrealProgram
from openunrealautomation.descriptor import UnrealProjectDescriptor
from openunrealautomation.version import UnrealVersion

import os
import pathlib
import winreg


class UnrealEnvironment:
    """
    Environment paths required for an automation job.
    It's assumed that only one engine and game project are used at a time.

    This class is not meant to be subclassed.

    Use the create_from_* factory methods instead of creating an UnrealPaths object directly.
    """

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
        self.engine_root = os.path.abspath(engine_root)
        self.is_source_engine = os.path.exists(
            f"{engine_root}/Engine/Build/SourceDistribution.txt")
        self.is_installed_engine = os.path.exists(
            f"{engine_root}/Engine/Build/InstalledBuild.txt")

        self.engine_version = UnrealVersion.create_from_file(f"{self.engine_root}/Engine/Build/Build.version")

        self.project_root = os.path.abspath(project_root)
        self.project_file = os.path.abspath(str(project_file))
        self.project_name = project_file.get_name()
        self._validate_paths()
        print(f"Created Unreal Environment:\n{self}")
        pass

    def __str__(self) -> str:
        has_project_bool = self.has_project()
        
        if self.is_source_engine:
            distribution_type = "Source"
        elif self.is_installed_engine:
            distribution_type = "Installed"
        else:
            distribution_type = "Unknown"
        
        return \
            f"Engine Root:     {self.engine_root}\n"\
            f"Engine Version:  {self.engine_version}\n"\
            f"Distribution:    {distribution_type}\n"\
            f"Has Project?:    {has_project_bool}\n" + (
                f"  -> Project Name: {self.project_name}\n"
                f"  -> Project Root: {self.project_root}\n"
                f"  -> Project File: {self.project_file}\n" if has_project_bool else "")

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

    # Commonly used member functions

    def has_project(self) -> bool:
        return len(self.project_root) > 0

    def get_program_path(self, program: UnrealProgram) -> str:
        if program == UnrealProgram.UAT:
            return os.path.abspath(f"{self.engine_root}/Engine/Build/BatchFiles/RunUAT.bat")
        if program == UnrealProgram.UBT:
            return os.path.abspath(f"{self.engine_root}/Engine/Build/BatchFiles/Build.bat")
        if program == UnrealProgram.EDITOR:
            return os.path.abspath(f"{self.engine_root}/Engine/Binaries/Win64/UnrealEditor.exe")
        if program == UnrealProgram.EDITOR_CMD:
            return os.path.abspath(f"{self.engine_root}/Engine/Binaries/Win64/UnrealEditor-Cmd.exe")

    # Utility functions

    @staticmethod
    def engine_root_from_project(project_file: UnrealProjectDescriptor) -> str:
        project_file_json = project_file.read()
        engine_association = project_file_json["EngineAssociation"]
        engine_root = UnrealEnvironment.engine_root_from_association(
            engine_association)
        if not engine_root is None:
            print(
                f"Engine association: {engine_association} -> {engine_root}")
            return engine_root

        engine_root = UnrealEnvironment.find_engine_parent_dir(
            project_file)
        if engine_root is None:
            raise OUAException(
                f"Could not find an engine root for project file {project_file}")
        return engine_root

    @staticmethod
    def engine_root_from_association(engine_association_key) -> str:
        """
        Search the windows registry for an engine installation key
        """
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
        path = pathlib.Path(dir)
        while True:
            if os.path.exists(f"{path}/Engine/Build/Build.version") and os.path.exists(f"{path}/Engine/Source"):
                # It's reasonable to expect that this is an Engine directory
                return str(path)
            if (path.parent == path):
                break
            path = path.parent
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
