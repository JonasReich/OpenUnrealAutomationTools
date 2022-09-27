
from locale import atoi
import subprocess
import re
import os
from openunrealautomation.util import run_subprocess
from typing import List

class UnrealPerforce:
    """
    Super lightweight Perforce (p4) commandline wrapper that serves the bare minimum required for internal commands.
    May be extended later for more robust Perforce implementation.
    """

    def __init__(self, cwd:str = None, check:bool = True) -> None:
        self.check = check
        self.cwd = cwd

    def get_current_cl(self) -> int:
        result_str = subprocess.check_output(["p4", "changes", "-m1", "//...#have"], encoding="UTF8")
        result = re.match("Change (?P<CL>\\d+) on \\d+/\\d+/\\d+", result_str)
        if result:
            return atoi(result["CL"])
        return 0

    def get_current_stream(self) -> str:
        current_stream_output = subprocess.check_output(["p4", "-F", "%Stream%", "-ztag", "client", "-o"], encoding="UTF8")
        current_stream_clean = current_stream_output.strip()
        assert(not "\n" in current_stream_clean)
        return current_stream_clean

    def sync(self, path, cl:int=None, force:bool=False):
        path = self._auto_path(path)
        args = ["sync"]
        if force:
            args += ["-f"]
        if cl is None:
            args += [path]
        else:
            args +=[f"{path}@{cl}"]
        self._p4([args])

    def add(self, path):
        path = self._auto_path(path)
        self._p4(["add", path])

    def edit(self, path):
        path = self._auto_path(path)
        self._p4(["edit", path])

    def delete(self, path):
        path = self._auto_path(path)
        self._p4(["delete", path])

    def reconcile(self, path):
        path = self._auto_path(path)
        self._p4(["reconcile", path])

    def _p4(self, args):
        _args = ["p4"] + args
        cwd = os.getcwd() if self.cwd is None else self.cwd
        subprocess.run(_args, encoding="UTF8", check=self.check, cwd=cwd)

    def _auto_path(self, path) -> str:
        if os.path.isdir(path):
            return path + "/..."
        return path

    def opened() -> List[str]:
        opened_files_str = subprocess.check_output(["p4", "opened"], encoding="UTF8")
        if "File(s) not opened on this client." in opened_files_str:
            return []
        else:
            return opened_files_str.splitlines()


if __name__ == "__main__":
    p4 = UnrealPerforce()
    print("Current CL:", p4.get_current_cl())
    print("Current Stream:", p4.get_current_stream())
