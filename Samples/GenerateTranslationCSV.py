"""
Convert the po files of the source language of an Unreal project into csv files usable by the OpenUnrealUtilities CSV Translations feature.
"""

import argparse
import csv
import os
import random

import polib
from openunrealautomation.p4 import UnrealPerforce

parser = argparse.ArgumentParser()
parser.add_argument("project_root")
parser.add_argument("targets")
parser.add_argument("--languages", default="en",
                    help="comma seperated string of UE language specifiers (e.g. 'de,en,fr')")
parser.add_argument("--source-language", default="en",
                    help="Language to use as source for all native texts.")
parser.add_argument("-P4", "--perforce", action="store_true",
                    help="If set, Perforce is enabled to check out files before editing them.")

args = parser.parse_args()
project_root = args.project_root
targets = args.targets
languages = args.languages
source_language = args.source_language

localization_root = os.path.join(
    project_root, "Content/Localization")

# We need to replace with the appropriate newlines - otherwise the text will not be considered identical
NEWLINE_REPLACE_CHARS = [
    ("\r\n", "\\r\\n"),
    ("\n", "\\n")
]


def clean_str(s: str) -> str:
    for from_str, to_str in NEWLINE_REPLACE_CHARS:
        s = s.replace(from_str, to_str)
    return s

# reverse of clean_str


def unclean_str(s: str) -> str:
    for to_str, from_str in NEWLINE_REPLACE_CHARS:
        s = s.replace(from_str, to_str)
    return s


def get_random_unicode(length):
    """Get a random unicode string of the given length
    SOURCE: https://stackoverflow.com/a/21666621"""

    try:
        get_char = unichr
    except NameError:
        get_char = chr

    # Update this to include code point ranges to be sampled
    include_ranges = [
        (0x0021, 0x0021),
        (0x0023, 0x0026),
        (0x0028, 0x007E),
        (0x00A1, 0x00AC),
        (0x00AE, 0x00FF),
        (0x0100, 0x017F),
        (0x0180, 0x024F),
        (0x2C60, 0x2C7F),
        (0x16A0, 0x16F0),
        (0x0370, 0x0377),
        (0x037A, 0x037E),
        (0x0384, 0x038A),
        (0x038C, 0x038C),
    ]

    alphabet = [
        get_char(code_point) for current_range in include_ranges
        for code_point in range(current_range[0], current_range[1] + 1)
    ]
    return ''.join(random.choice(alphabet) for i in range(length))


def leetify(text: str):
    LEET_CHARS = {
        'A': '4',
        'a': '@',
        'B': '8',
        'b': '8',
        'E': '3',
        'e': '3',
        'G': '9',
        'g': '9',
        'I': '1',
        'i': '!',
        'O': '0',
        'o': '0',
        'S': '5',
        's': '$',
        'T': '7',
        't': '7',
        'Z': '2',
        'z': '2',
    }

    keywords_to_skip = [
        "min(",
        "min_frac",
        "max_frac",
        "empty(",
        "floor(",
        "round(",
        "fmt(",
        "no=",
        "yes=",
        "<b>",
        "<s>",
        "<i>",
        "<b_gold>",
    ]

    def leetify_char(char):
        return LEET_CHARS.get(char, char)

    result_text = ""
    escape_next = False
    index = 0
    text_len = len(text)
    while index < text_len:
        source_char = text[index]
        if not escape_next and source_char == "{":
            end_argument_index = index
            while end_argument_index < text_len:
                end_argument_index = end_argument_index + 1
                if text[end_argument_index] == "}":
                    end_argument_index = end_argument_index + 1
                    break
            argument_string = text[index: end_argument_index]
            result_text = f"{result_text}{argument_string}"
            index = end_argument_index
            continue
        elif source_char == "`":
            escape_next = not escape_next
        else:
            escape_next = False
            found_keyword = False
            for keyword in keywords_to_skip:
                if text[index:].startswith(keyword):
                    result_text = result_text + keyword
                    index = index + len(keyword)
                    found_keyword = True
                    break
            if found_keyword:
                continue

        result_text = result_text + leetify_char(source_char)
        index = index + 1
    return f"‡{result_text}‡"


def generate_translation_csv(target_language, target):
    source_language_loca_root = os.path.join(
        localization_root, target, source_language)
    source_po_path = os.path.normpath(
        os.path.join(source_language_loca_root, f"{target}.po"))

    target_language_loca_root = os.path.join(
        localization_root, target, target_language)
    target_po_path = os.path.normpath(
        os.path.join(target_language_loca_root, f"{target}.po"))

    csv_dir = os.path.normpath(os.path.join(
        localization_root, "CSVTranslations"))
    csv_path = os.path.normpath(os.path.join(
        csv_dir, f"{target}_{target_language}.csv"))

    print("Processing PO file", target_po_path, ", and CSV", csv_path)

    if not os.path.exists(source_po_path):
        raise FileNotFoundError(source_po_path)

    source_po = polib.pofile(source_po_path)
    target_po = polib.pofile(target_po_path)
    target_po.clear()
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

            should_auto_translate = target_language.lower() == "en-us-posix"
            if should_auto_translate:
                translation_text = leetify(clean_str(source_text))
                # # Arbitrary factor by which to extend texts
                # source_len_factor = 1.3
                # translation_text = get_random_unicode(
                #     int(len(entry.msgid) * source_len_factor))
            else:
                translation_text = clean_str(entry.msgstr)

            if not should_auto_translate and (namespace in existing_lines and key in existing_lines[namespace]):
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

            # Write back the current translation into target PO
            entry.msgstr = unclean_str(translation_text)
            target_po.append(entry)

    total_lines = new_lines + reused_lines + changed_lines
    overlapping_lines = reused_lines + changed_lines
    removed_lines = previous_line_count - overlapping_lines
    print(
        f"line changes: new {new_lines}, reused {reused_lines}, changed {changed_lines}, total {total_lines}, removed {removed_lines}")
    target_po.save(target_po_path)

    # print(
    #     f"Deleting archive + locres files for {target} {language} to avoid conflicts with CSV on reimport")
    # archive_path = os.path.normpath(os.path.join(
    #     language_loca_root, f"{target}.archive"))

    # if os.path.exists(archive_path):
    #     os.remove(archive_path)
    # locres_path = os.path.normpath(os.path.join(
    #     language_loca_root, f"{target}.locres"))
    # if os.path.exists(locres_path):
    #     os.remove(locres_path)


if args.perforce:
    p4 = UnrealPerforce()
    print("P4 Edit:", localization_root)
    p4.edit(localization_root)

for language in languages.split(","):
    for target in targets.split(","):
        generate_translation_csv(language, target)
