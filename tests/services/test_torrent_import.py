from unittest.mock import MagicMock

import pytest

from murid import (
    Book,
    BookMatcher,
    CalibreError,
    TorrentImportConfig,
    TorrentImportService,
)


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

    service.import_torrents([(b"torrent", book)])

    torrent_client.add_torrent.assert_called_once()
    calibre.add_book.assert_called_once_with(book, "/downloads/dune")


def test_failed_torrent_add(service, torrent_client, calibre, book):
    torrent_client.add_torrent.return_value = None

    service.import_torrents([(b"torrent", book)])

    calibre.add_book.assert_not_called()


def test_calibre_error_adds_tag(service, torrent_client, calibre, book):
    torrent_client.add_torrent.return_value = "abc123"
    torrent_client.get_completed_path.return_value = "/downloads/dune"

    calibre.add_book.side_effect = CalibreError("db error")

    service.process_torrent("abc123", book)

    torrent_client.add_tag.assert_called_once_with("abc123", "import_failed")


def test_success_triggers_notification(service, torrent_client, calibre, notify, book):
    torrent_client.get_completed_path.return_value = "/downloads/dune"
    torrent_client.add_torrent.return_value = "abc123"
    calibre.contains_book.return_value = True

    service.process_torrent("abc123", book)

    notify.assert_called_once()
    args, kwargs = notify.call_args
    assert "Successfully imported" in kwargs["body"]


def test_failed_verification_adds_tag(service, torrent_client, calibre, book):
    torrent_client.get_completed_path.return_value = "/downloads/dune"
    calibre.contains_book.return_value = False

    service.process_torrent("abc123", book)

    torrent_client.add_tag.assert_called_once_with("abc123", "import_failed")


def test_process_torrent_no_retry(service, torrent_client, calibre, book):
    torrent_client.get_completed_path.return_value = None

    result = service.process_torrent("abc123", book)

    assert result is False
    assert torrent_client.get_completed_path.call_count == 1
    calibre.add_book.assert_not_called()
