"""Configure logging for the command-line application."""

import json
import logging
import os
import sys

from rich.console import Console
from rich.logging import RichHandler
from rich.text import Text

logger = logging.getLogger("murid")


class BookRichHandler(RichHandler):
    """Style known book arguments without guessing where titles or authors end."""

    def render_message(self, record: logging.LogRecord, message: str) -> Text:
        if isinstance(record.msg, Text):
            return record.msg.copy()
        text = Text(message)
        if isinstance(record.args, tuple) and record.args:
            book = record.args[0]
            prefix = f"{book}: "
            if hasattr(book, "title") and hasattr(book, "authors") and message.startswith(prefix):
                text.stylize("bold cyan", 0, len(prefix) - 2)
                if message[len(prefix) :].startswith(("imported", "added to", "already in")):
                    text.stylize("green", len(prefix), len(message))
        if record.levelno >= logging.ERROR:
            text.stylize("red")
        elif record.levelno >= logging.WARNING:
            text.stylize("yellow")
        return text


class JsonLogFormatter(logging.Formatter):
    """One JSON object per log record, on stderr."""

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "type": "log",
            "level": record.levelname.lower(),
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


class JournalFormatter(logging.Formatter):
    """Format records for systemd's journal stream parser."""

    _priority_by_level = {
        logging.DEBUG: 7,
        logging.INFO: 6,
        logging.WARNING: 4,
        logging.ERROR: 3,
        logging.CRITICAL: 2,
    }

    def format(self, record: logging.LogRecord) -> str:
        """Prefix the message with the syslog priority understood by journald."""
        priority = self._priority_by_level.get(record.levelno, 3)
        return f"<{priority}>{super().format(record)}"


def is_journal_stream(stream) -> bool:
    """Return whether *stream* is the journald stream assigned by systemd."""
    journal_stream = os.getenv("JOURNAL_STREAM")
    if not journal_stream:
        return False

    try:
        device, inode = (int(value) for value in journal_stream.split(":", maxsplit=1))
        stat = os.fstat(stream.fileno())
    except (OSError, ValueError):
        return False

    return (stat.st_dev, stat.st_ino) == (device, inode)


def setup_logger(
    log_level: str, *, include_date: bool = False, color: bool = True, output_format: str = "auto"
) -> None:
    """Set up the logger with the specified level and timestamp detail."""
    logging.disable(logging.NOTSET)
    logger.handlers.clear()
    logger.setLevel(log_level)

    if sys.stderr.isatty() and output_format == "auto":
        logger.addHandler(
            BookRichHandler(
                console=Console(stderr=True, no_color=True if not color else None),
                highlighter=None,
                rich_tracebacks=True,
                tracebacks_show_locals=False,
                show_path=False,
                log_time_format="[%x %X]" if include_date else "[%X]",
            )
        )
    else:
        handler = logging.StreamHandler()
        if output_format == "json":
            handler.setFormatter(JsonLogFormatter())
        elif is_journal_stream(sys.stderr):
            # systemd strips this prefix and records the appropriate PRIORITY field.
            # It supplies the timestamp itself, so do not duplicate one in the message.
            handler.setFormatter(JournalFormatter("%(message)s"))
        else:
            handler.setFormatter(
                logging.Formatter(
                    "[%(asctime)s] [%(levelname)s] %(message)s",
                    datefmt="%Y-%m-%dT%H:%M:%S%z",
                )
            )
        logger.addHandler(handler)
