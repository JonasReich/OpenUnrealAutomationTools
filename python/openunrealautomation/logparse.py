"""
Parse UE logs for warning / error summary.
"""

import argparse
import copy
import os.path
import re
from enum import Enum
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set, Tuple
from xml.etree.ElementTree import Element as XmlNode
from xml.etree.ElementTree import ElementTree as XmlTree

from alive_progress import alive_bar
from openunrealautomation.core import OUAException
from openunrealautomation.environment import UnrealEnvironment
from openunrealautomation.logfile import UnrealLogFile
from openunrealautomation.util import strtobool


def _get_name_id_list(xml_node: XmlNode, attribute: str) -> Set[str]:
    """Get a set of unique strings from a semi-colon separated string."""
    result = xml_node.get(attribute, default="").split(";")
    if result == ['']:
        return set()
    return set(result)


class UnrealLogSeverity(Enum):
    """
    Severity of messages. Not 1:1 the same as Unreal's log verbosity.
    Instead, we just differentiate between error, warning and message depending on the declarations in the parser xml file.
    Default level is MESSAGE
    """
    # int, icon, json value
    MESSAGE = 0, "??", "message"
    WARNING = 1, "??", "warning"
    SEVERE_WARNING = 2, "??", "severe_warning"
    ERROR = 3, "?", "error"
    # only distinguish internally for now -> auto step fails. json export etc should be unaffected.
    FATAL = 4, "?", "error"

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

    def json(self) -> str:
        return self.value[2]


class UnrealBuildStepStatus(Enum):
    """
    Status of a single build step
    """
    SUCCESS = 0, "✅", "success"
    FAILURE = 1, "❌", "failure"
    UNKNOWN = 2, "❓", "unknown"

    def __str__(self) -> str:
        return self.long_str()

    def get_icon(self) -> str:
        return self.value[1]

    def long_str(self) -> str:
        return self.value[2]


class UnrealLogFileLineMatch:
    """
    A pattern match of a single file from a log file.
    Stores meta information from where it was parsed and variables extracted from the line.
    """
    line: str = ""
    owning_pattern: Optional['UnrealLogFilePattern']
    # Line number where this match was first encountered
    line_nr: int
    string_vars: Dict[str, str]
    numeric_vars: Dict[str, float]
    occurences: int
    # List of tags that were added for this particular line
    # (this has to be done by external post-processing code atm)
    tags: Set[str]

    def __init__(self, line: str, owning_pattern: Optional['UnrealLogFilePattern'], line_nr: int, string_vars: dict = {}, numeric_vars: dict = {}) -> None:
        self.line = line
        self.owning_pattern = owning_pattern
        self.line_nr = line_nr
        self.string_vars = string_vars
        self.numeric_vars = numeric_vars
        self.occurences = 0
        self.tags = set()

    def __str__(self) -> str:
        return self.line

    def __eq__(self, other) -> bool:
        return self.line == other.line

    def __hash__(self) -> int:
        return hash(self.line)

    def get_tags(self) -> set:
        return self.tags.union(self.owning_pattern.tags, self.owning_pattern.owning_list.tags) if self.owning_pattern is not None and self.owning_pattern.owning_list is not None else set()

    def get_severity(self) -> UnrealLogSeverity:
        return self.owning_pattern.owning_list.severity if self.owning_pattern is not None and self.owning_pattern.owning_list is not None else UnrealLogSeverity.MESSAGE

    def json(self) -> dict:
        return {
            "line": self.line,
            "line_nr": self.line_nr,
            "severity": self.get_severity().json(),
            "strings": self.string_vars,
            "numerics": self.numeric_vars,
            "tags": list(self.get_tags()),
            "occurences": self.occurences
        }


