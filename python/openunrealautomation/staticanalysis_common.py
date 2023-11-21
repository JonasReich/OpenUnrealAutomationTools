"""
Common classes required for all static code analysis utils.
"""

from enum import Enum
import os
from typing import Dict, Generator, List, Optional
from xml.etree.ElementTree import Element as XmlNode
from xml.etree.ElementTree import fromstring as xml_fromstring
from xml.etree.ElementTree import tostring as xml_tostring
from xml.sax.saxutils import escape as __xml_escape

from openunrealautomation.environment import UnrealEnvironment
from openunrealautomation.util import read_text_file, write_text_file

# TODO implement sorting for a stable results list (by category > severity > rule > file > line)


class StaticAnalysisSeverity(Enum):
    ERROR = 0, "error"
    WARNING = 1, "warning"
    SUGGESTION = 2, "suggestion"
    HINT = 3, "hint"
    # Issues with this level are automatically ignored and excluded from export
    IGNORE = 4, ""

    def __str__(self) -> str:
        return self.value[1]

    def __lt__(self, other: "StaticAnalysisSeverity") -> bool:
        return self.value[0] < other.value[0]


class StaticAnalysisCategory:
    id: str
    description: str
    parent: Optional["StaticAnalysisCategory"]
    children: List["StaticAnalysisCategory"]
    rules: List["StaticAnalysisRule"]

    def __init__(self, id: str, description: str, parent: Optional["StaticAnalysisCategory"]):
        self.id = id
        self.description = description
        self.parent = parent
        self.children = []
        self.rules = []
        # create backlink to child categories
        if self.parent is not None:
            self.parent.children.append(self)

    def __eq__(self, other: "StaticAnalysisCategory") -> bool:
        return self.id == other.id

    def __lt__(self, other: "StaticAnalysisCategory") -> bool:
        return self.id < other.id

    def get_relative_id(self) -> str:
        if self.parent is None:
            return self.id
        else:
            return self.id.removeprefix(self.parent.id + "-")

    def get_num_issues_recursive(self) -> int:
        return sum(len(rule.issues) for rule in self.rules) + sum(child.get_num_issues_recursive() for child in self.children)


class StaticAnalysisRule:
    id: str
    description: str
    severity: StaticAnalysisSeverity
    category: StaticAnalysisCategory
    issues: List["StaticAnalysisIssue"]

    def __init__(self, id: str, description: str, severity: StaticAnalysisSeverity, category: StaticAnalysisCategory) -> None:
        self.id = id
        self.description = description
        self.severity = severity
        self.category = category
        self.category.rules.append(self)
        self.issues = []

    def __eq__(self, other: "StaticAnalysisRule") -> bool:
        return self.id == other.id

    def __lt__(self, other: "StaticAnalysisRule") -> bool:
        if self.severity < other.severity:
            return True
        return self.id < other.id

    def get_relative_id(self) -> str:
        return self.id.removeprefix(self.category.id + "-")


class StaticAnalysisIssue:
    file: str
    line: int
    column: int
    symbol: str
    message: str
    # Which rule produced this issue?
    rule: StaticAnalysisRule

    def __init__(self, file: str, line: int, column: int, symbol: str, message: str, rule: StaticAnalysisRule) -> None:
        self.file = file
        self.line = line
        self.column = column
        self.symbol = symbol
        self.message = message
        self.rule = rule
        self.rule.issues.append(self)

    def __lt__(self, other: "StaticAnalysisIssue") -> bool:
        """This ignores the parent rule, etc. Assumes we are just sorting inside a rule"""
        if self.file < other.file:
            return True
        if self.line < other.line:
            return True
        return self.column < other.column


