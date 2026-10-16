"""Configure logging for the command-line application."""

import logging
import sys

from rich.logging import RichHandler

logger = logging.getLogger("murid")


def setup_logger(log_level: str, *, include_date: bool = False) -> None:
    """Set up the logger with the specified level and timestamp detail."""
    logging.disable(logging.NOTSET)
    logger.handlers.clear()
    logger.setLevel(log_level)

    if sys.stderr.isatty():
        logger.addHandler(
            RichHandler(
                rich_tracebacks=True,
                tracebacks_show_locals=True,
                show_path=False,
                log_time_format="[%x %X]" if include_date else "[%X]",
            )
        )
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        logger.addHandler(handler)
