import os
import subprocess
import winreg

from openunrealautomation.core import OUAException, UnrealProgram
from openunrealautomation.environment import UnrealEnvironment


class UnrealEngine:
    """
    Interact with Unreal Engine executables (editor, build tools, etc) via this manager object.

    This class should never cache any paths directly. All of that must be done in UnrealEnvironment.
    If UnrealEnvironment changes, all functions should work as expected with the new environment.
    """

    environment: UnrealEnvironment = None

    def __init__(self, environment: UnrealEnvironment) -> None:
        self.environment = environment

    @staticmethod
    def create_from_engine_root(engine_root) -> 'UnrealEngine':
        return UnrealEngine(UnrealEnvironment.create_from_engine_root(engine_root=engine_root))

    @staticmethod
    def create_from_project_root(project_root: str) -> 'UnrealEngine':
        return UnrealEngine(UnrealEnvironment.create_from_project_root(project_root=project_root))

    @staticmethod
    def create_from_project_file(project_file: str) -> 'UnrealEngine':
        return UnrealEngine(UnrealEnvironment.create_from_project_file(project_file=project_file))

    @staticmethod
    def create_from_parent_tree(folder: str) -> 'UnrealEngine':
        """Recursively search through parents in the directory tree until either a project or engine root is found (project root is preferred) to create the environment for UE."""
        return UnrealEngine(UnrealEnvironment.create_from_parent_tree(folder=folder))

    def run(self, program: UnrealProgram, arguments: "list[str]" = [], map: str = None, raise_on_error: bool = True, add_default_parameters: bool = True) -> int:
        # project
        project_arg = [self.environment.project_name] if program in [
            UnrealProgram.EDITOR, UnrealProgram.EDITOR_CMD] else []

        # map
        if not map is None:
            map_arg = [map]
        elif add_default_parameters and self.environment.has_open_unreal_utilities():
            # Unreal does not come with a completely empty map we can use for unit tests, etc.
            # so we use the OUU EmptyWorld map
            map_arg = ["/OpenUnrealUtilities/Runtime/EmptyWorld"]
        else:
            map_arg = []

        # combine
        all_arguments = [self.environment.get_program_path(program)] +\
            project_arg + map_arg + arguments

        if add_default_parameters:
            all_arguments += self.get_default_program_arguments(program)

        print(" ".join(all_arguments))
        # TODO: Expose working directory?
        exit_code = subprocess.call(all_arguments)
        if raise_on_error == True and exit_code != 0:
            raise OUAException(
                f"Program {program} returned non-zero exit code: {exit_code}")
        return exit_code

    def generate_project_files(self, engine_sln=False) -> None:
        if not self.environment.is_source_engine and not self.environment.has_project:
            raise OUAException(
                "Cannot generate project files for environments that are not source builds but also do not have a project")
        if self.environment.has_project and os.path.exists(os.path.join(self.environment.project_root, "Source")) == False:
            raise OUAException(
                "Cannot generate project files for projects that do not have source files")

        # Generate the project files
        generate_script = self.get_generate_script()
        project_args = ["-project=" + str(self.environment.project_file),
                        "-game"] if not engine_sln else []
        generate_args = [generate_script] + project_args
        subprocess.call(generate_args,
                        cwd=os.path.dirname(self.environment.project_root))

    def get_generate_script(self) -> str:
        if self.environment.is_source_engine:
            return self.environment.engine_root + \
                "\\Engine\\Build\\BatchFiles\\GenerateProjectFiles.bat"

        # For versions of the engine installed using the launcher, we need to query the shell integration
        # to determine the location of the Unreal Version Selector executable, which generates VS project files
        try:
            key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,
                                 "Unreal.ProjectFile\\shell\\rungenproj\\command")
            if key:
                command = winreg.QueryValue(key, None)
                command = command.replace(' /projectfiles "%1"', "")
                return command.replace('"', '')
        except:
            pass
        raise OUAException(
            "Failed to determine GenerateProjectFiles script/command")

    def get_default_program_arguments(self, program: UnrealProgram) -> "list[str]":
        if program == UnrealProgram.EDITOR:
            return []
        if program == UnrealProgram.EDITOR_CMD:
            return ["-unattended", "-buildmachine", "-stdout", "-nopause", "-nosplash"]
        return []


if __name__ == "__main__":
    module_path = os.path.realpath(os.path.dirname(__file__))
    ue = UnrealEngine.create_from_parent_tree(module_path)
