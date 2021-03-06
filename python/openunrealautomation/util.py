"""
Utility functions
"""

import filecmp
import glob
import os
import pathlib
import platform
import re
import shutil
import stat
import subprocess
from typing import Any, Generator

from openunrealautomation.core import *


def walk_level(top, topdown=True, onerror=None, followlinks=False, level=1) -> None:
    """
    Copy of os.walk() with additional level parameter.
    @param level    How many sub-directories to traverse
    """
    # From https://stackoverflow.com/a/234329
    top = top.rstrip(os.path.sep)
    assert os.path.isdir(top)
    num_sep = top.count(os.path.sep)
    for root, dirs, files in os.walk(top, topdown=topdown, onerror=onerror, followlinks=followlinks):
        yield root, dirs, files
        num_sep_this = root.count(os.path.sep)
        if num_sep + level <= num_sep_this:
            del dirs[:]


def walk_parents(dir: str) -> Generator[str, None, None]:
    """Go through all parent directories of the given dir."""
    path = pathlib.Path(dir)
    while True:
        yield str(path)
        if (path.parent == path):
            break
        path = path.parent


def _on_rm_error(func, path, exc_info) -> None:
    # path contains the path of the file that couldn't be removed
    # let's just assume that it's read-only and unlink it.
    os.chmod(path, stat.S_IWRITE)
    os.unlink(path)


def force_rmtree(path: str, no_file_ok: bool = False) -> None:
    """Delete a directory tree. Also deletes read-only files."""
    if not os.path.exists(path) and no_file_ok:
        return
    shutil.rmtree(path, onerror=_on_rm_error)


def rmtree_empty(root) -> set[str]:
    """
    Delete empty directories in tree.
    Returns set of deleted directories.
    """
    # Source: https://stackoverflow.com/a/65624165
    # Need to cache deleted directories, because os.walk only evaluates child folders once when calling
    # and then goes through cached folder list.
    deleted = set()

    for current_dir, subdirs, files in os.walk(root, topdown=False):
        # has any files?
        if any(files):
            continue

        # has not deleted subdir?
        if any(os.path.join(current_dir, subdir)
               not in deleted for subdir in subdirs):
            continue

        os.rmdir(current_dir)
        deleted.add(current_dir)

    return deleted


def mirror_files(source_root: str, target_root: str, relative_paths: set[str], ignore_patterns: list[str] = []) -> int:
    """
    Take a list of relative file paths (e.g. from buildgraph) and copy them from source to target.
    Existing files in target that are not in source will be deleted.
    This is advantageous to other copytree implementations because it allows per-file filtering.

    Returns number of modified files (copies and deletions)
    """
    print(
        f"Syning {len(relative_paths)} files from {source_root} to {target_root}")
    # Scan for existing files
    existing_files_abs = glob.glob(
        f"{target_root}/**/*.*", recursive=True)
    existing_files = set()
    for abs_file in existing_files_abs:
        existing_files.add(os.path.relpath(
            abs_file, target_root))

    # Make sure the paths are in the right format. Otherwise we cannot do name matching
    relative_paths = set(os.path.normpath(path) for path in relative_paths)

    print(f"Found {len(existing_files)} existing files in {target_root}")

    check_files = relative_paths.union(set(existing_files))
    check_files_num = len(check_files)
    print(f"Checking {check_files_num} paths for differences to sync")

    num_modified_files = 0
    file_i = 0
    for file in check_files:
        source_file = os.path.join(source_root, file)
        target_file = os.path.join(target_root, file)
        pathlib.Path(target_file).parent.mkdir(parents=True, exist_ok=True)

        if any(re.match(pattern=ignore_pattern, string=file) for ignore_pattern in ignore_patterns):
            continue

        file_i += 1
        filenum_str = f"{file_i}/{check_files_num} :"

        if file in relative_paths and file in existing_files:
            # File exists, but content might have changed.
            # UBT already is timestamp based, so we should be fine with just checking time stamps here.
            if filecmp.cmp(source_file, target_file, shallow=True):
                # File exists and is up-to-date
                pass
            else:
                print(filenum_str, "change  ", file)
                shutil.copy2(source_file, target_file)
                num_modified_files += 1
        elif file in relative_paths:
            # File is new, copy it over
            print(filenum_str, "new     ", file)
            shutil.copy2(source_file, target_file)
            num_modified_files += 1
        elif os.path.exists(target_file):
            # File is not in new list, delete it
            print(filenum_str, "delete  ", file)
            os.remove(target_file)
            num_modified_files += 1
        else:
            raise OUAException(f"File {file} is only in existing_files, but does not exist on disk. "
                               "Was it deleted by some other process?")

    return num_modified_files


