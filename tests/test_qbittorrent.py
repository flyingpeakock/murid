from unittest.mock import Mock

import pytest

from hardcoverharvester.qbittorrent import Qbittorrent


@pytest.fixture
def book():
    return Mock(title="Dune")


@pytest.fixture
def client():
    return Mock()


@pytest.fixture
def calibre():
    return Mock()


def test_handle_torrents_empty(client, calibre):
    qbt = Qbittorrent(client, calibre, category="ebooks", dry_run=False)

    result = qbt.handle_torrents([])

    assert result == []


def test_handle_torrents_dry_run(client, calibre, book):
    qbt = Qbittorrent(client, calibre, category="ebooks", dry_run=True)

    result = qbt.handle_torrents([(b"torrent", book)])

    assert result == []
    client.torrents_add.assert_not_called()


def test_add_torrent_success(client, calibre, book):
    qbt = Qbittorrent(client, calibre, category="ebooks", dry_run=False)

    client.torrents_add.return_value = Mock(added_torrent_ids=["abc123"])

    result = qbt._add_torrent(b"file", book)

    assert result == "abc123"
    client.torrents_add.assert_called_once()


def test_add_torrent_failure(client, calibre, book):
    qbt = Qbittorrent(client, calibre, category="ebooks", dry_run=False)

    client.torrents_add.side_effect = Exception("boom")

    result = qbt._add_torrent(b"file", book)

    assert result is None


def test_completed_torrent_sends_to_calibre(monkeypatch, client, calibre, book):
    qbt = Qbittorrent(client, calibre, category="ebooks", dry_run=False)

    # add torrent returns id
    client.torrents_add.return_value = Mock(added_torrent_ids=["abc123"])

    # time control
    monkeypatch.setattr("time.time", lambda: 1000)

    # completed torrent
    client.torrents_info.return_value = [Mock(completed=True, content_path="/tmp/book.epub")]

    # avoid sleep loop
    monkeypatch.setattr("time.sleep", lambda x: None)

    qbt.handle_torrents([(b"torrent", book)])

    calibre.add_book.assert_called_once_with(book, "/tmp/book.epub")


def test_get_completed_path_success(client, calibre):
    qbt = Qbittorrent(client, calibre, "cat", False)

    client.torrents_info.return_value = [Mock(completed=True, content_path="/path/file.epub")]

    assert qbt._get_completed_path("abc") == "/path/file.epub"


def test_get_completed_path_not_completed(client, calibre):
    qbt = Qbittorrent(client, calibre, "cat", False)

    client.torrents_info.return_value = [Mock(completed=False, content_path="/path/file.epub")]

    assert qbt._get_completed_path("abc") is None


def test_get_completed_path_missing(client, calibre):
    qbt = Qbittorrent(client, calibre, "cat", False)

    client.torrents_info.side_effect = Exception("not found")

    assert qbt._get_completed_path("abc") is None


def test_send_to_calibre_failure_is_swallowed(client, calibre, book):
    qbt = Qbittorrent(client, calibre, "cat", False)

    calibre.add_book.side_effect = Exception("boom")

    # should NOT raise
    qbt._send_to_calibre(book, "/tmp/file.epub")
