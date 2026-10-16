from types import SimpleNamespace

import pytest

from murid.clients.hardcover import HardcoverError
from murid.commands import run_command


@pytest.mark.parametrize(("command", "method"), [("run", "run"), ("schedule", "start_scheduler")])
def test_runs_sync_command(monkeypatch, command, method):
    args = SimpleNamespace(command=command)
    calls = []
    sync_service = SimpleNamespace(
        run=lambda: calls.append("run"),
        start_scheduler=lambda: calls.append("start_scheduler"),
    )
    monkeypatch.setattr(
        "murid.commands.ServiceFactory",
        lambda parsed: SimpleNamespace(sync_service=lambda: sync_service),
    )

    assert run_command(args) == 0
    assert calls == [method]


def test_adds_book(monkeypatch, capsys):
    args = SimpleNamespace(command="add-book", name="Dune", path="/tmp/dune.epub")
    factory = object()
    calls = []
    monkeypatch.setattr("murid.commands.ServiceFactory", lambda parsed: factory)
    monkeypatch.setattr(
        "murid.commands.add_book", lambda *values: calls.append(values) or "Dune by Frank Herbert"
    )

    assert run_command(args) == 0
    assert calls == [("Dune", "/tmp/dune.epub", factory)]
    assert "Added Dune by Frank Herbert to Calibre" in capsys.readouterr().out


def test_shows_status(monkeypatch):
    args = SimpleNamespace(command="status")
    torrent_client = object()
    calls = []
    monkeypatch.setattr(
        "murid.commands.ServiceFactory",
        lambda parsed: SimpleNamespace(qbittorrent=lambda: torrent_client),
    )
    monkeypatch.setattr("murid.commands.print_status", calls.append)

    assert run_command(args) == 0
    assert calls == [torrent_client]


def test_searches_book(monkeypatch):
    args = SimpleNamespace(command="search-book", name="Dune", add=True)
    factory = object()
    calls = []
    monkeypatch.setattr("murid.commands.ServiceFactory", lambda parsed: factory)
    monkeypatch.setattr(
        "murid.commands.search_book", lambda *values, **kwargs: calls.append((values, kwargs))
    )

    assert run_command(args) == 0
    assert calls == [(("Dune", factory), {"add": True})]


def test_retries_imports(monkeypatch, capsys):
    result = SimpleNamespace(imported=1, already_present=0, pending=1, failed=0, skipped=0)
    retry_service = SimpleNamespace(retry_imports=lambda: result)
    args = SimpleNamespace(command="retry-import")
    monkeypatch.setattr(
        "murid.commands.ServiceFactory",
        lambda parsed: SimpleNamespace(retry_service=lambda: retry_service),
    )

    assert run_command(args) == 1
    assert "1 imported" in capsys.readouterr().out


def test_tests_connections(monkeypatch):
    args = SimpleNamespace(command="test-connection")
    factory = object()
    calls = []
    monkeypatch.setattr("murid.commands.ServiceFactory", lambda parsed, **kwargs: factory)
    monkeypatch.setattr(
        "murid.commands.check_connections", lambda created: calls.append(created) or False
    )

    assert run_command(args) == 1
    assert calls == [factory]


def test_sends_test_notification(monkeypatch):
    args = SimpleNamespace(command="test-notification")
    calls = []
    monkeypatch.setattr(
        "murid.commands.ServiceFactory",
        lambda parsed: SimpleNamespace(
            config={"apprise": {"urls": ["test"]}}, notifier=lambda: "notifier"
        ),
    )
    monkeypatch.setattr(
        "murid.commands.send_test_notification", lambda notify: calls.append(notify) or True
    )

    assert run_command(args) == 0
    assert calls == ["notifier"]


def test_validate_config_reports_missing_file(capsys, tmp_path):
    args = SimpleNamespace(command="validate-config", config_file=str(tmp_path / "missing.yaml"))

    assert run_command(args) == 1
    assert "Configuration file not found" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("list-missing", ("list_missing", None)),
        ("review-matches", ("review_matches", False)),
    ],
)
def test_inspection_commands(monkeypatch, command, expected):
    calls = []
    matcher = object()
    service = SimpleNamespace(
        list_missing=lambda value: calls.append(("list_missing", value)),
        review_matches=lambda value, matched: calls.append(("review_matches", matched)),
    )
    factory = SimpleNamespace(sync_service=lambda: service, matcher=lambda: matcher)
    monkeypatch.setattr("murid.commands.ServiceFactory", lambda parsed: factory)

    assert run_command(SimpleNamespace(command=command, matched=False)) == 0
    assert calls == [expected if command == "review-matches" else ("list_missing", matcher)]


@pytest.mark.parametrize("command", ["list-missing", "review-matches"])
def test_inspection_reports_hardcover_failure(monkeypatch, command, capsys):
    def fail(*args, **kwargs):
        raise HardcoverError("API unavailable")

    service = SimpleNamespace(list_missing=fail, review_matches=fail)
    factory = SimpleNamespace(sync_service=lambda: service, matcher=object)
    monkeypatch.setattr("murid.commands.ServiceFactory", lambda parsed: factory)

    assert run_command(SimpleNamespace(command=command, matched=None)) == 1
    output = capsys.readouterr()
    assert "API unavailable" in output.err
    assert output.out == ""


def test_validate_config_reports_valid_file(capsys, tmp_path, monkeypatch):
    config_file = tmp_path / "murid.yaml"
    config_file.write_text("test: true\n", encoding="utf-8")
    loaded = []
    monkeypatch.setattr("murid.commands.Config", lambda handle: loaded.append(handle.read()))

    args = SimpleNamespace(command="validate-config", config_file=str(config_file))
    assert run_command(args) == 0
    assert loaded == ["test: true\n"]
    assert "Configuration file is valid" in capsys.readouterr().out


def test_unknown_command(caplog):
    assert run_command(SimpleNamespace(command="unknown")) == 1
    assert "Unknown command: unknown" in caplog.text
