import argparse
import logging

from rich.logging import RichHandler
from rich_argparse import RichHelpFormatter

from . import __version__
from .harvester import HardcoverHarvesterApp

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
    arg_parser.add_argument(
        "--dry-run",
        "-d",
        help="see what will be downloaded without actually downloading",
        action="store_true",
        dest="dry_run",
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

    app = HardcoverHarvesterApp(args)
    app.run()


if __name__ == "__main__":
    main()
