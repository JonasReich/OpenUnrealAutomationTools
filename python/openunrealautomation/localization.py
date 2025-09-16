"""
Localization utilities
"""

import argparse
import csv
import os
import random
import re
from typing import Callable, Dict, List, Optional, Tuple

import polib
from openunrealautomation.p4 import UnrealPerforce

COMMENT_PREFIX_KEY = 'Key:\t'
COMMENT_PREFIX_SOURCE_LOCATION = 'SourceLocation:\t'
COMMENT_PREFIX_META_DATA = 'InfoMetaData:\t"'
COMMENT_SEPARATOR_META_DATA = '" : "'


class EntryWithMetaData:
    """
    Represents meta data for a single .po entry.
    """

    # this should be identical to entry.msgid.split(",")[1]
    key: str
    source_location: str
    meta_data: Dict[str, str]
    entry: polib.POEntry

    def __init__(self, entry: polib.POEntry):
        self.key = ''
        self.source_location = ''
        self.meta_data = dict()
        self.entry = entry

        lines = entry.comment.splitlines()
        for line in lines:
            if line.startswith(COMMENT_PREFIX_KEY):
                self.key = line.removeprefix(COMMENT_PREFIX_KEY)
            elif line.startswith(COMMENT_PREFIX_SOURCE_LOCATION):
                self.source_location = line.removeprefix(
                    COMMENT_PREFIX_SOURCE_LOCATION)
            elif line.startswith(COMMENT_PREFIX_META_DATA):
                line = line.removeprefix(COMMENT_PREFIX_META_DATA)
                key_end = line.find(COMMENT_SEPARATOR_META_DATA)
                if key_end < 0:
                    continue

                key = line[0:key_end]
                line = line[key_end + len(COMMENT_SEPARATOR_META_DATA):]

                value_end = line.rfind('"')
                if value_end < 0:
                    continue

                value = line[0:value_end]
                self.meta_data[key] = value


def _get_localization_root(project_root: str) -> str:
    return os.path.join(
        project_root, "Content/Localization")


# We need to replace with the appropriate newlines - otherwise the text will not be considered identical
NEWLINE_REPLACE_CHARS = [
    ("\r\n", "\\r\\n"),
    ("\n", "\\n")
]

