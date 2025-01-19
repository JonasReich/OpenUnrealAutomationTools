"""
Undo Perforce changes accross streams.
At the moment this only accepts a single changelist that will be undone in isolation.
"""

import argparse
import re

from openunrealautomation.p4 import UnrealPerforce

parser = argparse.ArgumentParser()
parser.add_argument("change")
args = parser.parse_args()

cl = args.change

unreal_p4 = UnrealPerforce()

current_branch = unreal_p4.get_current_stream()
print(f"current branch: {current_branch}")
current_branch_root = unreal_p4.resolve_virtual_stream_parent(current_branch)
print(f"current branch root: {current_branch_root}")

output = unreal_p4._p4_get_output(["undo", f"//...@{cl}"])
print(output)

print("-----STEP: check files to force integrate-----")
for line in output.splitlines():
    match = re.match(
        r"(\/\/.+?\/.+?\/(.*)) - file\(s\) not in client view", line)

    # if the file is not in current client, force integrate the version _before_ the CL
    if match:
        integrate_file = match.group(1)
        relative_integrate_file = match.group(2)

        local_file = f"{current_branch_root}/{relative_integrate_file}"

        previous_cl = str(int(cl) - 1)
        integrate_args = ["integrate", "-f", f"{integrate_file}@{previous_cl}",
                          local_file]
        print(" ".join(integrate_args))
        unreal_p4._p4(integrate_args)
        unreal_p4._p4(["resolve", "-at", local_file])
