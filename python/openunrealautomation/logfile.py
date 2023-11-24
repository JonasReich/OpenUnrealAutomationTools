"""
Access log text files from Unreal programs and the engine.
"""

import glob
import os
from datetime import datetime
from enum import Enum
from typing import Optional

from openunrealautomation.core import ue_time_to_string
from openunrealautomation.environment import UnrealEnvironment


class UnrealLogFile(Enum):
    """
    Unreal Log File Formats and Locations.
    """

    # Unreal Build Tool
    UBT = 0, "{engine_root}/Engine/Programs/UnrealBuildTool/", "Log", "-backup-{timestamp}", ".txt"
    # Generate project files
    UBT_GPF = 1, "{engine_root}/Engine/Programs/UnrealBuildTool", "Log_GPF", "-backup-{timestamp}", ".txt"
    # Unreal Header Tool
    UHT = 2, "{engine_root}/Engine/Programs/UnrealBuildTool/", "Log_UHT", "-backup-{timestamp}", ".txt"
    # Automation Tool
    # No backups of UAT logs. Instead the folder contains logs of substeps
    UAT = 3, "{engine_root}/Engine/Programs/AutomationTool/Saved/Logs/", "Log", "", ".txt"
    # When running UAT, individual logs for invoked steps are placed here.
    # This pattern matches all logs in that folder not including the UAT log itself.
    UAT_STEPS = 4, "{engine_root}/Engine/Programs/AutomationTool/Saved/Logs/", "{uat_step}-{uat_substep}", "", ".txt"
    # The backed up cook logs
    COOK = 5, "{engine_root}/Engine/Programs/AutomationTool/Saved/", "Cook", "-{timestamp}", ".txt"
    # Editor logs (esp. for commandlets / automation tests)
    EDITOR = 6, "{project_root}/Saved/Logs/", "{project_name}*", "-backup-{timestamp}", ".log"

    def root(self) -> str:
        """Format string for root directory of the log files"""
        return self.value[1]

    def file_name(self) -> str:
        """Format string for log file names"""
        return self.value[2]

    def date_suffix(self) -> str:
        """Format string for date suffixes"""
        return self.value[3]

    def extension(self) -> str:
        """File extensions including colon delimiter"""
        return self.value[4]

    def format(self, environment: UnrealEnvironment, time: Optional[datetime] = None, time_string: Optional[str] = None, uat_step: Optional[str] = None, uat_substep: Optional[str] = None) -> str:
        """Format a log file path string. time and time_string are optional because not all log files use them."""
        if not time is None:
            time_string = ue_time_to_string(time)
        complete_format = self.__str__()
        return os.path.normpath(complete_format.format(timestamp=time_string,
                                                       engine_root=environment.engine_root,
                                                       project_root=environment.project_root,
                                                       project_name=environment.project_name,
                                                       uat_step=uat_step,
                                                       uat_substep=uat_substep))

    def find_latest(self, environment: UnrealEnvironment) -> Optional[str]:
        """Find the latest local log file of a given log file category"""
        found_files = self.get_all(environment=environment)
        if found_files is None or len(found_files) == 0:
            return None
        else:
            # Files are sorted by date, so we can just use the last one
            return found_files[-1]

    def get_all(self, environment: UnrealEnvironment) -> list[str]:
        """
        Get all local log files of a given log file category.
        Files are sorted chronologically (old to new).
        """
        base_path = os.path.join(self.root(), self.file_name()).format(engine_root=environment.engine_root,
                                                                       project_root=environment.project_root,
                                                                       project_name=environment.project_name,
                                                                       # UAT Step and substeps need to be set to * for globbing
                                                                       uat_step="*",
                                                                       uat_substep="*")

        search_path = os.path.join(
            environment.engine_root, base_path + "*" + self.extension())
        print(f"Search {search_path} for logs...")
        found_files = glob.glob(search_path)
        found_files = [os.path.normpath(file) for file in found_files]
        found_files.sort(key=os.path.getctime)
        print("...found:", found_files)
        return found_files

    def __str__(self) -> str:
        """
        Combines the whole format string for the given log file category.
        This means the string never points to a valid local path but instead contains the following format params:
            - engine_root
            - project_name
            - timestamp
        """
        return self.root() + self.file_name() + self.date_suffix() + self.extension()


if __name__ == "__main__":
    env = UnrealEnvironment.create_from_invoking_file_parent_tree()

    print("----- All patterns -----")
    now = datetime.now()
    for file_type in UnrealLogFile:
        print(file_type)

    print("----- Base file names -----")
    now = datetime.now()
    for file_type in UnrealLogFile:
        print(file_type.format(env, now))

    print("----- Latest local files -----")
    for file_type in UnrealLogFile:
        print(file_type.find_latest(env))

    print("----- All UAT step records -----")
    all_uat_steps = UnrealLogFile.UAT_STEPS.get_all(env)
    if len(all_uat_steps) > 0:
        print(",\n".join(all_uat_steps))
    else:
        print(None)