def which_checked(command, display_name) -> str:
    """
    Get the executable path of a CLI command that is on PATH.
    Will raise an exception if the command is not found.

    Example:
    which_checked("powershell") -> "C:\\windows\\System32\\WindowsPowerShell\\v1.0\\powershell.EXE"
    """
    exe_path = shutil.which(command)
    if exe_path is None:
        raise OUAException(
            f"{command} ({display_name}) is not installed or cannot be found via PATH environment.")
    return exe_path


def set_system_env_var(name, value) -> None:
    """
    Set a system wide environment variable (like PATH).
    Does not affect the current environment, but all future commands.
    """
    if platform.system() != "Windows":
        raise NotImplementedError(
            "set_system_env_var() is only implemented on Windows")
    print(f"Setting environment variable: {name}={value}")
    os.system(f"setx {name} {value}")
    return


def add_startup(name: str, program: str, args: list[str]) -> None:
    """
    Add a batch file to startup/autostart that launches a program with arguments.
    This writes a batchfile to the user startup files.

    name        Name of the batch file
    program     Program path
    args        List of string arguments to pass to program on start
    """

    program = os.path.realpath(program)
    if not os.path.exists(program):
        raise OUAException(
            f"Program {program} does not exist. Cannot add it to autostart")

    bat_path = os.path.realpath(os.path.join(
        str(pathlib.Path.home()),
        "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup",
        f"{name}.bat"))

    with open(bat_path, "w+") as bat_file:
        bat_file.write(f"start {program} {' '.join(args)}")


def list_attrs(obj: object, class_filter: type) -> Generator[tuple[str, Any], None, None]:
    """
    List attributes of a specific type.
    Returns generator with tuple of attribute name and value.
    """
    for name in dir(obj):
        attr = getattr(obj, name)
        if isinstance(attr, class_filter):
            yield name, attr


def run_subprocess(*popenargs, check=False, **kwargs) -> int:
    """
    Runs a process while forwarding the output to stdout automatically.

    This was created as alternative to subprocess.call() because that did not properly
    forward all of the process stdout and stderr output.
    It's specifically created to support automation contexts like Jenkins where having
    all process output forwarded to the callee is required. Also polls the output while
    the process is running so you do not have to wait for it to complete

    Paramters:
    check       If true, a subprocess.CalledProcessError without captured output is raised
                on non-zero exit codes.
    Returns process exit code.
    """

    with subprocess.Popen(*popenargs, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, **kwargs) as p:
        try:
            # Grab stdout line by line as it becomes available.  This will loop until
            # p terminates.
            while p.poll() is None:
                # This blocks until it receives a newline.
                output = p.stdout.readline()
                output = "\n".join(output.splitlines())
                if output.strip() != "":
                    print(output)
            # When the subprocess terminates there might be unconsumed output
            # that still needs to be processed.
            remaining_out = p.stdout.read()
            remaining_out = "\n".join(remaining_out.splitlines())
            if remaining_out.strip() != "":
                print(remaining_out)

            if check and p.returncode != 0:
                raise subprocess.CalledProcessError(p.returncode, p.args,
                                        output=None, stderr=None)
            return p.returncode
        except:  # Including KeyboardInterrupt, wait handled that.
            p.kill()
            # We don't call p.wait() again as p.__exit__ does that for us.
            raise
