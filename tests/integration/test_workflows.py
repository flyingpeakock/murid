"""CLI workflows across configuration, clients, domain logic, and services."""

import json

import pytest

from murid.clients.myanonamouse import MyAnonamouse

pytestmark = pytest.mark.integration


def summary(result):
    return next(record for record in result.records if record["type"] == "sync_summary")


def test_sync_imports_preferred_file_and_second_run_is_idempotent(workflow):
    result = workflow.run("run")

    assert result.code == 0, result.errors
    assert summary(result)["imported"] == 1
    assert summary(result)["added"] == 1
    books = json.loads(workflow.database.read_text())
    assert [(book["title"], book["authors"]) for book in books] == [("Dune", "Frank Herbert")]
    assert books[0]["identifiers"]["hardcover"] == "42"
    imported = json.loads((workflow.library / "imports.jsonl").read_text())
    assert imported[-1] == str(workflow.downloads / "Dune.epub")
    assert set(workflow.api.torrents[0].tags.split(",")) == {
        "murid_media_ebook",
        "murid_hardcover_42",
    }
    assert workflow.api.added_files == [b"fixture torrent bytes"]

    workflow.requests.clear()
    second = workflow.run("run")

    assert second.code == 0, second.errors
    assert summary(second)["missing"] == 0
    assert summary(second)["imported"] == 0
    assert len(workflow.api.added_files) == 1
    assert len(json.loads(workflow.database.read_text())) == 1
    assert not any(url == MyAnonamouse.SEARCH_URL for _, url, _ in workflow.requests)


def test_dry_run_fetches_torrent_without_adding_or_importing(workflow):
    result = workflow.run("run", "--dry-run")

    assert result.code == 0, result.errors
    assert summary(result)["planned"] == 1
    assert summary(result)["dry_run"] is True
    assert workflow.api.added_files == []
    assert workflow.database.read_text() == "[]"
    assert not (workflow.library / "imports.jsonl").exists()
    assert any("download.php" in url for _, url, _ in workflow.requests)


@pytest.mark.parametrize("rejection", ["language", "format", "blacklist", "no_results"])
def test_unavailable_torrent_reports_failure_without_mutations(workflow, rejection):
    if rejection == "language":
        workflow.torrent_rows[0]["lang_code"] = "SWE"
    elif rejection == "format":
        workflow.torrent_rows[0]["filetypes"] = "pdf"
    elif rejection == "blacklist":
        workflow.config["blacklisted_torrent_ids"] = [101]
    else:
        workflow.torrent_rows.clear()

    result = workflow.run("run")

    assert result.code == 1, result.errors
    assert summary(result)["unavailable"] == 1
    assert summary(result)["ok"] is False
    assert workflow.api.added_files == []
    assert workflow.database.read_text() == "[]"
    assert not any("download.php" in url for _, url, _ in workflow.requests)


def test_failed_import_can_be_retried_without_adding_another_torrent(workflow):
    failure = workflow.library / "fail-import"
    failure.touch()

    result = workflow.run("run")

    assert result.code == 1
    assert summary(result)["failed"] == 1
    assert set(workflow.api.torrents[0].tags.split(",")) == {
        "murid_pending",
        "murid_import_failed",
        "murid_media_ebook",
        "murid_hardcover_42",
    }
    assert workflow.database.read_text() == "[]"

    failure.unlink()
    workflow.requests.clear()
    retry = workflow.run("retry-import")

    assert retry.code == 0, retry.errors
    assert len(json.loads(workflow.database.read_text())) == 1
    assert set(workflow.api.torrents[0].tags.split(",")) == {
        "murid_media_ebook",
        "murid_hardcover_42",
    }
    assert len(workflow.api.added_files) == 1
    assert not any("download.php" in url for _, url, _ in workflow.requests)


def test_hardcover_failure_aborts_sync_before_downloading(workflow):
    workflow.hardcover_error = True

    result = workflow.run("run")

    assert result.code == 1
    assert summary(result)["aborted"] is True
    assert any("reading list unavailable" in error["message"] for error in result.errors)
    assert workflow.api.added_files == []
    assert workflow.database.read_text() == "[]"
    assert not any(url == MyAnonamouse.SEARCH_URL for _, url, _ in workflow.requests)


def test_sync_uses_configured_custom_list(workflow):
    workflow.config["hardcover_api_keys"] = [
        {"api_key": "Bearer integration-token", "reading_list": {"download-queue": {}}}
    ]
    result = workflow.run("run")
    assert result.code == 0, result.errors
    assert summary(result)["imported"] == 1
    queries = [
        kwargs["json"]["query"]
        for _, url, kwargs in workflow.requests
        if url == "https://api.hardcover.app/v1/graphql"
    ]
    assert any("GetListBooks" in query for query in queries)
    assert all("GetUserBooks" not in query for query in queries)