class UnrealLogFilePattern:
    """
    A single pattern that is used for line matching.
    Patterns can be regex or simple string matches.
    Patterns cache all matches that were made using the pattern.
    Only the first pattern that gets a passing match will have the matching line even if later patterns would also match.
    """
    owning_scope: 'UnrealLogFilePatternScopeDeclaration'
    owning_list: Optional['UnrealLogFilePatternList']

    pattern: str
    is_regex: bool

    string_var_names: Set[str]
    numeric_var_names: Set[str]
    success_flag_names: Set[str]
    failure_flag_names: Set[str]
    tags: Set[str]

    def __init__(self, pattern: str,
                 owning_scope: 'UnrealLogFilePatternScopeDeclaration',
                 owning_list: Optional['UnrealLogFilePatternList'],
                 is_regex: bool,
                 string_var_names: Set[str],
                 numeric_var_names: Set[str],
                 success_flag_names: Set[str],
                 failure_flag_names: Set[str],
                 tags: Set[str]) -> None:
        self.owning_scope = owning_scope
        self.owning_list = owning_list
        self.pattern = pattern
        self.is_regex = is_regex
        self.string_var_names = string_var_names
        self.numeric_var_names = numeric_var_names
        self.success_flag_names = success_flag_names
        self.failure_flag_names = failure_flag_names
        self.tags = tags

    @staticmethod
    def _from_xml_node(xml_node: XmlNode, owning_scope: 'UnrealLogFilePatternScopeDeclaration', owning_list: Optional['UnrealLogFilePatternList'] = None) -> Optional['UnrealLogFilePattern']:
        if None is xml_node:
            return None
        is_regex = xml_node.get("Style", default="Regex") == "Regex"
        string_var_names = _get_name_id_list(xml_node, "StringVariables")
        numeric_var_names = _get_name_id_list(xml_node, "NumericVariables")
        success_flag_names = _get_name_id_list(xml_node, "SuccessFlags")
        failure_flag_names = _get_name_id_list(xml_node, "FailureFlags")

        if owning_list:
            success_flag_names = success_flag_names.union(
                owning_list.success_flag_names)
            failure_flag_names = failure_flag_names.union(
                owning_list.failure_flag_names)

        # convert to caps -> for legacy purposes. everything else is case senstitive.
        # TODO consider making the tags case sensitive as well!
        tags_set_nocaps = _get_name_id_list(xml_node, "Tags")
        if len(tags_set_nocaps) > 0:
            tags = set(tag.upper() for tag in tags_set_nocaps)
        else:
            tags: Set[str] = set()

        return UnrealLogFilePattern(str(xml_node.text),
                                    owning_scope=owning_scope,
                                    owning_list=owning_list,
                                    is_regex=is_regex,
                                    string_var_names=string_var_names,
                                    numeric_var_names=numeric_var_names,
                                    success_flag_names=success_flag_names,
                                    failure_flag_names=failure_flag_names,
                                    tags=tags)

    def match(self, line: str, line_nr: int) -> Optional[UnrealLogFileLineMatch]:
        """
        Search for pattern matches in a given line.
        Returns an UnrealLogFileLineMatch if a match was found. Otherwise None.
        Matches automatically alter the root pattern scope by reporting success/failure states of build steps.
        """
        # HACK: Remove newlines at end
        line = line[0:-1]

        if self.pattern is None:
            return None

        if self.is_regex:
            re_match = re.search(self.pattern, line)
            if re_match is None:
                return None
            string_vars = {}
            for name in self.string_var_names:
                named_group_value = re_match.group(name)
                if not named_group_value is None:
                    string_vars[name] = named_group_value
            numeric_vars = {}
            for name in self.numeric_var_names:
                named_group_value = re_match.group(name)
                if not named_group_value is None:
                    try:
                        numeric_vars[name] = float(named_group_value)
                    except ValueError:
                        numeric_vars[name] = float(
                            named_group_value.replace(",", "."))
            result_match = UnrealLogFileLineMatch(
                line, self, line_nr, string_vars, numeric_vars) if re_match else None
        else:
            # Convert both to lower case to make matching case-insensitive
            matches = self.pattern.lower() in line.lower()
            result_match = UnrealLogFileLineMatch(
                line, self, line_nr) if matches else None

        return result_match


class UnrealLogFilePatternList_MatchList:
    """
    A list of matches for a UnrealLogFilePatternList
    """
    source_list: 'UnrealLogFilePatternList'
    owning_scope_instance: 'UnrealLogFilePatternScopeInstance'
    matching_lines: list[UnrealLogFileLineMatch]

    def __init__(self, source_list: 'UnrealLogFilePatternList', owning_scope_instance: 'UnrealLogFilePatternScopeInstance') -> None:
        self.source_list = source_list
        self.owning_scope_instance = owning_scope_instance
        self.matching_lines = []

    def num_matches(self) -> int:
        return len(self.matching_lines)

    def filter_unique_lines(self) -> None:
        self.matching_lines = list(set(self.matching_lines))

    def get_header(self) -> str:
        scope_name = self.owning_scope_instance.get_fully_qualified_scope_name()
        return f"[{scope_name}] {self.source_list.severity.get_emoji()}  {self.source_list.group_name}"

    def match(self, line: str, line_number: int) -> Optional[UnrealLogFileLineMatch]:
        """
        Returns an UnrealLogFileLineMatch for the first pattern that matches the given line.
        May return None if no match was found.
        """
        # Go through exclude patterns first, because we always have to check all of these
        for pattern in self.source_list.exclude_patterns:
            if not pattern.match(line, line_number) is None:
                return None

        for pattern in self.source_list.include_patterns:
            match = pattern.match(line, line_number)
            if match is None:
                continue
            self.owning_scope_instance.flag_match_success(match)
            return match

    def match_tags(self, tags: List[str]) -> bool:
        """Returns true if the statically configured tag list or dynamically determined tags per line contain any of the input tags"""
        if len(tags) == 0 or self.source_list.match_tags(tags):
            return True
        for tag in tags:
            if any(tag in line.tags for line in self.matching_lines):
                return True
        return False

    def format(self, max_lines: int) -> str:
        num_lines = len(self.matching_lines)
        if num_lines == 0:
            return ""
        disp_lines = min(max_lines, num_lines) if max_lines >= 0 else num_lines
        header_str = self.get_header()
        header = f"### {header_str} ({disp_lines}/{num_lines}) <{';'.join(self.source_list.tags)}> ###\n"
        body = "\n".join(str(line)
                         for line in self.matching_lines[0:disp_lines])
        return header + body

    def json(self) -> Optional[dict]:
        num_lines = len(self.matching_lines)
        if num_lines == 0:
            return None
        lines_json_objs = list(filter(lambda x: x is not None, [
                               line.json() for line in self.matching_lines]))

        # Lines come from a set, which has non stable sorting.
        # In the json output we want the lines sorted by line number.
        lines_json_objs.sort(key=lambda line: line["line_nr"])

        return {
            "name": self.source_list.group_name,
            "severity": self.source_list.severity.json(),
            "tags": list(self.source_list.tags),
            "lines": lines_json_objs,
            "hidden": self.source_list.hidden
        }

    def _check_and_add(self, line: str, line_number: int) -> bool:
        match = self.match(line, line_number)
        if match is None:
            return False
        if match in self.matching_lines:
            match_idx = self.matching_lines.index(match)
            self.matching_lines[match_idx].occurences += 1
        else:
            self.matching_lines.append(match)
        return True


