"""
Update the local UnrealEngine version file.
"""

import argparse

from openunrealautomation.environment import UnrealEnvironment

if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument("engine_root")
    args = argparser.parse_args()

    env = UnrealEnvironment.create_from_engine_root(args.engine_root)
    env.build_version.update_local_version()
    print("New engine version: ", env.engine_version)
