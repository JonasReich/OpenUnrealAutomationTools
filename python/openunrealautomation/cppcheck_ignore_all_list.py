
import os
import subprocess
from pathlib import Path
from xml.etree import ElementTree

from openunrealautomation.util import (run_subprocess, which_checked,
                                       write_text_file)

which_checked("cppcheck")

error_list_xml_str = bytes.decode(subprocess.run(
    ["cppcheck", "--errorlist", "--xml", "--quiet"],
    shell=True, check=False, stdout=subprocess.PIPE).stdout, "utf-8")

xml = ElementTree.fromstring(error_list_xml_str)
all_error_ids = []
for error in xml.findall(".//error"):
    all_error_ids.append(error.get("id"))

all_error_ids.remove("preprocessorErrorDirective") # we need this one
#all_error_ids += ["missingInclude", "unknownMacro"]

out_path = os.path.join(Path(__file__).parent, "resources",
                        "cppcheck", "all_issues.suppress.cppcheck")
write_text_file(out_path, "\n".join(all_error_ids))
