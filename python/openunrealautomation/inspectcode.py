"""
Run Resharper's InspectCode static analysis command line and generate html reports from the xml reports.
InspectCode Docs: https://www.jetbrains.com/help/resharper/InspectCode.html
"""

import argparse
import os
import re
from typing import Dict, Generator, List
from xml.etree.ElementTree import Element as XmlNode
from xml.etree.ElementTree import fromstring as xml_fromstring
from xml.etree.ElementTree import tostring as xml_tostring
from xml.sax.saxutils import escape as __xml_escape

from openunrealautomation.environment import UnrealEnvironment
from openunrealautomation.unrealengine import UnrealEngine
from openunrealautomation.util import read_text_file, run_subprocess, which_checked, write_text_file

# These terms are always excluded (as we assume no games project is interested in messing with RiderLink plugin source, the Lyra source code, etc)
_HARDCODED_EXCLUDE_TERMS = ["RiderLink", "Lyra"]


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


def _generate_inspectcode_html_report(env: UnrealEnvironment, xml_report_path: str, html_report_path: str, include_paths: List[str], exclude_paths: List[str] = []):
    def _is_included(path) -> bool:
        if len(exclude_paths) > 0 and any(exclude in path for exclude in exclude_paths):
            return False
        return len(include_paths) == 0 or any(include in path for include in include_paths)

    xml_tree = xml_fromstring(read_text_file(xml_report_path))

    category_titles: Dict[str, str] = {}
    items_per_type: Dict[str, List[str]] = {}
    types_per_category: Dict[str, List[str]] = {}
    type_headers: Dict[str, str] = {}

    def add_item(type_id: str, item: str):
        if not type_id in items_per_type:
            items_per_type[type_id] = []
        items_per_type[type_id].append(item)

    def add_type(category_id: str, type_id: str) -> None:
        if not category_id in types_per_category:
            types_per_category[category_id] = []
        types_per_category[category_id].append(type_id)

    def get_prop(xml_node: XmlNode, prop_name: str) -> str:
        return str(xml_node.get(prop_name))

    for issue_type in xml_tree.findall(".//IssueType"):
        type_id = get_prop(issue_type, "Id")
        type_description = _xml_escape(
            get_prop(issue_type, 'Description').strip())
        if len(type_description) == 0:
            type_description = "<i>empty description</i>"
        type_headers[type_id] = f"<span class='type-header severity-{get_prop(issue_type,'Severity').lower()}'>{type_description}</span>"

        any_valid_item = False
        for issue in xml_tree.findall(".//Issue"):
            if get_prop(issue, "TypeId") != type_id:
                continue
            issue_file_path = get_prop(issue, "File")
            if not _is_included(issue_file_path):
                continue
            any_valid_item = True
            message_str = get_prop(issue, "Message")
            does_overflow = message_str.count("\n") > 3

            line_from_file = _read_single_line_from_file(
                issue_file_path, int(get_prop(issue, "Line")))

            add_item(
                type_id, f"<li><code class='src-path'>{_xml_escape(issue_file_path)}:{get_prop(issue,'Line')}</code><br/><code style='background-color:#15181c;'>{_xml_escape(line_from_file)}</code><span class=\"{'overflow-hider' if does_overflow else ''}\">{_xml_escape(message_str)}</span>{get_overflow_button(does_overflow)}</li>")

        if any_valid_item:
            category_id = get_prop(issue_type, "CategoryId")
            category_titles[category_id] = get_prop(issue_type, "Category")
            add_type(category_id, type_id)

    def get_section(id_str: str, summary: str, count: int, content: str, default_open=False) -> str:
        if len(str(summary).strip()) == 0:
            summary = "<i>empty summary</i>"
        return f"""<details id="{id_str}" {'open=""'if default_open else ''}>\n<summary><code class="issue-count">{count}</code> {summary}</summary>\n<div>\n{content}\n</div>\n</details>\n"""

    issue_list_str = ""
    num_total_issues = 0
    for category, title in category_titles.items():
        category_content = ""
        num_issues_in_cat = 0
        for type in types_per_category[category]:
            type_header = type_headers[type]
            type_content = "\n".join(items_per_type[type])
            num_issues_in_type = len(items_per_type[type])
            num_issues_in_cat += num_issues_in_type
            category_content += get_section(type,
                                            type_header,
                                            num_issues_in_type, f"<ol>{type_content}</ol>") + "\n"
        num_total_issues += num_issues_in_cat
        issue_list_str += get_section(category, title,
                                      num_issues_in_cat, category_content, default_open=True)

    issue_tree_str = get_section(
        "issues-root", "Total issues", num_total_issues, issue_list_str, default_open=True)

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

    logo_svg = """<svg fill="none" viewBox="0 0 70 70" class="resharper-logo" style="width: 1em;margin-right: 0.3em;padding-bottom: 0.2em;height: 1em;"><defs><linearGradient id="__JETBRAINS_COM__LOGO_PREFIX__2" x1="34.448" x2="64.631" y1="70.146" y2="26.155" gradientUnits="userSpaceOnUse"><stop offset="0.016" stop-color="#FF45ED"></stop><stop offset="0.4" stop-color="#DD1265"></stop><stop offset="1" stop-color="#FDB60D"></stop></linearGradient><linearGradient id="__JETBRAINS_COM__LOGO_PREFIX__1" x1="1.828" x2="48.825" y1="53.428" y2="9.226" gradientUnits="userSpaceOnUse"><stop offset="0.016" stop-color="#FF45ED"></stop><stop offset="0.661" stop-color="#DD1265"></stop></linearGradient><linearGradient id="__JETBRAINS_COM__LOGO_PREFIX__0" x1="47.598" x2="48.08" y1="-1.658" y2="26.117" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#DD1265"></stop><stop offset="0.055" stop-color="#DF1961"></stop><stop offset="0.701" stop-color="#F46330"></stop><stop offset="1" stop-color="#FC801D"></stop></linearGradient></defs><path fill="url(#__JETBRAINS_COM__LOGO_PREFIX__2)" d="M51.197 15.72 26.38 47.07 20.782 70h37.666L70 23.067 51.197 15.72Z"></path><path fill="url(#__JETBRAINS_COM__LOGO_PREFIX__1)" d="M48.986 0H11.613L0 47.07h55.607L48.986 0Z"></path><path fill="url(#__JETBRAINS_COM__LOGO_PREFIX__0)" d="M50.934 13.316 48.986 0l-4.204 13.316h6.152Z"></path><path fill="#000" d="M56 14H14v42h42V14Z"></path><path fill="#FFF" d="M34.417 48.65h-15.75v2.683h15.75V48.65Zm1.661-17.29H34.37v-2.877h2.203l.561-3.326h-1.977v-2.876h2.472l.561-3.28h2.967l-.562 3.28h3.259l.56-3.28h2.967l-.561 3.28h1.707v2.877h-2.202l-.562 3.325h1.978v2.877H45.27l-.585 3.37H41.72l.584-3.37h-3.258l-.585 3.37h-2.966l.584-3.37Zm6.72-2.877.561-3.326H40.1l-.561 3.326h3.258ZM19 19h7.187c1.991 0 3.519.532 4.582 1.594a4.86 4.86 0 0 1 1.347 3.593v.046a4.927 4.927 0 0 1-.932 3.11 5.398 5.398 0 0 1-2.437 1.763l3.841 5.615h-4.042l-3.254-4.829H22.44l.02 4.828H19V19Zm6.962 7.635a2.872 2.872 0 0 0 1.966-.606 2.054 2.054 0 0 0 .685-1.617v-.045a2.009 2.009 0 0 0-.72-1.684 3.176 3.176 0 0 0-1.998-.561h-3.436v4.513h3.503Z"></path></svg>"""
    title = "InspectCode Report"

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
    <h1>{logo_svg}{title}</h1>

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


