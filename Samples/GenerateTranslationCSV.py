"""
Convert the po files of the source language of an Unreal project into csv files usable by the OpenUnrealUtilities CSV Translations feature.
"""

import argparse

from openunrealautomation.localization import generate_all_translation_csvs

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root")
    parser.add_argument("targets")
    parser.add_argument("--languages", default="en",
                        help="comma separated string of UE language specifiers (e.g. 'de,en,fr')")
    parser.add_argument("--source-language", default="en",
                        help="Language to use as source for all native texts.")
    parser.add_argument("-P4", "--perforce", action="store_true",
                        help="If set, Perforce is enabled to check out files before editing them.")

    args = parser.parse_args()

    generate_all_translation_csvs(
        project_root=args.project_root,
        targets=args.targets.split(","),
        languages=args.languages.split(","),
        source_language=args.source_language,
        enable_p4=args.perforce
    )
