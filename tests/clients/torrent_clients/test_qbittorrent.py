from unittest.mock import Mock

import pytest
import qbittorrentapi

from murid import Qbittorrent, QbittorrentConfig


@pytest.fixture
def client():
    client = Mock()

    client.app.version = "5.1.0"
    client.app.web_api_version = "2.11.0"

    return client


@pytest.fixture
def book():
    return Mock(title="Dune")


def test_validate_success(client):
    qbt = Qbittorrent(
        QbittorrentConfig(
            client=client,
            category="ebooks",
            dry_run=False,
        )
    )

    client.auth_log_in.assert_called_once()
    client.auth_log_out.assert_called_once()

    assert qbt.client is client


def test_validate_login_failure(client):
    client.auth_log_in.side_effect = qbittorrentapi.LoginFailed("invalid credentials")

    with pytest.raises(SystemExit, match="1"):
        Qbittorrent(
            QbittorrentConfig(
                client=client,
                category="ebooks",
                dry_run=False,
            )
        )


def test_add_torrent_success(client, book):
    client.torrents_add.return_value = Mock(added_torrent_ids=["abc123"])

    qbt = Qbittorrent(QbittorrentConfig(client=client, category="ebooks", dry_run=False))

    torrent_id = qbt.add_torrent(
        (b"torrent-data", book),
        book,
    )

    assert torrent_id == "abc123"

    client.torrents_add.assert_called_once_with(
        torrent_files=(b"torrent-data", book),
        category="ebooks",
    )


def test_add_torrent_failure(client, book):
    client.torrents_add.side_effect = qbittorrentapi.Conflict409Error("boom")

    qbt = Qbittorrent(QbittorrentConfig(client=client, category="ebooks", dry_run=False))

    torrent_id = qbt.add_torrent(
        (b"torrent-data", book),
        book,
    )

    assert torrent_id is None


def test_get_completed_path_success(client):
    torrent = Mock(
        completed=True,
        content_path="/downloads/Dune.epub",
    )

    client.torrents_info.return_value = [torrent]

    qbt = Qbittorrent(QbittorrentConfig(client=client, category="ebooks", dry_run=False))

    path = qbt.get_completed_path("abc123")

    assert path == "/downloads/Dune.epub"


def test_get_completed_path_not_completed(client):
    torrent = Mock(
        completed=False,
        content_path="/downloads/Dune.epub",
    )

    client.torrents_info.return_value = [torrent]

    qbt = Qbittorrent(QbittorrentConfig(client=client, category="ebooks", dry_run=False))

    assert qbt.get_completed_path("abc123") is None


def test_get_completed_path_empty_result(client):
    client.torrents_info.return_value = [None]

    qbt = Qbittorrent(QbittorrentConfig(client=client, category="ebooks", dry_run=False))

    assert qbt.get_completed_path("abc123") is None


def test_login_failure_logs_error(client, caplog):
    client.auth_log_in.side_effect = qbittorrentapi.LoginFailed("bad login")

    with caplog.at_level("ERROR"):
        with pytest.raises(SystemExit):
            Qbittorrent(QbittorrentConfig(client=client, category="ebooks", dry_run=False))

    assert "Failed to authenticate with qBittorrent" in caplog.text
