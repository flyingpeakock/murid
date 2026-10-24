"""Exercise every inspection and work command through the real CLI."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
import yaml

pytestmark = pytest.mark.integration


def records(result, kind):
    return [record for record in result.records if record["type"] == kind]


def configure_audio(workflow):
    workflow.config.pop("calibre")
    workflow.config["hardcover_api_keys"] = [
        {
            "api_key": "Bearer integration-token",
            "reading_list": {"want-to-read": {"type": ["audiobook"]}},
        },
    ]
    workflow.config["audiobookshelf"] = {
        "url": "https://audio.example.com",
        "api_key": "private-audio-key",
        "library_id": "audio-id",
        "library_path": str(workflow.audio_library_path),
    }


def test_audio_config_validates_without_calibre_or_mount(workflow):
    configure_audio(workflow)
    assert not workflow.audio_library_path.exists()
    result = workflow.run("validate-config")
    assert result.code == 0, result.errors
    assert not workflow.audio_library_path.exists()


def test_grouped_ebook_lists_use_every_list(workflow):
    workflow.config["hardcover_api_keys"] = [
        {
            "api_key": "Bearer integration-token",
            "reading_list": {"want-to-read": {}},
        }
    ]
    result = workflow.run("list-missing")
    assert result.code == 0, result.errors
    assert records(result, "missing_summary")[0]["count"] == 1


def test_grouped_audio_config_can_run_discovery_without_library_writes(workflow):
    configure_audio(workflow)
    workflow.config["hardcover_api_keys"] = [
        {
            "api_key": "Bearer integration-token",
            "reading_list": {"audiobooks": {"type": "audiobook"}},
        }
    ]
    assert workflow.run("validate-config").code == 0
    result = workflow.run("run", "--dry-run")
    assert records(result, "sync_summary")[0]["missing"] == 1
    assert workflow.api.added_files == []


def test_audio_print_config_json_always_hides_key(workflow):
    configure_audio(workflow)
    workflow.config["redact_sensitive_data"] = False
    result = workflow.run("print-config")
    assert result.code == 0, result.errors
    rendered = records(result, "config")[0]["config"]
    assert rendered["audiobookshelf"]["api_key"] == "**REDACTED**"
    assert "private-audio-key" not in str(result)


def seed_library(workflow):
    workflow.database.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "title": "Dune",
                    "authors": "Frank Herbert",
                    "identifiers": {"hardcover": "42"},
                    "formats": ["/library/Dune.epub"],
                }
            ]
        )
    )


def seed_audio(workflow, tracks=1):
    workflow.audio_items = [
        {
            "id": "item-id",
            "libraryId": "audio-id",
            "mediaType": "book",
            "isMissing": False,
            "isInvalid": False,
            "media": {
                "numTracks": tracks,
                "numAudioFiles": tracks,
                "metadata": {"title": "Dune", "authors": [{"name": "Frank Herbert"}]},
                "tags": ["murid:hardcover:42"],
                "tracks": [{"duration": 100}] if tracks else [],
            },
        }
    ]


@pytest.mark.parametrize(
    "ebook_present,audio_present",
    [(True, False), (False, True), (True, True)],
)
def test_mixed_media_inspection_routes_each_request(workflow, ebook_present, audio_present):
    ebook_config = workflow.config["calibre"]
    configure_audio(workflow)
    workflow.config["calibre"] = ebook_config
    workflow.config["hardcover_api_keys"][0]["reading_list"] = {
        "want-to-read": {"type": ["ebook", "audiobook"]},
    }
    if ebook_present:
        seed_library(workflow)
    if audio_present:
        seed_audio(workflow)
    before = workflow.database.read_text()
    result = workflow.run("list-missing")
    assert result.code == 0, result.errors
    assert {r["media_type"] for r in records(result, "missing_book")} == (
        ({"ebook"} if not ebook_present else set())
        | ({"audiobook"} if not audio_present else set())
    )
    review = workflow.run("review-matches")
    assert review.code == 0, review.errors
    assert {r["media_type"]: r["matched"] for r in records(review, "match_review")} == {
        "ebook": ebook_present,
        "audiobook": audio_present,
    }
    assert workflow.database.read_text() == before
    assert workflow.api.added_files == []
    assert not any("myanonamouse" in url for _, url, _ in workflow.requests)


def test_audio_only_inspection_needs_no_calibre_and_ignores_ebook_only_items(workflow, monkeypatch):
    configure_audio(workflow)
    seed_audio(workflow, tracks=0)

    def no_calibre(*args, **kwargs):
        raise AssertionError("Calibre must not be initialized for audio-only requests")

    monkeypatch.setattr("murid.services.service_factory.Calibre", no_calibre)
    result = workflow.run("list-missing")
    assert result.code == 0, result.errors
    missing = records(result, "missing_book")
    assert len(missing) == 1
    assert missing[0]["media_type"] == "audiobook"
    assert missing[0]["destination"] == "Audiobookshelf"


@pytest.mark.parametrize("command", ["list-missing", "review-matches"])
def test_library_access_failure_is_not_reported_as_empty(workflow, command):
    configure_audio(workflow)
    workflow.audio_status = 403
    result = workflow.run(command)
    assert result.code == 1
    assert "HTTP 403" in str(result.errors)
    assert "private-audio-key" not in str(result)
    assert not records(result, "missing_book")
    assert not records(result, "missing_summary")
    assert not records(result, "review_summary")


def seed_torrent(workflow, **overrides):
    values = {
        "hash": "existing-hash",
        "name": "Dune",
        "state": "uploading",
        "category": "murid",
        "tags": "murid-timeout,murid",
        "progress": 1.0,
        "content_path": "/remote/downloads/Dune",
        "comment": "MID=101",
    }
    values.update(overrides)
    torrent = SimpleNamespace(**values)
    workflow.api.torrents.append(torrent)
    return torrent


@pytest.mark.parametrize(
    "tags,comment",
    [
        ("murid-import-failed,murid_media_audiobook", "MID=101"),
        ("murid-import-failed", "MID=101\n[murid:1]invalid-json"),
    ],
)
def test_search_preview_reports_invalid_torrent_identity_without_blocking_candidates(
    workflow, tags, comment
):
    torrent = seed_torrent(workflow, tags=tags, comment=comment)
    original = vars(torrent).copy()

    preview = workflow.run("search-book", "Dune", "--ebooks")

    assert preview.code == 0, preview.errors
    assert any(item["selected"] for item in records(preview, "candidate"))
    assert any("existing-hash" in error["message"] for error in preview.errors)
    assert vars(torrent) == original
    assert workflow.api.added_files == []
    assert workflow.database.read_text() == "[]"

    recovery = workflow.run("run")

    assert recovery.code == 1
    assert records(recovery, "sync_summary")[0]["skipped"] == 1
    assert vars(torrent) == original
    assert workflow.api.added_files == []
    assert workflow.database.read_text() == "[]"


@pytest.mark.parametrize("present", [False, True])
def test_list_missing_reports_library_matches(workflow, present):
    if present:
        seed_library(workflow)
    before = workflow.database.read_text()

    result = workflow.run("list-missing")

    assert result.code == 0, result.errors
    assert records(result, "missing_summary")[0]["count"] == (0 if present else 1)
    assert [item["book"]["id"] for item in records(result, "missing_book")] == (
        [] if present else [42]
    )
    assert workflow.database.read_text() == before
    assert workflow.api.added_files == []


@pytest.mark.parametrize("present", [False, True])
@pytest.mark.parametrize("filters", [(), ("--matched",), ("--unmatched",)])
def test_review_matches_applies_filters_and_reports_evidence(workflow, present, filters):
    if present:
        seed_library(workflow)
    before = workflow.database.read_text()

    result = workflow.run("review-matches", *filters)

    assert result.code == 0, result.errors
    expected = not filters or (filters == ("--matched",)) == present
    reviews = records(result, "match_review")
    assert len(reviews) == int(expected)
    assert records(result, "review_summary")[0]["count"] == int(expected)
    if reviews:
        assert reviews[0]["book"]["id"] == 42
        assert reviews[0]["matched"] is present
        if present:
            candidate = reviews[0]["candidates"][0]
            assert candidate["accepted"] is True
            assert candidate["score"] >= reviews[0]["threshold"]
            assert candidate["evidence"]
        else:
            assert reviews[0]["candidates"] == []
    assert workflow.database.read_text() == before


def test_status_reports_only_configured_category_and_attention(workflow):
    seed_torrent(workflow, tags="murid-import-failed,murid-timeout")
    seed_torrent(workflow, hash="other-hash", category="other", name="Unrelated")

    result = workflow.run("status")

    assert result.code == 0, result.errors
    assert records(result, "status")[0]["count"] == 1
    torrent = records(result, "torrent")[0]
    assert torrent["hash"] == "existing-hash"
    assert torrent["progress"] == 1.0
    assert torrent["state_label"] == "seeding"
    assert torrent["issues"] == ["import failed", "timed out"]
    assert records(result, "status_summary")[0]["attention"] == 1
    assert workflow.requests == []


def test_status_handles_empty_category(workflow):
    result = workflow.run("status")

    assert result.code == 0, result.errors
    assert records(result, "status")[0]["count"] == 0
    assert records(result, "torrent") == []


@pytest.mark.parametrize("add", [False, True])
def test_search_book_previews_candidates_or_imports_with_add(workflow, add):
    result = workflow.run("search-book", "Dune", *(("--add",) if add else ()))

    assert result.code == 0, result.errors
    assert records(result, "search")[0]["book"]["id"] == 42
    candidate = records(result, "candidate")[0]
    assert candidate["book"]["id"] == 101
    assert candidate["selected"] is True
    assert candidate["reasons"] == []
    assert len(workflow.api.added_files) == int(add)
    assert len(json.loads(workflow.database.read_text())) == int(add)
    assert any("download.php" in url for _, url, _ in workflow.requests) is add


def test_search_book_explains_rejection_and_add_fails(workflow):
    workflow.torrent_rows[0]["lang_code"] = "SWE"

    preview = workflow.run("search-book", "Dune")
    attempted_add = workflow.run("search-book", "Dune", "--add")

    assert preview.code == 0, preview.errors
    candidate = records(preview, "candidate")[0]
    assert candidate["selected"] is False
    assert "language" in candidate["reasons"]
    assert attempted_add.code == 1
    assert any("No torrent was selected" in error["message"] for error in attempted_add.errors)
    assert workflow.api.added_files == []
    assert workflow.database.read_text() == "[]"


def test_search_book_reports_unknown_title(workflow):
    result = workflow.run("search-book", "Unknown title")

    assert result.code == 1
    assert any("No Hardcover book matched" in error["message"] for error in result.errors)
    assert records(result, "candidate") == []
    assert workflow.api.added_files == []


@pytest.mark.parametrize("extension", ["epub", "pdf"])
def test_add_book_imports_hardcover_metadata_and_rejects_duplicate(workflow, extension):
    file = workflow.downloads / f"Dune.{extension}"
    file.write_bytes(b"fixture ebook")
    path = str(file)

    result = workflow.run("add-book", "Dune", path)
    duplicate = workflow.run("add-book", "Dune", path)

    assert result.code == 0, result.errors
    assert records(result, "imported")[0]["book"]["id"] == 42
    books = json.loads(workflow.database.read_text())
    assert len(books) == 1
    assert books[0]["title"] == "Dune"
    assert books[0]["authors"] == "Frank Herbert"
    assert books[0]["identifiers"]["hardcover"] == "42"
    assert duplicate.code == 1
    assert "already in Calibre" in duplicate.errors[0]["message"]
    assert workflow.api.added_files == []
    imports = (workflow.library / "imports.jsonl").read_text().splitlines()
    assert json.loads(imports[0])[-1] == path


@pytest.mark.parametrize("file_kind", ["missing", "directory"])
def test_add_book_rejects_invalid_paths(workflow, file_kind):
    path = workflow.downloads / "missing.epub" if file_kind == "missing" else workflow.downloads

    result = workflow.run("add-book", "Dune", str(path))

    assert result.code == 1
    assert "not a file" in result.errors[0]["message"]
    assert workflow.database.read_text() == "[]"
    assert workflow.requests == []


@pytest.mark.parametrize("progress", [0.5, 1.0])
def test_retry_import_handles_existing_download_without_adding(workflow, progress):
    torrent = seed_torrent(workflow, progress=progress)

    result = workflow.run("retry-import")

    assert result.code == (1 if progress < 1 else 0), result.errors
    outcome = records(result, "retry_summary")[0]
    assert outcome["imported"] == int(progress == 1)
    assert outcome["pending"] == int(progress < 1)
    assert len(json.loads(workflow.database.read_text())) == int(progress == 1)
    assert set(filter(None, torrent.tags.split(","))) == (
        {"murid-timeout", "murid"} if progress < 1 else set()
    )
    assert workflow.api.added_files == []
    assert not any("download.php" in url for _, url, _ in workflow.requests)


@pytest.mark.parametrize("hardcover_failure", [False, True])
def test_connection_checks_report_each_service_even_after_failure(workflow, hardcover_failure):
    workflow.hardcover_error = hardcover_failure

    result = workflow.run("test-connection")

    assert result.code == int(hardcover_failure), result.errors
    checks = {item["service"]: item for item in records(result, "connection")}
    assert set(checks) == {"Hardcover account 1", "Calibre", "MyAnonamouse", "qBittorrent"}
    assert checks["Hardcover account 1"]["ok"] is (not hardcover_failure)
    assert all(checks[name]["ok"] for name in ("Calibre", "MyAnonamouse", "qBittorrent"))
    outcome = records(result, "connection_summary")[0]
    assert outcome["passed"] == 4 - int(hardcover_failure)
    assert outcome["failed"] == int(hardcover_failure)
    assert workflow.database.read_text() == "[]"
    assert workflow.api.added_files == []


@pytest.mark.parametrize("valid", [False, True])
def test_validate_config_loads_yaml_and_reports_invalid_values(workflow, valid):
    if not valid:
        workflow.config["matcher_threshold"] = 1.5

    result = workflow.run("validate-config")

    assert result.code == (0 if valid else 1)
    if valid:
        assert records(result, "validation")[0]["valid"] is True
    else:
        assert result.errors[0]["valid"] is False
        assert "matcher_threshold" in result.errors[0]["message"]
    assert workflow.requests == []
    assert workflow.api.added_files == []


@pytest.mark.parametrize("redact", [False, True])
def test_print_config_includes_defaults_and_respects_redaction(workflow, redact):
    workflow.config["redact_sensitive_data"] = redact
    workflow.config["apprise"] = {
        "urls": [
            "tgram://123456:bot-secret/123456",
            "https://hooks.example.com/webhook-secret",
            "mailto://user:smtp-secret@example.com",
        ]
    }

    result = workflow.run("print-config")

    assert result.code == 0, result.errors
    config = records(result, "config")[0]["config"]
    assert config["matcher_threshold"] == 0.92
    assert config["schedule"] == "0 * * * *"
    assert config["filetypes"] == ["epub", "mobi"]
    assert config["hardcover_api_keys"] == (
        "**REDACTED**" if redact else workflow.config["hardcover_api_keys"]
    )
    assert config["mam_id"] == ("**REDACTED**" if redact else "integration-cookie")
    assert config["qbittorrent"]["password"] == ("**REDACTED**" if redact else "integration")
    assert config["apprise"] == ("**REDACTED**" if redact else workflow.config["apprise"])
    assert workflow.requests == []


@pytest.mark.parametrize("status", [200, 503])
def test_notification_uses_apprise_transport_and_reports_delivery(workflow, status):
    workflow.config["apprise"] = {"urls": ["json://notifications.invalid/notify"]}
    workflow.notification_status = status

    result = workflow.run("test-notification")

    assert result.code == (0 if status == 200 else 1), result.errors
    assert len(workflow.notifications) == 1
    notification = workflow.notifications[0]
    assert notification["title"] == "Murid - Test Notification"
    assert notification["message"] == "Hello from Murid!"
    assert notification["type"] == "info"
    if status == 200:
        assert records(result, "notification")[0]["sent"] is True
    else:
        assert "Notification failed" in result.errors[0]["message"]


def test_notification_reports_missing_destinations(workflow):
    result = workflow.run("test-notification")

    assert result.code == 1
    assert "no Apprise destinations configured" in result.errors[0]["message"]
    assert workflow.notifications == []


@pytest.mark.parametrize("first_cycle_fails", [False, True])
def test_schedule_reloads_config_and_runs_next_cycle(workflow, monkeypatch, first_cycle_fails):
    workflow.config["schedule"] = "* * * * *"
    base = datetime(2026, 1, 1)
    moments = iter(
        [
            base,
            base + timedelta(minutes=1),
            base + timedelta(minutes=1),
            base + timedelta(minutes=2),
        ]
    )

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            try:
                moment = next(moments)
            except StopIteration:
                raise KeyboardInterrupt from None
            if moment == base + timedelta(minutes=1):
                # Change the file after initial factory creation, before the cycle reload.
                config = {**workflow.config, "filetypes": ["mobi", "epub"]}
                workflow.config_file.write_text(yaml.safe_dump(config))
                workflow.hardcover_error = first_cycle_fails
            elif moment == base + timedelta(minutes=2):
                workflow.hardcover_error = False
            return moment

    monkeypatch.setattr("murid.services.sync_service.datetime", Clock)

    result = workflow.run("schedule")

    assert result.code == 130, result.errors
    cycles = records(result, "sync_summary")
    assert len(cycles) == 2
    if first_cycle_fails:
        assert cycles[0]["aborted"] is True
        assert cycles[1]["imported"] == 1
    else:
        assert cycles[0]["imported"] == 1
        assert cycles[1]["missing"] == 0
    assert len(json.loads(workflow.database.read_text())) == 1
    imported = json.loads((workflow.library / "imports.jsonl").read_text())
    assert imported[-1] == str(workflow.downloads / "Dune.mobi")
    assert len(workflow.api.added_files) == 1
