import argparse
import logging
import os
import platform
import sys
from pathlib import Path

from rich.logging import RichHandler
from rich_argparse import ArgumentDefaultsRichHelpFormatter

from . import __version__
from .muridApp import MuridApp

logger = logging.getLogger("murid")


def get_default_config_path() -> Path:
    app_name = "murid"
    file_name = "config.yaml"

    match platform.system():
        case "Linux":
            config_home = os.getenv("XDG_CONFIG_HOME") or str(Path.home() / ".config")
            return Path(config_home) / app_name / file_name

        case "Darwin":
            return Path.home() / "Library" / "Application Support" / app_name / file_name

        case "Windows":
            appdata = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
            return Path(appdata) / app_name / file_name

        case _:
            raise RuntimeError(f"Unsupported operating system: {platform.system()}")


def setupLogger(logLevel: str) -> None:
    logger.setLevel(logLevel)

    if sys.stderr.isatty():
        logger.addHandler(RichHandler(rich_tracebacks=True, tracebacks_show_locals=True))
    else:
        logger.addHandler(logging.StreamHandler())


def getArgParser(description: str) -> argparse.ArgumentParser:
    arg_parser = argparse.ArgumentParser(
        description=description, formatter_class=ArgumentDefaultsRichHelpFormatter
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
        "--dry-run",
        "-d",
        help="see what will be downloaded without actually downloading",
        action="store_true",
        dest="dry_run",
    )
    arg_parser.add_argument(
        "--schedule",
        "-s",
        help="run murid on a schedule",
        action="store_true",
        dest="schedule",
    )
    arg_parser.add_argument(
        "--test-notification",
        help="send a test notification and then exit",
        action="store_true",
        dest="test_notification",
    )
    arg_parser.add_argument(
        "--config",
        "-c",
        help="path to config file",
        default=get_default_config_path(),
        dest="config_file",
        type=str,
    )

    return arg_parser


def main() -> None:
    description = """
Murid automatically keeps your Calibre library in sync with your
reading list on Hardcover, with help from myAnonamouse.
"""
    args = getArgParser(description).parse_args()
    setupLogger(args.log_level)

    logger.info(f"Starting murid v{__version__}")

    app = MuridApp(args)
    if args.test_notification:
        app.test_notification()
        return

    try:
        if args.schedule:
            app.start_scheduler()
        else:
            app.run()
    except Exception as e:
        logger.exception(f"An error occurred: {e}")
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
