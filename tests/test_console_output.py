"""Regression coverage for terminal, redirected, and machine-readable output."""

import io
import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rich.console import Console
from rich.text import Text

from murid import ui
from murid.args import MuridArgumentParser
from murid.clients.myanonamouse import MAMError, MAMSearchError, MyAnonamouse, MyAnonamouseQuery
from murid.commands import run_command
from murid.logging_config import JsonLogFormatter
from murid.main import main
from murid.services.retry_service import RetryImportResult
from murid.services.status_service import print_status
from murid.services.sync_service import SyncService
from murid.services.torrent_import import ImportResult


@pytest.fixture(autouse=True)
def restore_output(monkeypatch):
    monkeypatch.setattr(ui, "OUTPUT_FORMAT", "auto")
    monkeypatch.setattr(ui, "console", Console())


def test_review_highlights_all_lines():
    rendered = ui.match_review(
        "Hardcover: Book\n  MATCH: Book\n  candidate: Other\n"
        "    Evidence: title\n  No Calibre match was assigned."
    )
    assert [rendered.plain[span.start : span.end] for span in rendered.spans] == [
        "Hardcover:",
        "  MATCH",
        "  candidate",
        "  No Calibre",
        "    Evidence:",
    ]


@pytest.mark.parametrize("format", ["auto", "plain", "json"])
def test_redirected_output_preserves_long_literal_values(format):
    ui.setup_output(color=True, output_format=format)
    stream = io.StringIO()
    message = "[bold] literal title " + "https://example.test/" + "x" * 150
    ui.output(Text(message), file=stream, kind="book", data={"title": message})
    result = stream.getvalue()
    assert "\x1b" not in result
    if format == "json":
        record = json.loads(result)
        assert record == {"type": "book", "message": message, "title": message}
    else:
        assert result == message + "\n"


@pytest.mark.parametrize("option", [["--no-color"], ["--format", "plain"], ["--format=json"]])
def test_help_respects_color_preference(monkeypatch, capsys, option):
    monkeypatch.setenv("FORCE_COLOR", "1")
    with pytest.raises(SystemExit) as exit_info:
        MuridArgumentParser("test").parse_args(["status", *option, "--help"])
    assert exit_info.value.code == 0
    assert "\x1b" not in capsys.readouterr().out


def test_no_color_environment_is_honored(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    ui.setup_output(color=True)
    assert ui.console.no_color


def test_json_status_contains_numeric_progress_and_issues(capsys):
    ui.setup_output(color=True, output_format="json")
    client = SimpleNamespace(
        category="murid",
        get_torrents=lambda: [
            SimpleNamespace(
                name="[bold] Dune",
                progress=0.5,
                state="stalledDL",
                tags="murid_timeout",
                hash="abc",
            )
        ],
    )
    print_status(client)
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    torrent = next(record for record in records if record["type"] == "torrent")
    assert torrent["name"] == "[bold] Dune"
    assert torrent["progress"] == 0.5
    assert torrent["state_label"] == "download stalled"
    assert torrent["issues"] == ["timed out"]
    assert records[-1]["attention"] == 1


@pytest.mark.parametrize("width", [48, 80, 120])
def test_status_terminal_layout_preserves_title_and_issue(monkeypatch, width):
    stream = io.StringIO()
    monkeypatch.setattr(
        ui, "console", Console(file=stream, width=width, force_terminal=True, color_system=None)
    )
    title = "Dune and its extraordinarily long edition subtitle"
    print_status(
        SimpleNamespace(
            category="murid",
            get_torrents=lambda: [
                SimpleNamespace(
                    name=title, progress=0.5, state="stalledUP", tags="murid_import_failed"
                )
            ],
        )
    )
    text = stream.getvalue()
    assert "Dune" in text
    assert "subtitle" in text
    assert "50%" in text
    assert "import" in text and "failed" in text
    assert "…" not in text


def test_json_log_keeps_exception_in_one_record():
    try:
        raise ValueError("first\nsecond")
    except ValueError:
        import sys

        record = logging.LogRecord("murid", logging.ERROR, "", 0, "failed", (), sys.exc_info())
    serialized = JsonLogFormatter().format(record)
    assert len(serialized.splitlines()) == 1
    assert "ValueError" in json.loads(serialized)["exception"]


def test_search_distinguishes_api_failure_from_no_results():
    mam = MyAnonamouse("fake")
    response = Mock()
    mam._request = Mock(return_value=response)
    response.json.return_value = {"error": "invalid session"}
    with pytest.raises(MAMError, match="invalid session"):
        mam.search(MyAnonamouseQuery("Dune"))
    response.json.return_value = {"error": "Nothing returned, out of 0"}
    assert mam.search(MyAnonamouseQuery("Dune")) == set()


def test_search_result_limit_is_visible(caplog):
    mam = MyAnonamouse("fake")
    response = Mock()
    response.json.return_value = {"data": [], "total_found": "250"}
    mam._request = Mock(return_value=response)
    mam.search(MyAnonamouseQuery("Dune"))
    assert "limited to 0 of 250 results" in caplog.text


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (ImportResult(added=1, imported=1), True),
        (ImportResult(added=1, pending=1), False),
        (ImportResult(failed=1), False),
    ],
)
def test_sync_summary_reflects_outcome(result, expected, capsys):
    ui.setup_output(color=False, output_format="json")
    retry = SimpleNamespace(last_result=RetryImportResult())
    service = SyncService(SimpleNamespace(args=SimpleNamespace(dry_run=False)))
    assert service._summary(1, {"searched": 1, "selected": 1}, result, retry) is expected
    record = json.loads(capsys.readouterr().out)
    assert record["type"] == "sync_summary"
    assert record["ok"] is expected
    assert record["imported"] == result.imported
    assert record["pending"] == result.pending
    assert record["failed"] == result.failed


