"""Configure logging for the command-line application."""

import json
import logging
import os
import sys

from rich.console import Console
from rich.logging import RichHandler
from rich.text import Text

logger = logging.getLogger("murid")

_JOURNAL_PRIORITIES = {
    logging.DEBUG: 7,
    logging.INFO: 6,
    logging.WARNING: 4,
    logging.ERROR: 3,
    logging.CRITICAL: 2,
}


def journal_message(message: str, level: int) -> str:
    """Prefix every journal stream line, including exception continuation lines."""
    priority = _JOURNAL_PRIORITIES.get(level, 3)
    # journald splits stream messages at newlines and NULs, resetting priority each time.
    return "\n".join(f"<{priority}>{line}" for line in message.replace("\0", "\n").split("\n"))


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

    def __init__(self, fmt: str = "%(message)s", *, formatter: logging.Formatter | None = None):
        super().__init__(fmt)
        self.message_formatter = formatter

    def format(self, record: logging.LogRecord) -> str:
        """Preserve the record's priority across plain text and JSON formatting."""
        message = (
            self.message_formatter.format(record)
            if self.message_formatter
            else super().format(record)
        )
        return journal_message(message, record.levelno)


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
        if is_journal_stream(sys.stderr):
            # systemd strips this prefix and records the appropriate PRIORITY field.
            # It supplies the timestamp itself, so do not duplicate one in the message.
            handler.setFormatter(
                JournalFormatter(formatter=JsonLogFormatter() if output_format == "json" else None)
            )
        elif output_format == "json":
            handler.setFormatter(JsonLogFormatter())
        else:
            handler.setFormatter(
                logging.Formatter(
                    "[%(asctime)s] [%(levelname)s] %(message)s",
                    datefmt="%Y-%m-%dT%H:%M:%S%z",
                )
            )
        logger.addHandler(handler)
