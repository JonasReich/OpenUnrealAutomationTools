"""
Pack and unpack zip files.
Must not have any dependencies on other modules!
"""

import argparse
import shutil

if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument("mode", help="Mode of the archiving operation. Either 'pack' or 'unpack'.")
    argparser.add_argument("dir", help="Directory that is archived from/to.")
    argparser.add_argument("archive", help="Path to the zip file (excluding '.zip' extension).")
    args = argparser.parse_args()
    if args.mode == "unpack":
        shutil.unpack_archive(filename=args.archive, extract_dir=args.dir, format="zip")
    elif args.mode == "pack":
        shutil.make_archive(base_name=args.archive, format="zip", root_dir=args.dir)
    else:
        raise argparse.ArgumentError("Invalid argument value for parameter 'mode'. Only valid options are 'unpack' and 'pack'.")
