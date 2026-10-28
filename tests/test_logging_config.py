import io
import json
import logging
import os
import sys
from types import SimpleNamespace

import pytest
from rich.logging import RichHandler

from murid.logging_config import (
    BookRichHandler,
    JournalFormatter,
    JsonLogFormatter,
    is_journal_stream,
    logger,
    setup_logger,
)


def test_setup_logger_tty(monkeypatch):
    logger.handlers.clear()
    monkeypatch.setattr("sys.stderr.isatty", lambda: True)

    setup_logger("DEBUG")

    assert logger.level == logging.DEBUG
    assert len(logger.handlers) == 1
    assert isinstance(logger.handlers[0], RichHandler)
    assert isinstance(logger.handlers[0], BookRichHandler)
    assert logger.handlers[0].console.stderr
    assert logger.handlers[0]._log_render.time_format == "[%X]"


def test_setup_logger_tty_with_date(monkeypatch):
    logger.handlers.clear()
    monkeypatch.setattr("sys.stderr.isatty", lambda: True)

    setup_logger("DEBUG", include_date=True)

    assert isinstance(logger.handlers[0], RichHandler)
    assert logger.handlers[0]._log_render.time_format == "[%x %X]"


def test_setup_logger_tty_without_color(monkeypatch):
    logger.handlers.clear()
    monkeypatch.setattr("sys.stderr.isatty", lambda: True)

    setup_logger("DEBUG", color=False)

    assert logger.handlers[0].console.no_color


def test_book_log_handler_uses_full_book_argument():
    from murid.domain.book import Book

    book = Book("Dune: Messiah", ["Author: Jr."], 1, [], "test")
    record = logging.LogRecord(
        "murid", logging.INFO, "", 0, "%s: selected torrent: freeleech", (book,), None
    )
    text = BookRichHandler().render_message(record, record.getMessage())
    assert [(span.start, span.end, str(span.style)) for span in text.spans] == [
        (0, len(str(book)), "bold green"),
    ]


def test_log_handler_colors_generic_info_messages():
    record = logging.LogRecord("murid", logging.INFO, "", 0, "Searching for books", (), None)
    text = BookRichHandler().render_message(record, record.getMessage())

    assert not text.spans


def test_setup_logger_non_tty(monkeypatch):
    logger.handlers.clear()
    monkeypatch.setattr("sys.stderr.isatty", lambda: False)
    monkeypatch.setattr("murid.logging_config.is_journal_stream", lambda _: False)

    setup_logger("INFO")

    assert logger.level == logging.INFO
    assert len(logger.handlers) == 1
    assert logger.handlers[0].formatter._fmt == "[%(asctime)s] [%(levelname)s] %(message)s"


def test_setup_logger_uses_journal_formatter_for_systemd_stream(monkeypatch):
    logger.handlers.clear()
    monkeypatch.setattr("sys.stderr.isatty", lambda: False)
    monkeypatch.setattr("murid.logging_config.is_journal_stream", lambda _: True)

    setup_logger("INFO")

    assert isinstance(logger.handlers[0].formatter, JournalFormatter)


def test_is_journal_stream_matches_device_and_inode(monkeypatch):
    stream = SimpleNamespace(fileno=lambda: 2)
    monkeypatch.setenv("JOURNAL_STREAM", "123:456")
    monkeypatch.setattr(
        "murid.logging_config.os",
        SimpleNamespace(
            getenv=os.getenv,
            fstat=lambda _: SimpleNamespace(st_dev=123, st_ino=456),
        ),
    )

    assert is_journal_stream(stream)


def test_is_journal_stream_rejects_missing_or_mismatched_metadata(monkeypatch):
    stream = SimpleNamespace(fileno=lambda: 2)
    monkeypatch.delenv("JOURNAL_STREAM", raising=False)
    assert not is_journal_stream(stream)

    monkeypatch.setenv("JOURNAL_STREAM", "123:456")
    monkeypatch.setattr(
        "murid.logging_config.os",
        SimpleNamespace(
            getenv=os.getenv,
            fstat=lambda _: SimpleNamespace(st_dev=123, st_ino=789),
        ),
    )
    assert not is_journal_stream(stream)


def test_journal_formatter_uses_syslog_priority_prefix():
    formatter = JournalFormatter("%(message)s")

    records = [
        (logging.DEBUG, "debug", "<7>debug"),
        (logging.INFO, "info", "<6>info"),
        (logging.WARNING, "warning", "<4>warning"),
        (logging.ERROR, "error", "<3>error"),
    ]

    for level, message, expected in records:
        record = logging.LogRecord("murid", level, "", 0, message, (), None)
        assert formatter.format(record) == expected


@pytest.mark.parametrize(
    ("level", "priority"),
    [
        (logging.DEBUG, 7),
        (logging.INFO, 6),
        (logging.WARNING, 4),
        (logging.ERROR, 3),
        (logging.CRITICAL, 2),
    ],
)
def test_journal_formatter_preserves_priority_on_every_line(level, priority):
    record = logging.LogRecord("murid", level, "", 0, "first\nsecond\0<0>third", (), None)
    assert JournalFormatter().format(record) == (
        f"<{priority}>first\n<{priority}>second\n<{priority}><0>third"
    )


def test_journal_exception_lines_keep_error_priority():
    try:
        raise ValueError("first\nsecond")
    except ValueError:
        record = logging.LogRecord("murid", logging.ERROR, "", 0, "failed", (), sys.exc_info())
    lines = JournalFormatter().format(record).splitlines()
    assert len(lines) > 3
    assert all(line.startswith("<3>") for line in lines)
    assert lines[-1] == "<3>second"


@pytest.mark.parametrize(
    ("level", "priority"),
    [
        (logging.DEBUG, 7),
        (logging.INFO, 6),
        (logging.WARNING, 4),
        (logging.ERROR, 3),
        (logging.CRITICAL, 2),
    ],
)
def test_json_logs_keep_journal_priority(monkeypatch, level, priority):
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    monkeypatch.setattr(logger, "handlers", [])
    monkeypatch.setattr(logger, "level", logging.WARNING)
    monkeypatch.setattr("murid.logging_config.is_journal_stream", lambda _: True)
    setup_logger("DEBUG", output_format="json")
    logger.log(level, "first\nsecond")
    serialized = stream.getvalue()
    assert serialized.startswith(f"<{priority}>")
    assert len(serialized.splitlines()) == 1
    record = json.loads(serialized[3:])
    assert record["level"] == logging.getLevelName(level).lower()
    assert record["message"] == "first\nsecond"


def test_redirected_json_logs_have_no_journal_prefix(monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    monkeypatch.setattr(logger, "handlers", [])
    monkeypatch.setattr(logger, "level", logging.WARNING)
    monkeypatch.setattr("murid.logging_config.is_journal_stream", lambda _: False)
    setup_logger("INFO", output_format="json")
    logger.error("failed")
    assert json.loads(stream.getvalue())["level"] == "error"
    assert isinstance(logger.handlers[0].formatter, JsonLogFormatter)
