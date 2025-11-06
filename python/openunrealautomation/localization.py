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


class POEntryWithMetaData:
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


class EntryWithMetaData(POEntryWithMetaData):
    """
    Class alias for PO entries
    """
    pass


class CSVEntryWithMetaData:
    """
    Represents meta data for a single .csv entry.
    """

    namespace: str
    key: str
    source_string: str
    translated_string: Optional[str]
    meta_data: Dict[str, str]

    def __init__(self, namespace: str, key: str, source_string: str, translated_string: Optional[str] = None, meta_data: Dict[str, str] = {}):
        self.namespace = namespace
        self.key = key
        self.source_string = source_string
        self.translated_string = translated_string
        self.meta_data = meta_data

    def combined_key(self) -> str:
        return f"{self.namespace}:{self.key}"

    @staticmethod
    def from_po_entry(entry: polib.POEntry) -> 'CSVEntryWithMetaData':
        [namespace, key] = entry.msgctxt.split(",")
        source_text = _clean_str(entry.msgid)

        # extract meta data from PO
        entry_with_meta_data = EntryWithMetaData(entry)

        meta_data = {}
        meta_data["Source"] = entry_with_meta_data.source_location
        meta_data.update(entry_with_meta_data.meta_data)

        return CSVEntryWithMetaData(namespace, key, source_text,
                                    meta_data=meta_data)

    @staticmethod
    def list_to_dict(entries: List['CSVEntryWithMetaData']) -> Dict[str, 'CSVEntryWithMetaData']:
        result = {}
        for entry in entries:
            combined_key = entry.combined_key()
            if combined_key in result:
                conflict_entry = result[combined_key]
                raise ValueError(
                    f"Duplicate entry for {combined_key}: {entry.meta_data.get('Source', '')} vs {conflict_entry.meta_data.get('Source', '')}")
            result[combined_key] = entry
        return result

    @staticmethod
    def from_po(po_file_path: str) -> List['CSVEntryWithMetaData']:
        return [CSVEntryWithMetaData.from_po_entry(entry) for entry in polib.pofile(po_file_path)]

    @staticmethod
    def from_source_csv(csv_path: str, project_root: str, namespace: str) -> List['CSVEntryWithMetaData']:
        new_lines = []
        # print("Merging additional source CSV", source_csv)
        with open(csv_path, 'r', newline='', encoding="utf-8") as csvfile:
            csvreader = csv.reader(csvfile, delimiter=',',
                                   quotechar='"', quoting=csv.QUOTE_ALL)

            [_key, _source_text, *
                source_csv_meta_data_keys] = next(csvreader)  # skip header

            for row in csvreader:
                if len(row) == 0:
                    continue
                try:
                    [key, source_text,
                        *meta_data_source_values] = row
                except ValueError:
                    raise ValueError(
                        f"Failed to unpack csv row: {csv_path}({csvreader.line_num})")

                csv_meta_data = dict()
                csv_meta_data["Source"] = os.path.relpath(
                    csv_path, project_root).replace("\\", "/") + f"({csvreader.line_num})"
                for metadata_key, metadata_value in zip(source_csv_meta_data_keys, meta_data_source_values):
                    # For some reason, Unreal exports metadata values with newlines unescaped.
                    # We need to re-escape them to be consistent with PO files and other CSV columns.
                    csv_meta_data[metadata_key] = _clean_str(metadata_value)

                new_lines.append(CSVEntryWithMetaData(namespace, key, source_text,
                                                      meta_data=csv_meta_data))
        return new_lines

    @staticmethod
    def diff(a: Dict[str, 'CSVEntryWithMetaData'], b: Dict[str, 'CSVEntryWithMetaData'], a_name: str = "A", b_name: str = "B", verbose=False) -> None:
        print(
            f"Diffing CSVs: {a_name} ({len(a)} entries) vs {b_name} ({len(b)} entries)")
        only_in_a = set(a.keys()) - set(b.keys())
        only_in_b = set(b.keys()) - set(a.keys())
        print(f"  removed:\t", len(only_in_a))
        print(f"  added:\t", len(only_in_b))
        different_source_text = 0
        for key in set(a.keys()).intersection(set(b.keys())):
            entry_a = a[key]
            entry_b = b[key]
            if entry_a.source_string != entry_b.source_string:
                different_source_text = different_source_text + 1
        print(f"  mod. source:\t", different_source_text)
        print(f"  unchanged:\t", len(a) -
              len(only_in_a) - different_source_text)

        if verbose:
            print("Diffing source text changes (verbose):")
        for key in set(a.keys()).intersection(set(b.keys())):
            entry_a = a[key]
            entry_b = b[key]
            if entry_a.source_string != entry_b.source_string:
                if verbose:
                    print(f"    {key}")
                    print(f"      {a_name} source: {entry_a.source_string}")
                    print(f"      {b_name} source: {entry_b.source_string}")
        pass


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


