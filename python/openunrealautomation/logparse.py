"""
Parse UE logs for warning / error summary.
"""

import argparse
import copy
import datetime
import glob
import os.path
import re
from enum import Enum
from pathlib import Path
from typing import Generator
from xml.etree.ElementTree import Element as XmlNode
from xml.etree.ElementTree import ElementTree as XmlTree

from openunrealautomation.core import *
from openunrealautomation.environment import UnrealEnvironment


class UnrealLogFile(Enum):
    # Unreal Build Tool
    UBT = 0, "{engine_root}/Engine/Programs/UnrealBuildTool/", "Log", "-backup-{timestamp}", ".txt"
    # Generate project files
    UBT_GPF = 1, "{engine_root}/Engine/Programs/UnrealBuildTool", "Log_GPF", "-backup-{timestamp}", ".txt"
    # Unreal Header Tool
    UHT = 2, "{engine_root}/Engine/Programs/UnrealBuildTool/", "Log_UHT", "-backup-{timestamp}", ".txt"
    # Automation Tool
    # No backups of UAT logs. Instead the folder contains logs of substeps
    UAT = 3, "{engine_root}/Engine/Programs/AutomationTool/Saved/Logs/", "Log", "", ".txt"
    # When running UAT, individual logs for invoked steps are placed here.
    # This pattern matches all logs in that folder not including the UAT log itself.
    UAT_STEPS = 4, "{engine_root}/Engine/Programs/AutomationTool/Saved/Logs/", "*-*", "", ".txt"
    # The backed up cook logs
    COOK = 5, "{engine_root}/Engine/Programs/AutomationTool/Saved/", "Cook", "-{timestamp}", ".txt"
    # Editor logs (esp. for commandlets / automation tests)
    EDITOR = 6, "{project_root}/Saved/Logs/", "{project_name}*", "-backup-{timestamp}", ".log"

    def root(self) -> str:
        return self.value[1]

    def file_name(self) -> str:
        return self.value[2]

    def date_suffix(self) -> str:
        return self.value[3]

    def ext(self) -> str:
        return self.value[4]

    def format(self, environment: UnrealEnvironment, time: datetime = None, time_string: str = None) -> str:
        if not time is None:
            time_string = ue_time_to_string(time)
        complete_format = self.root() + self.file_name() + \
            self.date_suffix() + self.ext()
        return complete_format.format(timestamp=time_string,
                                      engine_root=environment.engine_root,
                                      project_root=environment.project_root,
                                      project_name=environment.project_name)

    def find_latest(self, environment: UnrealEnvironment) -> str:
        found_files = self.get_all(environment=environment)
        if found_files is None or len(found_files) == 0:
            return None
        else:
            return found_files[-1]

    def get_all(self, environment: UnrealEnvironment) -> list[str]:
        base_path = os.path.join(self.root(), self.file_name()).format(engine_root=environment.engine_root,
                                                                       project_root=environment.project_root,
                                                                       project_name=environment.project_name)

        combined_path = base_path + \
            ("*" if not base_path.endswith("*") else "") + self.ext()
        search_path = os.path.join(environment.engine_root, combined_path)
        found_files = glob.glob(search_path)
        found_files = [os.path.normpath(file) for file in found_files]
        found_files.sort(key=os.path.getctime)
        return found_files

    def __str__(self) -> str:
        return self.root() + self.file_name() + self.ext()


class UnrealLogSeverity(Enum):
    """
    Severity of messages. Not 1:1 the same as Unreal's log verbosity.
    Instead, we just differentiate between error, warning and message depending on the declarations in the parser xml file.
    Default level is MESSAGE
    """
    MESSAGE = 0, "📄"
    WARNING = 1, "⚠️"
    ERROR = 2, "⛔"

    @staticmethod
    def from_string(string: str) -> 'UnrealLogSeverity':
        if string is None:
            return UnrealLogSeverity.MESSAGE
        capstr = string.upper()
        if capstr == "":
            return UnrealLogSeverity.MESSAGE

        for case in UnrealLogSeverity:
            if case.name == capstr:
                return case
        return UnrealLogSeverity.MESSAGE

    def get_emoji(self) -> str:
        return self.value[1]


class UnrealLogFilePattern:
    pattern: str = ""
    is_regex: bool = True

    def __init__(self, pattern: str, is_regex: bool):
        self.pattern = pattern
        self.is_regex = is_regex

    @staticmethod
    def from_xml_node(xml_node: XmlNode) -> 'UnrealLogFilePattern':
        if None is xml_node:
            return None
        is_regex = xml_node.get("Style", default="Regex") == "Regex"
        return UnrealLogFilePattern(xml_node.text, is_regex=is_regex)

    def match(self, line: str) -> bool:
        if self.is_regex:
            return re.search(self.pattern, line)
        else:
            # Convert both to lower case to make matching case-insensitive
            return self.pattern.lower() in line.lower()