class StaticAnalysisResults:
    """Results from a static analysis run. Should be combinable with results of other runs."""

    categories: Dict[str, StaticAnalysisCategory]
    rules: Dict[str, StaticAnalysisRule]
    issues: List[StaticAnalysisIssue]

    def __init__(self) -> None:
        self.categories = {}
        self.rules = {}
        self.issues = []

    def sort_recursively(self) -> None:
        for _, cat in self.categories.items():
            cat.rules = sorted(cat.rules)
            cat.children = sorted(cat.children)

        for _, rule in self.rules.items():
            rule.issues = sorted(rule.issues)

    def new_issue(self, file, line, column, symbol, message, rule_id):
        rule = self.rules[rule_id]

        new_issue = StaticAnalysisIssue(
            file, line, column, symbol, message, rule)
        self.issues.append(new_issue)

    def find_or_add_rule(self, id: str, description: str, severity: StaticAnalysisSeverity, category_id: str) -> StaticAnalysisRule:
        if id in self.rules:
            return self.rules[id]
        else:
            category = self.categories[category_id]
            self.rules[id] = StaticAnalysisRule(
                id, description, severity, category)
            return self.rules[id]

    def find_or_add_category(self, id: str, description: str, parent: Optional[StaticAnalysisCategory]) -> StaticAnalysisCategory:
        if id in self.categories:
            return self.categories[id]
        else:
            self.categories[id] = StaticAnalysisCategory(
                id, description, parent)
            return self.categories[id]

    def get_root_categories(self) -> List[StaticAnalysisCategory]:
        def __impl():
            for _, category in self.categories.items():
                if category.parent is None:
                    yield category
        result = __impl()
        return sorted(result)

    def get_num_issues_recursive(self) -> int:
        return sum(root_category.get_num_issues_recursive() for root_category in self.get_root_categories())

    def combine(self, other: "StaticAnalysisResults") -> "StaticAnalysisResults":
        """Combine two sets of results into a completely new object without touching either of them."""
        new_results = StaticAnalysisResults()
        new_results._copy_combine(self)
        new_results._copy_combine(other)
        return new_results

    def _copy_combine(self, other: "StaticAnalysisResults") -> None:
        """Deep copy over entries from other object.
        Iterates recursively starting from root, so parent entries / rules are guaranteed
        to be created in right order to be found.
        If two ruels / categories with the same name/ID exist on this object already,
        the new version is silently ignored, but new sub-entries are copied over."""

        def _copy_over_cat(cat: StaticAnalysisCategory) -> None:
            self_parent = self.categories[cat.parent.id] if cat.parent is not None else None
            self.find_or_add_category(
                cat.id, cat.description, self_parent)
            for rule in cat.rules:
                self.find_or_add_rule(
                    rule.id, rule.description, rule.severity, rule.category.id)
                for issue in rule.issues:
                    self.new_issue(issue.file, issue.line, issue.column,
                                   issue.symbol, issue.message, issue.rule.id)
            for child in cat.children:
                _copy_over_cat(child)

        for root_cat in other.get_root_categories():
            _copy_over_cat(root_cat)


def _read_single_line_from_file(file_path: str, line_nr: int) -> str:
    with open(file_path, "r", encoding="utf-8") as file:
        all_lines = file.readlines()
        try:
            return all_lines[line_nr-1]
        except:
            return "invalid-file-access"


def get_overflow_button(
    does_overflow): return '<a href="javascript:void(0);" class="open-overflow">Show all</a>' if does_overflow else ""


def _xml_escape(xml_str: str) -> str:
    return __xml_escape(xml_str).replace("\n", "<br/>")


