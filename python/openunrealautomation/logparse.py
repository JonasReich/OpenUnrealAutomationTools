﻿"""
Parse UE logs for warning / error summary.
"""

import argparse
import copy
import os.path
import re
from enum import Enum
from pathlib import Path
from typing import Iterator, List, Tuple
from xml.etree.ElementTree import Element as XmlNode
from xml.etree.ElementTree import ElementTree as XmlTree

from openunrealautomation.core import *
from openunrealautomation.environment import UnrealEnvironment
from openunrealautomation.logfile import UnrealLogFile


def _get_name_id_list(xml_node: XmlNode, attribute: str) -> set[str]:
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
    MESSAGE = 0, "📄", "message"
    WARNING = 1, "⚠️", "warning"
    ERROR = 2, "⛔", "error"
    # only distinguish internally for now -> auto step fails. json export etc should be unaffected.
    FATAL = 3, "⛔", "error"

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


class UnrealLogFileLineMatch:
    """
    A pattern match of a single file from a log file.
    Stores meta information from where it was parsed and variables extracted from the line.
    """
    line: str = ""
    owning_pattern: 'UnrealLogFilePattern'
    # Line number where this match was first encountered
    line_nr: int = 0
    string_vars: dict = {}
    numeric_vars: dict = {}
    occurences: int = 1
    # List of tags that were added for this particular line
    # (this has to be done by external post-processing code atm)
    tags: set = None

    def __init__(self, line: str, owning_pattern: 'UnrealLogFilePattern', line_nr: int, string_vars: dict = {}, numeric_vars: dict = {}) -> None:
        self.line = line
        self.owning_pattern = owning_pattern
        self.line_nr = line_nr
        self.string_vars = string_vars
        self.numeric_vars = numeric_vars
        self.tags = set()

    def __str__(self) -> str:
        return self.line

    def __eq__(self, other) -> bool:
        return self.line == other.line

    def __hash__(self) -> int:
        return hash(self.line)

    def get_tags(self) -> set:
        return self.tags.union(self.owning_pattern.tags, self.owning_pattern.owning_list.tags)

    def json(self) -> dict:
        return {
            "line": self.line,
            "line_nr": self.line_nr,
            "severity": self.owning_pattern.owning_list.severity.json(),
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
    owning_scope: 'UnrealLogFilePatternScope'
    owning_list: 'UnrealLogFilePatternList'

    pattern: str = ""
    is_regex: bool = True

    string_var_names: set
    numeric_var_names: set
    success_flag_names: set
    failure_flag_names: set
    tags: set

    def __init__(self, pattern: str,
                 owning_scope: 'UnrealLogFilePatternScope',
                 owning_list: 'UnrealLogFilePatternList',
                 is_regex: bool,
                 string_var_names: set,
                 numeric_var_names: set,
                 success_flag_names: set,
                 failure_flag_names: set,
                 tags: set):
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
    def _from_xml_node(xml_node: XmlNode, owning_scope: 'UnrealLogFilePatternScope', owning_list: 'UnrealLogFilePatternList' = None) -> 'UnrealLogFilePattern':
        if None is xml_node:
            return None
        is_regex = xml_node.get("Style", default="Regex") == "Regex"
        string_var_names = _get_name_id_list(xml_node, "StringVariables")
        numeric_var_names = _get_name_id_list(xml_node, "NumericVariables")
        success_flag_names = _get_name_id_list(xml_node, "SuccessFlags")
        failure_flag_names = _get_name_id_list(xml_node, "FailureFlags")

        # convert to caps -> for legacy purposes. everything else is case senstitive.
        # TODO consider making the tags case sensitive as well!
        tags_set_nocaps = _get_name_id_list(xml_node, "Tags")
        if len(tags_set_nocaps) > 0:
            tags = set(tag.upper() for tag in tags_set_nocaps)
        else:
            tags = set()

        return UnrealLogFilePattern(xml_node.text,
                                    owning_scope=owning_scope,
                                    owning_list=owning_list,
                                    is_regex=is_regex,
                                    string_var_names=string_var_names,
                                    numeric_var_names=numeric_var_names,
                                    success_flag_names=success_flag_names,
                                    failure_flag_names=failure_flag_names,
                                    tags=tags)

    def match(self, line: str, line_nr: int) -> UnrealLogFileLineMatch:
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

        if not result_match is None:
            full_scope_name = self.owning_scope.get_fully_qualified_scope_name()
            for flag in self.success_flag_names:
                flag = full_scope_name if flag == "auto" else flag
                self._flag_success(flag, True)
            for flag in self.failure_flag_names:
                flag = full_scope_name if flag == "auto" else flag
                self._flag_success(flag, False)
            if not self.owning_list is None and self.owning_list.severity == UnrealLogSeverity.FATAL:
                # Automatically flag the owning scope as failure.
                self._flag_success(full_scope_name, False)

        return result_match

    def _flag_success(self, flag: str, is_success: bool) -> None:
        """Reports a success or failure to the root scope."""
        # TODO At the moment this always uses the root scope, but maybe there is some benefit in tracking these flags on sub-scopes?
        root_scope: 'UnrealLogFilePatternScope' = self.owning_scope.root_scope
        for step_index, (previous_flag, previous_is_success) in enumerate(root_scope.step_success_flags):
            if previous_flag != flag:
                continue
            if previous_is_success != is_success:
                if is_success == False:
                    # Marking a previously successful step as failed is okay-ish - we just overwrite with new value
                    root_scope.step_success_flags[step_index] = (
                        flag, is_success)
                else:
                    # However, this is definitely undesirable.
                    print(f"The step success flag '{flag}' was previously set to failure and is now set to success inside scope",
                          self.owning_scope.scope_name)
            # The same flag was already present. We don't want duplicate flags
            return

        root_scope.step_success_flags.append((flag, is_success))


class UnrealLogFilePatternList:
    """
    A list of log file patterns.
    Only the first pattern in a list that matches will contain the line match. Later potential matches are skipped.
    Exclude patterns (negative matches) override include patterns (positive matches).
    """
    group_name: str = ""
    severity: UnrealLogSeverity
    tags: set[str] = None
    owning_scope: 'UnrealLogFilePatternScope'
    include_patterns: list[UnrealLogFilePattern]
    exclude_patterns: list[UnrealLogFilePattern]
    matching_lines: set[UnrealLogFileLineMatch]

    def __init__(self, group_name: str, owning_scope: 'UnrealLogFilePatternScope'):
        self.group_name = group_name
        self.owning_scope = owning_scope
        self.severity = UnrealLogSeverity.MESSAGE
        self.tags = set()
        self.include_patterns = []
        self.exclude_patterns = []
        self.matching_lines = []

    def match(self, line: str, line_number: int) -> UnrealLogFileLineMatch:
        """
        Returns an UnrealLogFileLineMatch for the first pattern that matches the given line.
        May return None if no match was found.
        """
        # Go through exclude patterns first, because we always have to check all of these
        for pattern in self.exclude_patterns:
            if not pattern.match(line, line_number) is None:
                return None

        first_match: UnrealLogFileLineMatch = None
        for pattern in self.include_patterns:
            first_match = pattern.match(line, line_number)
            if not first_match is None:
                break

        return first_match

    def match_tags(self, tags: list[str]) -> bool:
        """Returns true if the statically configured tag list or dynamically determined tags per line contain any of the input tags"""
        if len(tags) == 0:
            return True
        for tag in tags:
            if tag is None or tag == "" or tag.upper() in self.tags:
                return True
            if any(tag in pattern.tags for pattern in self.include_patterns):
                return True
            if any(tag in line.tags for line in self.matching_lines):
                return True
        return False

    def get_header(self) -> str:
        scope_name = self.owning_scope.get_fully_qualified_scope_name()
        return f"[{scope_name}] {self.severity.get_emoji()}  {self.group_name}"

    def format(self, max_lines: int) -> str:
        num_lines = len(self.matching_lines)
        if num_lines == 0:
            return ""
        disp_lines = min(max_lines, num_lines) if max_lines >= 0 else num_lines
        header_str = self.get_header()
        header = f"### {header_str} ({disp_lines}/{num_lines}) <{';'.join(self.tags)}> ###\n"
        body = "\n".join(str(line)
                         for line in self.matching_lines[0:disp_lines])
        return header + body

    def json(self) -> dict:
        num_lines = len(self.matching_lines)
        if num_lines == 0:
            return None
        lines_json_objs = list(filter(lambda x: x is not None, [
                               line.json() for line in self.matching_lines]))

        # Lines come from a set, which has non stable sorting.
        # In the json output we want the lines sorted by line number.
        lines_json_objs.sort(key=lambda line: line["line_nr"])

        return {
            "name": self.get_header(),
            "severity": self.severity.json(),
            "tags": list(self.tags),
            "lines": lines_json_objs
        }

    def num_matches(self) -> int:
        return len(self.matching_lines)

    def filter_unique_lines(self) -> None:
        self.matching_lines = list(set(self.matching_lines))

    @staticmethod
    def _from_xml_node(xml_node: XmlNode, owning_scope: 'UnrealLogFilePatternScope') -> 'UnrealLogFilePatternList':
        result_list = UnrealLogFilePatternList(
            xml_node.get("Name"),
            owning_scope=owning_scope)

        result_list.severity = UnrealLogSeverity.from_string(
            xml_node.get("Severity", default=""))
        tags_str = xml_node.get("Tags", default="")
        if len(tags_str) > 0:
            result_list.tags = set(tag.upper() for tag in tags_str.split(";"))

        for pattern in xml_node.findall("Include"):
            result_list.include_patterns.append(
                UnrealLogFilePattern._from_xml_node(pattern, owning_scope, result_list))
        for pattern in xml_node.findall("Exclude"):
            result_list.exclude_patterns.append(
                UnrealLogFilePattern._from_xml_node(pattern, owning_scope, result_list))
        return result_list

    def _check_and_add(self, line: str, line_number: int) -> bool:
        match = self.match(line, line_number)
        if match:
            if match in self.matching_lines:
                match_idx = self.matching_lines.index(match)
                self.matching_lines[match_idx].occurences += 1
            else:
                self.matching_lines.append(match)
            return True
        return False


class UnrealLogFilePatternScope:
    """
    A pattern scope contains multiple pattern lists and child scope.
    There is only ever one topmost root scope.
    The root scope tracks step_success_flags usually associated with nested scopes (e.g. Job.Build=success, Job.Cook=failure).
    """
    scope_name: str
    parent_target_name: str = None
    root_scope: 'UnrealLogFilePatternScope' = None
    parent_scope: 'UnrealLogFilePatternScope' = None
    require_all_lines_match: bool

    child_scopes: list['UnrealLogFilePatternScope']
    start_patterns: list[UnrealLogFilePattern] = []
    end_patterns: list[UnrealLogFilePattern] = []
    pattern_lists: list[UnrealLogFilePatternList]

    # Only valid on root scope
    step_success_flags: List[Tuple[str, bool]]

    def __init__(self,
                 scope_name,
                 parent_target_name,
                 require_all_lines_match: bool,
                 parent_scope: 'UnrealLogFilePatternScope'):
        self.scope_name = scope_name
        self.parent_target_name = parent_target_name
        self.parent_scope = parent_scope
        self.root_scope = self if parent_scope is None else parent_scope.root_scope

        self.require_all_lines_match = require_all_lines_match

        self.child_scopes = []
        self.pattern_lists = []
        self.step_success_flags = []

    def is_root_scope(self) -> bool:
        return self.root_scope == self

    def num_patterns(self) -> int:
        result = 0
        for list in self.pattern_lists:
            result += len(list.include_patterns) + len(list.exclude_patterns)
        for child_scope in self.child_scopes:
            result += child_scope.num_patterns()
        return result

    def num_matches(self) -> int:
        return sum(pattern.num_matches() for pattern in self.pattern_lists) + sum(child_scope.num_matches() for child_scope in self.child_scopes)

    def _check_and_add(self, line: str, line_number: int) -> bool:
        """
        Check a line on current scope and its pattern lists for matches or bubble up to parent scopes.
        Does NOT recurse into child scopes!
        """
        for pattern_list in self.pattern_lists:
            if pattern_list._check_and_add(line, line_number):
                return True

        if self.parent_scope is None:
            return False

        # If not match in own patterns was found, bubble up to parents
        return self.parent_scope._check_and_add(line, line_number)

    def format(self, max_lines: int):
        """
        Format the scope and all its contents for pretty printing.
        max_lines are passed to each pattern list (so the total number of displayed lines is likely much larger).
        """
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
        """
        The fully qualified scope name is the name of the current scope preceded by the full chain of parent scopes.
        """
        return ((self.parent_scope.get_fully_qualified_scope_name() + ".") if not self.parent_scope is None else "") + self.scope_name

    def filter_inline(self, tags: list[str], min_severity: UnrealLogSeverity, min_matches: int = 1, unique_lines: bool = True) -> None:
        """
        Filter out match results by
        - duplicates
        - required tags (any if empty)
        - minimum severity
        - minimum number of matches per pattern list
        This is a lossy operation. In most cases, you'll want to use filter() to create a deep copy of the scope and retain an unfiltered original list.
        """
        self.pattern_lists = [pattern_list for pattern_list in self.pattern_lists if
                              len(pattern_list.matching_lines) >= min_matches and
                              pattern_list.severity.value >= min_severity.value and
                              pattern_list.match_tags(tags)]
        if unique_lines:
            for pattern_list in self.pattern_lists:
                pattern_list.filter_unique_lines()

        for child_scope in self.child_scopes:
            child_scope.filter_inline(tags, min_severity)

    def filter(self, tag: str, min_severity: UnrealLogSeverity, min_matches: int = 1) -> 'UnrealLogFilePatternScope':
        """
        Create a deep copy of this scope and filter out match results (see filter_inline).
        Only supported on root scopes to avoid invalid linking of scopes.
        """
        if not self.is_root_scope():
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
        result = {"scopes": self._json_patterns()}
        if self.is_root_scope():
            # Convert tuples to more json friendly dicts
            result["steps"] = [{"step": step, "success": is_success}
                               for (step, is_success) in self.step_success_flags]
        return result

    def all_scopes(self) -> Iterator['UnrealLogFilePatternScope']:
        """Iterate all nested scopes"""
        yield self
        for child_scope in self.child_scopes:
            for scope in child_scope.all_scopes():
                yield scope

    def all_parent_scopes(self) -> Iterator['UnrealLogFilePatternScope']:
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

    def all_matching_lines(self) -> Iterator[UnrealLogFileLineMatch]:
        """Iterate all matching lines inside all lists inside all child scopes"""
        for list in self.all_lists():
            for line in list.matching_lines:
                yield line

    def get_string_variable(self, variable_name) -> str:
        """
        Get the first instance of a string variable with the given name.
        If multiple lines have a variable with that name, only the first occurence will be returned.
        """
        for line in self.all_matching_lines():
            result = line.string_vars.get(variable_name)
            if not result is None:
                return result
        return None

    @staticmethod
    def _from_xml_node(xml_node: XmlNode, root_node: XmlNode, parent_scope: 'UnrealLogFilePatternScope' = None, parent_target_name: str = None) -> 'UnrealLogFilePatternScope':
        """
        Create a scope object from an XML node.
        The node can be either a <Template> or <Target> node.
        """
        result_scope = UnrealLogFilePatternScope(
            xml_node.get("Name"),
            parent_target_name,
            xml_node.get("RequireAllLinesMatch"),
            parent_scope=parent_scope)

        result_scope._set_start_end_patterns(xml_node)

        # Fill info + Generate child scopes.
        result_scope._fill_scope_from_xml_node(xml_node,
                                               root_node)
        return result_scope

    def _fill_scope_from_xml_node(self, xml_node: XmlNode, root_node: XmlNode) -> None:
        for pattern_list in xml_node.findall("./Patterns"):
            self.pattern_lists.append(
                UnrealLogFilePatternList._from_xml_node(pattern_list, self))
        for scope in xml_node.findall("./Scope"):
            self._link_child_scope(
                UnrealLogFilePatternScope._from_xml_node(scope,
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

    def _set_start_end_patterns(self, xml_node) -> None:
        self.start_patterns = []
        self.end_patterns = []

        for node in xml_node.findall("Start"):
            self.start_patterns.append(UnrealLogFilePattern._from_xml_node(
                node, self))

        for node in xml_node.findall("End"):
            self.end_patterns.append(UnrealLogFilePattern._from_xml_node(
                node, self))

    def _link_child_scope(self, child_scope: 'UnrealLogFilePatternScope') -> None:
        child_scope.parent_scope = self
        self.child_scopes.append(child_scope)
        child_scope.root_scope = self.root_scope

    def _json_patterns(self) -> List[dict]:
        jsons = list(filter(lambda x: x is not None, [
                     pattern.json() for pattern in self.pattern_lists]))
        for child_scope in self.child_scopes:
            jsons += child_scope._json_patterns()
        return jsons


def get_log_patterns(xml_path: str, target_name: str) -> UnrealLogFilePatternScope:
    """
    Import a list of log file patterns from an xml file.
    Groups are assigned to a target that must match to the input target_name.
    """
    print("Importing log file pattern list from", xml_path)
    root_node = XmlTree(file=xml_path)
    for target in root_node.findall("./Target"):
        if target.get("Name") == target_name:
            return UnrealLogFilePatternScope._from_xml_node(target, root_node, parent_scope=None, parent_target_name=target_name)
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
        for line_number, line in enumerate(file, 1):
            # What's a higher priority?
            # 1) opening child scopes <- current implementation
            # 2) closing current scope
            scope_changed = False
            for child_scope in current_scope.child_scopes:
                for start_pattern in child_scope.start_patterns:
                    if start_pattern.match(line, line_number):
                        current_scope = child_scope
                        scope_changed = True
                        break
                # Can't enter two child scopes at the same time, e.g.
                # scope A { scope X {}, scope Y {}} --> can't enter X and Y at the same time
                if scope_changed:
                    break

            # Allow parsing a line that is on the end line of a scope
            line_checked = current_scope._check_and_add(line, line_number)

            # Do not allow entering a new scope and exiting the same scope on the same line
            if not scope_changed:
                # Allow not only current scope, but also all parent scopes to end.
                # This is required, because script steps may crash / exit preemptively, which would result in socpes not being closed properly,
                # which in turn might mess up parsing rules of the next steps.
                for check_parent_scope in current_scope.all_parent_scopes():
                    if (any(end_pattern.match(line, line_number)
                            for end_pattern in filter(lambda end_pattern: not end_pattern is None, check_parent_scope.end_patterns))
                            or (check_parent_scope.require_all_lines_match and not line_checked)):
                        current_scope = check_parent_scope.parent_scope
                        scope_changed = True
                        break
                if scope_changed:
                    continue

            # A line can only be matched by one scope. We assume inner scopes have more detailed info/parsing rules
            # and prioritize them over outer scopes.
            # Because of this, we can end a scope by "does not contain x" patterns
            if not line_checked:
                current_scope._check_and_add(line, line_number)

    if current_scope is not root_scope:
        print(
            f"WARNING: Child scope '{current_scope.get_fully_qualified_scope_name()}' was opened but not closed. This may be a sign of an uncompleted automation step.")

    return root_scope


def print_parsed_log(path: str, logparse_patterns_xml: str, target_name: str, max_lines=20) -> None:
    header_divider = "\n==========================="
    print(header_divider, "\nParsing log file", path, "...", header_divider)

    scope_with_matches = parse_log(path, logparse_patterns_xml, target_name)
    # scope_with_matches.filter_inline(
    #     "", min_severity=UnrealLogSeverity.MESSAGE)
    print("\n", scope_with_matches.format(max_lines))


if __name__ == "__main__":
    env = UnrealEnvironment.create_from_invoking_file_parent_tree()

    argparser = argparse.ArgumentParser()
    argparser.add_argument("--file")
    cli_args = argparser.parse_args()
    cli_args.file

    patterns_xml = os.path.join(
        Path(__file__).parent, "resources/logparse_patterns.xml")

    parse_file = cli_args.file if not cli_args.file is None else UnrealLogFile.UAT.find_latest(
        env)
    print_parsed_log(parse_file, patterns_xml, "BuildCookRun", max_lines=0)
