"""
Create a static HTML file for a build report and other project automation metrics.
Extends the logparse module.
"""

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from alive_progress import alive_bar
from openunrealautomation.automationtest import test_report
from openunrealautomation.inspectcode import inspectcode
from openunrealautomation.logparse import UnrealLogFilePatternScopeInstance, _main_get_files, parse_log
from openunrealautomation.staticanalysis_common import StaticAnalysisResults, static_analysis_html_report
from openunrealautomation.unrealengine import UnrealEngine
from openunrealautomation.util import read_text_file, write_text_file


def _parsed_log_dict_to_json(parsed_log_dict: dict, output_json_path: str) -> str:
    json_str = json.dumps(parsed_log_dict, indent=4)

    # Replace backticks for javascript. Not great. Not terrible.
    json_str = json_str.replace("`", "'")

    write_text_file(output_json_path, json_str)
    return json_str


def _generate_html_inline_source_log(parsed_log: UnrealLogFilePatternScopeInstance, source_file: str, source_file_count: int, source_file_display: str, log_file_str: str, include_all_lines: bool) -> str:
    """HTML code for the sources with roots for issues of each file."""
    log_file_lines = log_file_str.splitlines()
    log_file_line_count = len(log_file_lines)
    html_lines = []

    # Number of lines beofre and after match...
    relevant_line_context_pad = 5
    all_relevant_lines = set()
    for line in parsed_log.all_matching_lines(include_hidden=True):
        for i in range(line.line_nr - relevant_line_context_pad, line.line_nr + 1 + relevant_line_context_pad):
            all_relevant_lines.add(i)

    with alive_bar(log_file_line_count, title="_generate_html_inline_source_log") as update_progress_bar:
        last_line_was_relevant = True
        for line_number, line in enumerate(log_file_lines, 1):
            update_progress_bar()

            if include_all_lines or line_number in all_relevant_lines:
                padded_line_number = str(line_number).rjust(
                    len(str(log_file_line_count)), "0")
                html_lines.append(
                    f'<code id="source-log-{source_file}-{line_number}">{padded_line_number}: {line}</code><br/>\n')
                last_line_was_relevant = True
            else:
                if last_line_was_relevant:
                    html_lines.append("...<br/>\n")
                last_line_was_relevant = False

    log_file_str_html = "".join(html_lines)

    return \
        f'<div class="col-12 box-ouu">'\
        f'<div>File #{source_file_count}: <pre class="source-file-title">{source_file_display}</pre></div>\n'\
        f'<div id="{source_file}_code-summary" class="code-summary"></div>'\
        f'<button class="btn-expand-source-container btn btn-sm btn-outline-secondary" onclick="expandSourceContainer(this);">Show source log</button>'\
        f'<div class="source-log-container text-nowrap p-3 code-container" style="display:none;">\n{log_file_str_html}\n</div>'\
        f'</div>'


def _generate_plotly_icicle_chart(plot_id: str, plot_title: str, js_data_dict: str) -> str:
    injected_javascript = f"""
    var {plot_id}_data = [{{
        type: "icicle",
        {js_data_dict},
        tiling : {{orientation : 'v'}}
    }}];

    var {plot_id}_layout = {{
        title: {{
            text: '{plot_title}',
            xref: 'paper'
        }},
        margin: {{l: 10, r: 10, b: 10, t: 40}},
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        // The size is adjusted for final layout with padding, etc.
        // More responsive sizing would be preferable.
        width: 773,
        height: 378
    }};

    $('#stats-chart-root').append("<div id='{plot_id}' class='p-2 m-3 bg-dark'></div>");

    Plotly.newPlot('{plot_id}', {plot_id}_data, {plot_id}_layout);
    """

    return injected_javascript


def _generate_hierarchical_cook_timing_stat_html(log_file_name, log_file_str) -> str:
    root_node = None
    last_node = None
    last_parent = None
    last_indent = 0

    all_nodes = []

    all_labels = set()

    lines = log_file_str.splitlines()
    with alive_bar(len(lines), title="_generate_hierarchical_cook_timing_stat_html") as update_progress_bar:
        for line in lines:
            update_progress_bar()

            matches = re.search(
                r"LogCook: Display:   (?P<Indent>\s*)(?P<Label>\w+): (?P<Time>\d+\.\d+)s \((?P<Counter>\d+)\)", line)
            if matches:
                indent = len(matches.group("Indent")) / 2
                label = matches.group("Label")
                value = matches.group("Time")

                while label in all_labels:
                    label += "_"
                all_labels.add(label)

                if indent < last_indent:
                    new_parent = last_parent["parent"]
                elif indent > last_indent:
                    new_parent = last_node
                else:
                    new_parent = last_parent

                last_indent = indent

                new_node = {
                    "label": label,
                    "parent": new_parent,
                    "value": float(value),
                    "children": []
                }

                if not new_parent is None:
                    new_parent["children"].append(new_node)

                if root_node is None:
                    root_node = new_node
                last_node = new_node
                last_parent = new_parent

                all_nodes.append(new_node)

    if len(all_nodes) == 0:
        return ""

    for node in all_nodes:
        node["parent"] = node["parent"]["label"] if node["parent"] is not None else ""
    for node in all_nodes:
        node["children"] = ""

    js_data_dict = f"labels : {[node['label'] for node in all_nodes]},\n" +\
        f"parents : {[node['parent'] for node in all_nodes]},\n" +\
        f"values : {[node['value'] for node in all_nodes]}"

    return _generate_plotly_icicle_chart(
        plot_id="cook_hierarchy_timer_info",
        plot_title=f"Hierarchical Cook Timing ({log_file_name})",
        js_data_dict=js_data_dict)


