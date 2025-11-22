"""
Lightweight utilites to get information from Perforce environment.
This should be optional for the core openunrealatuomation functionality,
but some of the automation tools will be tied to Perforce anyways,
because Epic's tooling assumes Perforce as only source control tool in many places.
"""

import datetime
import glob
import hashlib
import os
import pickle
import re
import subprocess
import time
from locale import atoi
from typing import Dict, List, Optional, Tuple

from openunrealautomation.util import ouu_temp_file


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
        self._current_cl = None

    def get_current_cl(self, force_refresh=False) -> int:
        if self._current_cl and not force_refresh:
            # returned cached value
            return self._current_cl

        result_str = self._p4_get_output(["changes", "-m1", "//...#have"])
        result = re.match(r"Change (?P<CL>\d+) on \d+/\d+/\d+", result_str)
        if result:
            self._current_cl = atoi(result["CL"])
            return self._current_cl
        return 0

    def get_current_stream(self) -> str:
        current_stream_output = self._p4_get_output(
            ["-F", "%Stream%", "-ztag", "client", "-o"])
        current_stream_clean = current_stream_output.strip()
        assert (not "\n" in current_stream_clean)
        return current_stream_clean

    def resolve_virtual_stream_parent(self, stream) -> str:
        """
        Returns the input stream if it's not a virutal stream or parent stream for virtual streams.
        Does not resolve the stream recursively!
        Expects stream input paths in the format '//depot-root/stream-name'
        """

        depot_root_match = re.match(r"\/\/(.+?)\/.+?", stream)
        assert depot_root_match
        depot_root = depot_root_match.group(1)

        stream_config = self._p4_get_output(
            ["stream", "-o", stream])
        if not re.search(r"Type:\s+virtual", stream_config):
            return stream
        match = re.search(
            r"Parent:\s+(\/\/" + depot_root + r"\/.+)", stream_config)
        assert match
        source_stream = str(match.group(1)).strip()
        return source_stream

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

    def add(self, path, verbose: bool = True):
        path = self._auto_path(path)
        if verbose:
            self._p4(["add", path])
        else:
            output = self._p4_get_output(["add", path])
            num_added_files = output.count("opened for add")
            print(f"P4: add {path} -> Added {num_added_files} files.")

    def edit(self, path, verbose=True):
        path = self._auto_path(path)
        if verbose:
            self._p4(["edit", path])
        else:
            output = self._p4_get_output(["edit", path])
            num_edited_files = output.count("opened for edit")
            print(f"P4: edit {path} -> Edited {num_edited_files} files.")

    def delete(self, path):
        path = self._auto_path(path)
        self._p4(["delete", path])

    def reconcile(self, path):
        path = self._auto_path(path)
        self._p4(["reconcile", path])

    def revert_unchanged(self, path, verbose=True):
        path = self._auto_path(path)
        if verbose:
            self._p4(["revert", "-a", path])
        else:
            output = self._p4_get_output(["revert", "-a", path])
            num_reverted_files = output.count("reverted")
            print(
                f"P4: revert {path} -> Reverted {num_reverted_files} unchanged files.")

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

    def get_last_change_user(self, path: str, ignore_copies=True) -> Optional[str]:
        last_change = self.get_last_change(path, ignore_copies)
        if last_change:
            return last_change[1]
        return None

    def get_last_change(self, path: str, ignore_copies=True) -> Optional[Tuple[int, str]]:
        output = self._p4_get_output(["filelog", "-m1", "-s", path])

        if ignore_copies:
            copy_source_match = re.search(
                r"... copy from (?P<source>//.*#\d+)", output)
            if copy_source_match:
                # Follow the chain of copies recursively
                return self.get_last_change(copy_source_match.group("source"), True)
        match = re.search(
            r"change (?P<changelist>\d+) .* by (?P<user>.+?)@", output)
        if match:
            return int(match.group("changelist")), match.group("user")
        return None

    def get_last_change_date(self, path: str, ignore_copies=True) -> Optional[datetime.date]:
        output = self._p4_get_output(["filelog", "-m1", "-s", path])

        if ignore_copies:
            copy_source_match = re.search(
                r"... copy from (?P<source>//.*#\d+)", output)
            if copy_source_match:
                # Follow the chain of copies recursively
                return self.get_last_change_date(copy_source_match.group("source"), True)
        match = re.search(
            r"change (?P<changelist>\d+) .* on (?P<date>.+) by (?P<user>.+?)@", output)
        if match:
            return datetime.datetime.strptime(match.group("date"), "%Y/%m/%d").date()
        return None

    def get_depot_location(self, local_path: str) -> str:
        return self._p4_get_output(["where", local_path]).split(" ")[0]

    def get_current_stream_changed_files_since(self, duration: datetime.timedelta) -> List[str]:
        now = datetime.datetime.now()
        start_time = now-duration
        start_time_str = start_time.strftime("%Y/%m/%d:%H:%M:%S")
        return [line.split("#")[0] for line in self._p4_get_output(["files", f"...@{start_time_str},@now"]).splitlines()]

    def set_uat_env_vars(self) -> None:
        current_cl = self.get_current_cl()
        assert current_cl > 0

        # Setting these variables speeds up UAT quite a lot, because it doesn't have to look up this changelist info.
        os.environ["uebp_CL"] = str(current_cl)
        print(f"SETENV uebp_CL {current_cl}")
        # We don't really care about a distinction of code and content changelists with our scripts (yet).
        # Running BuildGraph for UGS distributed binaries would need this, but regular Steam builds should not need to care,
        # because they use the plain CL info 99% of the time.
        os.environ["uebp_CodeCL"] = str(current_cl)
        print(f"SETENV uebp_CodeCL {current_cl}")

    def _p4(self, args):
        _args = ["p4"] + args
        cwd = os.getcwd() if self.cwd is None else self.cwd
        subprocess.run(_args, encoding="unicode_escape",
                       check=self.check, cwd=cwd)

    def _p4_get_output(self, args) -> str:
        _args = ["p4"] + args
        cwd = os.getcwd() if self.cwd is None else self.cwd
        try:
            return subprocess.check_output(_args, cwd=cwd, stderr=subprocess.STDOUT, bufsize=1, shell=True, universal_newlines=True)
        except subprocess.CalledProcessError as e:
            print(
                f"Encountered non-zero exit code for Perforce command 'p4 {' '.join(_args)}': {e.returncode}. Dumping output below...")
            print(e.output)
            raise e

    def _auto_path(self, path) -> str:
        if os.path.isdir(path):
            return path + "/..."
        return path