def test_empty_pending_set_does_not_report_timeout():
    from murid.services.torrent_import import TorrentImportConfig, TorrentImportService

    service = TorrentImportService(TorrentImportConfig(Mock(), Mock(), Mock(), Mock(), timeout=0))
    assert service._is_timeout(0, {}) is False
    service.notify.assert_not_called()


@pytest.mark.parametrize("configured", [True, False])
def test_notification_failure_is_reported(monkeypatch, capsys, configured):
    factory = SimpleNamespace(
        config={"apprise": {"urls": ["test"]}} if configured else {},
        notifier=lambda: lambda **kwargs: False,
    )
    monkeypatch.setattr("murid.commands.ServiceFactory", lambda args: factory)
    assert run_command(SimpleNamespace(command="test-notification")) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Notification failed" in captured.err if configured else "no Apprise" in captured.err


def test_main_reports_unexpected_failure_once(monkeypatch, caplog):
    monkeypatch.setattr("sys.argv", ["murid", "status"])
    logger = logging.getLogger("murid")
    monkeypatch.setattr(logger, "handlers", [])
    monkeypatch.setattr(logger, "level", logging.WARNING)
    monkeypatch.setattr("murid.main.run_command", Mock(side_effect=RuntimeError("boom")))
    assert main() == 1
    failures = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert len(failures) == 1
    assert failures[0].getMessage() == "Unexpected error: boom"
    assert not failures[0].exc_info


def test_query_rejection_is_concise_even_at_debug_level(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["murid", "status", "--log-level", "debug"])
    logger = logging.getLogger("murid")
    monkeypatch.setattr(logger, "handlers", [])
    monkeypatch.setattr(logger, "level", logging.WARNING)
    monkeypatch.setattr(
        "murid.main.run_command", Mock(side_effect=MAMSearchError("query rejected"))
    )
    assert main() == 1
    captured = capsys.readouterr()
    assert "query rejected" in captured.err
    assert "Traceback" not in captured.err


def test_failed_search_is_not_counted_as_an_empty_result(capsys):
    ui.setup_output(color=False, output_format="json")
    service = SyncService(SimpleNamespace(args=SimpleNamespace(dry_run=False)))
    retry = SimpleNamespace(last_result=RetryImportResult())
    assert not service._summary(
        1, {"searched": 1, "selected": 0, "search_failed": 1, "failed": 1}, ImportResult(), retry
    )
    result = json.loads(capsys.readouterr().out)
    assert result["failed"] == result["search_failed"] == 1
    assert result["unavailable"] == 0


def test_debug_includes_one_traceback(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["murid", "status", "--log-level", "debug"])
    logger = logging.getLogger("murid")
    monkeypatch.setattr(logger, "handlers", [])
    monkeypatch.setattr(logger, "level", logging.WARNING)
    monkeypatch.setattr("murid.main.run_command", Mock(side_effect=RuntimeError("boom")))
    assert main() == 1
    captured = capsys.readouterr()
    assert captured.err.count("Traceback (most recent call last)") == 1
    assert "starting murid" in captured.err
    assert captured.out == ""


@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_summary_includes_retry_outcomes(dry_run, capsys):
    ui.setup_output(color=False, output_format="json")
    service = SyncService(SimpleNamespace(args=SimpleNamespace(dry_run=dry_run)))
    retry = SimpleNamespace(last_result=RetryImportResult(imported=1, pending=1))
    assert service._summary(1, {"searched": 0, "skipped": 1}, ImportResult(), retry) is dry_run
    record = json.loads(capsys.readouterr().out)
    assert (record["imported"], record["pending"], record["deferred"]) == (1, 1, 1)


def test_sync_reports_aborted_outcome_before_propagating(capsys):
    ui.setup_output(color=False, output_format="json")
    service = SyncService(SimpleNamespace(retry_service=Mock(side_effect=MAMError("offline"))))
    with pytest.raises(MAMError, match="offline"):
        service.run()
    result = json.loads(capsys.readouterr().out)
    assert result["type"] == "sync_summary"
    assert result["aborted"] and not result["ok"]


def test_run_exit_code_reflects_service_failure(monkeypatch):
    factory = SimpleNamespace(sync_service=lambda: SimpleNamespace(run=lambda: False))
    monkeypatch.setattr("murid.commands.ServiceFactory", lambda args: factory)
    assert run_command(SimpleNamespace(command="run")) == 1


def test_print_config_json_is_a_structured_record(monkeypatch, tmp_path, capsys):
    ui.setup_output(color=False, output_format="json")
    config_file = tmp_path / "config.yaml"
    config_file.write_text("ignored: true\n", encoding="utf-8")
    monkeypatch.setattr("murid.commands.Config", lambda handle: "api_key: REDACTED\n")
    assert run_command(SimpleNamespace(command="print-config", config_file=str(config_file))) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["type"] == "config"
    assert record["config"] == {"api_key": "REDACTED"}
