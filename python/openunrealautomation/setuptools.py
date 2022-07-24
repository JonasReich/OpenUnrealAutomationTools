"""
Utilitiy functions to setup tools related to Unreal Engine (e.g. Visual Studio).
"""

import json
import re
import subprocess
import time
import urllib
import urllib.error

import requests
from pathlib import Path

import vswhere

from openunrealautomation.environment import UnrealEnvironment
from openunrealautomation.util import *


class VisualStudioCode:
    """
    Utilities to setup Visual Studio Code
    """

    workspace_root: str = ""
    exe_path: str = ""
    config_dir: str = ""

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = os.path.abspath(workspace_root)
        self.exe_path = which_checked(
            "code", "Visual Studio Code")
        self.config_dir = os.path.join(self.workspace_root, ".vscode")

    def get_settings(self) -> dict:
        """
        Get a dictionary of current workspace settings.
        """
        vscode_config_file_path = self._get_settings_path()
        if not os.path.exists(vscode_config_file_path):
            return {}
        with open(vscode_config_file_path, "r") as config_file:
            return json.load(config_file)

    def set_settings(self, new_data: dict, replace: bool = False) -> None:
        """
        Update the (workpace) settings file.
        Either replace or append to the file.
        If appending, existing keys can only be rewritten, not deleted.
        """
        config_data = new_data if replace else {
            **self.get_settings(), **new_data}
        with open(self._get_settings_path(), "w") as config_file:
            json.dump(config_data, config_file, indent=4)

    def install_extension(self, identifier) -> None:
        """
        Install an extension by its identifier.
        (e.g. "ms-vscode.cpptools" for Microsoft C/C++ tools)
        """
        return subprocess.run([self.exe_path, "--install-extension", identifier], check=True)

    def _get_settings_path(self) -> str:
        return os.path.join(
            self.config_dir, "settings.json")


class VisualStudioNotFoundException(Exception):
    pass


class VisualStudio:
    """
    Utilities to setup Visual Studio
    """

    environment: UnrealEnvironment = None

    # Version number (e.g. "16.11.14" for my current install of VS2019)
    version: str = ""
    major_version: int = 0
    minor_version: int = 0
    patch_version: int = 0

    # Product line (e.g. "2019" for VS2019)
    product_line_version: str = ""

    installation_path: str = ""

    def __init__(self, environment: UnrealEnvironment, version: str = None) -> None:
        """
        version: A version range for instances to find. Example: '[15.0,16.0)' will find versions 15.*.
        Note that version numbers diverge from version 
        """
        self.environment = environment

        # vswhere is a python wrapper for the offical Microsoft tool of the same name to locate VS installations.
        # See https://github.com/microsoft/vswhere
        latest_applicable_version = vswhere.get_latest(
            legacy=True, version=version)
        if latest_applicable_version is None:
            raise VisualStudioNotFoundException(
                "No applicable installation of VisualStudio found")

        self.version = latest_applicable_version["catalog"]["productDisplayVersion"]
        self.product_line_version = latest_applicable_version["catalog"]["productLineVersion"]

        version_match = re.search(
            "(?P<major>\\d+).(?P<minor>\\d+).(?P<patch>\\d+)", self.version)
        self.major_version = int(version_match.group("major"))
        self.minor_version = int(version_match.group("minor"))
        self.patch_version = int(version_match.group("patch"))

        self.installation_path = latest_applicable_version["installationPath"]

        print(
            f"Found Visual Studio {self.product_line_version} Installation ({self.version}): {self.installation_path}")

    def install_extension(self, vsix_path: str) -> int:
        vsix_installer = os.path.join(
            self.installation_path,
            "Common7\IDE\VSIXInstaller.exe")

        print("Installing", os.path.basename(vsix_path), "...")
        return subprocess.run([vsix_installer, "/quiet", vsix_path], check=True)

    def download_and_install_extension(self, name: str, download_url: str, retries: int = 3) -> int:
        downloads_dir = os.path.join(
            str(Path.home()), "Downloads/VSExtensions", self.product_line_version)
        os.makedirs(downloads_dir, exist_ok=True)

        # to get content after redirection
        download_src = requests.get(
            download_url, allow_redirects=True).url
        download_target = os.path.join(downloads_dir, name)

        # Assume that a file with matching name is already the right extension.
        # That's what I would do as a user anyways.
        # Theoretically we can also check installed extensions instead.
        if not os.path.exists(download_target):
            print("Downloading", name, "...")
            num_retries = 0
            while(True):
                num_retries += 1
                try:
                    download_success = True
                    urllib.request.urlretrieve(download_src, download_target)
                except urllib.error.HTTPError as http_error:
                    download_success = False
                    print("Received HTTPError: ", str(http_error))
                    if http_error.code == 429:
                        if num_retries > retries:
                            raise OUAException(
                                f"Ran out of retries to download {download_src}")
                        print(
                            "HTTP Error 429 (Too many requests) received. Trying again 3 seconds...")
                        time.sleep(3)
                    else:
                        raise http_error
                if download_success:
                    break

        return self.install_extension(download_target)

    def install_unrealvs(self):
        """Install the unrealvs extension shipped with UE"""

        version_folder = f"VS{self.product_line_version}"
        vsix_path = os.path.join(
            self.environment.engine_root,
            "Engine/Extras/UnrealVS",
            version_folder,
            "UnrealVS.vsix")

        self.install_extension(vsix_path=vsix_path)


class FASTBuildCacheMode(Enum):
    READ = 0, "r"
    WRITE = 1, "w"
    READ_WRITE = 2, "rw"

    def __str__(self) -> str:
        return self.value[1]


class FASTBuild:
    environment: UnrealEnvironment = None

    def __init__(self, environment: UnrealEnvironment) -> None:
        self.environment = environment

    def setup(self, brokerage_path: str = None, cache_path: str = None, cache_mode: FASTBuildCacheMode = None) -> None:
        """Perform complete setup (brokerage path, startup registration, """
        self.set_environment_variables(brokerage_path=brokerage_path,
                                       cache_path=cache_path,
                                       cache_mode=cache_mode)
        self.add_buildworker_startup()
        self.start_buildworker()

    def add_buildworker_startup(self) -> None:
        """Add the Buildworker to startup/autostart"""
        add_startup("FBuildWorker", self.get_buildworker_exe(),
                    ["-nosubprocess"])

    def set_environment_variables(self, brokerage_path: str = None, cache_path: str = None, cache_mode: FASTBuildCacheMode = None) -> None:
        """
        Permanently store the brokerage path, cache path and cache setting to the system environment.
        Alternatively you can also set those settings in the command line environment only.
        """
        if brokerage_path is not None:
            set_system_env_var("FASTBUILD_BROKERAGE_PATH", brokerage_path)
        if cache_path is not None:
            set_system_env_var("FASTBUILD_CACHE_PATH", cache_path)
        if cache_mode is not None:
            set_system_env_var("FASTBUILD_CACHE_MODE", str(cache_mode))

    def start_buildworker(self) -> None:
        # Do not use call -> We do not want to wait for the process to exit
        subprocess.Popen([self.get_buildworker_exe(), "-nosubprocess"])

    def get_buildworker_exe(self) -> str:
        """Returns the path to the buildworker executable"""
        return os.path.join(self._bin_path(), "FBuildWorker.exe")

    def _bin_path(self) -> str:
        return os.path.join(self.environment.engine_root, "Engine/Extras/ThirdPartyNotUE/FASTBuild/Win64")


if __name__ == "__main__":
    VisualStudio("[16.0,18.0)")
