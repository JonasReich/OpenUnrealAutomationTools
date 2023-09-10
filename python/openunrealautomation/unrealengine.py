"""
Interact with Unreal Engine executables (editor, build tools, etc).
"""

import json
import os
import subprocess
import winreg
from typing import List, Optional, Set, Tuple
from xml.etree.ElementTree import Element as XmlNode
from xml.etree.ElementTree import ElementTree as XmlTree

from openunrealautomation.core import (OUAException, UnrealBuildConfiguration,
                                       UnrealBuildTarget, UnrealProgram)
from openunrealautomation.descriptor import UnrealProjectDescriptor
from openunrealautomation.environment import UnrealEnvironment
from openunrealautomation.util import (args_str, run_subprocess, walk_level,
                                       which_checked)


class UnrealEngine:
    """
    Interact with Unreal Engine executables (editor, build tools, etc) via this manager object.

    This class should never cache any paths directly. All of that must be done in UnrealEnvironment.
    If UnrealEnvironment changes, all functions should work as expected with the new environment.
    """

    environment: UnrealEnvironment
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
        return UnrealEngine(UnrealEnvironment.create_from_project_file(project_file=UnrealProjectDescriptor(project_file)))

    @staticmethod
    def create_from_parent_tree(folder: str) -> 'UnrealEngine':
        """Recursively search through parents in the directory tree until either a project or engine root is found (project root is preferred) to create the environment for UE."""
        return UnrealEngine(UnrealEnvironment.create_from_parent_tree(folder=folder))

    def run(self,
            program: UnrealProgram,
            arguments: "list[str]" = [],
            map: Optional[str] = None,
            program_name: str = "",
            raise_on_error: bool = True,
            add_default_parameters: bool = True,
            generate_coverage_reports: bool = False) -> int:
        """
        Run an Unreal program.

        program                     Which unreal program type to run. If program=UnrealProgram.PROGRAM, you must also set program_name.
        arguments                   List of arguments to pass to the application.
        map                         If applicable (game/editor) use this as startup map.
        program_name                If program=UnrealProgram.PROGRAM, this is the name of the program to start.
        raise_on_error              If true, non-zero exit codes will be raised as exceptions.
        add_default_parameters      If true a list of default parameters (including a default map) will be passed to the application.
        generate_coverage_reports   If true and the target is either EDITOR or EDITOR_CMD, opencppcoverage is used to generate a coverage report in the project Saved folder.

        returns application exit code
        """
        assert self.environment.project_file is not None

        all_arguments = []

        program_path = self.environment.get_program_path(
            program=program, program_name=program_name)
        program_exe_name = os.path.basename(program_path)

        # opencppcoverage
        if generate_coverage_reports:
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
                all_arguments += [self.environment.project_file.file_path]
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
        exit_code = run_subprocess(all_arguments, check=raise_on_error)
        return exit_code

    def run_commandlet(self,
                       commandlet_name: str,
                       arguments: "list[str]" = [],
                       map: Optional[str] = None,
                       raise_on_error: bool = True,
                       add_default_parameters: bool = True,
                       allow_commandlet_rendering: bool = False,
                       generate_coverage_reports: bool = False) -> int:
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
        generate_coverage_reports   If true and the target is either EDITOR or EDITOR_CMD, opencppcoverage is used to generate a coverage report in the project Saved folder.

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
                        generate_coverage_reports=generate_coverage_reports)

    def run_tests(self, test_filter: Optional[str] = None,
                  game_test_target: bool = True,
                  arguments: "list[str]" = [],
                  generate_report_file: bool = False,
                  report_directory: Optional[str] = None,
                  convert_junit: bool = True,
                  setup_report_viewer: bool = False,
                  generate_coverage_reports: bool = False):
        """
        Execute game or editor tests in the editor cmd - Either in game or in editor mode (depending on game_test_target flag).

        test_filter                 Optional string that specifies which test categories shall be executed. Seprated by pluses.
        game_test_target            If true, the editor is launched in game mode (significantly faster). If false in editor mode. The test selection is updated accordingly.
        arguments                   Additional commandline arguments to pass to UE.
        generate_report_file        If true, a test report (json + html) is saved by UE into the project's Saved directory.
        report_directory            Optional path to a directory to place automation reports. By defautl a generated folder in the projects Saved directory is used. 
        convert_junit               If true, the test results json file is converted into a JUnit xml file (e.g. to report test status to Jenkins/TeamCity).
        setup_report_viewer         If true, all bower_components required for Epic's test viewer html page are installed into the report directory. This requires bower to be installed and on PATH.
        generate_coverage_reports   If true, the application is launched via opencppcoverage to generate code coverage reports in the project's Saved directory.
        """

        setup_report_viewer_actual = generate_report_file and setup_report_viewer
        # Already check for requirements at the start, so there are no surprises after running tests.
        bower_path = None
        if setup_report_viewer_actual:
            bower_path = which_checked("bower", "Bower (available via npm)")

        if report_directory is None:
            report_directory = self.environment.get_default_test_report_directory()

        if test_filter is None:
            optional_ouu_tests = "+OpenUnrealUtilities" if self.environment.has_open_unreal_utilities() else ""
            test_filter = f"{self.environment.project_name}+Project.Functional{optional_ouu_tests}"

        all_args = ["-game", "-gametest"] if game_test_target \
            else ["-editor", "-editortest"]
        all_args.append(
            f"-ExecCmds=Automation RunTests Now {test_filter};Quit")
        if generate_report_file:
            os.makedirs(report_directory, exist_ok=True)
            all_args.append(f"-ReportExportPath={report_directory}")
        all_args.append("-nullrhi")
        all_args += arguments

        # run
        unreal_exit_code = self.run(UnrealProgram.EDITOR_CMD,
                                    arguments=all_args,
                                    map=None,
                                    raise_on_error=True,
                                    add_default_parameters=True,
                                    generate_coverage_reports=generate_coverage_reports)

        if generate_report_file and convert_junit:
            json_path = os.path.join(report_directory, "index.json")
            junit_path = os.path.join(report_directory, "JUnitTestResults.xml")
            self._convert_test_results_to_junit(
                json_path=json_path, junit_path=junit_path)

        if setup_report_viewer_actual and bower_path is not None:
            bower_json = os.path.join(
                self.environment.engine_root, "Engine/Content/Automation/bower.json")
            # Install bower components to report directory
            run_subprocess([bower_path, "install", bower_json],
                           cwd=report_directory)

        return unreal_exit_code

    def run_buildgraph(self,
                       script: str,
                       target: str,
                       variables: "dict[str, str]" = {},
                       arguments: "list[str]" = []) -> int:
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

    def get_buildgraph_files(self, tag: str) -> Set[str]:
        """
        Get tagged file list from last buildgraph execution.
        """
        xml_files = []
        buildgraph_saved_dir = os.path.join(
            self.environment.engine_root, "Engine/Saved/BuildGraph")
        for root, dirs, files in walk_level(buildgraph_saved_dir, level=1):
            for filename in files:
                if filename == f"Tag-{tag}.xml":
                    xml_files.append(os.path.join(root, filename))
        if len(xml_files) == 0:
            raise OUAException(f"No valid xml file found for tag {tag}")
        elif len(xml_files) > 1:
            print("WARNING: More than 1 xml file found for tag",
                  tag, ":", len(xml_files))

        xml_file = xml_files[0]
        xml_tree = XmlTree(file=xml_file)
        local_files = xml_tree.findall(
            "./LocalFiles/LocalFile")

        tagged_files = set()
        for file_node in local_files:
            tagged_files.add(file_node.text)
        return tagged_files

    def generate_project_files(self, engine_sln=False, extra_shell=False) -> None:
        """
        Generate project files (the C++/C# projects and .sln on Windows).

        engine_sln      If true, the solution will be generated for the engine. If false, only a project solution will be generated.
        """
        if not self.environment.is_source_engine and not self.environment.has_project:
            raise OUAException(
                "Cannot generate project files for environments that are not source builds but also do not have a project")
        if self.environment.has_project() and os.path.exists(os.path.join(self.environment.project_root, "Source")) == False:
            raise OUAException(
                "Cannot generate project files for projects that do not have source files")
        assert self.environment.project_file is not None

        # Generate the project files
        (generator_path, is_script) = self._get_generate_project_files_path()
        if is_script:
            # via a GenerateProjectFiles.bat script
            generate_args = [generator_path]
            if not engine_sln:
                generate_args += [
                    "-project=" + str(self.environment.project_file.file_path),
                    "-game"
                ]
        else:
            # via UnrealVersionSelector.exe
            generate_args = [generator_path, "/projectfiles",
                             str(self.environment.project_file.file_path)]

        if extra_shell:
            cmd = args_str(generate_args)
            print(cmd)
            # This creates an extra shell window that will remain open if the project file generation fails for the user to see.
            subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            generate_directory = os.path.dirname(self.environment.project_root)
            run_subprocess(generate_args,
                           cwd=generate_directory,
                           print_args=True)

    def build(self,
              target: UnrealBuildTarget,
              build_configuration:
              UnrealBuildConfiguration,
              platform: Optional[str] = None,
              program_name: str = "") -> int:
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

    def clean(self,
              target: UnrealBuildTarget,
              build_configuration: UnrealBuildConfiguration,
              platform: Optional[str] = None,
              program_name: str = "") -> int:
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

    def update_local_version(self) -> int:
        return self.run(UnrealProgram.UAT, ["UpdateLocalVersion", "-P4", "-Licensee", "-Promoted=0"])

    def _get_generate_project_files_path(self) -> Tuple[str, bool]:
        """
        Returns a tuple of
        - A) the path to a script file/application that can be used to generate project files.
        - B) bool: whether A) is a generate script or the version selector executable.
        """
        if self.environment.is_source_engine:
            return (self.environment.engine_root +
                    "\\Engine\\Build\\BatchFiles\\GenerateProjectFiles.bat", True)

        # For versions of the engine installed using the launcher, we need to query the shell integration
        # to determine the location of the Unreal Version Selector executable, which generates VS project files
        try:
            key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,
                                 "Unreal.ProjectFile\\shell\\rungenproj\\command")
            if key:
                command = winreg.QueryValue(key, None)
                command = command.replace(' /projectfiles "%1"', "")
                return (command.replace('"', ''), False)
        except:
            pass
        raise OUAException(
            "Failed to determine GenerateProjectFiles script/command")

    def _get_default_program_arguments(self, program: UnrealProgram) -> List[str]:
        """
        Returns some reasonable default arguments for a given program.

        This list does not include position sensitive command line arguments like project or startup map.
        Those should be configured directly in UnrealEngine.run().
        """
        assert self.environment.project_file is not None
        project_arg = f"-project={self.environment.project_file.file_path}"

        if program == UnrealProgram.EDITOR:
            return []
        if program == UnrealProgram.EDITOR_CMD:
            return ["-unattended", "-buildmachine", "-stdout", "-nopause", "-nosplash", "-FullStdOutLogOutput"]
        if program == UnrealProgram.UBT:
            return ["-utf8output", project_arg]
        if program == UnrealProgram.UAT:
            return ["-utf8output", "-unattended", project_arg]
        return []

    def _get_ubt_arguments(self,
                           target: UnrealBuildTarget,
                           build_configuration: UnrealBuildConfiguration,
                           platform: str,
                           program_name: str):
        project_name = str(self.environment.project_name)
        target_args = {
            UnrealBuildTarget.GAME: self.environment.project_name,
            UnrealBuildTarget.SERVER: project_name + "Server",
            UnrealBuildTarget.CLIENT: project_name + "Client",
            UnrealBuildTarget.EDITOR: project_name + "Editor",
            UnrealBuildTarget.PROGRAM: program_name,
        }

        all_arguments = [target_args[target],
                         platform,
                         str(build_configuration),
                         "-WaitMutex"]
        return all_arguments

    def _get_opencppcoverage_arguments(self, program_name: str):
        """
        Returns commandline parameters for opencpppcoverage.

        program_name        Name of the program you want to launch with opencppcoverage.
                            This is not the application path, but a short name to identify your launch in saved directory.
        """

        opencppcoverage_name = "opencppcoverage"
        which_checked(opencppcoverage_name)

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

    def _convert_test_results_to_junit(self, json_path: str, junit_path: str) -> None:
        print(f"Converting {json_path} to {junit_path}...")
        with open(json_path, "r", encoding="utf-8-sig") as json_file:
            json_results = json.loads(json_file.read())

            test_platform = json_results['devices'][0]['platform']
            report_created_on = json_results['reportCreatedOn']
            testsuite_id = f"UnrealTest {test_platform} @ {report_created_on}"
            num_failures = str(json_results["failed"])
            num_tests = str(int(json_results["succeeded"]) + int(num_failures))
            testsuite_time = str(json_results["totalDuration"])

            testsuite_node = XmlNode("testsuite")
            testsuite_node.set("id", testsuite_id)
            testsuite_node.set("tests", num_tests)
            testsuite_node.set("failures", num_failures)
            testsuite_node.set("time", testsuite_time)

            for test in json_results["tests"]:
                test_node = XmlNode("testcase")
                test_node.set("name", test["testDisplayName"])
                test_node.set("classname", test["fullTestPath"])
                test_node.set("status", test["state"])
                test_node.set("time", str(test["duration"]))

                for entry in test["entries"]:
                    if entry["event"]["type"] == "Info":
                        continue

                    event_node = XmlNode("failure")
                    event_node.set("message", entry["event"]["message"])
                    event_type = entry["event"]["type"]
                    event_node.set("type", event_type)
                    event_node.text = event_type
                    event_node.text += "\n" + entry["event"]["message"]
                    event_node.text += "\n" + entry["filename"]
                    event_node.text += "\n" + str(entry["lineNumber"])

                testsuite_node.append(test_node)

            # Use the same data as from the first testsuite
            root_node = XmlNode("testsuites")
            root_node.set("id", testsuite_id)
            root_node.set("tests", num_tests)
            root_node.set("failures", num_failures)
            root_node.set("time", testsuite_time)
            root_node.append(testsuite_node)

            xml_tree = XmlTree(root_node)
            xml_tree.write(junit_path, encoding="utf-8", xml_declaration=True)

            # Always report tets back to TeamCity.
            # This is not necessarily required, but should never hurt.
            # See https://www.jetbrains.com/help/teamcity/service-messages.html#Importing+XML+Reports
            print(f"##teamcity[importData type='junit' path='{junit_path}']")


if __name__ == "__main__":
    module_path = os.path.realpath(os.path.dirname(__file__))
    ue = UnrealEngine.create_from_parent_tree(module_path)