def read_translation_csv(csv_path: str, ignore_duplicates: bool = False) -> Dict[str, CSVEntryWithMetaData]:
    """
    Read an existing translation CSV and return a dictionary of namespace -> key -> CSVEntryWithMetaData.
    Supports both "CombinedKey" and "Namespace" formats.
    """
    existing_lines = dict()
    # use utf-8-sig to handle both utf-8 with and without BOM
    with open(csv_path, 'r', newline='', encoding="utf-8-sig") as csvfile:
        csvreader = csv.reader(csvfile, delimiter=',',
                               quotechar='"', quoting=csv.QUOTE_ALL)

        get_key_func: Callable[[List[str]], CSVEntryWithMetaData]
        header_row = next(csvreader)
        header_row[0]
        if header_row[0:3] == ["CombinedKey", "SourceString", "LocalizedString"]:
            def _get_combined_key_row(row: List[str]) -> CSVEntryWithMetaData:
                metadata_keys = header_row[3:]
                metadata_values = row[3:]
                combined_key = row[0]
                namespace, key = combined_key.split(":", 1)
                return CSVEntryWithMetaData(namespace, key, row[1], row[2], meta_data=dict(zip(metadata_keys, metadata_values)))
            get_key_func = _get_combined_key_row
        elif header_row[0:4] == ["Namespace", "Key", "SourceString", "LocalizedString"]:
            def _get_namespace_key_row(row: List[str]) -> CSVEntryWithMetaData:
                metadata_keys = header_row[4:]
                metadata_values = row[4:]
                return CSVEntryWithMetaData(row[0], row[1], row[2], row[3], meta_data=dict(zip(metadata_keys, metadata_values)))
            get_key_func = _get_namespace_key_row
        else:
            raise ValueError(
                f"Unexpected CSV header row in {csv_path}: {header_row}")

        for row in csvreader:
            new_entry = get_key_func(row)
            combined_key = new_entry.combined_key()
            if combined_key in existing_lines:
                if ignore_duplicates:
                    continue
                else:
                    raise ValueError(
                        f"Duplicate entry for {combined_key} in {csv_path}")
            existing_lines[combined_key] = new_entry

    return existing_lines


def write_translation_csv(csv_path: str, entries: Dict[str, CSVEntryWithMetaData], combine_key: bool, meta_data_keys: Optional[List[str]] = None):
    """
    Write a translation CSV from a list of CSVEntryWithMetaData.
    """
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with open(csv_path, 'w', newline='', encoding="utf-8") as csvfile:
        csvwriter = csv.writer(csvfile, delimiter=',',
                               quotechar='"', quoting=csv.QUOTE_ALL)
        header_row = []
        if combine_key:
            header_row += ["CombinedKey"]
        else:
            header_row += ["Namespace", "Key"]
        header_row += ["SourceString", "LocalizedString"]
        if meta_data_keys:
            header_row += meta_data_keys
        csvwriter.writerow(header_row)

        for _combined_key, entry in entries.items():
            combined_key = entry.combined_key()
            if combined_key != _combined_key:
                raise ValueError(
                    f"Mismatch of combined key {combined_key} vs {_combined_key}")
            row = []
            if combine_key:
                row += [combined_key]
            else:
                row += [entry.namespace, entry.key]
            row += [entry.source_string, entry.translated_string]
            if meta_data_keys:
                for meta_data_key in meta_data_keys:
                    row.append(entry.meta_data.get(meta_data_key, ""))
            csvwriter.writerow(row)


def generate_translation_csv(project_root, source_language, target_language, target,
                             line_filter_func: Optional[Callable[[
                                 CSVEntryWithMetaData], bool]] = None,
                             line_conversion_func: Optional[Callable[[
                                 CSVEntryWithMetaData], None]] = None,
                             source_csvs: List[Tuple[str, str]] = [],
                             meta_data_keys: List[str] = []):
    localization_root = _get_localization_root(project_root)

    source_language_loca_root = os.path.join(
        localization_root, target, source_language)
    source_po_path = os.path.normpath(
        os.path.join(source_language_loca_root, f"{target}.po"))

    print("\n##", target, "##")
    print("Extracting strings from PO file",
          source_po_path, "to CSV")

    if not os.path.exists(source_po_path):
        raise FileNotFoundError(source_po_path)

    new_lines: List[CSVEntryWithMetaData] = []

    new_lines += CSVEntryWithMetaData.from_po(source_po_path)

    for source_csv, csv_namespace in source_csvs:
        new_lines += CSVEntryWithMetaData.from_source_csv(
            source_csv, project_root, csv_namespace)

    if line_filter_func:
        num_unfiltered_lines = len(new_lines)
        new_lines = list(
            filter(lambda line: line_filter_func(line), new_lines))
        print("Filtered lines:", num_unfiltered_lines, "->", len(new_lines))

    for line in new_lines:
        if line_conversion_func:
            line.translated_string = line_conversion_func(line)

    new_lines_dict = CSVEntryWithMetaData.list_to_dict(new_lines)

    csv_dir = os.path.normpath(os.path.join(
        localization_root, "CSVTranslations"))
    os.makedirs(csv_dir, exist_ok=True)

    last_sent_dir = os.path.normpath(os.path.join(
        csv_dir, "LastSentToTranslation"))
    last_translated_dir = os.path.normpath(os.path.join(
        csv_dir, "ReceivedTranslation"))
    export_dir = os.path.normpath(os.path.join(
        csv_dir, "ExportForTranslation"))
    game_dir = os.path.normpath(os.path.join(
        csv_dir, "ExportForGame"))

    csv_file_name = f"{target}_{target_language}.csv"

    meta_data_keys.insert(0, "Source")  # always include source location first
    write_translation_csv(os.path.normpath(os.path.join(
        export_dir, csv_file_name)), new_lines_dict, combine_key=True, meta_data_keys=meta_data_keys)

    # export without metadata for game
    write_translation_csv(os.path.normpath(os.path.join(
        game_dir, csv_file_name)), new_lines_dict, combine_key=False, meta_data_keys=None)

    last_sent_csv_path = os.path.normpath(os.path.join(
        last_sent_dir, csv_file_name))
    if os.path.exists(last_sent_csv_path):
        print("Diffing against last sent CSV", last_sent_csv_path)
        old_lines_dict = read_translation_csv(
            last_sent_csv_path, ignore_duplicates=True)
        CSVEntryWithMetaData.diff(
            old_lines_dict, new_lines_dict, a_name="LastSent", b_name="Current", verbose=True)
    else:
        print("No last sent CSV to diff against")


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
