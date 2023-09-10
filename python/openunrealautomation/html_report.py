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

from openunrealautomation.logparse import (UnrealLogFilePatternScopeInstance,
                                           _main_get_files, parse_log)
from openunrealautomation.util import read_text_file, write_text_file


def _parsed_log_dict_to_json(parsed_log_dict: dict, output_json_path: str) -> str:
    json_str = json.dumps(parsed_log_dict, indent=4)

    # Replace backticks for javascript. Not great. Not terrible.
    json_str = json_str.replace("`", "'")

    # Remove unnecessary fluff components for overview (json).
    # The full log still has those components.
    json_str = json_str.replace("Warning: ", "").replace(
        "Error: ", "").replace("Display: ", "").replace("[AssetLog] ", "")
    write_text_file(output_json_path, json_str)
    return json_str


def _generate_html_inline_source_log(source_file: str, source_file_count: int, source_file_display: str, log_file_str: str) -> str:
    log_file_lines = log_file_str.splitlines()
    log_file_str_html = ""
    log_file_line_count = len(log_file_lines)
    for line_number, line in enumerate(log_file_lines, 1):
        padded_line_number = str(line_number).rjust(
            len(str(log_file_line_count)), "0")
        log_file_str_html += f'<code id="source-log-{source_file}-{line_number}">{padded_line_number}: {line}</code><br/>\n'

    return f'<div class="col-12 box-ouu">'\
        f'<h5>Source File #{source_file_count}: {source_file_display}</h5>\n'\
        f'<div id="source-log" class="text-nowrap p-3 code-container">\n{log_file_str_html}\n</div>'\
        '</div>'


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


def _generate_hierarchical_cook_timing_stat_html(log_file_str) -> str:
    root_node = None
    last_node = None
    last_parent = None
    last_indent = 0

    all_nodes = []

    all_labels = set()

    for line in log_file_str.splitlines():
        matches = re.match(
            r"LogCook: Display:   (?P<Indent>\s*)(?P<Label>\w+): (?P<Time>\d+\.\d+)s \((?P<Counter>\d+)\)", line)
        if matches:
            indent = len(matches.group("Indent")) / 2
            label = matches.group("Label")
            value = matches.group("Time")

            while label in all_labels:
                label += "_"
            all_labels.add(label)

            if indent < last_indent:
                assert type(last_parent) is dict
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
        plot_title="Hierarchical Cook Timing",
        js_data_dict=js_data_dict)


def generate_html_report(
    html_report_template_path: Optional[str],
    html_report_path: str,
    # Source path and parsed log file
    log_files: List[Tuple[str, UnrealLogFilePatternScopeInstance]],
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
        injected_javascript += _generate_hierarchical_cook_timing_stat_html(
            log_file_str)
        parsed_log_dict = parsed_log.json()
        source_file_name = Path(log_file_path).name
        source_file_id = source_file_name.replace(".", "_").replace(
            " ", "_").replace("(", "_").replace(")", "_")
        parsed_log_dict["source_file"] = source_file_id
        parsed_log_dicts[source_file_id] = parsed_log_dict
        inline_source_log += _generate_html_inline_source_log(
            source_file_id, source_file_count, source_file_name, log_file_str)

    json_str = _parsed_log_dict_to_json(parsed_log_dicts, out_json_path)

    if html_report_template_path is None:
        html_report_template_path = os.path.join(
            Path(__file__).parent, "resources/build_issues_template.html")

    html_template = read_text_file(html_report_template_path)

    output_html = html_template.\
        replace("INLINE_JSON", json_str).\
        replace("INLINE_SOURCE_LOG", inline_source_log).\
        replace("REPORT_TITLE", report_title).\
        replace("REPORT_DESCRIPTION", "").\
        replace("INLINE_JAVASCRIPT", injected_javascript).\
        replace("BACKGROUND_IMAGE_URI", background_image_uri).\
        replace("FILTER_TAGS_AND_LABELS", str(filter_tags_and_labels))

    write_text_file(html_report_path, output_html)


if __name__ == "__main__":
    files = _main_get_files()

    temp_dir = os.path.join(tempfile.gettempdir(), "OpenUnrealAutomation")
    os.makedirs(temp_dir, exist_ok=True)

    patterns_xml = os.path.join(
        Path(__file__).parent, "resources/logparse_patterns.xml")

    all_logs = []
    for target, file in files:
        parsed_log = parse_log(
            file, patterns_xml, target)
        all_logs.append((file, parsed_log))

    report_path = os.path.join(temp_dir, "test_report")
    generate_html_report(None, report_path + ".html", all_logs,
                         report_path + ".json", "OUA Test Report", "", {})