class UnrealLogFilePatternList:
    """
    A list of log file patterns.
    Only the first pattern in a list that matches will contain the line match. Later potential matches are skipped.
    Exclude patterns (negative matches) override include patterns (positive matches).
    """
    group_name: str
    # If true, the matches in this list will be hidden in output. i.e. only used as intermediate steps for variable gathering, etc.
    hidden: bool
    severity: UnrealLogSeverity
    tags: Set[str]
    owning_scope: 'UnrealLogFilePatternScopeDeclaration'
    include_patterns: list[UnrealLogFilePattern]
    exclude_patterns: list[UnrealLogFilePattern]
    success_flag_names: set
    failure_flag_names: set

    def __init__(self, group_name: str, owning_scope: 'UnrealLogFilePatternScopeDeclaration') -> None:
        self.group_name = group_name
        self.owning_scope = owning_scope
        self.severity = UnrealLogSeverity.MESSAGE
        self.tags = set()
        self.include_patterns = []
        self.exclude_patterns = []
        self.success_flag_names = set()
        self.failure_flag_names = set()

    def match_tags(self, tags: List[str]) -> bool:
        """Returns true if the statically configured tag list contains any of the input tags"""
        if len(tags) == 0:
            return True
        for tag in tags:
            if tag is None or tag == "" or tag.upper() in self.tags:
                return True
            if any(tag in pattern.tags for pattern in self.include_patterns):
                return True
        return False

    @staticmethod
    def _from_xml_node(xml_node: XmlNode, owning_scope: 'UnrealLogFilePatternScopeDeclaration') -> 'UnrealLogFilePatternList':
        result_list = UnrealLogFilePatternList(
            str(xml_node.get("Name")),
            owning_scope=owning_scope)

        result_list.severity = UnrealLogSeverity.from_string(
            xml_node.get("Severity", default=""))
        result_list.hidden = strtobool(xml_node.get("Hidden"))

        tags_str = xml_node.get("Tags", default="")
        if len(tags_str) > 0:
            result_list.tags = set(tag.upper() for tag in tags_str.split(";"))

        # This needs to happen before pattern nodes are generated!
        result_list.success_flag_names = _get_name_id_list(
            xml_node, "SuccessFlags")
        result_list.failure_flag_names = _get_name_id_list(
            xml_node, "FailureFlags")

        for pattern in xml_node.findall("Include"):
            include_pattern = UnrealLogFilePattern._from_xml_node(
                pattern, owning_scope, result_list)
            if include_pattern is not None:
                result_list.include_patterns.append(include_pattern)
        for pattern in xml_node.findall("Exclude"):
            exclude_pattern = UnrealLogFilePattern._from_xml_node(
                pattern, owning_scope, result_list)
            if exclude_pattern is not None:
                result_list.exclude_patterns.append(exclude_pattern)

        return result_list


