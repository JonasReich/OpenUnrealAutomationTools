
import os
from typing import Optional
from xml.etree.ElementTree import Element as XmlNode
from xml.etree.ElementTree import fromstring as xml_fromstring

from openunrealautomation.unrealengine import UnrealEngine
from openunrealautomation.util import read_text_file, which_checked


def _get_opencppcoverage_arguments(ue: UnrealEngine, program_name: str, coverage_report_path: str):
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
                    ue.environment.project_root, "--sources", ue.environment.project_root]
    result_args += ["--excluded_sources", "*Engine*", "--excluded_sources",
                    "*Intermediate*", "--excluded_sources", "*.gen.cpp"]
    result_args += ["--cover_children"]
    result_args += ["--working_dir", ue.environment.project_root]

    # export paths
    result_args += [f"--export_type=cobertura:{coverage_report_path}/cobertura.xml",
                    f"--export_type=html:{coverage_report_path}"]

    # Always last argument before UE program commandline
    result_args += ["--"]
    return result_args


def find_coverage_file(dir: str) -> Optional[str]:
    cobertura_xml = os.path.join(dir, "cobertura.xml")
    return os.path.normpath(cobertura_xml) if os.path.exists(cobertura_xml) else None


def coverage_html_report(cobertura_xml_path: str) -> str:
    xml_tree = xml_fromstring(read_text_file(cobertura_xml_path))

    def get_prop(xml_node: XmlNode, prop_name: str) -> str:
        return str(xml_node.get(prop_name))

    def get_line_rate(node) -> int:
        return int(float(get_prop(node, "line-rate")) * 100)

    def make_line_rate_str(node, label, bg_style) -> str:
        line_rate = get_line_rate(node)
        return f'<div class="row">'\
            f'<div class="col">{label}</div>'\
            f'<div class="col">'\
            f'<div class="progress border border-secondary bg-dark">'\
            f'<div class="progress-bar {bg_style}" role="progressbar" style="width: {line_rate}%;" aria-valuenow="{line_rate}" aria-valuemin="0" aria-valuemax="100">{line_rate}%</div>'\
            f'</div>'\
            f'</div>'\
            f'</div>'

    result_str = ""
    for package in xml_tree.findall(".//package"):
        package_name = get_prop(package, "name")
        result_str += make_line_rate_str(package, package_name, "bg-secondary")

    return f'<div class="p-3 small"><h5>C++ Code Coverage</h5>{make_line_rate_str(xml_tree, "Total Coverage", "bg-success")}<hr>{result_str}</div>'
