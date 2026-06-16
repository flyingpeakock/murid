import argparse
import logging
import sys

import apprise
from rich.logging import RichHandler
from rich_argparse import RichHelpFormatter

from . import __version__
from .hardcoverHarvesterApp import HardcoverHarvesterApp

logger = logging.getLogger("HardcoverHarvester")


class AppriseHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        if record.levelno >= logging.ERROR:
            apprise.notify(
                body=record.getMessage(),
                title=f"HardcoverHarvester - {record.levelname}",
                severity=apprise.NotifySeverity.ERROR,
            )


def setupLogger(logLevel: str) -> None:
    logger.setLevel(logLevel)

    if sys.stderr.isatty():
        logger.addHandler(RichHandler(rich_tracebacks=True, tracebacks_show_locals=True))
    else:
        logger.addHandler(logging.StreamHandler())


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
        "--dry-run",
        "-d",
        help="see what will be downloaded without actually downloading",
        action="store_true",
        dest="dry_run",
    )
    arg_parser.add_argument(
        "--run-once",
        "-r",
        help="run the harvester once and then exit (no scheduler)",
        action="store_true",
        dest="run_once",
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
        default="config.yaml",
        dest="config_file",
        type=str,
        required=True,
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
    if args.test_notification:
        app.test_notification()
        return

    try:
        if args.run_once:
            app.run()
        else:
            app.start_scheduler()
    except Exception as e:
        logger.exception(f"An error occurred: {e}")
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