class UnrealPerforceLastChangeUserCache:
    """Lookup last change developer for a p4 file.
    This is particularly useful for asset validation jobs that need to lookup the same paths over and over again.
    The cache_id should be some string that invalidates in a semi-frequent schedule so you don't get completely outdated data.

    This should maybe be changed to just using a date based invalidation (e.g. clear every 30mins).
    """

    def __init__(self, p4: UnrealPerforce, cache_id: str):
        self.p4 = p4
        self.user_map = p4.get_user_map()
        self.last_change_user_by_file = {}

        all_cache_files = list(glob.glob(ouu_temp_file(
            "p4.cache.last_change_user_by_file.*")))
        all_cache_files.sort(key=lambda x: os.path.getmtime(x))
        # delete all but the latest cache file (assuming if you parse again for the same file you want the most recent results)
        for outdate_cache_file in all_cache_files[1:]:
            os.remove(outdate_cache_file)

        self.cache_file_path = ouu_temp_file(
            "p4.cache.last_change_user_by_file." + str(int(hashlib.sha256(cache_id.encode('utf-8')).hexdigest(), 16)) + ".pkl")

        if os.path.exists(self.cache_file_path):
            print("Import user changes cache from",
                  self.cache_file_path)
            with open(self.cache_file_path, "rb") as cache:
                self.last_change_user_by_file = pickle.load(cache)

    def get(self, file_path: str) -> Optional[str]:
        if file_path in self.last_change_user_by_file:
            user = self.last_change_user_by_file.get(file_path)
        else:
            try:
                user = self.p4.get_last_change_user(
                    file_path)
                print("file_path:", file_path, "user:", user)
            except:
                user = None
            self.last_change_user_by_file[file_path] = user
        return user

    def write_cache(self) -> None:
        with open(self.cache_file_path, "wb") as cache:
            return pickle.dump(self.last_change_user_by_file, cache)


if __name__ == "__main__":
    p4 = UnrealPerforce()
    print("Current CL:", p4.get_current_cl())
    print("Current Stream:", p4.get_current_stream())

    print("All Users:\n", "\n".join(
        [f"\t{user}" for _, user in p4.get_user_map().items()]))