RANDOM_UNICODE_CHAR_RANGES = [
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


def _clean_str(s: str) -> str:
    for from_str, to_str in NEWLINE_REPLACE_CHARS:
        s = s.replace(from_str, to_str)
    return s

# reverse of clean_str


def _unclean_str(s: str) -> str:
    for to_str, from_str in NEWLINE_REPLACE_CHARS:
        s = s.replace(from_str, to_str)
    return s


def get_random_unicode_string(length: int, include_ranges=RANDOM_UNICODE_CHAR_RANGES):
    """Get a random unicode string of the given length
    SOURCE: https://stackoverflow.com/a/21666621"""

    try:
        get_char = unichr
    except NameError:
        get_char = chr

    alphabet = [
        get_char(code_point) for current_range in include_ranges
        for code_point in range(current_range[0], current_range[1] + 1)
    ]
    return ''.join(random.choice(alphabet) for i in range(length))


def add_start_end_marks(text: str) -> str:
    return f"‡{text}‡"


def leetify(text: str) -> str:
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

    def leetify_char(char) -> str:
        return LEET_CHARS.get(char, char)  # type: ignore

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
    return result_text


def generate_translation_csv(project_root, source_language, target_language, target,
                             reuse_mismatched=True,
                             line_filter_func: Optional[Callable[[
                                 str, Dict[str, str]], bool]] = None,
                             line_conversion_func: Optional[Callable[[
                                 str], str]] = None,
                             write_back_po=True,
                             source_csvs: List[Tuple[str, str]] = [],
                             meta_data_keys: List[str] = []):
    localization_root = _get_localization_root(project_root)

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
                [namespace, key, source_text, translation_text, *rest] = row
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

    def _add_new_line(source_text, namespace, key, source_location, meta_data: Dict[str, str]):
        if line_filter_func is not None:
            if not line_filter_func(source_text, meta_data):
                return

        nonlocal reused_lines, new_lines, changed_lines
        should_auto_translate = line_conversion_func is not None
        if should_auto_translate:
            assert line_conversion_func
            translation_text = line_conversion_func(_clean_str(source_text))
        else:
            # new line, no auto translation
            translation_text = ""

        if not should_auto_translate and (namespace in existing_lines and key in existing_lines[namespace]):
            (existing_source_text,
                existing_translation_text) = existing_lines[namespace][key]
            if source_text == existing_source_text:
                reused_lines = reused_lines + 1
                translation_text = existing_translation_text
            else:
                changed_lines = changed_lines + 1
                if reuse_mismatched:
                    translation_text = existing_translation_text
        else:
            new_lines = new_lines + 1

        meta_data_columns = []
        for meta_data_key in meta_data_keys:
            meta_data_columns.append(meta_data.get(meta_data_key, ""))

        csvwriter.writerow(
            [namespace, key, source_text, translation_text, source_location] + meta_data_columns)

        # Write back the current translation into target PO
        entry.msgstr = _unclean_str(translation_text)
        target_po.append(entry)

    with open(csv_path, 'w', newline='', encoding="utf-8") as csvfile:

        csvwriter = csv.writer(csvfile, delimiter=',',
                               quotechar='"', quoting=csv.QUOTE_ALL)
        csvwriter.writerow(
            ["Namespace", "Key", "SourceString", "LocalizedString", "Source"] + meta_data_keys)
        for entry in source_po:
            [namespace, key] = entry.msgctxt.split(",")
            source_text = _clean_str(entry.msgid)
            entry_with_meta_data = EntryWithMetaData(entry)
            source_location = entry_with_meta_data.source_location

            _add_new_line(source_text, namespace, key,
                          source_location, entry_with_meta_data.meta_data)

        for source_csv, csv_namespace in source_csvs:
            print("Merging additional source CSV", source_csv)
            with open(source_csv, 'r', newline='', encoding="utf-8") as csvfile:
                csvreader = csv.reader(csvfile, delimiter=',',
                                       quotechar='"', quoting=csv.QUOTE_ALL)

                [_key, _source_text, *
                    source_csv_meta_data_keys] = next(csvreader)  # skip header

                for row in csvreader:
                    [key, source_text,
                        *meta_data_source_values] = row

                    existing_entry = target_po.find(f"{csv_namespace},{key}")

                    if existing_entry is not None:
                        # namespace + key already present
                        print(
                            f"{csv_namespace},{key} already present in target PO, skipping")
                        continue

                    csv_meta_data = dict()
                    for metadata_key, metadata_value in zip(source_csv_meta_data_keys, meta_data_source_values):
                        csv_meta_data[metadata_key] = metadata_value

                    _add_new_line(source_text, csv_namespace, key,
                                  os.path.relpath(source_csv, project_root).replace("\\", "/") + f"({csvreader.line_num})", csv_meta_data)

    total_lines = new_lines + reused_lines + changed_lines
    overlapping_lines = reused_lines + changed_lines
    removed_lines = previous_line_count - overlapping_lines
    print(
        f"line changes: new {new_lines}, reused {reused_lines}, changed {changed_lines}, total {total_lines}, removed {removed_lines}")

    if write_back_po:
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


def generate_all_translation_csvs(project_root, targets: List[str], languages: List[str], source_language, enable_p4=True):
    if enable_p4:
        p4 = UnrealPerforce()
        localization_root = _get_localization_root(project_root)
        print("P4 Edit:", localization_root)
        p4.edit(localization_root)

    for language in languages:
        for target in targets:
            generate_translation_csv(
                project_root, source_language, language, target)