class UnrealLogFilePatternList:
    group_name: str = ""
    severity: UnrealLogSeverity
    tags: set[str]
    owning_scope: 'UnrealLogFilePatternScope'
    include_patterns: list[UnrealLogFilePattern]
    exclude_patterns: list[UnrealLogFilePattern]
    matching_lines: list[str]

    def __init__(self, group_name: str, owning_scope: 'UnrealLogFilePatternScope'):
        self.group_name = group_name
        self.owning_scope = owning_scope
        self.severity = UnrealLogSeverity.MESSAGE
        self.tags = set()
        self.include_patterns = []
        self.exclude_patterns = []
        self.matching_lines = []

    @staticmethod
    def from_xml_node(xml_node: XmlNode, owning_scope: 'UnrealLogFilePatternScope') -> 'UnrealLogFilePatternList':
        result_list = UnrealLogFilePatternList(
            xml_node.get("Name"),
            owning_scope=owning_scope)

        result_list.severity = UnrealLogSeverity.from_string(
            xml_node.get("Severity", default=""))
        result_list.tags = set(tag.upper()
                               for tag in xml_node.get("Tags", default="").split(";"))

        for pattern in xml_node.findall("Include"):
            result_list.include_patterns.append(
                UnrealLogFilePattern.from_xml_node(pattern))
        for pattern in xml_node.findall("Exclude"):
            result_list.exclude_patterns.append(
                UnrealLogFilePattern.from_xml_node(pattern))
        return result_list

    def match(self, line: str) -> bool:
        return any(pattern.match(line) for pattern in self.include_patterns) and \
            not any(pattern.match(line)
                    for pattern in self.exclude_patterns)

    def match_tags(self, tags: list[str]) -> bool:
        if len(tags) == 0:
            return True
        return any(tag is None or tag == "" or tag.upper() in self.tags for tag in tags)

    def check_and_add(self, line: str) -> bool:
        if self.match(line):
            self.matching_lines.append(line[0:-1])
            return True
        return False

    def format(self, max_lines: int) -> str:
        num_lines = len(self.matching_lines)
        disp_lines = min(max_lines, num_lines) if max_lines > 0 else num_lines
        scope_name = self.owning_scope.get_fully_qualified_scope_name()
        header = f"### [{scope_name}] {self.severity.get_emoji()}  {self.group_name} ({disp_lines}/{num_lines}) <{';'.join(self.tags)}> ###\n"
        body = "\n".join(self.matching_lines[0:disp_lines])
        return header + body


class UnrealLogFilePatternScope:
    scope_name: str
    start_patterns: list[UnrealLogFilePattern]
    end_patterns: list[UnrealLogFilePattern]
    child_scopes: list['UnrealLogFilePatternScope']
    parent_scope: 'UnrealLogFilePatternScope' = None
    pattern_lists: list[UnrealLogFilePatternList]

    def __init__(self,
                 scope_name,
                 start_patterns: list[UnrealLogFilePattern],
                 end_patterns: list[UnrealLogFilePattern]):
        self.scope_name = scope_name
        self.start_patterns = start_patterns
        self.end_patterns = end_patterns
        self.child_scopes = []
        self.pattern_lists = []

    def num_patterns(self):
        result = 0
        for list in self.pattern_lists:
            result += len(list.include_patterns) + len(list.exclude_patterns)
        for child_scope in self.child_scopes:
            result += child_scope.num_patterns()
        return result

    def link_child_scope(self, child_scope: 'UnrealLogFilePatternScope') -> None:
        child_scope.parent_scope = self
        self.child_scopes.append(child_scope)

    def fill_scope_from_xml_node(self, xml_node: XmlNode, root_node: XmlNode) -> None:
        for pattern_list in xml_node.findall("./Patterns"):
            self.pattern_lists.append(
                UnrealLogFilePatternList.from_xml_node(pattern_list, self))
        for scope in xml_node.findall("./Scope"):
            self.link_child_scope(
                UnrealLogFilePatternScope.from_xml_node(scope, root_node))
        for link in xml_node.findall("./Link"):
            template_name = link.get("Template")
            for template in root_node.findall("./Template"):
                if template.get("Name") == template_name:
                    self.fill_scope_from_xml_node(template, root_node)

    def from_xml_node(xml_node: XmlNode, root_node: XmlNode) -> 'UnrealLogFilePatternScope':
        start_patterns = [UnrealLogFilePattern.from_xml_node(
            node) for node in xml_node.findall("Start")]
        end_patterns = [UnrealLogFilePattern.from_xml_node(
            node) for node in xml_node.findall("End")]

        result_scope = UnrealLogFilePatternScope(
            xml_node.get("Name"),
            start_patterns,
            end_patterns)
        result_scope.fill_scope_from_xml_node(xml_node, root_node)
        return result_scope

    def check_and_add(self, line: str) -> bool:
        """Check a line on current scope or bubble up"""
        for pattern_list in self.pattern_lists:
            if pattern_list.check_and_add(line):
                return True
        # If not match in own patterns was found, bubble up to parents
        return self.parent_scope.check_and_add(line) if not self.parent_scope is None else False

    def format(self, max_lines: int):
        result = ""
        for pattern_list in self.pattern_lists:
            result += pattern_list.format(max_lines).strip() + "\n\n"
        for child_scope in self.child_scopes:
            result += child_scope.format(max_lines).strip() + "\n\n"

        # Remove all whitespace over more than 2 lines
        while "\n\n\n" in result:
            result = result.replace("\n\n\n", "\n\n")

        # Strip whitespace at start + end
        return result.strip()

    def get_fully_qualified_scope_name(self) -> str:
        return ((self.parent_scope.get_fully_qualified_scope_name() + ".") if not self.parent_scope is None else "") + self.scope_name

    def filter_inline(self, tags: list[str], min_severity: UnrealLogSeverity, min_matches: int = 1) -> None:
        self.pattern_lists = [pattern_list for pattern_list in self.pattern_lists if
                              len(pattern_list.matching_lines) >= min_matches and
                              pattern_list.severity.value >= min_severity.value and
                              pattern_list.match_tags(tags)]

        for child_scope in self.child_scopes:
            child_scope.filter_inline(tags, min_severity)

    def filter(self, tag: str, min_severity: UnrealLogSeverity, min_matches: int = 1) -> 'UnrealLogFilePatternScope':
        self_copy = copy.deepcopy(self)
        tags = tag.split(";")
        self_copy.filter_inline(tags, min_severity, min_matches)
        return self_copy


