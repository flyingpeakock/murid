from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import qbittorrentapi

from murid.clients.torrent_clients import Qbittorrent, QbittorrentConfig
from murid.clients.torrent_clients.qbittorrent import QbittorrentError
from murid.domain.book import Book
from murid.domain.torrent_metadata import TorrentMetainfo
from murid.domain.torrent_request import read_request, write_request_comment


def legacy_torrent(**overrides):
    return SimpleNamespace(
        **{
            "hash": "legacy",
            "category": "murid",
            "comment": "MID=123",
            "tags": "murid_pending,murid_media_audiobook,murid_hardcover_42",
            **overrides,
        }
    )


@pytest.mark.parametrize("media", ["ebook", "audiobook"])
def test_add_tracks_hash_and_persists_identity(qbit_api, torrent_file, media):
    qbt = Qbittorrent(QbittorrentConfig(qbit_api, "murid", False), poll_interval=0)
    book = Book("Dune", ["Frank Herbert"], 42, [], "hardcover")
    torrent_id = qbt.add_torrent(torrent_file, book, media_type=media)
    assert torrent_id == TorrentMetainfo(torrent_file).hashes[0]
    assert qbit_api.items[0].tags == "murid"
    assert read_request(qbit_api.items[0]) == (media, 42)
    uploaded = qbit_api.torrents_add.call_args.kwargs["torrent_files"]
    assert (
        TorrentMetainfo(uploaded).values[b"info"] == TorrentMetainfo(torrent_file).values[b"info"]
    )
    assert TorrentMetainfo(uploaded).comment.startswith("MID=123\n")
    assert qbit_api.tag_definitions == {"murid"}


@pytest.mark.parametrize("response", ["Fails.", SimpleNamespace(added_torrent_ids=[])])
def test_add_unsuccessful_response(qbit_api, torrent_file, response):
    qbit_api.torrents_add.side_effect = None
    qbit_api.torrents_add.return_value = response
    qbt = Qbittorrent(QbittorrentConfig(qbit_api, "murid", False), poll_interval=0)
    assert qbt.add_torrent(torrent_file, Book("Dune", [], 42, [], "hardcover")) is None
    assert not qbit_api.items


def test_add_delayed_legacy_acknowledgement_polls_exact_hash(qbit_api, torrent_file):
    info = qbit_api.torrents_info.side_effect
    remaining = [2]

    def delayed(**kwargs):
        if kwargs.get("torrent_hashes") and kwargs.get("category") and remaining[0]:
            remaining[0] -= 1
            return []
        return info(**kwargs)

    qbit_api.torrents_info.side_effect = delayed
    qbt = Qbittorrent(QbittorrentConfig(qbit_api, "murid", False), poll_interval=0)
    expected = TorrentMetainfo(torrent_file).hashes[0]
    assert qbt.add_torrent(torrent_file, Book("Dune", [], 42, [], "hardcover")) == expected
    polls = [
        call.kwargs
        for call in qbit_api.torrents_info.call_args_list
        if call.kwargs.get("torrent_hashes") and call.kwargs.get("category")
    ]
    assert polls == [{"category": "murid", "torrent_hashes": expected}] * 3


def test_add_lookup_is_bounded(qbit_api, torrent_file):
    qbit_api.torrents_add.side_effect = None
    qbit_api.torrents_add.return_value = "Ok."
    qbt = Qbittorrent(QbittorrentConfig(qbit_api, "murid", False), poll_interval=0)
    assert qbt.add_torrent(torrent_file, Book("Dune", [], 42, [], "hardcover")) is None
    polls = [
        call
        for call in qbit_api.torrents_info.call_args_list
        if call.kwargs.get("torrent_hashes") and call.kwargs.get("category")
    ]
    assert len(polls) == 10


def test_add_rejects_invalid_metainfo_before_mutating(qbit_api):
    qbt = Qbittorrent(QbittorrentConfig(qbit_api, "murid", False))
    with pytest.raises(QbittorrentError, match="Invalid torrent metainfo"):
        qbt.add_torrent(b"bad", Book("Dune", [], 42, [], "hardcover"))
    qbit_api.torrents_add.assert_not_called()
    qbit_api.torrents_info.assert_not_called()


