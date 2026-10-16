"""Main entry point for the murid application."""

import logging
import sys

import argcomplete

from . import __version__
from .args import MuridArgumentParser
from .commands import run_command
from .logging_config import setup_logger

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
        getattr(args, "log_level", "ERROR"),
        include_date=args.command == "schedule",
    )

    logger.info(
        r"""
     ) _     _
    ( (^)-~-(^)
__,-.\_( 6 6 )__,-.___
| 'M'   \   /   'M'  |
|        >o<         |
    ______/\______
   /              \
  / starting murid \
  \%s/
   \______________/
""",
        f"v{__version__}".center(16),
    )

    try:
        return run_command(args)

    except Exception as e:
        logger.error("An error occurred: %r", e)
        raise e


if __name__ == "__main__":
    sys.exit(main())