def get_log_patterns(xml_path: str, target_name: str) -> UnrealLogFilePatternScope:
    """
    Import a list of log file patterns from an xml file.
    Groups are assigned to a target that must match to the input target_name.
    """
    print("Importing log file pattern list from", xml_path)
    root_node = XmlTree(file=xml_path)
    for target in root_node.findall("./Target"):
        if target.get("Name") == target_name:
            return UnrealLogFilePatternScope.from_xml_node(target, root_node)
    raise OUAException(f"No definition for log file target {target_name}")


def parse_log(log_path: str, logparse_patterns_xml: str, target_name: str) -> UnrealLogFilePatternScope:
    """
    Parse the log file into a dictionary.
    Each key of the dict represents a named group of patterns.
    Groups are themselves assigned to log file types, so we can have different patterns for different log files.
    The tree of pattern groups are defined in xml files (see resources/logparse_patterns.xml for sample).
    """
    if log_path is None:
        raise OUAException("Cannot parse None logfile")

    root_scope = get_log_patterns(logparse_patterns_xml, target_name)
    if root_scope.num_patterns() == 0:
        raise OUAException("No log parsing patterns found!")

    current_scope = root_scope

    with open(log_path, "r") as file:
        for line in file:
            # What's a higher priority?
            # 1) opening child scopes <- current implementation
            # 2) closing current scope
            scope_changed = False
            for child_scope in current_scope.child_scopes:
                for start_pattern in child_scope.start_patterns:
                    if start_pattern.match(line):
                        current_scope = child_scope
                        scope_changed = True
                        break
                if scope_changed:
                    break

            if not scope_changed and any(end_pattern.match(line) for end_pattern in current_scope.end_patterns):
                current_scope = current_scope.parent_scope
                scope_changed = True

            current_scope.check_and_add(line)

    if current_scope is not root_scope:
        print(
            f"WARNING: Child scope '{current_scope.get_fully_qualified_scope_name()}' was opened but not closed. This may be a sign of an uncompleted automation step.")

    return root_scope


def print_parsed_log(path: str, logparse_patterns_xml: str, target_name: str, max_lines=20) -> None:
    header = "\n==========================="
    print(header, "\nParsing log file", path, "...", header)

    scope_with_matches = parse_log(path, logparse_patterns_xml, target_name)
    scope_with_matches.filter_inline(
        "", min_severity=UnrealLogSeverity.MESSAGE)
    print("\n", scope_with_matches.format(max_lines))


if __name__ == "__main__":
    env = UnrealEnvironment.create_from_parent_tree(Path(__file__).parent)

    argparser = argparse.ArgumentParser()
    argparser.add_argument("-File")
    cli_args = argparser.parse_args()
    cli_args.File

    print("----- Base file names -----")
    now = datetime.now()
    for file_type in UnrealLogFile:
        print(file_type.format(env, now))

    print("----- Latest local files -----")
    for file_type in UnrealLogFile:
        print(file_type.find_latest(env))

    print("----- ALL UAT STEPS -----")
    print(",\n".join(UnrealLogFile.UAT_STEPS.get_all(env)))

    print("----- PARSE TEST -----")
    patterns_xml = os.path.join(
        Path(__file__).parent, "resources/logparse_patterns.xml")

    parse_file = cli_args.File if not cli_args.File is None else UnrealLogFile.UAT.find_latest(
        env)
    print_parsed_log(parse_file, patterns_xml, "BuildCookRun", max_lines=0)
