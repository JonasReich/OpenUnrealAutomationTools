"""
Convert the po files of the source language of an Unreal project into csv files usable by the OpenUnrealUtilities CSV Translations feature.
"""

import argparse
import os

import openunrealautomation.localization as localization
from openunrealautomation.environment import UnrealEnvironment

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="Game")
    parser.add_argument("--project", default=None)
    parser.add_argument("--languages", default="en,de,fr,en-us-POSIX",
                        help="comma separated string of UE language specifiers (e.g. 'en,de,fr')")
    parser.add_argument("--gather", action="store_true",
                        help="Switch: Run gather commandlet before generating CSV")
    parser.add_argument("--source-language", default="en",
                        help="Language to use as source for all native texts.")
    parser.add_argument("-P4", "--perforce", action="store_true",
                        help="If set, Perforce is enabled to check out files before editing them.")

    args = parser.parse_args()

    target = args.target
    languages = args.languages.split(",")
    soruce_language = args.source_language

    # Set to True to export CSVs for OpenUnrealUtilities runtime import, False to write back to PO files for Unreal's built-in localization system.
    EXPORT_FOR_GAME_OUU = True

    if args.project:
        env = UnrealEnvironment.create_from_project_root(args.project)
    else:
        env = UnrealEnvironment.create_from_parent_tree(__file__)
    project_root = env.project_root

    # 1st step: gather new texts from uassets into PO
    if args.gather:
        localization.run_gather_commandlet(env, target, ["Gather", "Export"])
        quit()

    # 2nd step: collect source strings from PO and CSVs
    source_csvs = localization.collect_source_cvs(
        project_root, ["Content/Text/*.csv", "Plugins/**/Content/Text/*.csv"])
    source_strings = localization.collect_source_strings(
        project_root, source_language="en", po_targets=[] if EXPORT_FOR_GAME_OUU else [target], source_csvs=source_csvs)

    # ... now per language ...
    for language in languages:
        # 3rd step: import existing translations (or generate translations, etc)
        translation_csv_path = os.path.join(localization.get_csv_dir(
            project_root, "FromTranslators"), f"{language}.csv")

        if os.path.exists(translation_csv_path):
            translations = localization.import_csv_translations(
                language, target, source_strings, [translation_csv_path])
        else:
            # no translations yet, use source strings as placeholders
            translations = source_strings

        # 4th step: generate CSV for translators
        # If your game has any csv metadata columns, add them to meta_data_keys
        localization.write_translation_csv(
            os.path.join(localization.get_csv_dir(project_root, "ForTranslators"), f"{language}.csv"), translations, combine_key=True, meta_data_keys=["Source"])

        if EXPORT_FOR_GAME_OUU:
            # 5th step: generate CSV for game if you use OpenUnrealUtilities CSV import at runtime
            localization.export_csv_for_game_ouu(
                project_root, target, language, translations)
        else:
            # ... or write back to PO files for Unreal if you use Unreal's built-in localization system that needs locres files included in the pak files.
            # -> this needs to be followed by running the "Import" and "Compile" gather commandlet steps to get the translations into the game.
            localization.write_translation_po(
                project_root, language, target, translations)

    # 6th step: import and compile translations into locres files
    if not EXPORT_FOR_GAME_OUU:
        localization.run_gather_commandlet(
            env, target, ["Import", "Compile"], languages=languages)
