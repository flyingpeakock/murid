"""Audiobook command routing with real imports and offline server responses."""

import shutil
import sys

import pytest

pytestmark = pytest.mark.integration


def audio_setup(workflow):
    workflow.config.pop("calibre")
    workflow.config["hardcover_api_keys"] = [
        {
            "api_key": "Bearer integration-token",
            "reading_list": {"audiobooks": {"type": "audiobook"}},
        }
    ]
    workflow.audio_library_path.mkdir()
    workflow.config["audiobookshelf"] = {
        "url": "https://audio.example.com",
        "api_key": "private-audio-key",
        "library_id": "audio-id",
        "library_path": str(workflow.audio_library_path),
        "scan_timeout_seconds": 1,
    }
    source = workflow.downloads.parent / "audio-downloads" / "Dune"
    source.mkdir(parents=True)
    (source / "CD1").mkdir()
    (source / "CD2").mkdir()
    (source / "CD1/01.mp3").write_bytes(b"first audio track")
    (source / "CD2/01.mp3").write_bytes(b"second audio track")
    (source / "cover.jpg").write_bytes(b"cover")
    return source


def record(result, kind):
    return next(item for item in result.records if item["type"] == kind)


def test_manual_folder_import_retains_all_tracks_and_retry_is_idempotent(workflow):
    source = audio_setup(workflow)
    result = workflow.run("add-book", "Dune", str(source), "--media-type", "audiobook")
    assert result.code == 0, result.errors
    assert record(result, "imported")["destination"] == "Audiobookshelf"
    assert record(result, "imported")["media_type"] == "audiobook"
    target = workflow.audio_library_path / "Frank Herbert/Dune [hardcover-42]"
    assert (target / "CD1/01.mp3").read_bytes() == b"first audio track"
    assert (target / "CD2/01.mp3").read_bytes() == b"second audio track"
    assert (source / "CD1/01.mp3").exists()
    assert workflow.api.added_files == []
    assert workflow.audio_scans == 1
    again = workflow.run("add-book", "Dune", str(source), "--media-type", "audiobook")
    assert again.code == 0, again.errors
    assert workflow.audio_scans == 1
    assert len(list(workflow.audio_library_path.rglob(".murid-import.json"))) == 1


def test_manual_pending_import_recovers_after_source_removal(workflow, monkeypatch):
    source = audio_setup(workflow)
    clock = {"time": 0}
    monkeypatch.setattr("time.monotonic", lambda: clock["time"])
    monkeypatch.setattr("time.sleep", lambda seconds: clock.update(time=clock["time"] + seconds))
    workflow.audio_auto_scan = False
    result = workflow.run("add-book", "Dune", str(source), "--media-type", "audiobook")
    assert result.code == 1
    pending = next(item for item in result.errors if item["type"] == "import_pending")
    assert pending["destination"] == "Audiobookshelf"
    shutil.rmtree(source)
    workflow.audio_auto_scan = True
    again = workflow.run("add-book", "Dune", str(source), "--media-type", "audiobook")
    assert again.code == 0, again.errors
    assert len(list(workflow.audio_library_path.rglob(".murid-import.json"))) == 1
    assert workflow.api.added_files == []


def test_manual_audio_dry_run_checks_source_without_copying_or_scanning(workflow):
    source = audio_setup(workflow)
    result = workflow.run("add-book", "Dune", str(source), "--audiobooks", "--dry-run")
    assert result.code == 0, result.errors
    assert record(result, "planned")["media_type"] == "audiobook"
    assert list(workflow.audio_library_path.iterdir()) == []
    assert not (workflow.audio_library_path.parent / ".murid-staging-audio-library").exists()
    assert workflow.audio_scans == 0
    assert workflow.api.added_files == []


