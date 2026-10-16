from unittest.mock import ANY, Mock

import pytest
import qbittorrentapi

from murid import Qbittorrent, QbittorrentConfig
from murid.clients.torrent_clients.qbittorrent import QbittorrentError


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

    with pytest.raises(QbittorrentError, match="invalid credentials"):
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
        b"torrent-data",
        book,
    )

    assert torrent_id == "abc123"

    client.torrents_add.assert_called_once_with(
        torrent_files=b"torrent-data",
        category="ebooks",
        tags=ANY,
    )


def test_add_torrent_failure(client, book):
    client.torrents_add.side_effect = qbittorrentapi.Conflict409Error("boom")

    qbt = Qbittorrent(QbittorrentConfig(client=client, category="ebooks", dry_run=False))

    torrent_id = qbt.add_torrent(
        b"torrent-data",
        book,
    )

    assert torrent_id is None


def test_get_completed_path_success(client):
    torrent = Mock(
        completed=100,
        progress=1.0,
        content_path="/downloads/Dune.epub",
    )

    client.torrents_info.return_value = [torrent]

    qbt = Qbittorrent(QbittorrentConfig(client=client, category="ebooks", dry_run=False))

    path = qbt.get_completed_path("abc123")

    assert path == "/downloads/Dune.epub"


def test_get_completed_path_not_completed(client):
    torrent = Mock(
        completed=1,
        progress=0.01,
        content_path="/downloads/Dune.epub",
    )

    client.torrents_info.return_value = [torrent]

    qbt = Qbittorrent(QbittorrentConfig(client=client, category="ebooks", dry_run=False))

    assert qbt.get_completed_path("abc123") is None


def test_get_completed_path_empty_result(client):
    client.torrents_info.return_value = []

    qbt = Qbittorrent(QbittorrentConfig(client=client, category="ebooks", dry_run=False))

    assert qbt.get_completed_path("abc123") is None


def test_login_failure_leaves_reporting_to_caller(client, caplog):
    client.auth_log_in.side_effect = qbittorrentapi.LoginFailed("bad login")

    with caplog.at_level("ERROR"):
        with pytest.raises(QbittorrentError, match="Failed to authenticate with qBittorrent"):
            Qbittorrent(QbittorrentConfig(client=client, category="ebooks", dry_run=False))

    assert caplog.text == ""


def test_get_torrents_uses_configured_category(client):
    torrents = [Mock(name="Dune")]
    client.torrents_info.return_value = torrents
    qbt = Qbittorrent(QbittorrentConfig(client=client, category="ebooks", dry_run=False))

    assert qbt.get_torrents() is torrents
    client.torrents_info.assert_called_once_with(category="ebooks")


@pytest.mark.parametrize("response", ["Fails.", Mock(added_torrent_ids=[])])
def test_add_torrent_unsuccessful_response(client, book, response):
    client.torrents_add.return_value = response
    qbt = Qbittorrent(QbittorrentConfig(client=client, category="ebooks", dry_run=False))
    assert qbt.add_torrent(b"torrent-data", book) is None
    client.torrents_info.assert_not_called()


def test_add_torrent_legacy_response_tracks_delayed_add(client, book):
    client.torrents_add.return_value = "Ok."
    client.torrents_info.side_effect = [[], [Mock(hash="abc123")]]
    qbt = Qbittorrent(
        QbittorrentConfig(client=client, category="ebooks", dry_run=False), poll_interval=0
    )
    assert qbt.add_torrent(b"torrent-data", book) == "abc123"
    tag = client.torrents_add.call_args.kwargs["tags"]
    client.torrents_info.assert_called_with(category="ebooks", tag=tag)
    client.torrents_remove_tags.assert_called_once_with(tags=tag, torrent_hashes="abc123")


def test_add_torrent_legacy_response_lookup_is_bounded(client, book):
    client.torrents_add.return_value = "Ok."
    client.torrents_info.return_value = []
    qbt = Qbittorrent(
        QbittorrentConfig(client=client, category="ebooks", dry_run=False), poll_interval=0
    )
    assert qbt.add_torrent(b"torrent-data", book) is None
    assert client.torrents_info.call_count == 10


@pytest.mark.parametrize("second_response", [[], [Mock(progress=0.5)]])
def test_get_completed_path_rechecks_after_move(client, second_response, monkeypatch):
    monkeypatch.setattr("murid.clients.torrent_clients.qbittorrent.time.sleep", lambda _: None)
    client.torrents_info.side_effect = [[Mock(progress=1.0)], second_response]
    qbt = Qbittorrent(QbittorrentConfig(client=client, category="ebooks", dry_run=False))
    assert qbt.get_completed_path("abc123") is None


def test_tag_lookup_scopes_category_and_handles_tag_whitespace(client):
    torrent = Mock(tags="other,murid_timeout, third")
    client.torrents_info.return_value = [torrent, Mock(tags="murid_timeout_other")]
    qbt = Qbittorrent(QbittorrentConfig(client=client, category="ebooks", dry_run=False))
    assert qbt.get_torrents_with_tag("murid_timeout") == [torrent]
    client.torrents_info.assert_called_once_with(category="ebooks", tag="murid_timeout")
