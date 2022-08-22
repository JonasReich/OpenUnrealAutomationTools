
from locale import atoi
import subprocess
import re
from openunrealautomation.util import run_subprocess


class UnrealPerforce:
    """
    Super lightweight Perforce (p4) commandline wrapper that serves the bare minimum required for internal commands.
    May be extended later for more robust Perforce implementation.
    """

    def get_current_cl() -> int:
        result_str = subprocess.check_output(["p4", "changes", "-m1", "//...#have"], encoding="UTF8")
        result = re.match("Change (?P<CL>\\d+) on \\d+/\\d+/\\d+", result_str)
        if result:
            return atoi(result["CL"])
        return 0

    def get_current_stream() -> str:
        current_stream_output = subprocess.check_output(["p4", "-F", "%Stream%", "-ztag", "client", "-o"], encoding="UTF8")
        current_stream_clean = current_stream_output.strip()
        assert(not "\n" in current_stream_clean)
        return current_stream_clean

    def sync(file, cl:int=None, force:bool=False):
        args = ["p4", "sync"]
        if force:
            args += ["-f"]
        if cl is None:
            args += [file]
        else:
            args +=[f"{file}@{cl}"]
        subprocess.run(args, encoding="UTF8", check=True)


if __name__ == "__main__":
    p4 = UnrealPerforce()
    print("Current CL:", p4.get_current_cl())
    print("Current Stream:", p4.get_current_stream())