@pytest.mark.parametrize(
    "error", [qbittorrentapi.Conflict409Error, qbittorrentapi.UnsupportedMediaType415Error]
)
def test_add_api_failure_does_not_start_tracking(qbit_api, torrent_file, error):
    qbit_api.torrents_add.side_effect = error("rejected")
    qbt = Qbittorrent(QbittorrentConfig(qbit_api, "murid", False))
    assert qbt.add_torrent(torrent_file, Book("Dune", [], 42, [], "hardcover")) is None
    assert not qbit_api.items


def test_automatic_migration_verifies_comment_before_removing_tags(qbit_api):
    torrent = legacy_torrent(
        tags="user,murid_pending,murid_timeout,murid_import_failed,"
        "murid_media_audiobook,murid_hardcover_42,murid_add_" + "a" * 32
    )
    qbit_api.items = [torrent]
    qbit_api.tag_definitions = set(torrent.tags.split(",")) | {"murid_add_" + "b" * 32}
    qbt = Qbittorrent(QbittorrentConfig(qbit_api, "murid", False))
    qbt.get_torrents(migrate=True)
    assert read_request(torrent) == ("audiobook", 42)
    assert torrent.comment.startswith("MID=123\n[murid:1]")
    assert set(torrent.tags.split(",")) == {"user", "murid", "murid-timeout", "murid-import-failed"}
    assert qbit_api.tag_definitions == set(torrent.tags.split(","))
    calls = [call[0] for call in qbit_api.mock_calls]
    assert calls.index("torrents_properties") < calls.index("torrents_remove_tags")
    qbit_api.reset_mock()
    qbt.get_torrents(migrate=True)
    qbit_api.torrents_set_comment.assert_not_called()
    qbit_api.torrents_remove_tags.assert_not_called()


@pytest.mark.parametrize("media", ["ebook", "audiobook"])
def test_filtered_migration_only_updates_selected_media(qbit_api, media):
    torrents = [
        legacy_torrent(hash=medium, tags=f"murid_pending,murid_media_{medium},murid_hardcover_42")
        for medium in ("ebook", "audiobook")
    ]
    qbit_api.items = torrents
    qbit_api.tag_definitions = set().union(*(set(t.tags.split(",")) for t in torrents))
    original = {t.hash: vars(t).copy() for t in torrents}
    qbt = Qbittorrent(QbittorrentConfig(qbit_api, "murid", False))

    selected = qbt.get_torrents(migrate=True, media_type=media)

    assert [t.hash for t in selected] == [media]
    assert selected[0].tags == "murid"
    assert read_request(selected[0]) == (media, 42)
    excluded = next(t for t in torrents if t.hash != media)
    assert vars(excluded) == original[excluded.hash]
    assert set(excluded.tags.split(",")) <= qbit_api.tag_definitions
    qbit_api.torrents_set_comment.assert_called_once()
    assert qbit_api.torrents_set_comment.call_args.kwargs["torrent_hashes"] == media


def test_filtered_migration_retains_invalid_identity_for_retry_diagnostics(qbit_api):
    torrent = legacy_torrent(tags="murid_pending,murid_media_video")
    qbit_api.items = [torrent]
    original = vars(torrent).copy()
    qbt = Qbittorrent(QbittorrentConfig(qbit_api, "murid", False))

    assert qbt.get_torrents(migrate=True, media_type="ebook") == [torrent]

    assert vars(torrent) == original
    qbit_api.torrents_set_comment.assert_not_called()
    qbit_api.torrents_remove_tags.assert_not_called()


@pytest.mark.parametrize("media", ["ebook", "audiobook"])
def test_add_does_not_migrate_excluded_media(qbit_api, torrent_file, media):
    other = "audiobook" if media == "ebook" else "ebook"
    excluded = legacy_torrent(tags=f"murid_pending,murid_media_{other},murid_hardcover_42")
    qbit_api.items = [excluded]
    original = vars(excluded).copy()
    qbt = Qbittorrent(QbittorrentConfig(qbit_api, "murid", False))

    assert qbt.add_torrent(torrent_file, Book("Dune", [], 42, [], "hardcover"), media_type=media)

    assert vars(excluded) == original
    qbit_api.torrents_set_comment.assert_not_called()
    qbit_api.torrents_remove_tags.assert_not_called()