def test_audio_search_preview_and_add_dry_run_use_audio_preferences(workflow):
    audio_setup(workflow)
    workflow.torrent_rows[0]["filetypes"] = "mp3"
    workflow.torrent_rows[0]["main_cat"] = 13
    result = workflow.run("search-book", "Dune", "--audiobooks")
    assert result.code == 0, result.errors
    assert record(result, "candidate")["selected"]
    assert record(result, "candidate")["destination"] == "Audiobookshelf"
    assert record(result, "candidate")["media_type"] == "audiobook"
    assert not any("download.php" in url for _, url, _ in workflow.requests)
    result = workflow.run("search-book", "Dune", "--media-type", "audiobook", "--add", "--dry-run")
    assert result.code == 0, result.errors
    assert record(result, "planned")["destination"] == "Audiobookshelf"
    assert workflow.api.added_files == []
    assert workflow.audio_scans == 0


def test_audio_connection_diagnostics_are_read_only_and_skip_calibre(workflow):
    audio_setup(workflow)
    result = workflow.run("test-connection")
    assert result.code == 0, [item for item in result.records if item.get("ok") is False]
    services = {item["service"]: item for item in result.records if item["type"] == "connection"}
    assert services["Audiobookshelf"]["ok"]
    assert "v2.37.1" in services["Audiobookshelf"]["detail"]
    assert "Calibre" not in services
    assert workflow.audio_scans == 0
    assert not (workflow.audio_library_path.parent / ".murid-staging-audio-library").exists()
    assert workflow.api.added_files == []
    assert list(workflow.audio_library_path.iterdir()) == []


def test_default_ebook_manual_import_still_works_with_mixed_lists(workflow):
    source = audio_setup(workflow)
    workflow.config["calibre"] = {
        "calibredb_executable": sys.executable,
        "library": str(workflow.library),
    }
    workflow.config["hardcover_api_keys"][0]["reading_list"]["want-to-read"] = {}
    result = workflow.run("add-book", "Dune", str(workflow.downloads / "Dune.epub"))
    assert result.code == 0, result.errors
    assert record(result, "imported")["media_type"] == "ebook"
    assert record(result, "imported")["destination"] == "Calibre"
    assert workflow.audio_scans == 0
    assert (source / "CD1/01.mp3").exists()


def test_ebook_manual_dry_run_never_invokes_calibre_import(workflow):
    result = workflow.run("add-book", "Dune", str(workflow.downloads / "Dune.epub"), "--dry-run")
    assert result.code == 0, result.errors
    assert record(result, "planned")["destination"] == "Calibre"
    assert workflow.database.read_text() == "[]"
    assert not (workflow.library / "imports.jsonl").exists()


def test_audio_status_identifies_media_destination_and_conflicting_tags(workflow):
    from types import SimpleNamespace

    audio_setup(workflow)
    workflow.api.torrents = [
        SimpleNamespace(
            hash="audio-hash",
            name="Dune",
            category="murid",
            progress=1,
            state="uploading",
            tags="murid_pending,murid_media_audiobook,murid_hardcover_42",
        )
    ]
    result = workflow.run("status")
    assert result.code == 0, result.errors
    torrent = record(result, "torrent")
    assert (torrent["media_type"], torrent["destination"], torrent["hardcover_id"]) == (
        "audiobook",
        "Audiobookshelf",
        42,
    )
    workflow.api.torrents[0].tags += ",murid_media_ebook"
    result = workflow.run("status")
    torrent = record(result, "torrent")
    assert torrent["media_type"] is None and torrent["destination"] is None
    assert "invalid request identity" in torrent["issues"]
    assert record(result, "status_summary")["attention"] == 1


