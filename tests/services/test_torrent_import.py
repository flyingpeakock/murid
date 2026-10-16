import logging
import time
from unittest.mock import MagicMock

import pytest

from murid.clients.calibre import CalibreError
from murid.domain.book import Book
from murid.domain.book_matcher import BookMatcher
from murid.notifications.apprise import AppriseHandler
from murid.services.torrent_import import TorrentImportConfig, TorrentImportService


def make_book():
    return Book(
        title="Dune",
        authors=["Frank Herbert"],
        id=1,
        isbn=[],
        source="test",
    )


@pytest.fixture
def book():
    return make_book()


@pytest.fixture
def matcher():
    return MagicMock(spec=BookMatcher)


@pytest.fixture
def calibre():
    c = MagicMock()
    c.contains_book.return_value = True
    return c


@pytest.fixture
def torrent_client():
    c = MagicMock()
    c.poll_interval = 0  # speed up loops
    return c


@pytest.fixture
def notify():
    return MagicMock()


@pytest.fixture
def service(torrent_client, calibre, matcher, notify):
    config = TorrentImportConfig(
        torrent_client=torrent_client,
        calibre=calibre,
        matcher=matcher,
        notify=notify,
        dry_run=False,
    )
    return TorrentImportService(config)


def test_dry_run_does_not_add_torrents(service, torrent_client, book):
    service.dry_run = True

    service.import_torrents([(b"torrent", book)])

    torrent_client.add_torrent.assert_not_called()


def test_no_torrents(service, torrent_client):
    service.import_torrents([])

    torrent_client.add_torrent.assert_not_called()


def test_successful_import(service, torrent_client, calibre, matcher, book):
    torrent_client.add_torrent.return_value = "abc123"
    torrent_client.get_completed_path.return_value = "/downloads/dune"

    result = service.import_torrents([(b"torrent", book)])

    torrent_client.add_torrent.assert_called_once()
    calibre.add_book.assert_called_once_with(book, "/downloads/dune")
    assert (result.added, result.imported, result.pending, result.failed) == (1, 1, 0, 0)


def test_import_selects_requested_file_from_completed_pack(
    service,
    torrent_client,
    calibre,
    book,
    monkeypatch,
    tmp_path,
):
    pack = tmp_path / "book-pack"
    pack.mkdir()
    selected_file = pack / "Frank Herbert - Dune.epub"
    selected_file.touch()
    (pack / "Frank Herbert - Dune Messiah.epub").touch()
    torrent_client.get_completed_path.return_value = str(pack)
    service.matcher = BookMatcher()
    monkeypatch.setattr("murid.services.torrent_import.time.sleep", lambda _: None)

    service.process_torrent("abc123", book)

    calibre.add_book.assert_called_once_with(book, str(selected_file))


def test_no_suitable_file_tags_torrent_and_notifies_apprise(
    service,
    torrent_client,
    calibre,
    notify,
    book,
    monkeypatch,
    tmp_path,
):
    class DummyApprise:
        def __init__(self):
            self.calls = []

        def notify(self, **kwargs):
            self.calls.append(kwargs)

    pack = tmp_path / "book-pack"
    pack.mkdir()
    (pack / "Foundation.epub").touch()
    (pack / "Hyperion.epub").touch()
    torrent_client.get_completed_path.return_value = str(pack)
    service.matcher = BookMatcher()
    monkeypatch.setattr("murid.services.torrent_import.time.sleep", lambda _: None)

    apprise_client = DummyApprise()
    handler = AppriseHandler(apprise_client)
    murid_logger = logging.getLogger("murid")
    murid_logger.addHandler(handler)
    try:
        result = service.process_torrent("abc123", book)
    finally:
        murid_logger.removeHandler(handler)

    assert result is True
    calibre.add_book.assert_not_called()
    torrent_client.add_tag.assert_called_once_with("abc123", "murid_import_failed")
    notify.assert_not_called()
    assert len(apprise_client.calls) == 1
    assert apprise_client.calls[0]["title"] == "murid - ERROR"
    assert "could not select a unique ebook file" in apprise_client.calls[0]["body"]


def test_failed_torrent_add(service, torrent_client, calibre, book):
    torrent_client.add_torrent.return_value = None

    result = service.import_torrents([(b"torrent", book)])

    calibre.add_book.assert_not_called()
    assert (result.added, result.failed) == (0, 1)