@pytest.mark.parametrize("failure", ["rejected", "ignored"])
def test_failed_migration_preserves_old_tags(qbit_api, failure):
    torrent = legacy_torrent()
    original = torrent.tags
    qbit_api.items = [torrent]
    qbit_api.torrents_set_comment.side_effect = (
        qbittorrentapi.Forbidden403Error("denied") if failure == "rejected" else None
    )
    qbt = Qbittorrent(QbittorrentConfig(qbit_api, "murid", False))
    with pytest.raises((QbittorrentError, qbittorrentapi.Forbidden403Error)):
        qbt.get_torrents(migrate=True)
    assert torrent.tags == original
    qbit_api.torrents_remove_tags.assert_not_called()
    qbit_api.torrents_delete_tags.assert_not_called()


def test_migration_does_not_delete_definitions_used_in_other_categories(qbit_api):
    qbit_api.items = [legacy_torrent(), legacy_torrent(hash="other", category="other")]
    qbit_api.tag_definitions = set(qbit_api.items[0].tags.split(","))
    qbt = Qbittorrent(QbittorrentConfig(qbit_api, "murid", False))
    qbt.get_torrents(migrate=True)
    assert "murid_hardcover_42" in qbit_api.tag_definitions
    assert qbit_api.items[1].tags == "murid_pending,murid_media_audiobook,murid_hardcover_42"


@pytest.mark.parametrize("dry_run,migrate", [(True, True), (False, False)])
def test_read_only_listing_and_dry_run_leave_legacy_state_untouched(qbit_api, dry_run, migrate):
    torrent = legacy_torrent()
    original = vars(torrent).copy()
    qbit_api.items = [torrent]
    qbt = Qbittorrent(QbittorrentConfig(qbit_api, "murid", dry_run))
    qbt.get_torrents(migrate=migrate)
    assert vars(torrent) == original
    qbit_api.torrents_set_comment.assert_not_called()
    qbit_api.torrents_add_tags.assert_not_called()
    qbit_api.torrents_remove_tags.assert_not_called()
    qbit_api.torrents_delete_tags.assert_not_called()


def test_missing_list_comment_is_loaded_from_properties(qbit_api):
    qbit_api.items = [legacy_torrent()]
    info = qbit_api.torrents_info.side_effect
    qbit_api.torrents_info.side_effect = lambda **kwargs: [
        SimpleNamespace(**{key: value for key, value in vars(t).items() if key != "comment"})
        for t in info(**kwargs)
    ]
    qbt = Qbittorrent(QbittorrentConfig(qbit_api, "murid", False))
    assert qbt.get_torrents()[0].comment == "MID=123"


def test_migration_resumes_after_comment_written_before_tags_removed(qbit_api):
    torrent = legacy_torrent(comment=write_request_comment("MID=123", ("audiobook", 42)))
    qbit_api.items = [torrent]
    qbt = Qbittorrent(QbittorrentConfig(qbit_api, "murid", False))
    qbt.get_torrents(migrate=True)
    assert torrent.tags == "murid"
    qbit_api.torrents_set_comment.assert_not_called()


@pytest.mark.parametrize("remaining", ["murid_media_audiobook", "murid_hardcover_42"])
def test_migration_resumes_after_some_identity_tags_removed(qbit_api, remaining):
    torrent = legacy_torrent(
        comment=write_request_comment("MID=123", ("audiobook", 42)), tags="murid," + remaining
    )
    qbit_api.items = [torrent]
    qbt = Qbittorrent(QbittorrentConfig(qbit_api, "murid", False))
    qbt.get_torrents(migrate=True)
    assert torrent.tags == "murid"
    assert read_request(torrent) == ("audiobook", 42)


def test_migration_preserves_lifecycle_when_replacement_tag_is_not_saved(qbit_api):
    torrent = legacy_torrent()
    qbit_api.items = [torrent]
    qbit_api.torrents_add_tags.side_effect = None
    qbt = Qbittorrent(QbittorrentConfig(qbit_api, "murid", False))
    with pytest.raises(QbittorrentError, match="Lifecycle tag migration"):
        qbt.get_torrents(migrate=True)
    assert torrent.tags == "murid_pending,murid_media_audiobook,murid_hardcover_42"
    qbit_api.torrents_remove_tags.assert_not_called()


@pytest.fixture
def client():
    client = Mock()

    client.app.version = "5.1.0"
    client.app.web_api_version = "2.11.0"
    client.torrents_info.return_value = []

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
    torrents = [Mock(name="Dune", tags="", comment="")]
    client.torrents_info.return_value = torrents
    qbt = Qbittorrent(QbittorrentConfig(client=client, category="ebooks", dry_run=False))

    assert qbt.get_torrents() is torrents
    client.torrents_info.assert_called_once_with(category="ebooks")


