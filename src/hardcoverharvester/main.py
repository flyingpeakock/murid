#!/usr/bin/env python3

import argparse
import logging

from rich.logging import RichHandler
from rich_argparse import RichHelpFormatter

from . import __version__
from .calibre import Calibre, CalibreError
from .config import Config, ConfigError
from .hardcover import Hardcover

logger = logging.getLogger("HardcoverHarvester")


def setupLogger(logLevel: str) -> None:
    logger.setLevel(logLevel)
    logger.addHandler(RichHandler(rich_tracebacks=True, tracebacks_show_locals=True))


def getArgParser(description: str) -> argparse.ArgumentParser:
    arg_parser = argparse.ArgumentParser(description=description, formatter_class=RichHelpFormatter)
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
        type=str,
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
        with open(args.config_file, "r") as f:
            config = Config(f)
    except ConfigError as e:
        logger.error(f"Error loading config: {e}")
        raise SystemExit(1) from e
    except FileNotFoundError as e:
        logger.error(f"Config file not found: {args.config_file}")
        raise SystemExit(1) from e
    except Exception as e:
        logger.error(f"Unexpected error loading config: {e}")
        raise SystemExit(1) from e

    try:
        calibre = Calibre(config.get("calibre_db_path"))
    except CalibreError as e:
        logger.error(f"Error initializing Calibre: {e}")
        raise SystemExit(1) from e

    calibreBooks = calibre.get_books()
    count = len(calibreBooks)
    logger.info(
        f"Fetched {count} book{'s' if count != 1 else ''} from Calibre database"
    )

    hardcoverObjects = []
    hardcoverBooks = []
    for user in config.get("users"):
        logger.debug(f"Processing user_id: {user['id']}")
        hardcoverObjects.append(Hardcover(user["api_key"], user["id"]))
        hardcoverBooks.extend(hardcoverObjects[-1].get_books())
    count = len(hardcoverBooks)
    logger.info(
        f"Fetched {count} book{'s' if count != 1 else ''} from Hardcover API"
    )
    logger.debug(f"Hardcover books: {hardcoverBooks}")

    return 0


if __name__ == "__main__":
    main()