class UnrealLogFilePatternScopeDeclaration:
    """
    A pattern scope contains multiple pattern lists and child scope.
    There is only ever one topmost root scope.
    """
    scope_name: str
    scope_display_name_var: Optional[str]
    parent_target_name: Optional[str]
    root_scope: 'UnrealLogFilePatternScopeDeclaration'
    parent_scope: Optional['UnrealLogFilePatternScopeDeclaration']
    require_all_lines_match: bool

    child_scope_declarations: List['UnrealLogFilePatternScopeDeclaration']
    start_patterns: List[UnrealLogFilePattern]
    end_patterns: List[UnrealLogFilePattern]
    pattern_lists: List[UnrealLogFilePatternList]

    def __init__(self,
                 scope_name: str,
                 scope_display_name_var: Optional[str],
                 parent_target_name: Optional[str],
                 require_all_lines_match: bool,
                 parent_scope: Optional['UnrealLogFilePatternScopeDeclaration']) -> None:
        self.scope_name = scope_name
        self.scope_display_name_var = scope_display_name_var
        self.parent_target_name = parent_target_name
        self.parent_scope = parent_scope
        self.root_scope = self if parent_scope is None else parent_scope.root_scope
        self.require_all_lines_match = require_all_lines_match

        self.child_scope_declarations = []
        self.start_patterns = []
        self.end_patterns = []
        self.pattern_lists = []

    def is_root_scope(self) -> bool:
        return self.root_scope == self

    def num_patterns(self) -> int:
        result = 0
        for list in self.pattern_lists:
            result += len(list.include_patterns) + len(list.exclude_patterns)
        for child_scope_template in self.child_scope_declarations:
            result += child_scope_template.num_patterns()
        return result

    def get_fully_qualified_scope_name(self) -> str:
        """
        The fully qualified scope name is the name of the current scope preceded by the full chain of parent scopes.
        """
        return ((self.parent_scope.get_fully_qualified_scope_name() + ".") if not self.parent_scope is None else "") + self.scope_name

    def all_scopes(self) -> Iterator['UnrealLogFilePatternScopeDeclaration']:
        """Iterate all nested scopes"""
        yield self
        for child_scope in self.child_scope_declarations:
            for scope in child_scope.all_scopes():
                yield scope

    def all_parent_scopes(self) -> Iterator['UnrealLogFilePatternScopeDeclaration']:
        """Iterate the chain of parent scopes up to the root scope."""
        yield self
        if self.parent_scope is None:
            return
        for scope in self.parent_scope.all_parent_scopes():
            yield scope

    def all_lists(self) -> Iterator['UnrealLogFilePatternList']:
        """Iterate all pattern lists inside all child scopes"""
        for scope in self.all_scopes():
            for pattern_list in scope.pattern_lists:
                yield pattern_list

    @staticmethod
    def _from_xml_node(xml_node: XmlNode, root_node: XmlTree, parent_scope: Optional['UnrealLogFilePatternScopeDeclaration'] = None, parent_target_name: Optional[str] = None) -> 'UnrealLogFilePatternScopeDeclaration':
        """
        Create a scope object from an XML node.
        The node can be either a <Template> or <Target> node.
        """
        result_scope = UnrealLogFilePatternScopeDeclaration(
            str(xml_node.get("Name")),
            xml_node.get("DisplayNameVariable"),
            parent_target_name,
            bool(xml_node.get("RequireAllLinesMatch")),
            parent_scope=parent_scope)

        result_scope._set_start_end_patterns(xml_node)

        # Fill info + Generate child scopes.
        result_scope._fill_scope_from_xml_node(xml_node,
                                               root_node)
        return result_scope

    def _fill_scope_from_xml_node(self, xml_node: XmlNode, root_node: XmlTree) -> None:
        for pattern_list in xml_node.findall("./Patterns"):
            self.pattern_lists.append(
                UnrealLogFilePatternList._from_xml_node(pattern_list, self))
        for scope in xml_node.findall("./Scope"):
            self._link_child_scope(
                UnrealLogFilePatternScopeDeclaration._from_xml_node(scope,
                                                                    root_node=root_node,
                                                                    parent_scope=self,
                                                                    parent_target_name=self.parent_target_name))
        for link in xml_node.findall("./Link"):
            template_name = link.get("Template")
            found_template = False
            # Prefer templates
            for template in root_node.findall("./Template"):
                if template.get("Name") == template_name:
                    self._fill_scope_from_xml_node(template, root_node)
                    found_template = True
                    break
            # If there is not template with matching name, fallback to linking targets
            if not found_template:
                for template in root_node.findall("./Target"):
                    if template.get("Name") == template_name:
                        self._fill_scope_from_xml_node(template, root_node)
                        found_template = True
                        break
            if not found_template:
                raise OUAException(
                    f"No template or target with name {template_name} was found")

    def _set_start_end_patterns(self, xml_node: XmlNode) -> None:
        self.start_patterns = []
        self.end_patterns = []

        for node in xml_node.findall("Start"):
            start_pattern = UnrealLogFilePattern._from_xml_node(node, self)
            if start_pattern is not None:
                self.start_patterns.append(start_pattern)

        for node in xml_node.findall("End"):
            end_pattern = UnrealLogFilePattern._from_xml_node(
                node, self)
            if end_pattern is not None:
                self.end_patterns.append(end_pattern)

    def _link_child_scope(self, child_scope: 'UnrealLogFilePatternScopeDeclaration') -> None:
        child_scope.parent_scope = self
        self.child_scope_declarations.append(child_scope)
        child_scope.root_scope = self.root_scope