def _generate_html_report(env: UnrealEnvironment, analysis_results: StaticAnalysisResults, html_report_path: str, include_paths: List[str], exclude_paths: List[str] = []):
    def _is_included(path) -> bool:
        if len(exclude_paths) > 0 and any(exclude in path for exclude in exclude_paths):
            return False
        return len(include_paths) == 0 or any(include in path for include in include_paths)

    include_paths = [os.path.relpath(path, env.project_root)
                     for path in include_paths]
    exclude_paths = [os.path.relpath(path, env.project_root)
                     for path in exclude_paths]

    analysis_results.sort_recursively()

    # TODO get rid of these temporary variables and just do it all inline in a big loop over all categories.
    items_per_type: Dict[str, List[str]] = {}
    type_headers: Dict[str, str] = {}

    def add_item(type_id: str, item: str):
        if not type_id in items_per_type:
            items_per_type[type_id] = []
        items_per_type[type_id].append(item)

    def id_desc_join(id: str, desc: str) -> str:
        return f"{id} - {desc}" if len(desc) > 0 else id

    for type_id, issue_type in analysis_results.rules.items():
        type_description = _xml_escape(
            id_desc_join(issue_type.get_relative_id(), issue_type.description))
        if len(type_description) == 0:
            type_description = "<i>empty description</i>"
        type_headers[type_id] = f"<span class='type-header severity-{issue_type.severity}'>{type_description}</span>"

        for issue in sorted(issue_type.issues):
            issue.file = os.path.relpath(issue.file, env.project_root)
            issue_file_path = issue.file
            if not _is_included(issue_file_path):
                continue
            does_overflow = issue.message.count("\n") > 3

            line_from_file = _read_single_line_from_file(
                issue_file_path, issue.line)

            add_item(
                type_id, f"<li><code class='src-path'>{_xml_escape(issue_file_path)}:{issue.line}</code><br/><code style='background-color:#15181c;'>{_xml_escape(line_from_file)}</code><span class=\"{'overflow-hider' if does_overflow else ''}\">{_xml_escape(issue.message)}</span>{get_overflow_button(does_overflow)}</li>")

    def get_section(id_str: str, summary: str, count: int, content: str, default_open=False) -> str:
        if len(str(summary).strip()) == 0:
            summary = "<i>empty summary</i>"
        return f"""<details id="{id_str}" {'open=""'if default_open else ''}>\n<summary><code class="issue-count">{count}</code> {summary}</summary>\n<div>\n{content}\n</div>\n</details>\n"""

    def get_catgeory_report_str(category: StaticAnalysisCategory) -> str:
        category_content = ""

        for rule in sorted(category.rules):
            type_id = rule.id
            type_header = type_headers[type_id]
            type_content = "\n".join(items_per_type[type_id]) if type_id in items_per_type else ""
            num_issues_in_type = len(items_per_type[type_id]) if type_id in items_per_type else 0
            category_content += get_section(type_id,
                                            type_header,
                                            num_issues_in_type, f"<ol>{type_content}</ol>") + "\n"
        for child_cat in sorted(category.children):
            category_content += get_catgeory_report_str(child_cat)

        return get_section(category.id,
                           id_desc_join(category.get_relative_id(),
                                        category.description),
                           category.get_num_issues_recursive(),
                           category_content,
                           default_open=True)

    issue_list_str = ""
    for root_category in analysis_results.get_root_categories():
        issue_list_str += get_catgeory_report_str(root_category)

    issue_tree_str = get_section(
        "issues-root", "Total issues", analysis_results.get_num_issues_recursive(), issue_list_str, default_open=True)

    style = """
    code { color: var(--bs-gray-500); }
    ul, ol { margin: 0; }
    ol {
        list-style: decimal-leading-zero;
        margin-left: 3em;
    }

    details {
        padding-left: 20px;
    }

    .issue-count {
        min-width: 30px;
        display: inline-block;
        background-color: var(--bs-gray-800);
    }

    summary, .src-path {
        cursor: pointer;
    }

    .src-path:click {
        cursor: copy;
    }

    summary::-webkit-details-marker {
        display: none;
    }

    .type-header {
        color: var(--severity-color);
    }

    :root {
        --severity-color: black;
    }

    .severity-suggestion { --severity-color: var(--bs-info); }
    .severity-warning { --severity-color: var(--bs-warning); }
    .severity-error { --severity-color: var(--bs-danger); }

    .overflow-hider {
        max-height: 3em;
        height: auto;
        transition: ease-in-out all 0.2s;
        overflow: hidden;
        display: inline-block;
        width: 100%;
    }

    .clipboard-notify {
        /*animation-name: flash;
        animation-timing-function: ease-out;
        animation-duration: 1s;*/
    }

    .clipboard-notify:after {
        content: " Copied!";
        color: transparent;
        background: transparent;
        animation-name: flash;
        animation-duration: 2s;
        animation-iteration-count: 1;
        margin-left:1em;
        padding-right:1em;
        padding-left: 1em;
    }

    @keyframes flash {
        10% {
            color: inherit;
            background: #28a745;
        }
        90% {
            color: transparent;
            background: transparent;
        }
    }
    """

    javascript = """
    $(document).ready(function(e) {
        $('.open-overflow').click(function(e) {
            let $wrapper = $(this).parent().find('.overflow-hider');
            $wrapper.removeClass('overflow-hider');
            $(this).remove();
        });
        $('.src-path').click(function(e) {
            $(this).addClass('clipboard-notify').delay('2000').queue(function(){$(this).removeClass('clipboard-notify').dequeue(); });
            navigator.clipboard.writeText($(this).text());
        });
         $('#search-input').on('keypress', function (e) {
            if(e.which === 13){
                search($(this).val());
            }
        });
    });

    function search(search_term) {
        $("code.src-path").each(function(){
            let bullet = $(this).closest("li");
            if (search_term == "") {
                $(bullet).show().addClass("bullet-visible");
            } else if ($(this).text().includes(search_term)) {
                $(bullet).show().addClass("bullet-visible");
            } else {
                $(bullet).hide().removeClass("bullet-visible");
            }
        });
        $("code.issue-count").each(function(){
            let container = $(this).closest("details");
            let num_active_bullets = $(container).find(".bullet-visible").length;
            $(this).text(num_active_bullets);
            $(container).toggle(num_active_bullets > 0);
        });
        $("#issues-root").show();
    }
    """

    title = f"{env.project_name} - Static Code Analysis Report"

    def make_include_exlude_paths_html(path_list) -> str:
        if len(path_list) == 0:
            return " <i style='color:var(--bs-gray-500);'>nothing</i>"
        else:
            bullets = "\n".join([f'<li>{path}</li>' for path in path_list])
            does_overflow = len(path_list) > 4
            hider_class = "overflow-hider" if does_overflow else ""
            return f"<ul class='{hider_class}'>{bullets}</ul>{get_overflow_button(does_overflow)}"
    include_paths_html = make_include_exlude_paths_html(include_paths)
    exclude_paths_html = make_include_exlude_paths_html(exclude_paths)

    # <!doctype html />
    html_str = f"""
    <html lang="en">
    <head>
    <meta charset="utf-8" />
    <title>{title}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-T3c6CoIi6uLrA9TneNEoa7RxnatzjcDSCmG1MXxSR1GAsXEV/Dwwykc2MPK8M2HN" crossorigin="anonymous" />
    </head>
    <body class="bg-dark text-light">
    <div class="p-3">
    <h1>{title}</h1>

    <span>Report for Unreal Project {env.project_name}</span><br/>
    <div style="border: var(--bs-gray-700) solid 1px; border-radius: 0.5em; padding: 0.5em; margin: 0.5em;">
        Included:
        {include_paths_html}
        <br/>
        Excluded:
        {exclude_paths_html}
    </div>
    <br/>
    <input type="text" class="form-control bg-dark-subtle" id="search-input" aria-describedby="search-help" placeholder="Search..." style="max-width:500px;">
    <small id="search-help" class="form-text text-muted">Search by source file.</small>
    <br/>
    {issue_tree_str}

    </div>
    <style>{style}</style>
    <script src="https://code.jquery.com/jquery-3.7.1.min.js" integrity="sha256-/JqT3SQfawRcv/BIHPThkBvs0OEvtFFmqPF/lYI/Cxo=" crossorigin="anonymous"></script>
    <script>
    {javascript}
    </script>
    </body>
    </html>
    """

    prettify = False
    if not prettify:
        write_text_file(html_report_path, html_str)
    else:
        def _prettyfy_xml(current, parent=None, index=-1, depth=0):
            for i, node in enumerate(current):
                _prettyfy_xml(node, current, i, depth + 1)
            if parent is not None:
                if index == 0:
                    parent.text = '\n' + ('\t' * depth)
                else:
                    parent[index - 1].tail = '\n' + ('\t' * depth)
                if index == len(parent) - 1:
                    current.tail = '\n' + ('\t' * (depth - 1))

        # Pretty but overly verbose
        xml_data = xml_fromstring(html_str)
        _prettyfy_xml(xml_data)
        html_str_tidy = bytes.decode(
            xml_tostring(xml_data, method="html"), "utf-8")
        write_text_file(html_report_path, html_str_tidy)
