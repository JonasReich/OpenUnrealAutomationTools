"""
Convert the po files of the source language of an Unreal project into csv files usable by the OpenUnrealUtilities CSV Translations feature.
"""

import argparse

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

    if args.project:
        env = UnrealEnvironment.create_from_project_root(args.project)
    else:
        env = UnrealEnvironment.create_from_parent_tree(__file__)
    project_root = env.project_root

    if args.gather:
        localization.run_gather_commandlet(env, target, ["Gather", "Export"])
        quit()

    source_csvs = localization.collect_source_cvs(
        project_root, ["Content/Text/*.csv", "Plugins/**/Content/Text/*.csv"])
    target_source_strings = localization.collect_source_strings(
        project_root, source_language="en", target=target)

    for language in languages:
        for line in target_source_strings.values():
            # line objects are re-used across languages, so we need to reset translated string to avoid bleeding translations from other languages
            # TODO move this to internals - auto-translation should be handled via conversion delegate in generate_translation_csv function so user doesn't need to know about this!
            line.translated_string = ""

        # this line modifies the line dict -> translations are loaded in
        localization.generate_translation_csv(project_root=project_root,
                                              target_language=language,
                                              target=target,
                                              new_lines_dict=target_source_strings)

        # write back to game po
        localization.write_translation_po(project_root=project_root,
                                          language=language,
                                          target=target,
                                          new_lines_dict=target_source_strings)
