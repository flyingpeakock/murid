import logging
from types import SimpleNamespace

import pytest

from murid.main import main


@pytest.mark.parametrize(
    "command", [["status"], ["list-missing"], ["add-book", "Book", "book.epub"]]
)
def test_inspection_commands_report_missing_config(monkeypatch, capsys, tmp_path, command):
    config_file = str(tmp_path / "nonexistent.yaml")
    monkeypatch.setattr("sys.argv", ["murid", *command, "--config", config_file])
    logger = logging.getLogger("murid")
    monkeypatch.setattr(logger, "handlers", [])
    monkeypatch.setattr(logger, "level", logger.level)

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "[ERROR] Config file not found:" in captured.err
    assert config_file in captured.err
    assert "starting murid" not in captured.err
    assert captured.out == ""


@pytest.mark.parametrize("command", ["run", "schedule"])
def test_main_dispatches_command(monkeypatch, command):
    args = SimpleNamespace(command=command, log_level="INFO")
    calls = []
    monkeypatch.setattr(
        "murid.main.MuridArgumentParser",
        lambda _: SimpleNamespace(parse_args=lambda: args),
    )
    monkeypatch.setattr("murid.main.setup_logger", lambda level: calls.append(("log", level)))
    monkeypatch.setattr("murid.main.run_command", lambda parsed: calls.append(("run", parsed)) or 0)

    assert main() == 0
    assert calls == [("log", "INFO"), ("run", args)]


def test_main_exits_on_exception(monkeypatch):
    args = SimpleNamespace(command="run", log_level="INFO")
    monkeypatch.setattr(
        "murid.main.MuridArgumentParser",
        lambda _: SimpleNamespace(parse_args=lambda: args),
    )
    monkeypatch.setattr("murid.main.setup_logger", lambda *_: None)

    def fail(_):
        raise RuntimeError("boom")

    monkeypatch.setattr("murid.main.run_command", fail)

    with pytest.raises(RuntimeError, match="boom"):
        main()


@pytest.mark.parametrize("phase", ["parse", "command"])
def test_keyboard_interrupt_exits_quietly(monkeypatch, capsys, caplog, phase):
    def interrupt(*_):
        raise KeyboardInterrupt

    args = SimpleNamespace(command="schedule")
    monkeypatch.setattr(
        "murid.main.MuridArgumentParser",
        lambda _: SimpleNamespace(parse_args=interrupt if phase == "parse" else lambda: args),
    )
    monkeypatch.setattr("murid.main.setup_logger", lambda _: None)
    monkeypatch.setattr("murid.main.run_command", interrupt)
    assert main() == 130
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "KeyboardInterrupt" not in caplog.text
    assert not any(record.exc_info for record in caplog.records)
