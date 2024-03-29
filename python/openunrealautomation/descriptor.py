"""
Descriptor files are config files in json format.
Examples: .uproject, .uplugin, .version

For each descriptor type, there is a unique descriptor class ensuring type safety and exposing additional members.
"""

import glob
import json
import os
import os.path
from pathlib import Path

from openunrealautomation.core import OUAException


class UnrealDescriptor():
    """
    Base class for UE descriptor files.
    """

    file_path: str = ""

    def __init__(self, file_path) -> None:
        self.file_path = os.path.normpath(file_path)

    def __str__(self) -> str:
        return self.file_path

    def __bool__(self) -> bool:
        return len(self.file_path) > 0

    @classmethod
    def try_find_file(cls, path):
        """
        Try to find a descriptor file based on its extension in a directory.
        Raises if less or more than one file are found.
        """
        directory = path if os.path.isdir(path) else Path(path).parent
        descriptor_files = glob.glob(f"{directory}/*{cls.get_extension()}")
        if len(descriptor_files) == 0:
            raise OUAException(
                f"No descriptor file found in directory {directory}")
        if len(descriptor_files) > 1:
            raise OUAException(
                f"Multiple descriptor files found in directory {directory}: {descriptor_files}")
        return descriptor_files[0]

    @classmethod
    def get_extension(cls) -> str:
        """
        Get the extension for this type of descriptor file.
        Extension should start with dot ('.') character.
        """
        raise NotImplementedError()

    def get_name(self) -> str:
        """
        Get the name of this descriptor file.
        For plugins this should match the plugin name.
        For games this should match the game name.
        """
        return os.path.basename(self.file_path).replace(self.get_extension(), "")

    def read(self) -> dict:
        """
        Read the file into a python dictionary.
        """
        try:
            with open(self.file_path, "r", encoding="utf-8-sig", errors="ignore") as file:
                return json.load(file)
        except Exception as e:
            raise OUAException(
                "Failed to read descriptor file ", self.file_path)

    def write(self, values: dict) -> None:
        """
        Write the dictionary back into the json file.
        """
        with open(self.file_path, "w", encoding="utf-8") as file:
            json.dump(values, file, indent=4)
            print("Wrote", self.file_path)


class UnrealProjectDescriptor(UnrealDescriptor):
    """Descriptor for Unreal project (uproject) files."""

    @staticmethod
    def try_find(directory) -> 'UnrealProjectDescriptor':
        return UnrealProjectDescriptor(UnrealProjectDescriptor.try_find_file(directory))

    @classmethod
    def get_extension(cls) -> str:
        return ".uproject"


class UnrealPluginDescriptor(UnrealDescriptor):
    """Descriptor for Unreal plugin (uplugin) files."""

    @staticmethod
    def try_find(directory) -> 'UnrealPluginDescriptor':
        return UnrealPluginDescriptor(UnrealPluginDescriptor.try_find_file(directory))

    @classmethod
    def get_extension(cls) -> str:
        return ".uplugin"
