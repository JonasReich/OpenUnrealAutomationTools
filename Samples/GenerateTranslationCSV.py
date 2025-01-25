"""
Convert the po files of the source language of an Unreal project into csv files usable by the OpenUnrealUtilities CSV Translations feature.
"""

import argparse
import csv
import os

import polib

parser = argparse.ArgumentParser()
parser.add_argument("project_root")
parser.add_argument("targets")
parser.add_argument("--languages", default="en",
                    help="comma seperated string of UE language specifiers (e.g. 'de,en,fr')")

args = parser.parse_args()
project_root = args.project_root
targets = args.targets
languages = args.languages

replace_chars = [
    ("\r\n", "\\r\\n")
]


def clean_str(s: str) -> str:
    for from_str, to_str in replace_chars:
        s = s.replace(from_str, to_str)
    return s

# reverse of clean_str


def unclean_str(s: str) -> str:
    for to_str, from_str in replace_chars:
        s = s.replace(from_str, to_str)
    return s


def generate_translation_csv(target):
    language_loca_root = os.path.join(
        project_root, "Content/Localization/Game", language)
    source_po_path = os.path.normpath(
        os.path.join(language_loca_root, f"{target}.po"))

    csv_dir = os.path.normpath(os.path.join(
        project_root, "CSVTranslations"))
    csv_path = os.path.normpath(os.path.join(
        csv_dir, f"{target}_{language}.csv"))

    print("Processing PO file", source_po_path, ", and CSV", csv_path)

    if not os.path.exists(source_po_path):
        raise FileNotFoundError(source_po_path)

    source_po = polib.pofile(source_po_path)
    existing_lines = dict()

    os.makedirs(csv_dir, exist_ok=True)

    previous_line_count = 0
    if os.path.exists(csv_path):
        with open(csv_path, 'r', newline='', encoding="utf-8") as csvfile:
            csvreader = csv.reader(csvfile, delimiter=',',
                                   quotechar='"', quoting=csv.QUOTE_ALL)

            for row in csvreader:
                [namespace, key, source_text, translation_text] = row
                if namespace not in existing_lines:
                    existing_lines[namespace] = dict()
                existing_lines[namespace][key] = (
                    source_text, translation_text)
                previous_line_count = previous_line_count + 1

    # remove header line
    previous_line_count = previous_line_count - 1 if previous_line_count > 0 else 0

    new_lines = 0
    reused_lines = 0
    changed_lines = 0

    with open(csv_path, 'w', newline='', encoding="utf-8") as csvfile:

        csvwriter = csv.writer(csvfile, delimiter=',',
                               quotechar='"', quoting=csv.QUOTE_ALL)
        csvwriter.writerow(
            ["Namespace", "Key", "SourceString", "LocalizedString"])
        for entry in source_po:
            [namespace, key] = entry.msgctxt.split(",")
            source_text = clean_str(entry.msgid)
            translation_text = clean_str(entry.msgstr)

            if namespace in existing_lines and key in existing_lines[namespace]:
                (existing_source_text,
                 existing_translation_text) = existing_lines[namespace][key]
                if source_text == existing_source_text:
                    reused_lines = reused_lines + 1
                    translation_text = existing_translation_text
                else:
                    changed_lines = changed_lines + 1
            else:
                new_lines = new_lines + 1

            csvwriter.writerow([namespace, key, source_text, translation_text])

            # Write back the current translation into PO
            entry.msgstr = unclean_str(translation_text)

    total_lines = new_lines + reused_lines + changed_lines
    overlapping_lines = reused_lines + changed_lines
    removed_lines = previous_line_count - overlapping_lines
    print(
        f"line changes: new {new_lines}, reused {reused_lines}, changed {changed_lines}, total {total_lines}, removed {removed_lines}")
    source_po.save(source_po_path)

    print(
        f"Deleting archive + locres files for {target} {language} to avoid conflicts with CSV on reimport")
    archive_path = os.path.normpath(os.path.join(
        language_loca_root, f"{target}.archive"))
    if os.path.exists(archive_path):
        os.remove(archive_path)
    locres_path = os.path.normpath(os.path.join(
        language_loca_root, f"{target}.locres"))
    if os.path.exists(locres_path):
        os.remove(locres_path)


for language in languages.split(","):
    for target in targets.split(","):
        generate_translation_csv(target)
