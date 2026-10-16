import logging

from rich.logging import RichHandler

from murid.logging_config import logger, setup_logger


def test_setup_logger_tty(monkeypatch):
    logger.handlers.clear()
    monkeypatch.setattr("sys.stderr.isatty", lambda: True)

    setup_logger("DEBUG")

    assert logger.level == logging.DEBUG
    assert len(logger.handlers) == 1
    assert isinstance(logger.handlers[0], RichHandler)
    assert logger.handlers[0]._log_render.time_format == "[%X]"


def test_setup_logger_tty_with_date(monkeypatch):
    logger.handlers.clear()
    monkeypatch.setattr("sys.stderr.isatty", lambda: True)

    setup_logger("DEBUG", include_date=True)

    assert isinstance(logger.handlers[0], RichHandler)
    assert logger.handlers[0]._log_render.time_format == "[%x %X]"


def test_setup_logger_non_tty(monkeypatch):
    logger.handlers.clear()
    monkeypatch.setattr("sys.stderr.isatty", lambda: False)

    setup_logger("INFO")

    assert logger.level == logging.INFO
    assert len(logger.handlers) == 1
