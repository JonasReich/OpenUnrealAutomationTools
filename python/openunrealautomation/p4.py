"""
Lightweight utilites to get information from Perforce environment.
This should be optional for the core openunrealatuomation functionality,
but some of the automation tools will be tied to Perforce anyways,
because Epic's tooling assumes Perforce as only source control tool in many places.
"""

import os
import re
import subprocess
from locale import atoi
from typing import Dict, List, Optional


class UnrealPerforceUserInfo:
    username: str = ""
    email: str = ""
    display_name: str = ""
    last_access_str: str = ""
    valid_user: bool = False

    def __init__(self, p4_users_line: str) -> None:
        matches = re.match(
            r"(?P<username>\w+) \<(?P<email>[\w\.@]+)\> \((?P<display_name>.+?)\) accessed (?P<last_access_str>\d{4}\/\d{2}\/\d{2})", p4_users_line)
        if matches:
            self.valid_user = True
            self.username = matches.group("username")
            self.email = matches.group("email")
            self.display_name = matches.group("display_name")
            self.last_access_str = matches.group("last_access_str")

    def __str__(self) -> str:
        # This format is identical to a line of the output from "p4 users"
        return f"{self.username} <{self.email}> ({self.display_name}) accessed {self.last_access_str}"

    def __bool__(self) -> bool:
        return self.valid_user


class UnrealPerforce:
    """
    Super lightweight Perforce (p4) commandline wrapper that serves the bare minimum required for internal commands.
    May be extended later for more robust Perforce implementation.
    """

    def __init__(self, cwd: Optional[str] = None, check: bool = True) -> None:
        self.check = check
        self.cwd = cwd

    def get_current_cl(self) -> int:
        result_str = self._p4_get_output(["changes", "-m1", "//...#have"])
        result = re.match(r"Change (?P<CL>\d+) on \d+/\d+/\d+", result_str)
        if result:
            return atoi(result["CL"])
        return 0

    def get_current_stream(self) -> str:
        current_stream_output = self._p4_get_output(
            ["-F", "%Stream%", "-ztag", "client", "-o"])
        current_stream_clean = current_stream_output.strip()
        assert (not "\n" in current_stream_clean)
        return current_stream_clean

    def sync(self, path, cl: Optional[int] = None, force: bool = False):
        path = self._auto_path(path)
        args = ["sync"]
        if force:
            args += ["-f"]
        if cl is None:
            args += [path]
        else:
            args += [f"{path}@{cl}"]
        self._p4(args)

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

    def opened(self) -> List[str]:
        opened_files_str = self._p4_get_output(["opened"])
        if "File(s) not opened on this client." in opened_files_str:
            return []
        else:
            return opened_files_str.splitlines()

    def get_user_map(self) -> Dict[str, UnrealPerforceUserInfo]:
        result = {}
        users_str = self._p4_get_output(["users"])
        for line in users_str.splitlines():
            user = UnrealPerforceUserInfo(line)
            if user:
                result[user.username] = user
        return result

    def get_user(self, user_name: str) -> UnrealPerforceUserInfo:
        users_str = self._p4_get_output(["users", user_name])
        return UnrealPerforceUserInfo(users_str)

    def _p4(self, args):
        _args = ["p4"] + args
        cwd = os.getcwd() if self.cwd is None else self.cwd
        subprocess.run(_args, encoding="UTF8", check=self.check, cwd=cwd)

    def _p4_get_output(self, args) -> str:
        _args = ["p4"] + args
        cwd = os.getcwd() if self.cwd is None else self.cwd
        return str(subprocess.check_output(_args, cwd=cwd), encoding="UTF8", errors="ignore")

    def _auto_path(self, path) -> str:
        if os.path.isdir(path):
            return path + "/..."
        return path


if __name__ == "__main__":
    p4 = UnrealPerforce()
    print("Current CL:", p4.get_current_cl())
    print("Current Stream:", p4.get_current_stream())
    # print("All Users:\n", "\n".join([f"\t{user}" for _, user in p4.get_user_map().items()]))