def get_all_active_sources(engine: UnrealEngine, skip_export: bool) -> List[str]:
    """
    Get all active source directories
    """
    target_info = engine.get_target_json_dict(skip_export=skip_export)

    def get_all_module_folders() -> Generator[str, None, None]:
        engine_root_prefix = str(engine.environment.engine_root) + "\\"
        for _, module in target_info["Modules"].items():
            module_dir: str = module["Directory"]
            if module_dir.startswith(engine.environment.project_root):
                root_relative_path = module_dir.removeprefix(
                    engine_root_prefix)
                yield root_relative_path

    all_modules = get_all_module_folders()
    all_sources = set()
    for module_path in all_modules:
        match = re.match(r"^(?P<plugin>.*Source\\).*$", module_path)
        if match:
            all_sources.add(match.group("plugin"))

    all_sources = list(all_sources)
    all_sources.sort()
    return all_sources


def _run_inspectcode(env: UnrealEnvironment, inspectcode_exe: str):
    root_relative_project_path = os.path.relpath(
        env.project_root, env.engine_root)
    include_paths = [f"{root_relative_project_path}\\Source\\**",
                     f"{root_relative_project_path}\\Plugins\\**\\Source\\**"]
    includes_str = ";".join(include_paths)
    exclude_paths = ["**\\*.cs",
                     "**\\**.generated.h",
                     "**\\**.gen.cpp"]
    excludes_str = ";".join(exclude_paths)

    # keep turned off for now. we have enough issues as is and times are shorter (I think?)
    solution_wide_analysis = False
    swea_param = "--swea" if solution_wide_analysis else "--no-swea"

    command_line = [inspectcode_exe,
                    "--build",
                    f'--project="{env.project_name}"',
                    # This target name is required or otherwise the ENTIRE solution is built. May need to be adjusted for non-game targets or samples, etc that end up in other dirs
                    f'--target="Games\\{env.project_name}"',
                    swea_param,
                    f'--properties="Configuration=Development Editor;Platform=Win64"',
                    f'--include="{includes_str}"',
                    f'--exclude="{excludes_str}"',
                    '-o="resharperReport.xml"',
                    env.get_engine_solution()]
    run_subprocess(command_line)


