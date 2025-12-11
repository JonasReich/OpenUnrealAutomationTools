"""
Localization utilities
"""

import csv
import datetime
import glob
import os
import random
import re
from typing import Callable, Dict, List, Optional, Tuple

import polib
from openunrealautomation.environment import UnrealEnvironment
from openunrealautomation.p4 import UnrealPerforce
from openunrealautomation.unrealengine import UnrealEngine
from openunrealautomation.util import ouu_temp_file

COMMENT_PREFIX_KEY = 'Key:\t'
COMMENT_PREFIX_SOURCE_LOCATION = 'SourceLocation:\t'
COMMENT_PREFIX_META_DATA = 'InfoMetaData:\t"'
COMMENT_SEPARATOR_META_DATA = '" : "'
PO_WRAP_WIDTH = 900


def write_csv(file_name: str, rows: List[List[str]]) -> str:
    path = ouu_temp_file("Localization/" + file_name + ".csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='', encoding="utf-8") as csv_file:
        csv_writer = csv.writer(csv_file, delimiter=',',
                                quotechar='"', quoting=csv.QUOTE_ALL)
        csv_writer.writerows(rows)
    return path


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

    def to_po_entry(self) -> polib.POEntry:
        result = polib.POEntry()
        result.msgctxt = self.namespace + "," + self.key
        result.msgid = _unclean_str(self.source_string)
        result.msgstr = _unclean_str(self.translated_string)

        source = self.meta_data['Source']

        meta_data_rows = [f"{COMMENT_PREFIX_META_DATA}{meta_key}{COMMENT_SEPARATOR_META_DATA}{meta_value}\"" for meta_key,
                          meta_value in self.meta_data.items() if meta_key != 'Source']
        result.comment = "\n".join([
            f"{COMMENT_PREFIX_KEY}{self.key}",
            f"{COMMENT_PREFIX_SOURCE_LOCATION}{source}"
        ]
            + meta_data_rows
        )
        result.occurrences = [(source, None)]
        return result

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

    def write_po_file(entries: Dict[str, 'CSVEntryWithMetaData'], po_file_path: str, target: str, language: str) -> None:
        os.makedirs(os.path.dirname(po_file_path), exist_ok=True)
        if os.path.exists(po_file_path):
            po_file = polib.pofile(po_file_path)
        else:
            po_file = polib.POFile(encoding="utf-8")

            # Add all the file metadata fields usually added by UE exports
            # (Proper value for plural forms would need lookup to be resolved)
            date_str = datetime.datetime.now().strftime("%Y-%M-%D %h:%m")

            po_file.metadata = {
                "Project-Id-Version": target,
                "POT-Creation-Date": date_str,
                "PO-Revision-Date": date_str,
                "Language-Team": "",
                "Language": language,
                "MIME-Version": "1.0",
                "Content-Type": "text/plain; charset=UTF-8",
                "Content-Transfer-Encoding": "8bit",
                "Plural-Forms": "unknown"}

        po_file.header = f"{target} {language} translation.\nAutomated export by OpenUnrealAutomationTools (c) 2025 Jonas Reich.\n"

        po_file.clear()
        for entry in entries.values():
            po_file.append(entry.to_po_entry())
        po_file.wrapwidth = PO_WRAP_WIDTH
        po_file.save(po_file_path)

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
    def diff(diff_name: str, a: Dict[str, 'CSVEntryWithMetaData'], b: Dict[str, 'CSVEntryWithMetaData'], a_name: str = "A", b_name: str = "B", verbose=False) -> None:
        print(
            f"Diffing CSVs: {a_name} ({len(a)} entries) vs {b_name} ({len(b)} entries)")
        only_in_a = set(a.keys()) - set(b.keys())
        only_in_b = set(b.keys()) - set(a.keys())
        diff_name = f"{diff_name}_Diff_{a_name}_{b_name}"

        rows = [["CombinedKey", f"SourceString {a_name}"]]
        for key in only_in_a:
            entry_a = a[key]
            rows.append([key, entry_a.source_string])
        removed_diff = write_csv(diff_name + "_removed", rows)
        diff_suffix = f"\t -> diff: {removed_diff}" if verbose else ""
        print(f"  removed:       {len(only_in_a)}{diff_suffix}")

        print(f"  added:         {len(only_in_b)}")

        different_translation_text = 0
        different_source_text = 0

        mod_source_rows = [
            ["CombinedKey", f"SourceString {a_name}", f"SourceString {b_name}"]]
        mod_translation_rows = [
            ["CombinedKey", f"Translation {a_name}", f"Translation {b_name}"]]
        for key in set(a.keys()).intersection(set(b.keys())):
            entry_a = a[key]
            entry_b = b[key]
            if entry_a.source_string != entry_b.source_string:
                different_source_text = different_source_text + 1
                if verbose:
                    mod_source_rows.append(
                        [key, entry_a.source_string, entry_b.source_string])
            if entry_a.translated_string != entry_b.translated_string:
                different_translation_text = different_translation_text + 1
                if verbose:
                    mod_translation_rows.append(
                        [key, str(entry_a.translated_string), str(entry_b.translated_string)])
        mod_diff = write_csv(diff_name + "_modified_source", mod_source_rows)
        diff_suffix = f"\t -> diff: {mod_diff}" if verbose else ""
        print(f"  mod. source:   {different_source_text}{diff_suffix}")

        num_unchanged = len(a) - len(only_in_a) - different_source_text
        print(f"  same source:   {num_unchanged}")

        mod_diff = write_csv(
            diff_name + "_modified_translation", mod_translation_rows)
        diff_suffix = f"\t -> diff: {mod_diff}" if verbose else ""
        print(f"  mod. transl.:  {different_translation_text}{diff_suffix}")


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
        column_indices = {header_row[i]: i for i in range(len(header_row))}

        use_combined_key = "CombinedKey" in column_indices

        # validate CSV format
        try:
            assert "SourceString" in column_indices
            assert "LocalizedString" in column_indices
            if use_combined_key:
                assert "Key" not in column_indices
                assert "Namespace" not in column_indices
            else:
                assert "Key" in column_indices
                assert "Namespace" in column_indices
        except:
            raise ValueError(
                f"Unexpected CSV header row in {csv_path}: {', '.join(header_row)}")
        non_metadata_keys = [
            "SourceString", "LocalizedString", "Key", "Namespace", "CombinedKey"]
        metadata_keys = [
            key for key in header_row if key not in non_metadata_keys]

        for row in csvreader:
            source_string = row[column_indices["SourceString"]]
            translated_string = row[column_indices["LocalizedString"]]
            if use_combined_key:
                _combined_key = row[column_indices["CombinedKey"]]
                namespace, key = _combined_key.split(":", 1)
            else:
                namespace = row[column_indices["Namespace"]]
                key = row[column_indices["Key"]]
            meta_data = {meta_key: row[column_indices[meta_key]]
                         for meta_key in metadata_keys}
            new_entry = CSVEntryWithMetaData(
                namespace, key, source_string, translated_string, meta_data)
            combined_key = new_entry.combined_key()
            if use_combined_key:
                # pyright: ignore[reportPossiblyUnboundVariable]
                assert _combined_key
                assert combined_key == _combined_key, f"Mismatch of combined key {combined_key} vs {_combined_key}"
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

    rows = []
    header_row = []
    if combine_key:
        header_row += ["CombinedKey"]
    else:
        header_row += ["Namespace", "Key"]
    header_row += ["SourceString", "LocalizedString"]
    if meta_data_keys:
        header_row += meta_data_keys
    rows.append(header_row)

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
        rows.append(row)
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with open(csv_path, 'w', newline='', encoding="utf-8") as csvfile:
        csvwriter = csv.writer(csvfile, delimiter=',',
                               quotechar='"', quoting=csv.QUOTE_ALL)
        csvwriter.writerows(rows)
        print("Wrote", len(rows) - 1, "CSV rows to", csv_path)


def get_csv_dir(project_root: str, dir_name: str) -> str:
    localization_root = _get_localization_root(project_root)
    base_csv_dir = os.path.normpath(os.path.join(
        localization_root, "CSVTranslations"))
    result = os.path.normpath(os.path.join(
        base_csv_dir, dir_name))
    if os.path.exists(result) == False:
        os.makedirs(result, exist_ok=True)
    return result


def import_csv_translations(target_language, target,
                            new_lines_dict: Dict[str, CSVEntryWithMetaData],
                            translation_csvs: List[str],
                            translation_override_csvs: List[str] = [],
                            keep_translation_if_source_changed: bool = True,
                            verbose_diff: bool = False) -> Dict[str, CSVEntryWithMetaData]:
    """
    Reads a number of translation files into the new_lines_dict translated_strings properties.
    Also performs diffs to detect differences between translations and current strings and listing untranslated lines.
    """

    diff_id = target + "_" + target_language
    last_translated_lines = {}

    if len(translation_csvs) == 0:
        print("No translated CSV to import")
    else:
        for translation_csv in translation_csvs:
            if not os.path.exists(translation_csv):
                continue

        p4 = UnrealPerforce()
        translations_date = p4.get_last_change_date(translation_csv)
        print(
            f"combine current sources with translations from {translations_date}")
            last_translated_lines.update(read_translation_csv(translation_csv,
                                                              ignore_duplicates=True))

        # diff first, then update source strings / metadata based on current values
        CSVEntryWithMetaData.diff(diff_id,
                                  last_translated_lines, new_lines_dict, a_name="LastTranslated", b_name="Current", verbose=verbose_diff)

        overrides = {}
        for translation_csv in translation_override_csvs:
            if not os.path.exists(translation_csv):
                continue

            p4 = UnrealPerforce()
            translations_date = p4.get_last_change_date(translation_csv)
            print(
                f"combine current sources with overrides from {translations_date}")
            raw_overrides = read_translation_csv(translation_csv,
                                                     ignore_duplicates=True)
            for override_key, override_value in raw_overrides.items():
                if override_key in new_lines_dict:
                    overrides[override_key] = override_value

        # diff first, then merge overrides into the translations
        CSVEntryWithMetaData.diff(diff_id,
                                  last_translated_lines, overrides, a_name="LastTranslated", b_name="Overrides", verbose=verbose_diff)

        last_translated_lines.update(overrides)

        only_in_translation = last_translated_lines.keys() - new_lines_dict.keys()
        for key in only_in_translation:
            last_translated_lines.pop(key)

        # do NOT track stats of lines here - the diff will be done later
        for combined_key, new_line in new_lines_dict.items():
            if not combined_key in last_translated_lines:
                last_translated_lines[combined_key] = CSVEntryWithMetaData(
                    new_line.namespace, new_line.key, new_line.source_string, None, meta_data=new_line.meta_data.copy())
                continue

            translated_line = last_translated_lines[combined_key]
            if new_line.source_string != translated_line.source_string:
                if not keep_translation_if_source_changed:
                    del translated_line
                    continue
                else:
                    translated_line.source_string = new_line.source_string
            translated_line.meta_data = new_line.meta_data.copy()

        untranslated = list(
        filter(lambda entry: entry.source_string != "" and entry.translated_string == "", new_lines_dict.values()))
        if len(untranslated) > 0:
            rows = [["CombinedKey", "SourceString"]]
            for entry in untranslated:
                rows.append(
                    [entry.combined_key(), entry.source_string])
            untranslated_csv = write_csv(
            f"{diff_id}_untranslated", rows)
            csv_suffix = f"\t -> {untranslated_csv}" if verbose_diff else ""
        else:
            csv_suffix = ""
        print(
            f"  untranslated:  {len(untranslated)}{csv_suffix}")

    return last_translated_lines
    if meta_data_keys is None:
        meta_data_keys = []


def export_csv_for_game_ouu(project_root: str, target_csv_file_name: str, new_lines_dict: Dict[str, CSVEntryWithMetaData]):
    """
    Exports lines for import into a game that uses OpenUnrealUtilities to import CSV strings at runtime.
    """
    # this path is REQUIRED by OpenUnrealUtiltiies text import
    game_dir = get_csv_dir(project_root, "ExportForGame")
    # export without metadata for game - never combine key for game, as Unreal expects separate columns
    write_translation_csv(os.path.normpath(os.path.join(
        game_dir, target_csv_file_name)), new_lines_dict, combine_key=False, meta_data_keys=None)


def collect_source_cvs(root: str, root_relative_glob_patterns: List[str], path_to_namespace_pattern=r"Text\\(.*).csv") -> List[Tuple[str, str]]:
    """Search for string tables from a glob pattern list. Default path_to_namespace_pattern assumes that the csvs have a namespace relative to a Text/ directory"""
    source_csvs: List[Tuple[str, str]] = []
    for glob_pattern in root_relative_glob_patterns:
        for csv_path in glob.glob(os.path.join(root, glob_pattern), recursive=True):
            namespace_match = re.search(path_to_namespace_pattern, csv_path)
            assert namespace_match, f"Failed to extract namespace from {csv_path}"
            namespace = namespace_match.group(1).replace("\\", "/")
            source_csvs.append((csv_path, namespace))
    return source_csvs


def collect_source_strings(project_root: str, source_language: str, target: str, line_filter_func: Optional[Callable[[
        CSVEntryWithMetaData], bool]] = None,
        source_csvs: List[Tuple[str, str]] = []) -> Dict[str, CSVEntryWithMetaData]:
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

    new_lines_dict = CSVEntryWithMetaData.list_to_dict(new_lines)
    return new_lines_dict


def write_translation_po(project_root: str, language: str, target: str, new_lines_dict: Dict[str, CSVEntryWithMetaData]) -> None:
    """
    Write out the current lines dict into a po file for the given language and UE project name.
    This does not retain any existing data from that po file.
    """
    localization_root = _get_localization_root(project_root)
    language_loca_root = os.path.join(
        localization_root, target, language)
    po_path = os.path.normpath(
        os.path.join(language_loca_root, f"{target}.po"))
    print(f"Writing po file to {po_path}")
    CSVEntryWithMetaData.write_po_file(
        entries=new_lines_dict, po_file_path=po_path, target=target, language=language)


def run_gather_commandlet(env: UnrealEnvironment, loc_project: str, commands=["Gather", "Export"]):
    assert env
    configs_str = ";".join(
        [f"{env.project_root}/Config/Localization/{loc_project}_{command}.ini" for command in commands])
    ue = UnrealEngine(env)
    ue.run_commandlet("GatherText", arguments=[f"-config=\"{configs_str}\""])
