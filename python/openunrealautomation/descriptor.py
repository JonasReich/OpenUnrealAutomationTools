
import glob
import os
import json
from abc import abstractmethod
from pydoc import describe
import glob
from .core import OUAException


class UnrealDescriptor:
    file_path: str = ""

    def __init__(self, file_path) -> None:
        self.file_path = file_path

    def __str__(self) -> str:
        return self.file_path

    @classmethod
    def try_find_file(cls, directory):
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
        pass

    def get_name(self) -> str:
        return os.path.basename(self.file_path).replace(self.get_extension(), "")

    def read(self) -> dict:
        with open(self.file_path, "r") as file:
            return json.load(file)


class UnrealProjectDescriptor(UnrealDescriptor):
    @abstractmethod
    def try_find(directory) -> 'UnrealProjectDescriptor':
        return UnrealProjectDescriptor(UnrealProjectDescriptor.try_find_file(directory))

    @classmethod
    def get_extension(cls) -> str:
        return ".uproject"


class UnrealPluginDescriptor(UnrealDescriptor):
    @abstractmethod
    def try_find(directory) -> 'UnrealPluginDescriptor':
        return UnrealPluginDescriptor(UnrealPluginDescriptor.try_find_file(directory))

    @classmethod
    def get_extension(cls) -> str:
        return ".uplugin"