class UnrealLogFilePatternScopeInstance:
    """
    A result of a parsing attempt. Every scope declaration can appear multiple times, so we need to separate different instances of the same scope.
    E.g. you could have a declaration for {Build{Compile,Cook}} but multiple instances resulting in {Build_1{Compile_1, Cook_1}, Build_2{Compile_2, Cook_2}}

    The root scope tracks step_success_flags usually associated with nested scopes (e.g. Job.Build=success, Job.Cook=failure).
    """

    source_file: str
    parent_scope_instance: Optional['UnrealLogFilePatternScopeInstance']
    child_scope_instances: List['UnrealLogFilePatternScopeInstance']
    scope_declaration: 'UnrealLogFilePatternScopeDeclaration'

    start_line_match: Optional[UnrealLogFileLineMatch]
    end_line_match: Optional[UnrealLogFileLineMatch]

    instance_number: int

    # Only valid on root scope
    step_success_flags: List[Tuple[str, UnrealBuildStepStatus]]

    pattern_match_lists: List[UnrealLogFilePatternList_MatchList]

    def __init__(self, source_file: str, parent_scope_instance: Optional['UnrealLogFilePatternScopeInstance'], scope_declaration: 'UnrealLogFilePatternScopeDeclaration', start_match: UnrealLogFileLineMatch, instance_number: int) -> None:
        self.source_file = source_file
        self.parent_scope_instance = parent_scope_instance
        self.scope_declaration = scope_declaration
        self.start_line_match = start_match
        self.end_line_match = None
        self.instance_number = instance_number

        self.child_scope_instances = []
        self.step_success_flags = []
        self.pattern_match_lists = []
        for pattern_list in self.scope_declaration.pattern_lists:
            self.pattern_match_lists.append(
                UnrealLogFilePatternList_MatchList(pattern_list, self))

    def open_child_scope(self, scope_declaration: 'UnrealLogFilePatternScopeDeclaration', start_match: UnrealLogFileLineMatch) -> 'UnrealLogFilePatternScopeInstance':
        num_instances_same_type = 0
        for child_scope_instance in self.child_scope_instances:
            if child_scope_instance.scope_declaration == scope_declaration:
                num_instances_same_type += 1

        new_child_scope = UnrealLogFilePatternScopeInstance(
            self.source_file, self, scope_declaration, start_match=start_match, instance_number=num_instances_same_type)

        self.child_scope_instances.append(new_child_scope)
        return new_child_scope

    def close_scope(self, end_match: UnrealLogFileLineMatch) -> None:
        for child_scope in self.child_scope_instances:
            child_scope.close_scope(end_match)

        if self.end_line_match is None:
            self.end_line_match = end_match
        if len(self.step_success_flags) == 0:
            self.step_success_flags.append(
                (self.get_fully_qualified_scope_name(), UnrealBuildStepStatus.UNKNOWN))

    def num_matches(self) -> int:
        return sum(match_list.num_matches() for match_list in self.pattern_match_lists) + sum(child_scope_instance.num_matches() for child_scope_instance in self.child_scope_instances)

    def _check_and_add(self, line: str, line_number: int) -> bool:
        """
        Check a line on current scope INSTANCE and its pattern lists for matches or bubble up to parent scopes.
        Does NOT recurse into child scopes!
        """
        for match_list in self.pattern_match_lists:
            if match_list._check_and_add(line, line_number):
                return True

        if self.parent_scope_instance is None:
            return False

        # If not match in own patterns was found, bubble up to parents
        return self.parent_scope_instance._check_and_add(line, line_number)

    def format(self, max_lines: int) -> str:
        """
        Format the scope and all its contents for pretty printing.
        max_lines are passed to each pattern list (so the total number of displayed lines is likely much larger).
        """
        result = ""
        for match_list in self.pattern_match_lists:
            result += match_list.format(max_lines).strip() + "\n\n"
        for child_scope_instance in self.child_scope_instances:
            result += child_scope_instance.format(max_lines).strip() + "\n\n"

        # Remove all whitespace over more than 2 lines
        while "\n\n\n" in result:
            result = result.replace("\n\n\n", "\n\n")

        # Strip whitespace at start + end
        return result.strip()

    def get_local_scope_name(self) -> str:
        suffix = f"_{self.instance_number}" if self.instance_number > 0 else ""
        return f"{self.scope_declaration.scope_name}{suffix}"

    def get_scope_display_name(self, fully_qualified: bool = False, add_line_suffix: bool = True) -> str:

        if fully_qualified:
            base_name = self.get_local_scope_name() if self.parent_scope_instance is None else (
                self.parent_scope_instance.get_scope_display_name(fully_qualified=True, add_line_suffix=False) + "." + self.get_local_scope_name())
        else:
            base_name = self.get_local_scope_name()

        line_nr_str = str(
            self.start_line_match.line_nr) if self.start_line_match is not None else '?'
        line_number_suffix = f" @ {line_nr_str}-{'?' if self.end_line_match is None else str(self.end_line_match.line_nr)}" if add_line_suffix else ""
        display_suffix = f" - {self.get_string_variable(self.scope_declaration.scope_display_name_var)}" if self.scope_declaration.scope_display_name_var is not None else ""
        return f"{base_name}{display_suffix}{line_number_suffix}"

    def get_fully_qualified_scope_name(self) -> str:
        """
        The name of scope instances contains the full name of the template plus a number to differentiate
        multiple instances of the same declaration.
        """
        base_name = "" if self.parent_scope_instance is None else (
            self.parent_scope_instance.get_fully_qualified_scope_name() + ".")

        return f"{base_name}{self.get_local_scope_name()}"

    def get_status(self, flag: str) -> UnrealBuildStepStatus:
        for _flag, status in self.step_success_flags:
            if _flag == flag:
                return status
        return UnrealBuildStepStatus.UNKNOWN

    def get_scope_status(self) -> UnrealBuildStepStatus:
        return self.get_status(self.get_fully_qualified_scope_name())

    def filter_inline(self, tags: List[str], min_severity: UnrealLogSeverity, min_matches: int = 1, unique_lines: bool = True) -> None:
        """
        Filter out match results by
        - duplicates
        - required tags (any if empty)
        - minimum severity
        - minimum number of matches per pattern list
        This is a lossy operation. In most cases, you'll want to use filter() to create a deep copy of the scope and retain an unfiltered original list.
        """
        self.pattern_match_lists = [match_list for match_list in self.pattern_match_lists if
                                    len(match_list.matching_lines) >= min_matches and
                                    match_list.source_list.severity.value >= min_severity.value and
                                    match_list.match_tags(tags)]
        if unique_lines:
            for match_list in self.pattern_match_lists:
                match_list.filter_unique_lines()

        for child_scope_instance in self.child_scope_instances:
            child_scope_instance.filter_inline(tags, min_severity)

    def filter(self, tag: str, min_severity: UnrealLogSeverity, min_matches: int = 1) -> 'UnrealLogFilePatternScopeInstance':
        """
        Create a deep copy of this scope instance and filter out match results (see filter_inline).
        Only supported on root scopes to avoid invalid linking of scopes.
        """
        if not self.scope_declaration.is_root_scope():
            raise OUAException(
                f"Creating a deep copy of a scope is only allowed for the root scope, but {self.get_fully_qualified_scope_name()} is not a root scope. "
                f"It might still work, but I never tested it and don't want to break anything")
        self_copy = copy.deepcopy(self)
        tags = tag.split(";")
        self_copy.filter_inline(tags, min_severity, min_matches)
        return self_copy

    def json(self) -> dict:
        """
        Return a plain (json compatible) dictionary representation of this scope with its lists and matches.
        Child scopes without matches are omitted.
        """
        result = {}
        result["name"] = f"{self.get_scope_status().get_icon()} {self.get_scope_display_name()}"
        result["start"] = self.start_line_match.json(
        ) if self.start_line_match is not None else ""
        result["end"] = self.end_line_match.json(
        ) if self.end_line_match is not None else ""
        match_lists_jsons = [list.json()
                             for list in self.pattern_match_lists]
        result["match_lists"] = [
            list_json for list_json in match_lists_jsons if list_json is not None]
        result["child_scopes"] = [scope.json()
                                  for scope in self.child_scope_instances]

        result["status"] = self.get_scope_status().long_str()
        result["steps"] = [{"step": step, "status": str(step_status)}
                           for (step, step_status) in self.step_success_flags]
        return result

    def all_scope_instances(self, self_depth=0) -> Iterator[Tuple['UnrealLogFilePatternScopeInstance', int]]:
        """Iterate all nested scope instances"""
        yield self, self_depth
        for child_scope_instance in self.child_scope_instances:
            for scope, child_depth in child_scope_instance.all_scope_instances(self_depth+1):
                yield scope, child_depth

    def all_parent_scope_instances(self) -> Iterator['UnrealLogFilePatternScopeInstance']:
        """Iterate the chain of parent scope instances up to the root scope."""
        yield self
        if self.parent_scope_instance is None:
            return
        for scope in self.parent_scope_instance.all_parent_scope_instances():
            yield scope

    def all_match_lists(self) -> Iterator['UnrealLogFilePatternList_MatchList']:
        """Iterate all pattern lists inside all child scopes"""
        for scope, _ in self.all_scope_instances():
            for match_list in scope.pattern_match_lists:
                yield match_list

    def all_matching_lines(self, include_hidden=True) -> Iterator[UnrealLogFileLineMatch]:
        """Iterate all matching lines inside all lists inside all child scopes"""
        if self.start_line_match is not None:
            if include_hidden or (self.start_line_match.owning_pattern and self.start_line_match.owning_pattern.owning_list and not self.start_line_match.owning_pattern.owning_list.hidden):
                yield self.start_line_match
        if self.end_line_match is not None:
            if include_hidden or (self.end_line_match.owning_pattern and self.end_line_match.owning_pattern.owning_list and not self.end_line_match.owning_pattern.owning_list.hidden):
                yield self.end_line_match
        for list in self.all_match_lists():
            if include_hidden or not list.source_list.hidden:
                for line in list.matching_lines:
                    yield line

    def get_string_variable(self, variable_name: str) -> Optional[str]:
        """
        Get the first instance of a string variable with the given name.
        If multiple lines have a variable with that name, only the first occurence will be returned.
        """
        for line in self.all_matching_lines():
            result = line.string_vars.get(variable_name)
            if result is not None:
                return result
        return None

    def flag_match_success(self, match: UnrealLogFileLineMatch) -> None:
        if match.owning_pattern is None:
            return

        full_scope_name = self.get_fully_qualified_scope_name()
        for flag in match.owning_pattern.success_flag_names:
            flag = full_scope_name if flag == "auto" else flag
            self._flag_step_status(flag, UnrealBuildStepStatus.SUCCESS)
        for flag in match.owning_pattern.failure_flag_names:
            flag = full_scope_name if flag == "auto" else flag
            self._flag_step_status(flag, UnrealBuildStepStatus.FAILURE)
        if match.owning_pattern.owning_list is not None and match.owning_pattern.owning_list.severity == UnrealLogSeverity.FATAL:
            # Automatically flag the owning scope as failure.
            self._flag_step_status(
                full_scope_name, UnrealBuildStepStatus.FAILURE)

    def _flag_step_status(self, flag: str, step_status: UnrealBuildStepStatus) -> None:
        """Reports a success or failure to the root scope."""
        # TODO At the moment this always uses the root scope, but maybe there is some benefit in tracking these flags on sub-scopes?
        # root_scope: 'UnrealLogFilePatternScopeDeclaration' = self.owning_scope.scope_declaration.root_scope
        flag_modified = False

        for step_index, (previous_flag, previous_step_status) in enumerate(self.step_success_flags):
            if previous_flag != flag:
                continue
            if previous_step_status == step_status:
                # The same flag was already present. We don't want duplicate flags / status
                pass
            else:
                if step_status == UnrealBuildStepStatus.FAILURE:
                    # Marking a previously successful step as failed is okay-ish - we just overwrite with new value
                    self.step_success_flags[step_index] = (
                        flag, step_status)
                    flag_modified = True
                    break
                else:
                    # However, this is definitely undesirable.
                    print(f"The step success flag '{flag}' was previously set to failure and is now set to success inside scope",
                          self.scope_declaration.scope_name)
                    break
        if not flag_modified:
            self.step_success_flags.append((flag, step_status))
            flag_modified = True

        if flag_modified:
            if step_status == UnrealBuildStepStatus.FAILURE:
                full_scope_name = self.get_fully_qualified_scope_name()
                if flag == full_scope_name:
                    if self.parent_scope_instance is not None:
                        self.parent_scope_instance._flag_step_status(
                            self.parent_scope_instance.get_fully_qualified_scope_name(), UnrealBuildStepStatus.FAILURE)
                else:
                    self._flag_step_status(
                        full_scope_name, UnrealBuildStepStatus.FAILURE)