def test_calibre_error_adds_tag(service, torrent_client, calibre, book):
    torrent_client.add_torrent.return_value = "abc123"
    torrent_client.get_completed_path.return_value = "/downloads/dune"

    calibre.add_book.side_effect = CalibreError("db error")

    service.process_torrent("abc123", book)

    torrent_client.add_tag.assert_called_once_with("abc123", "murid_import_failed")


def test_success_triggers_notification(service, torrent_client, calibre, notify, book):
    torrent_client.get_completed_path.return_value = "/downloads/dune"
    torrent_client.add_torrent.return_value = "abc123"
    calibre.contains_book.return_value = True

    service.process_torrent("abc123", book)

    notify.assert_called_once()
    args, kwargs = notify.call_args
    assert "imported into Calibre" in kwargs["body"]


def test_failed_verification_adds_tag(service, torrent_client, calibre, book):
    torrent_client.get_completed_path.return_value = "/downloads/dune"
    calibre.contains_book.return_value = False

    service.process_torrent("abc123", book)

    torrent_client.add_tag.assert_called_once_with("abc123", "murid_import_failed")


def test_process_torrent_no_retry(service, torrent_client, calibre, book):
    torrent_client.get_completed_path.return_value = None

    result = service.process_torrent("abc123", book)

    assert result is False
    assert torrent_client.get_completed_path.call_count == 1
    calibre.add_book.assert_not_called()


def test_is_timeout_returns_false_before_timeout(service):
    service.timeout = 1800

    result = service._is_timeout(
        start_time=time.time(),
        pending={"abc": "book"},
    )

    assert result is False


def test_is_timeout_returns_true_after_timeout(
    service,
    torrent_client,
    notify,
):
    service.timeout = 1

    pending = {
        "abc123": "Dune",
    }

    result = service._is_timeout(
        start_time=time.time() - 10,
        pending=pending,
    )

    assert result is True

    notify.assert_called_once()

    torrent_client.add_tag.assert_called_once_with(
        "abc123",
        "murid_timeout",
    )


def test_is_timeout_tags_all_pending_torrents(
    service,
    torrent_client,
    notify,
):
    service.timeout = 1

    pending = {
        "a": "Book A",
        "b": "Book B",
        "c": "Book C",
    }

    service._is_timeout(
        start_time=time.time() - 10,
        pending=pending,
    )

    assert torrent_client.add_tag.call_count == 3

    torrent_client.add_tag.assert_any_call("a", "murid_timeout")
    torrent_client.add_tag.assert_any_call("b", "murid_timeout")
    torrent_client.add_tag.assert_any_call("c", "murid_timeout")

    assert notify.call_count == 3


def test_timeout_notification_contains_timeout_value(
    service,
    torrent_client,
    notify,
):
    service.timeout = 123

    service._is_timeout(
        start_time=time.time() - 1000,
        pending={"abc": "Dune"},
    )

    _, kwargs = notify.call_args

    assert "123 seconds" in kwargs["body"]


def test_shared_hash_reports_collision_without_losing_first_book(
    service, torrent_client, calibre, book, monkeypatch, caplog
):
    other = Book(title="Dune Messiah", authors=book.authors, id=2, isbn=[], source="test")
    torrent_client.add_torrent.return_value = "shared"
    torrent_client.get_completed_path.return_value = "/downloads/dune.epub"
    monkeypatch.setattr("murid.services.torrent_import.time.sleep", lambda _: None)

    result = service.import_torrents([(b"pack", book), (b"pack", other)])

    calibre.add_book.assert_called_once_with(book, "/downloads/dune.epub")
    assert (result.added, result.imported, result.failed, result.pending) == (1, 1, 1, 0)
    assert "already assigned" in caplog.text
    torrent_client.remove_tag.assert_called_once_with("shared", "murid_pending")


def test_calibre_timeout_tags_import_failure(service, torrent_client, calibre, book, monkeypatch):
    torrent_client.get_completed_path.return_value = "/downloads/dune.epub"
    calibre.add_book.side_effect = CalibreError("Calibre command timed out after 120 seconds")
    monkeypatch.setattr("murid.services.torrent_import.time.sleep", lambda _: None)

    assert service.process_torrent("abc123", book)
    assert service.last_outcome == "failed"
    torrent_client.add_tag.assert_called_once_with("abc123", "murid_import_failed")
