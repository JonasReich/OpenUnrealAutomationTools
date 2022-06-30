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

    def run(self,
            program: UnrealProgram,
            arguments: "list[str]" = [],
            map: str = None,
            program_name: str = "",
            raise_on_error: bool = True,
            add_default_parameters: bool = True,
            genearte_coverage_reports: bool = False) -> int:
        """
        Run an Unreal program.

        program                     Which unreal program type to run. If program=UnrealProgram.PROGRAM, you must also set program_name.
        arguments                   List of arguments to pass to the application.
        map                         If applicable (game/editor) use this as startup map.
        program_name                If program=UnrealProgram.PROGRAM, this is the name of the program to start.
        raise_on_error              If true, non-zero exit codes will be raised as exceptions.
        add_default_parameters      If true a list of default parameters (including a default map) will be passed to the application.
        genearte_coverage_reports   If true and the target is either EDITOR or EDITOR_CMD, opencppcoverage is used to generate a coverage report in the project Saved folder.

        returns application exit code
        """
        all_arguments = []

        program_path = self.environment.get_program_path(
            program=program, program_name=program_name)
        program_exe_name = os.path.basename(program_path)

        # opencppcoverage
        if genearte_coverage_reports:
            if not (program in [UnrealProgram.EDITOR, UnrealProgram.EDITOR_CMD] and self.environment.has_project()):
                raise OUAException(
                    "opencppcoverage can currently only be used with EDITOR and EDITOR_CMD targets and a project")
            all_arguments += self._get_opencppcoverage_arguments(
                program_name=program_exe_name)

        # program
        all_arguments += [program_path]

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

    def run_commandlet(self,
                       commandlet_name: str,
                       arguments: "list[str]" = [],
                       map: str = None,
                       raise_on_error: bool = True,
                       add_default_parameters: bool = True,
                       allow_commandlet_rendering: bool = False,
                       genearte_coverage_reports: bool = False) -> int:
        """
        Run a commandlet in the UE editor.

        commandlet_name             Name of the commandlet.
        arguments                   Additional commandline arguments to pass to UE.
        map                         Startup map for the editor. If left empty and OpenUnrealUtilities plugin is installed, an empty map is used by default.
        raise_on_error              If true, non-zero exit codes will be raised as exceptions.
        add_default_parameters      If true a list of default parameters (including a default map) will be passed to the application.
        allow_commandlet_rendering  If true, an additonal commandline flag will be added to allow commandline rendering.
                                    Otherwise no render commands via RHI can be used by the commandlet.
                                    Required to be true for any commandlets that deal with textures/materials/render targets/etc.
        genearte_coverage_reports   If true and the target is either EDITOR or EDITOR_CMD, opencppcoverage is used to generate a coverage report in the project Saved folder.

        returns UE's exit code
        """
        rhi_arg = "-AllowCommandletRendering" if allow_commandlet_rendering else "-nullrhi"
        run_arg = f"-run={commandlet_name}"
        all_arguments = [rhi_arg, run_arg] + arguments
        return self.run(UnrealProgram.EDITOR_CMD,
                        arguments=all_arguments,
                        map=map,
                        raise_on_error=raise_on_error,
                        add_default_parameters=add_default_parameters,
                        genearte_coverage_reports=genearte_coverage_reports)

    def run_tests(self, test_filter: str = None,
                  game_test_target: bool = True,
                  arguments: "list[str]" = [],
                  generate_report_file: bool = True,
                  extract_report_viewer: bool = True,
                  genearte_coverage_reports: bool = False):
        """
        Execute game or editor tests in the editor cmd - Either in game or in editor mode (depending on game_test_target flag).

        test_filter                 String that specifies which test categories shall be executed. Seprated by pluses.
        game_test_target            If true, the editor is launched in game mode (significantly faster). If false in editor mode. The test selection is updated accordingly.
        arguments                   Additional commandline arguments to pass to UE.
        generate_report_file        If true, a test report (json + html) is saved by UE into the project's Saved directory.
        extract_report_viewer       If true, a modified version of the test report html file to view the json is copied into the test report.
                                    This is to replace UE's default html file, which cannot be used without installing js/css dependencies.
        genearte_coverage_reports   If true, the application is launched via opencppcoverage to generate code coverage reports in the project's Saved directory.
        """

        if test_filter is None:
            optional_ouu_tests = "+OpenUnrealUtilities" if self.environment.has_open_unreal_utilities() else ""
            test_filter = f"{self.environment.project_name}+Project.Functional{optional_ouu_tests}"

        all_args = ["-game", "-gametest"] if game_test_target \
            else ["-editor", "-editortest"]
        all_args.append(
            f"-ExecCmds=Automation RunTests Now {test_filter};Quit")
        if generate_report_file:
            report_export_path = f"{self.environment.project_root}/Saved/Automation/Reports/TestReport-{self.environment.creation_time_str}"
            all_args.append(f"-ReportExportPath={report_export_path}")
        all_args.append("-nullrhi")
        all_args += arguments

        # run
        exit_code = self.run(UnrealProgram.EDITOR_CMD,
                             arguments=all_args,
                             map=None,
                             raise_on_error=True,
                             add_default_parameters=True,
                             genearte_coverage_reports=genearte_coverage_reports)

        if generate_report_file and extract_report_viewer:
            # copy over test report viewer template
            test_report_viewer_zip = os.path.realpath(
                f"{os.path.dirname(__file__)}/resources/TestReportViewer_Template.zip")
            print(
                f"\nUnpacking {test_report_viewer_zip} to {report_export_path}/...")
            shutil.unpack_archive(test_report_viewer_zip,
                                  report_export_path, "zip")

        return exit_code

    def run_buildgraph(self, script: str, target: str, variables: "dict[str, str]" = {}, arguments: "list[str]" = []) -> int:
        """
        Run BuildGraph via UAT.

        script          BuildGraph XML script file
        target          The target defined in the script that should be built
        variables       (optional) Dictionary of additional variables to pass to buildgraph. Pass the raw variable name as key,
                        this function resolves the -set:key=value syntax.
        arguments       (optional) Additonal arguments to pass to UAT (like -buildmachine, -P4, etc.) Include the dash!
        """
        all_arguments = ["BuildGraph",
                         f"-script={script}", f"-target={target}"] + arguments
        for key, value in variables.items():
            all_arguments.append(f"-Set:{key}={value}")
        return self.run(UnrealProgram.UAT, arguments=all_arguments)

    def generate_project_files(self, engine_sln=False) -> None:
        """
        Generate project files (the C++/C# projects and .sln on Windows).

        engine_sln      If true, the solution will be generated for the engine. If false, only a project solution will be generated.
        """
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

    def build(self, target: UnrealBuildTarget, build_configuration: UnrealBuildConfiguration, platform: str = None, program_name: str = "") -> int:
        """
        Launch UBT to build the provided target.

        target                  Which target to build. If this is PROGRAM, you must also set program_name.
                                For other targets the default naming scheme ProjectName+Suffix is assumed.
                                If your game uses other target names, build it as PROGRAM instead.
        build_configuration     Which build configuration to use.
        platform                Platform to build for. Default is None which gets resolved to current host platform.
        program_name            Only required for program targets: Name of the program to build.
        """

        if platform is None:
            platform = self.environment.host_platform

        all_arguments = self._get_ubt_arguments(
            target=target,
            build_configuration=build_configuration,
            platform=platform,
            program_name=program_name)

        all_arguments += [
            "-NoHotReloadFromIDE",
            "-progress",
            "-noubtmakefiles"
        ]

        if target == UnrealBuildTarget.EDITOR:
            # TODO: Is this really required??
            all_arguments.append("-editorrecompile")

        return self.run(UnrealProgram.UBT, arguments=all_arguments)

    def clean(self, target: UnrealBuildTarget, build_configuration: UnrealBuildConfiguration, platform: str = None, program_name: str = "") -> int:
        """
        Cleans the build files for a given target
        """

        if platform is None:
            platform = self.environment.host_platform

        all_arguments = self._get_ubt_arguments(
            target=target,
            build_configuration=build_configuration,
            platform=platform,
            program_name=program_name)

        all_arguments += ["-clean"]

        return self.run(UnrealProgram.UBT, arguments=all_arguments)

    def _get_generate_script(self) -> str:
        """Returns the path to a script file that can be used to generate project files."""
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
        """
        Returns some reasonable default arguments for a given program.

        This list does not include position sensitive command line arguments like project or startup map.
        Those should be configured directly in UnrealEngine.run().
        """
        if program == UnrealProgram.EDITOR:
            return []
        if program == UnrealProgram.EDITOR_CMD:
            return ["-unattended", "-buildmachine", "-stdout", "-nopause", "-nosplash"]
        if program == UnrealProgram.UBT:
            return ["-utf8output"]
        return []

    def _get_ubt_arguments(self, target: UnrealBuildTarget, build_configuration: UnrealBuildConfiguration, platform: str, program_name: str):
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
                         "-WaitMutex"]
        return all_arguments

    def _get_opencppcoverage_arguments(self, program_name: str):
        """
        Returns commandline parameters for opencpppcoverage.

        program_name        Name of the program you want to launch with opencppcoverage.
                            This is not the application path, but a short name to identify your launch in saved directory.
        """

        opencppcoverage_name = "opencppcoverage"
        if shutil.which(opencppcoverage_name) is None:
            raise OUAException(
                "opencppcoverage must be installed and available via PATH.")

        result_args = []
        # directory args
        result_args += [opencppcoverage_name, "--modules",
                        self.environment.project_root, "--sources", self.environment.project_root]
        result_args += ["--excluded_sources", "*Engine*", "--excluded_sources",
                        "*Intermediate*", "--excluded_sources", "*.gen.cpp"]
        result_args += ["--cover_children"]
        result_args += ["--working_dir", self.environment.project_root]

        # export paths
        coverage_report_root = os.path.abspath(
            f"{self.environment.project_root}/Saved/CoverageReports/")
        coverage_report_path = f"{coverage_report_root}/{program_name}_{self.environment.creation_time_str}"
        result_args += [f"--export_type=cobertura:{coverage_report_path}/cobertura.xml",
                        f"--export_type=html:{coverage_report_path}"]

        # Always last argument before UE program commandline
        result_args += ["--"]
        return result_args


if __name__ == "__main__":
    module_path = os.path.realpath(os.path.dirname(__file__))
    ue = UnrealEngine.create_from_parent_tree(module_path)