def get_log_patterns(xml_path: Optional[str], target_name: str) -> UnrealLogFilePatternScopeDeclaration:
    """
    Import a list of log file patterns from an xml file.
    Groups are assigned to a target that must match to the input target_name.
    """
    xml_path = xml_path if xml_path else _get_default_patterns_xml()
    print("Importing log file pattern list from", xml_path)
    root_node = XmlTree(file=xml_path)
    for target in root_node.findall("./Target"):
        if target.get("Name") == target_name:
            return UnrealLogFilePatternScopeDeclaration._from_xml_node(target, root_node, parent_scope=None, parent_target_name=target_name)
    raise OUAException(
        f"No definition for log file target '{target_name}' in patterns from {xml_path}")


class LogScopeChange(Enum):
    UNCHANGED = 0,
    OPEN = 1,
    CLOSE = 2


def parse_log(log_path: str, logparse_patterns_xml: Optional[str], target_name: str) -> UnrealLogFilePatternScopeInstance:
    """
    Parse the log file into a dictionary.
    Each key of the dict represents a named group of patterns.
    Groups are themselves assigned to log file types, so we can have different patterns for different log files.
    The tree of pattern groups are defined in xml files (see resources/logparse_patterns.xml for sample).
    """
    if log_path is None:
        raise OUAException("Cannot parse None logfile")

    print(f"Parsing log file '{log_path}'")

    root_scope_declaration = get_log_patterns(
        logparse_patterns_xml, target_name)
    if root_scope_declaration.num_patterns() == 0:
        raise OUAException("No log parsing patterns found!")

    # current_scope = root_scope_declaration
    root_scope_instance = UnrealLogFilePatternScopeInstance(
        source_file=log_path,
        parent_scope_instance=None,
        scope_declaration=root_scope_declaration,
        # TODO Move into first iteration so we get the first line?
        start_match=UnrealLogFileLineMatch(
            "", None, 0),
        instance_number=0)
    current_scope_instance = root_scope_instance

    def try_open_scope() -> None:
        nonlocal current_scope_instance
        nonlocal scope_change

        if current_scope_instance is None or current_scope_instance.scope_declaration is None:
            return

        for child_scope_declaration in current_scope_instance.scope_declaration.child_scope_declarations:
            for start_pattern in child_scope_declaration.start_patterns:
                start_match = start_pattern.match(line, line_number)
                if start_match is None:
                    continue
                current_scope_instance = current_scope_instance.open_child_scope(
                    scope_declaration=child_scope_declaration, start_match=start_match)
                current_scope_instance.flag_match_success(start_match)
                scope_change = LogScopeChange.OPEN
                break
            # Can't enter two child scopes at the same time, e.g.
            # scope A { scope X {}, scope Y {}} --> can't enter X and Y at the same time
            if scope_change is LogScopeChange.OPEN:
                break

    def try_close_scope() -> None:
        nonlocal current_scope_instance
        nonlocal scope_change

        scope_close_needed = False
        end_match = None
        for end_pattern in filter(lambda end_pattern: not end_pattern is None, check_parent_scope_declaration.end_patterns):
            end_match = end_pattern.match(line, line_number)
            if end_match is None:
                continue
            check_parent_scope.flag_match_success(end_match)
            scope_close_needed = True
            break

        if not scope_close_needed and check_parent_scope_declaration.require_all_lines_match and not line_checked:
            scope_close_needed = True

        if scope_close_needed:
            if end_match is not None:
                check_parent_scope.close_scope(end_match)
            current_scope_instance = check_parent_scope.parent_scope_instance
            scope_change = LogScopeChange.CLOSE

    with open(log_path, "r") as file:
        lines = file.readlines()
        with alive_bar(len(lines), title="parsing lines") as update_progress_bar:
            for line_number, line in enumerate(lines, 0):
                update_progress_bar()

                # What's a higher priority?
                # 1) closing current scope <- current implementation
                # 2) opening child scopes
                scope_change = LogScopeChange.UNCHANGED

                # Allow parsing a line that is on the end line of a scope
                line_checked = current_scope_instance._check_and_add(
                    line, line_number)

                # Allow not only current scope, but also all parent scopes to end/close.
                # This is required, because script steps may crash / exit preemptively, which would result in socpes not being closed properly,
                # which in turn might mess up parsing rules of the next steps.
                for check_parent_scope in current_scope_instance.all_parent_scope_instances():
                    check_parent_scope_declaration = check_parent_scope.scope_declaration
                    try_close_scope()
                    if scope_change is not LogScopeChange.UNCHANGED:
                        break

                try_open_scope()

                # A line can be matched by multiple scopes. Always give the starting and ending scope an opportunity to parse it.
                current_scope_instance._check_and_add(line, line_number)

    if not current_scope_instance.scope_declaration.is_root_scope():
        print(
            f"WARNING: Child scope '{current_scope_instance.get_fully_qualified_scope_name()}' was opened but not closed. This may be a sign of an uncompleted automation step.")

    return root_scope_instance