def test_audio_summary_and_notification_include_the_actual_destination(workflow):
    from types import SimpleNamespace

    source = audio_setup(workflow)
    workflow.config["apprise"] = {"urls": ["json://notifications.invalid/notify"]}
    workflow.api.torrents = [
        SimpleNamespace(
            hash="existing",
            name="Dune",
            category="murid",
            progress=1,
            state="uploading",
            comment="",
            content_path=str(source),
            tags="murid_pending,murid_media_audiobook,murid_hardcover_42",
        )
    ]
    result = workflow.run("run")
    assert result.code == 0, result.errors
    summary = record(result, "sync_summary")
    assert summary["by_media"]["audiobook"]["imported"] == 1
    assert summary["by_media"]["audiobook"]["destination"] == "Audiobookshelf"
    assert workflow.api.added_files == []
    assert any("Audiobookshelf [audiobook]" in str(payload) for payload in workflow.notifications)


def test_audio_retry_dry_run_retains_torrent_tags_and_library(workflow):
    from types import SimpleNamespace

    source = audio_setup(workflow)
    tags = "murid_pending,murid_media_audiobook,murid_hardcover_42"
    workflow.api.torrents = [
        SimpleNamespace(
            hash="existing",
            name="Dune",
            category="murid",
            progress=1,
            state="uploading",
            comment="",
            content_path=str(source),
            tags=tags,
        )
    ]
    result = workflow.run("retry-import", "--dry-run")
    assert result.code == 1
    assert record(result, "retry_summary")["by_media"]["audiobook"]["pending"] == 1
    assert workflow.api.torrents[0].tags == tags
    assert workflow.audio_scans == 0
    assert list(workflow.audio_library_path.iterdir()) == []


@pytest.mark.parametrize(
    "command,kind",
    [
        ("list-missing", "missing_book"),
        ("review-matches", "match_review"),
    ],
)
@pytest.mark.parametrize("media", ["ebook", "audiobook"])
def test_filtered_inspection_ignores_unavailable_other_library(
    workflow, monkeypatch, command, kind, media
):
    audio_setup(workflow)
    workflow.config["hardcover_api_keys"][0]["reading_list"]["download-queue"] = {}
    workflow.config["calibre"] = {
        "calibredb_executable": sys.executable,
        "library": str(workflow.library),
    }
    if media == "ebook":
        workflow.audio_status = 503
    else:
        monkeypatch.setattr(
            "murid.services.service_factory.Calibre",
            lambda *_args, **_kwargs: pytest.fail("Unrelated ebook library initialized"),
        )
    flag = "--ebooks" if media == "ebook" else "--audiobooks"
    result = workflow.run(command, flag)
    assert result.code == 0, result.errors
    rows = [item for item in result.records if item["type"] == kind]
    assert len(rows) == 1 and rows[0]["media_type"] == media
    list_queries = [
        kwargs["json"]["variables"]["slug"]
        for _, url, kwargs in workflow.requests
        if url == "https://api.hardcover.app/v1/graphql"
        and "GetListBooks" in kwargs["json"]["query"]
    ]
    assert set(list_queries) == {"download-queue" if media == "ebook" else "audiobooks"}
    if media == "ebook":
        assert not any(
            url.startswith("https://audio.example.com/") for _, url, _ in workflow.requests
        )


@pytest.mark.parametrize("command", ["run", "retry-import"])
def test_ebook_filter_preserves_pending_audio_and_avoids_audio_backend(workflow, command):
    from types import SimpleNamespace

    source = audio_setup(workflow)
    workflow.config["hardcover_api_keys"][0]["reading_list"]["download-queue"] = {}
    workflow.config["calibre"] = {
        "calibredb_executable": sys.executable,
        "library": str(workflow.library),
    }
    workflow.audio_status = 503
    tags = "murid_pending,murid_media_audiobook,murid_hardcover_42"
    workflow.api.torrents = [
        SimpleNamespace(
            hash="audio",
            name="Dune audio",
            category="murid",
            progress=1,
            state="uploading",
            comment="",
            content_path=str(source),
            tags=tags,
        )
    ]
    result = workflow.run(command, "--ebooks", "--dry-run")
    assert result.code == 0, result.errors
    assert workflow.api.torrents[0].tags == tags
    assert not any(url.startswith("https://audio.example.com/") for _, url, _ in workflow.requests)
    assert workflow.api.added_files == []
