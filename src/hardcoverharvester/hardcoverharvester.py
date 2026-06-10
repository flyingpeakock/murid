#!/usr/bin/env python3

from . import __version__
import argparse
from rich_argparse import RichHelpFormatter


def getArgParser(description: str) -> argparse.ArgumentParser:
    arg_parser = argparse.ArgumentParser(
        description=description, formatter_class=RichHelpFormatter
    )
    arg_parser.add_argument("--version", "-v", action="version", version=__version__)


def main() -> None:
    description = """
Fetch books from Hardcover API and search for them in MyAnonamous.
Downloads are sent to qBittorrent and then added to Calibre.
"""
    arg_parser = getArgParser(description)
    args = arg_parser.parse_args()

if __name__ == "__main__":
    main()