@pytest.mark.parametrize("second_response", [[], [Mock(progress=0.5)]])
def test_get_completed_path_rechecks_after_move(client, second_response, monkeypatch):
    monkeypatch.setattr("murid.clients.torrent_clients.qbittorrent.time.sleep", lambda _: None)
    client.torrents_info.side_effect = [[Mock(progress=1.0)], second_response]
    qbt = Qbittorrent(QbittorrentConfig(client=client, category="ebooks", dry_run=False))
    assert qbt.get_completed_path("abc123") is None


def test_tag_lookup_scopes_category_and_handles_tag_whitespace(client):
    torrent = Mock(tags="other,murid-timeout, third", comment="")
    client.torrents_info.return_value = [torrent, Mock(tags="murid-timeout_other", comment="")]
    qbt = Qbittorrent(QbittorrentConfig(client=client, category="ebooks", dry_run=False))
    assert qbt.get_torrents_with_tag("murid-timeout") == [torrent]
    client.torrents_info.assert_called_once_with(category="ebooks")


@pytest.mark.parametrize("requested", ["murid-import-failed", "murid_import_failed"])
def test_tag_lookup_loads_comments_only_for_matching_canonical_or_legacy_tags(client, requested):
    irrelevant = [SimpleNamespace(hash=str(index), tags="murid") for index in range(1000)]
    matching = [
        SimpleNamespace(hash="canonical", tags="user, murid-import-failed"),
        SimpleNamespace(hash="legacy", tags="murid_import_failed, user"),
    ]
    client.torrents_info.return_value = irrelevant + matching
    client.torrents_properties.return_value = SimpleNamespace(comment="MID=123")
    qbt = Qbittorrent(QbittorrentConfig(client, "murid", False))

    assert qbt.get_torrents_with_tag(requested) == matching

    client.torrents_info.assert_called_once_with(category="murid")
    assert [call.kwargs for call in client.torrents_properties.call_args_list] == [
        {"torrent_hash": "canonical"},
        {"torrent_hash": "legacy"},
    ]
    assert all(torrent.comment == "MID=123" for torrent in matching)
    assert all(not hasattr(torrent, "comment") for torrent in irrelevant)


def test_tag_lookup_without_matches_only_lists_torrents(client):
    client.torrents_info.return_value = [
        SimpleNamespace(hash=str(index), tags="murid") for index in range(1000)
    ]
    qbt = Qbittorrent(QbittorrentConfig(client, "murid", False))

    assert qbt.get_torrents_with_tag("murid-import-failed") == []

    client.torrents_info.assert_called_once_with(category="murid")
    client.torrents_properties.assert_not_called()


@pytest.mark.parametrize(
    "source,content,expected",
    [
        ("/downloads", "/downloads/Dune/book.epub", Path("/mapped/Dune/book.epub")),
        ("/downloads/", "/downloads/Dune.epub", Path("/mapped/Dune.epub")),
        ("/downloads", "/downloads", Path("/mapped")),
        ("/downloads", "/downloads-old/Dune.epub", "/downloads-old/Dune.epub"),
        ("/downloads", "/other/downloads/Dune.epub", "/other/downloads/Dune.epub"),
        ("/downloads", "/downloads/../other/Dune.epub", "/downloads/../other/Dune.epub"),
        ("/", "/Dune.epub", Path("/mapped/Dune.epub")),
        (r"C:\Downloads", r"C:\Downloads\Dune\book.epub", Path("/mapped/Dune/book.epub")),
        (r"C:\Downloads", r"C:\Downloads-old\Dune.epub", r"C:\Downloads-old\Dune.epub"),
        (r"C:\Downloads", r"D:\Downloads\Dune.epub", r"D:\Downloads\Dune.epub"),
    ],
)
def test_path_mapping_respects_directories(client, monkeypatch, source, content, expected):
    monkeypatch.setattr("murid.clients.torrent_clients.qbittorrent.time.sleep", lambda _: None)
    client.torrents_info.return_value = [Mock(progress=1, content_path=content)]
    qbt = Qbittorrent(
        QbittorrentConfig(
            client=client,
            category="ebooks",
            dry_run=False,
            mapping={"qbit_path": source, "murid_path": "/mapped/"},
        )
    )
    assert qbt.get_completed_path("abc123") == str(expected)