def parse_logs(log_dir: str, logparse_patterns_xml: Optional[str], target_name: str) -> List[UnrealLogFilePatternScopeInstance]:
    log_file_paths = []
    print(f"Searching for build logs in {log_dir}...")
    for path in os.scandir(log_dir):
        if not path.is_file():
            continue
        # Skip this node which is always generated and should _rarely_ fail -> Optimize readability for 90% of build logs
        if path.name == "get_all_buildgraph_node_names.log":
            continue
        log_file_paths.append(path.path)
    log_file_paths.sort(key=lambda path: os.path.getctime(path))
    parsed_logs = []
    for log_file_path in log_file_paths:
        parsed_log = parse_log(
            log_file_path, logparse_patterns_xml, target_name)
        parsed_logs.append(parsed_log)
    return parsed_logs


def print_parsed_log(path: str, logparse_patterns_xml: str, target_name: str, max_lines: int = 20) -> None:
    header_divider = "\n==========================="
    print(header_divider, "\nParsing log file", path, "...", header_divider)

    scope_with_matches = parse_log(path, logparse_patterns_xml, target_name)
    print("\n", scope_with_matches.format(max_lines))


def _main_get_files() -> List[Tuple[str, Optional[str]]]:
    env = UnrealEnvironment.create_from_invoking_file_parent_tree()

    argparser = argparse.ArgumentParser()
    argparser.add_argument("--files")
    cli_args = argparser.parse_args()

    files: List[Tuple[str, Optional[str]]]
    if cli_args.files is not None:
        files_strs = cli_args.files.split(",")
        files = []
        for i in range(0, len(files_strs), 2):
            files.append((files_strs[i], files_strs[i+1]))
    else:
        files = [
            ("UAT", UnrealLogFile.UAT.find_latest(env)),
            ("Cook", UnrealLogFile.COOK.find_latest(env)),
            ("Unreal", UnrealLogFile.EDITOR.find_latest(env))
        ]

    return files


def _get_default_patterns_xml():
    return os.path.normpath(os.path.join(
        Path(__file__).parent, "resources/logparse_patterns.xml"))


if __name__ == "__main__":
    files = _main_get_files()

    for target, file in files:
        if file is not None:
            print_parsed_log(file, _get_default_patterns_xml(), target)
        else:
            print("no file for target", target)
