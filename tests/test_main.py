import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from murid.main import (
    get_arg_parser,
    get_default_config_path,
    logger,
    main,
    setup_logger,
)


def test_default_config_path_linux(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/config")

    assert get_default_config_path() == Path("/tmp/config/murid/config.yaml")


def test_default_config_path_linux_fallback(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: Path("/home/test"))

    assert get_default_config_path() == Path("/home/test/.config/murid/config.yaml")


def test_default_config_path_macos(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr(Path, "home", lambda: Path("/Users/test"))

    assert get_default_config_path() == Path(
        "/Users/test/Library/Application Support/murid/config.yaml"
    )


def test_default_config_path_windows(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setenv("APPDATA", r"C:\Users\Test\AppData\Roaming")

    path = get_default_config_path()

    assert str(path).endswith("murid/config.yaml")
    assert "Roaming" in str(path)


def test_default_config_path_unsupported(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Plan9")

    with pytest.raises(RuntimeError):
        get_default_config_path()


def test_setup_logger_tty(monkeypatch):
    logger.handlers.clear()

    monkeypatch.setattr("sys.stderr.isatty", lambda: True)

    setup_logger("DEBUG")

    assert logger.level == logging.DEBUG
    assert len(logger.handlers) == 1


def test_setup_logger_non_tty(monkeypatch):
    logger.handlers.clear()

    monkeypatch.setattr("sys.stderr.isatty", lambda: False)

    setup_logger("INFO")

    assert logger.level == logging.INFO
    assert len(logger.handlers) == 1


def test_arg_parser_defaults():
    parser = get_arg_parser("test")

    args = parser.parse_args([])

    assert args.log_level == "INFO"
    assert args.dry_run is False
    assert args.schedule is False
    assert args.test_notification is False


def test_arg_parser_flags():
    parser = get_arg_parser("test")

    args = parser.parse_args(
        [
            "--log-level",
            "DEBUG",
            "--dry-run",
            "--schedule",
            "--test-notification",
            "--config",
            "/tmp/config.yaml",
        ]
    )

    assert args.log_level == "DEBUG"
    assert args.dry_run is True
    assert args.schedule is True
    assert args.test_notification is True
    assert args.config_file == "/tmp/config.yaml"


def test_main_runs_app(monkeypatch):
    app = SimpleNamespace(
        run=lambda: setattr(app, "ran", True),
        start_scheduler=lambda: None,
        ran=False,
    )

    factory = SimpleNamespace(
        sync_service=lambda: app,
    )

    monkeypatch.setattr(
        "murid.main.ServiceFactory",
        lambda args: factory,
    )

    monkeypatch.setattr(
        "murid.main.get_arg_parser",
        lambda _: SimpleNamespace(
            parse_args=lambda: SimpleNamespace(
                log_level="INFO",
                dry_run=False,
                schedule=False,
                test_notification=False,
            )
        ),
    )

    monkeypatch.setattr("murid.main.setup_logger", lambda *_: None)

    main()

    assert app.ran


def test_main_runs_scheduler(monkeypatch):
    app = SimpleNamespace(
        run=lambda: None,
        started=False,
    )

    def start_scheduler():
        app.started = True

    app.start_scheduler = start_scheduler

    factory = SimpleNamespace(
        sync_service=lambda: app,
    )

    monkeypatch.setattr(
        "murid.main.ServiceFactory",
        lambda args: factory,
    )

    monkeypatch.setattr(
        "murid.main.get_arg_parser",
        lambda _: SimpleNamespace(
            parse_args=lambda: SimpleNamespace(
                log_level="INFO",
                dry_run=False,
                schedule=True,
                test_notification=False,
            )
        ),
    )

    monkeypatch.setattr("murid.main.setup_logger", lambda *_: None)

    main()

    assert app.started


def test_main_test_notification(monkeypatch):
    called = {}

    app = SimpleNamespace(
        run=lambda: pytest.fail("should not run"),
        start_scheduler=lambda: pytest.fail("should not schedule"),
    )

    factory = SimpleNamespace(
        sync_service=lambda: app,
        notifier=lambda: "notifier",
    )

    monkeypatch.setattr(
        "murid.main.ServiceFactory",
        lambda args: factory,
    )

    monkeypatch.setattr(
        "murid.main.test_notification",
        lambda notifier: called.setdefault(
            "notifier",
            notifier,
        ),
    )

    monkeypatch.setattr(
        "murid.main.get_arg_parser",
        lambda _: SimpleNamespace(
            parse_args=lambda: SimpleNamespace(
                log_level="INFO",
                dry_run=False,
                schedule=False,
                test_notification=True,
            )
        ),
    )

    monkeypatch.setattr("murid.main.setup_logger", lambda *_: None)

    main()

    assert called["notifier"] == "notifier"


def test_main_exits_on_exception(monkeypatch):
    app = SimpleNamespace(
        run=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        start_scheduler=lambda: None,
    )

    factory = SimpleNamespace(
        sync_service=lambda: app,
    )

    monkeypatch.setattr(
        "murid.main.ServiceFactory",
        lambda args: factory,
    )

    monkeypatch.setattr(
        "murid.main.get_arg_parser",
        lambda _: SimpleNamespace(
            parse_args=lambda: SimpleNamespace(
                log_level="INFO",
                dry_run=False,
                schedule=False,
                test_notification=False,
            )
        ),
    )

    monkeypatch.setattr("murid.main.setup_logger", lambda *_: None)

    with pytest.raises(SystemExit):
        main()
