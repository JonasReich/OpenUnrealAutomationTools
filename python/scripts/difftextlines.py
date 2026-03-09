"""This script compares two text files by parsing each file into a set of lines and then reporting the differences in patch format."""

import argparse

import openunrealautomation.util as oua_util

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("file1", help="Path to the first text file")
parser.add_argument("file2", help="Path to the second text file")
args = parser.parse_args()

line_set1 = set()
line_set2 = set()
with open(args.file1, 'r') as f1:
    for line in f1:
        line_set1.add(line.rstrip('\n'))
with open(args.file2, 'r') as f2:
    for line in f2:
        line_set2.add(line.rstrip('\n'))
only_in_file1 = line_set1 - line_set2
only_in_file2 = line_set2 - line_set1

for line in sorted(only_in_file1):
    print(f"-{line}")
for line in sorted(only_in_file2):
    print(f"+{line}")
