"""Main entry point for the murid application."""

import logging
import sys

import argcomplete

from . import __version__
from .args import MuridArgumentParser
from .clients.calibre import CalibreError
from .clients.hardcover import HardcoverError
from .clients.myanonamouse import MAMError, MAMSearchError
from .clients.torrent_clients.qbittorrent import QbittorrentError
from .commands import run_command
from .config.config import ConfigError
from .logging_config import setup_logger
from .ui import colored, setup_output

logger = logging.getLogger("murid")


def main() -> int:
    """Run the CLI, treating Ctrl-C as a quiet cancellation."""
    try:
        return _main()
    except KeyboardInterrupt:
        return 130


def _main() -> int:
    """Main entry point for the application.

    Sets up logging, parses command-line arguments, and runs the main application logic.
    """
    description = (
        "Murid keeps your Calibre library in sync with your Hardcover reading list. "
        "It finds missing books through MyAnonamouse, supports scheduled runs, "
        "and can review book matches without downloading anything."
    )
    parser = MuridArgumentParser(description)
    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    setup_logger(
        getattr(args, "log_level", "WARNING"),
        include_date=args.command == "schedule",
        color=not getattr(args, "no_color", False),
        output_format=getattr(args, "output_format", "auto"),
    )
    setup_output(
        color=not getattr(args, "no_color", False),
        output_format=getattr(args, "output_format", "auto"),
    )

    logger.info(
        colored(
            r"""
     ) _     _
    ( (^)-~-(^)
__,-.\_( 6 6 )__,-.___
| 'M'   \   /   'M'  |
|        >o<         |
    ______/\______
   /              \
  / starting murid \
  \VERSION/
   \______________/
""".replace("VERSION", f"v{__version__}".center(16)),
            "cyan",
        ),
    )

    try:
        return run_command(args)

    except MAMSearchError as error:
        logger.error("%s", error)
        return 1
    except (
        CalibreError,
        HardcoverError,
        MAMError,
        QbittorrentError,
        ConfigError,
        OSError,
    ) as error:
        logger.error("%s", error, exc_info=logger.isEnabledFor(logging.DEBUG))
        return 1
    except Exception as error:  # pylint: disable=broad-exception-caught
        logger.error("Unexpected error: %s", error, exc_info=logger.isEnabledFor(logging.DEBUG))
        return 1


if __name__ == "__main__":
    sys.exit(main())
