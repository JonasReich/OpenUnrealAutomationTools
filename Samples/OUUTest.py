import os

from openunrealautomation.core import UnrealProgram
from openunrealautomation.unrealengine import UnrealEngine

ue = UnrealEngine.create_from_parent_tree(
    os.path.realpath(os.path.dirname(__file__)))


def run_gauntlet_editor_tests():
    """This is not a custom Gauntlet test, but executes UE automation tests in Editor"""
    ue.run(UnrealProgram.UAT, [
        "RunUnreal", "-platform=Win64", "-configuration=Development",
        # this...
        # f"-build={ue.environment.project_root}\Saved\StagedBuilds",
        # ...is equivalent to
        "-build=local",
        # Use our custom scripts
        f"-ScriptDir={ue.environment.project_root}\Build\Scripts",
        # And this GAUNTLET test name:
        "-test=EditorAutomation",
        # ...which expects a test filter for automation controller
        "-RunTest=OpenUnrealUtilities"
    ])


def run_gauntlet_custom_multiplayer_tests():
    """
    This IS a custom Gauntlet test, which should not execute automation tests (necessarily),
    but do some custom funky shit (e.g. network multiplayer testing).
    """
    ue.run(UnrealProgram.UAT, [
        "RunUnreal", "-platform=Win64", "-configuration=Development",
        # this...
        # f"-build={ue.environment.project_root}\Saved\StagedBuilds",
        # ...is equivalent to
        "-build=local",
        # Use our custom scripts
        f"-ScriptDir={ue.environment.project_root}\Build\Scripts",
        # And this GAUNTLET test name:
        "-test=OUUTest.MultiplayerTest"
    ])


run_gauntlet_custom_multiplayer_tests()