def inspectcode(engine: UnrealEngine, skip_build: bool, include_paths: List[str] = [], exclude_paths: List[str] = []) -> None:
    """
    Runs inspectcode on all project and plugin source files.
    """

    # TQ2 specific auto-detection of portable inspectcode folder
    tq2_inspectcode_path = f"{engine.environment.engine_root}/Tools/ReSharperCodeInspect/inspectcode.exe"
    if os.path.exists(tq2_inspectcode_path):
        inspectcode_exe = tq2_inspectcode_path
    else:
        # If the binary is not found, we assume it's on PATH
        inspectcode_exe = "inspectcode.exe"
        which_checked(inspectcode_exe)

    env = engine.environment

    if not skip_build:
        # InspectCode needs solution for analysis.
        # It should already be present, but we can't be 100% sure in a CI context, so better safe than sorry.
        engine.generate_project_files(engine_sln=True)

        # Run the main inspectcode exe.
        # This is most likely the most time consuming part, because it may have to rebuild the entire project and then analyze all the source files.
        _run_inspectcode(env, inspectcode_exe)

    # If the target was not rebuilt, the module list also doesn't need to be re-exported.
    all_sources = get_all_active_sources(engine, skip_export=skip_build)

    report_include_paths = include_paths if len(
        include_paths) > 0 else all_sources
    report_exclude_paths = exclude_paths
    _generate_inspectcode_html_report(env,
                                      f"{env.engine_root}/resharperReport.xml",
                                      f"{env.engine_root}/inspectCodeReport.html",
                                      include_paths=report_include_paths,
                                      exclude_paths=report_exclude_paths)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--include", default="")
    parser.add_argument("--exclude", default="")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    skip_build = args.skip_build

    def array_arg(parm_str: str):
        result = str.split(parm_str, ";")
        if '' in result and len(result) == 1:
            return []
        return result

    include_paths = array_arg(args.include)
    exclude_paths = array_arg(args.exclude)

    exclude_paths += _HARDCODED_EXCLUDE_TERMS

    print("skip build:", skip_build)
    print("include:", include_paths)
    print("exclude:", exclude_paths)

    ue = UnrealEngine.create_from_parent_tree(os.getcwd())
    inspectcode(ue, skip_build=skip_build, include_paths=include_paths,
                exclude_paths=exclude_paths)
