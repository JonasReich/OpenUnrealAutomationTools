from ast import arg
import os
import shutil
import subprocess
import winreg

from openunrealautomation.core import *
from openunrealautomation.environment import UnrealEnvironment


class UnrealEngine:
    """
    Interact with Unreal Engine executables (editor, build tools, etc) via this manager object.

    This class should never cache any paths directly. All of that must be done in UnrealEnvironment.
    If UnrealEnvironment changes, all functions should work as expected with the new environment.
    """

    environment: UnrealEnvironment = None
    # If true, run commands just print their command line and do not actually launch any executables
    dry_run: bool = False

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
        all_arguments = []

        # program
        all_arguments += [self.environment.get_program_path(program)]

        # project
        if program in [UnrealProgram.EDITOR, UnrealProgram.EDITOR_CMD] and self.environment.has_project():
            if self.environment.is_native_project():
                # Only use the project name for native projects
                all_arguments += [self.environment.project_name]
            else:
                # Need the fully qualified project file path for foreign projects
                all_arguments += [self.environment.project_file]
        else:
            pass

        # map
        if program in [UnrealProgram.EDITOR, UnrealProgram.EDITOR_CMD]:
            if not map is None:
                all_arguments.append(map)
            elif add_default_parameters and self.environment.has_open_unreal_utilities():
                # Unreal does not come with a completely empty map we can use for unit tests, etc.
                # so we use the OUU EmptyWorld map
                all_arguments.append("/OpenUnrealUtilities/Runtime/EmptyWorld")
            else:
                pass

        # additional args
        all_arguments += arguments

        # additional default args
        if add_default_parameters:
            all_arguments += self._get_default_program_arguments(program)

        print(" ".join(all_arguments))

        if self.dry_run:
            return 0

        # TODO: Expose working directory?
        exit_code = subprocess.call(all_arguments)
        if raise_on_error == True and exit_code != 0:
            raise OUAException(
                f"Program {program} returned non-zero exit code: {exit_code}")
        return exit_code

    def run_commandlet(self, commandlet_name: str,  arguments: "list[str]" = [], map: str = None, raise_on_error: bool = True, add_default_parameters: bool = True, allow_commandlet_rendering: bool = False) -> int:
        rhi_arg = "-AllowCommandletRendering" if allow_commandlet_rendering else "-nullrhi"
        run_arg = f"-run={commandlet_name}"
        all_arguments = [rhi_arg, run_arg] + arguments
        return self.run(UnrealProgram.EDITOR_CMD,
                        arguments=all_arguments,
                        map=map,
                        raise_on_error=raise_on_error,
                        add_default_parameters=add_default_parameters)

    def run_tests(self, test_filter: str = None, report_export_path: str = None, game_test_target: bool = True, arguments: "list[str]" = []):
        """
        Execute game or editor tests in the editor cmd - Either in game or in editor mode (depending on game_test_target flag).

        @param test_filter String that specifies which test categories shall be executed. Seprated by pluses. 
        """

        if test_filter is None:
            optional_ouu_tests = "+OpenUnrealUtilities" if self.environment.has_open_unreal_utilities() else ""
            test_filter = f"{self.environment.project_name}+Project.Functional{optional_ouu_tests}"
        if report_export_path is None:
            timestamp = self.environment.creation_time_str
            report_export_path = f"{self.environment.project_root}/Saved/Automation/Reports/TestReport-{timestamp}"

        all_args = ["-game", "-gametest"] if game_test_target \
            else ["-editor", "-editortest"]
        all_args.append(
            f"-ExecCmds=Automation RunTests Now {test_filter};Quit")
        all_args.append(f"-ReportExportPath={report_export_path}")
        all_args.append("-nullrhi")
        all_args += arguments

        # run
        exit_code = self.run(UnrealProgram.EDITOR_CMD,
                             arguments=all_args,
                             map=None,
                             raise_on_error=True,
                             add_default_parameters=True)

        # copy over test report viewer template
        test_report_viewer_zip = os.path.realpath(f"{os.path.dirname(__file__)}/resources/TestReportViewer_Template.zip")
        print(f"\nUnpacking {test_report_viewer_zip} to {report_export_path}/...")
        shutil.unpack_archive(test_report_viewer_zip, report_export_path, "zip")

        return exit_code

    def run_buildgraph(self, script: str, target: str, variables: "dict[str, str]" = {}, arguments: "list[str]" = []) -> int:
        """
        Run BuildGraph via UAT.

        @param script BuildGraph XML script file
        @param target The target defined in the script that should be built
        @param variables (optional) Dictionary of additional variables to pass to buildgraph. Pass the raw variable name as key,
        this function resolves the -set:key=value syntax.
        @param arguments (optional) Additonal arguments to pass to UAT (like -buildmachine, -P4, etc.) Include the dash!
        """
        all_arguments = ["BuildGraph",
                         f"-script={script}", f"-target={target}"] + arguments
        for key, value in variables:
            all_arguments.append(f"-Set:{key}={value}")
        return self.run(UnrealProgram.UAT, arguments=all_arguments)

    def generate_project_files(self, engine_sln=False) -> None:
        if not self.environment.is_source_engine and not self.environment.has_project:
            raise OUAException(
                "Cannot generate project files for environments that are not source builds but also do not have a project")
        if self.environment.has_project and os.path.exists(os.path.join(self.environment.project_root, "Source")) == False:
            raise OUAException(
                "Cannot generate project files for projects that do not have source files")

        # Generate the project files
        generate_script = self._get_generate_script()
        project_args = ["-project=" + str(self.environment.project_file),
                        "-game"] if not engine_sln else []
        generate_args = [generate_script] + project_args
        subprocess.call(generate_args,
                        cwd=os.path.dirname(self.environment.project_root))

    def build(self, target: UnrealBuildTarget, build_configuration: UnrealBuildConfiguration, platform: str = "Win64", program_name: str = "") -> int:
        target_args = {
            UnrealBuildTarget.GAME: self.environment.project_name,
            UnrealBuildTarget.SERVER: self.environment.project_name + "Server",
            UnrealBuildTarget.CLIENT: self.environment.project_name + "Client",
            UnrealBuildTarget.EDITOR: self.environment.project_name + "Editor",
            UnrealBuildTarget.PROGRAM: program_name,
        }

        all_arguments = [target_args[target],
                         platform,
                         str(build_configuration),
                         f"-Project={self.environment.project_file}",
                         "-NoHotReloadFromIDE",
                         "-progress",
                         "-noubtmakefiles"]

        if target == UnrealBuildTarget.EDITOR:
            # TODO: Is this really required??
            all_arguments.append("-editorrecompile")

        return self.run(UnrealProgram.UBT, arguments=all_arguments)

    def _get_generate_script(self) -> str:
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

    def _get_default_program_arguments(self, program: UnrealProgram) -> "list[str]":
        if program == UnrealProgram.EDITOR:
            return []
        if program == UnrealProgram.EDITOR_CMD:
            return ["-unattended", "-buildmachine", "-stdout", "-nopause", "-nosplash"]
        if program == UnrealProgram.UBT:
            return ["-utf8output"]
        return []


if __name__ == "__main__":
    module_path = os.path.realpath(os.path.dirname(__file__))
    ue = UnrealEngine.create_from_parent_tree(module_path)
