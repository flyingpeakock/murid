#!/usr/bin/env python3

from . import __version__
from .hardcover import Hardcover
from .config import Config

import argparse
import logging
import yaml
from rich_argparse import RichHelpFormatter
from rich.logging import RichHandler

logger = logging.getLogger("HardcoverHarvester")


def setupLogger(logLevel: str) -> None:
    FORMAT = "%(message)s"
    logger.setLevel(logLevel)
    logger.addHandler(RichHandler(rich_tracebacks=True, tracebacks_show_locals=True))


def getArgParser(description: str) -> argparse.ArgumentParser:
    arg_parser = argparse.ArgumentParser(
        description=description, formatter_class=RichHelpFormatter
    )
    arg_parser.add_argument("--version", "-v", action="version", version=__version__)
    arg_parser.add_argument(
        "--log-level",
        "-l",
        help="logging level",
        default="INFO",
        dest="log_level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )
    arg_parser.add_argument(
        "--config",
        "-c",
        help="path to config file",
        default="config.yaml",
        dest="config_file",
        type=argparse.FileType("r"),
    )

    return arg_parser


def main() -> None:
    description = """
Fetch books from Hardcover API and search for them in MyAnonamous.
Downloads are sent to qBittorrent and then added to Calibre.
"""
    args = getArgParser(description).parse_args()
    setupLogger(args.log_level)

    logger.info(f"Starting HardcoverHarvester v{__version__}")

    try:
        config = Config(args.config_file)
    except ConfigError as e:
        logger.error(f"Error loading config: {e}")
        return

    books = []
    for user in config.get("users"):
        logger.debug(f"Processing user_id: {user['id']}")
        hardcover = Hardcover(user["api_key"], user["id"])
        books.extend(hardcover.get_books())
    logger.info(
        f"Fetched {len(books)} book{'s' if len(books) != 1 else ''} from Hardcover API"
    )


if __name__ == "__main__":
    main()