def generate_html_report(
    html_report_template_path: Optional[str],
    html_report_path: str,
    # Source path and parsed log file
    log_files: List[Tuple[str, UnrealLogFilePatternScopeInstance]],
    embedded_reports: List[str],
    out_json_path: str,
    report_title: str,
    background_image_uri: str,
    filter_tags_and_labels: Dict[str, str]
):

    parsed_log_dicts = {}

    injected_javascript = ""

    inline_source_log = ""
    for source_file_count, (log_file_path, parsed_log) in zip(range(1, len(log_files) + 1), log_files):
        log_file_str = read_text_file(log_file_path)
        injected_javascript += _generate_hierarchical_cook_timing_stat_html(Path(log_file_path).name,
                                                                            log_file_str)
        parsed_log_dict = parsed_log.json()
        source_file_name = Path(log_file_path).name

        source_file_id = source_file_name
        prohibited_chars = ". ()@;[]#,="
        for prohibited_char in prohibited_chars:
            source_file_id = source_file_id.replace(prohibited_char, "_")
        parsed_log_dict["source_file"] = source_file_id
        parsed_log_dict["source_file_name"] = source_file_name
        parsed_log_dicts[source_file_id] = parsed_log_dict

        inline_source_log += _generate_html_inline_source_log(parsed_log,
                                                              source_file_id,
                                                              source_file_count,
                                                              source_file_name,
                                                              log_file_str,
                                                              include_all_lines=False)

    json_str = _parsed_log_dict_to_json(parsed_log_dicts, out_json_path)

    embedded_reports_str = ""
    for embedded_report in embedded_reports:
        embedded_reports_str += f"""<div class="col-12 box-ouu p-0">{embedded_report}</div>"""

    if html_report_template_path is None:
        # The default report isn't even a single template, but a set of files that are combined to a template.
        # This could potentially be replaced with some static site builder, but most of them do not support building
        # monolithic html files without any external css/js files.
        def read_default_template(extension) -> str:
            return read_text_file(os.path.join(
                Path(__file__).parent, f"resources/build_issues_template.{extension}"))
        html_template = read_default_template("html")
        js_template = read_default_template("js")
        css_template = read_default_template("css")

        html_template = html_template.replace(
            "MAIN_JAVASCRIPT", js_template).replace("/*REPORT_CSS*/", css_template)
    else:
        html_template = read_text_file(html_report_template_path)

    output_html = html_template.\
        replace("INLINE_JSON", json_str).\
        replace("ISSUES_AND_SOURCES", inline_source_log).\
        replace("REPORT_TITLE", report_title).\
        replace("INLINE_JAVASCRIPT", injected_javascript).\
        replace("BACKGROUND_IMAGE_URI", background_image_uri).\
        replace("FILTER_TAGS_AND_LABELS", str(filter_tags_and_labels)).\
        replace("EMBEDDED_REPORTS", embedded_reports_str)

    write_text_file(html_report_path, output_html)


if __name__ == "__main__":
    ue = UnrealEngine.create_from_parent_tree(str(Path(__file__).parent))

    files = _main_get_files()

    temp_dir = os.path.join(tempfile.gettempdir(), "OpenUnrealAutomation")
    os.makedirs(temp_dir, exist_ok=True)

    patterns_xml = os.path.join(
        Path(__file__).parent, "resources/logparse_patterns.xml")

    all_logs = []
    for target, file in files:
        if file is None:
            continue
        parsed_log = parse_log(
            file, patterns_xml, target)
        all_logs.append((file, parsed_log))

    report_path = os.path.join(temp_dir, "test_report")

    static_analysis_results = inspectcode(ue, may_skip_build=True)
    static_analysis_report = static_analysis_html_report(ue.environment,
                                                         static_analysis_results,
                                                         embeddable=True)

    test_report_html = test_report(ue, True)

    generate_html_report(None, report_path + ".html", all_logs, [test_report_html, static_analysis_report],
                         report_path + ".json", "OUA Test Report", "", {"CODE": "🤖 Code", "ART": "🎨 Art"})
