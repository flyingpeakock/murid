from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from murid.clients.myanonamouse import MAMError
from murid.domain.book import Book
from murid.domain.book_matcher import BookMatcher
from murid.domain.torrent import Torrent, TorrentMetadata
from murid.services.retry_service import RetryService
from murid.services.torrent_import import TorrentImportConfig, TorrentImportService


@pytest.fixture
def torrent_client():
    return Mock()


@pytest.fixture
def import_service():
    service = Mock()
    service.dry_run = False
    return service


@pytest.fixture
def mam():
    return Mock()


@pytest.fixture
def service(torrent_client, import_service, mam):
    return RetryService(
        torrent_client=torrent_client,
        import_service=import_service,
        myanonamouse=mam,
    )


@pytest.fixture
def book():
    return Book(
        title="Dune",
        authors=["Frank Herbert"],
        id=1,
        isbn=[],
        source="test",
    )


def test_fetch_previous_torrents_empty(service, torrent_client):
    torrent_client.get_torrents_with_tag.return_value = []

    assert list(service.fetch_previous_torrents()) == []


def test_fetch_previous_torrents_valid_mid(service, torrent_client):
    torrent_client.get_torrents_with_tag.return_value = [
        SimpleNamespace(
            hash="torrent1",
            comment="something MID=123 something",
        )
    ]

    assert list(service.fetch_previous_torrents()) == [("torrent1", 123)]


def test_fetch_previous_torrents_ignores_missing_mid(
    service,
    torrent_client,
):
    torrent_client.get_torrents_with_tag.return_value = [
        SimpleNamespace(
            hash="torrent1",
            comment="no mam id here",
        )
    ]

    assert list(service.fetch_previous_torrents()) == []


def test_fetch_previous_torrents_mixed(service, torrent_client):
    torrent_client.get_torrents_with_tag.return_value = [
        SimpleNamespace(hash="a", comment="MID=111"),
        SimpleNamespace(hash="b", comment="nothing"),
        SimpleNamespace(hash="c", comment="MID=222"),
    ]

    assert list(service.fetch_previous_torrents()) == [
        ("a", 111),
        ("c", 222),
    ]


def make_torrent(book):
    return Torrent(
        book=book,
        metadata=TorrentMetadata(
            category=1,
            size=100,
            seeders=1,
            leechers=0,
            freeleech=False,
            vip=False,
        ),
    )


def test_get_book_by_mam_id_success(service, mam, book):
    mam.search.return_value = [make_torrent(book)]

    result = service.get_book_by_mam_id(123)

    assert result == book


def test_get_book_by_mam_id_no_results(service, mam):
    mam.search.return_value = []

    assert service.get_book_by_mam_id(123) is None


def test_get_book_by_mam_id_multiple_results(service, mam, book):
    mam.search.return_value = [
        make_torrent(book),
        make_torrent(book),
    ]

    assert service.get_book_by_mam_id(123) is None


def test_get_book_by_mam_id_mam_error(service, mam):
    mam.search.side_effect = MAMError("boom")

    assert service.get_book_by_mam_id(123) is None


def test_retry_torrents_success(
    service,
    import_service,
    torrent_client,
    book,
):
    service.fetch_previous_torrents = Mock(return_value=[("torrent1", 123)])

    service.get_book_by_mam_id = Mock(return_value=book)

    import_service.process_torrent.return_value = True
    import_service.calibre.contains_book.side_effect = [False, True]

    assert service.retry_torrents() == set()

    assert torrent_client.remove_tag.call_args_list == [
        call("torrent1", "murid_timeout"),
        call("torrent1", "murid_pending"),
    ]


def test_retry_torrents_returns_book_while_torrent_is_incomplete(
    service,
    import_service,
    torrent_client,
    book,
):
    service.fetch_previous_torrents = Mock(return_value=[("torrent1", 123)])

    service.get_book_by_mam_id = Mock(return_value=book)

    import_service.process_torrent.return_value = False
    import_service.calibre.contains_book.return_value = False

    assert service.retry_torrents() == {book}

    torrent_client.remove_tag.assert_not_called()


def test_retry_torrents_book_not_found(
    service,
    import_service,
    torrent_client,
):
    service.fetch_previous_torrents = Mock(return_value=[("torrent1", 123)])

    service.get_book_by_mam_id = Mock(return_value=None)

    assert service.retry_torrents() == set()

    import_service.process_torrent.assert_not_called()
    torrent_client.remove_tag.assert_not_called()


def test_retry_torrents_does_not_import_book_already_in_calibre(
    service, import_service, torrent_client, book
):
    service.fetch_previous_torrents = Mock(return_value=[("torrent1", 123)])
    service.get_book_by_mam_id = Mock(return_value=book)
    import_service.calibre.contains_book.return_value = True

    assert service.retry_torrents() == set()

    import_service.process_torrent.assert_not_called()
    assert torrent_client.remove_tag.call_args_list == [
        call("torrent1", "murid_timeout"),
        call("torrent1", "murid_pending"),
    ]


def test_retry_torrents_clears_timeout_after_failed_import(
    service, import_service, torrent_client, book
):
    service.fetch_previous_torrents = Mock(return_value=[("torrent1", 123)])
    service.get_book_by_mam_id = Mock(return_value=book)
    import_service.calibre.contains_book.return_value = False
    import_service.process_torrent.return_value = True

    assert service.retry_torrents() == set()

    import_service.process_torrent.assert_called_once_with("torrent1", book)
    assert torrent_client.remove_tag.call_args_list == [
        call("torrent1", "murid_timeout"),
        call("torrent1", "murid_pending"),
    ]


def test_scheduled_retry_tags_completed_import_failure(
    torrent_client, mam, book, tmp_path, monkeypatch
):
    (tmp_path / "Foundation.epub").touch()
    torrent_client.get_completed_path.return_value = str(tmp_path)
    calibre = Mock()
    calibre.contains_book.return_value = False
    import_service = TorrentImportService(
        TorrentImportConfig(
            torrent_client=torrent_client,
            calibre=calibre,
            matcher=BookMatcher(),
            notify=Mock(),
        )
    )
    service = RetryService(torrent_client, import_service, mam)
    service.fetch_previous_torrents = Mock(return_value=[("torrent1", 123)])
    service.get_book_by_mam_id = Mock(return_value=book)
    monkeypatch.setattr("murid.services.torrent_import.time.sleep", lambda _: None)

    assert service.retry_torrents() == set()

    torrent_client.add_tag.assert_called_once_with("torrent1", "murid_import_failed")
    assert torrent_client.remove_tag.call_args_list == [
        call("torrent1", "murid_timeout"),
        call("torrent1", "murid_pending"),
    ]


def test_retry_torrents_dry_run_does_not_import_or_change_tags(
    service, import_service, torrent_client, book
):
    service.fetch_previous_torrents = Mock(return_value=[("torrent1", 123)])
    service.get_book_by_mam_id = Mock(return_value=book)
    import_service.calibre.contains_book.return_value = False
    import_service.dry_run = True

    assert service.retry_torrents() == {book}

    import_service.process_torrent.assert_not_called()
    torrent_client.remove_tag.assert_not_called()


def tagged_torrent(tags, comment="MID=123", hash="torrent1"):
    return SimpleNamespace(tags=tags, comment=comment, hash=hash)


def test_retry_imports_imports_completed_timeout(service, torrent_client, import_service, book):
    torrent_client.get_torrents.return_value = [tagged_torrent("murid_timeout")]
    service.get_book_by_mam_id = Mock(return_value=book)
    import_service.calibre.contains_book.side_effect = [False, True]
    import_service.process_torrent.return_value = True

    result = service.retry_imports()

    assert result.imported == 1
    assert result.pending == result.failed == result.skipped == 0
    import_service.process_torrent.assert_called_once_with("torrent1", book)
    torrent_client.remove_tag.assert_called_once_with("torrent1", "murid_timeout")


def test_retry_imports_keeps_failed_tag_on_failure(service, torrent_client, import_service, book):
    torrent_client.get_torrents.return_value = [tagged_torrent("murid_import_failed")]
    service.get_book_by_mam_id = Mock(return_value=book)
    import_service.calibre.contains_book.return_value = False
    import_service.process_torrent.return_value = True

    result = service.retry_imports()

    assert result.failed == 1
    torrent_client.remove_tag.assert_not_called()


def test_retry_imports_leaves_incomplete_download_tagged(
    service, torrent_client, import_service, book
):
    torrent_client.get_torrents.return_value = [tagged_torrent("murid_timeout")]
    service.get_book_by_mam_id = Mock(return_value=book)
    import_service.calibre.contains_book.return_value = False
    import_service.process_torrent.return_value = False

    result = service.retry_imports()

    assert result.pending == 1
    torrent_client.remove_tag.assert_not_called()


def test_retry_imports_clears_tags_when_already_in_calibre(
    service, torrent_client, import_service, book
):
    torrent_client.get_torrents.return_value = [
        tagged_torrent("murid_timeout, murid_import_failed")
    ]
    service.get_book_by_mam_id = Mock(return_value=book)
    import_service.calibre.contains_book.return_value = True

    result = service.retry_imports()

    assert result.already_present == 1
    import_service.process_torrent.assert_not_called()
    assert {call.args for call in torrent_client.remove_tag.call_args_list} == {
        ("torrent1", "murid_timeout"),
        ("torrent1", "murid_import_failed"),
    }


def test_retry_imports_skips_unknown_torrents(service, torrent_client, import_service):
    torrent_client.get_torrents.return_value = [
        tagged_torrent("other"),
        tagged_torrent("murid_timeout", comment="missing", hash="torrent2"),
        tagged_torrent("murid_import_failed", hash="torrent3"),
    ]
    service.get_book_by_mam_id = Mock(return_value=None)

    result = service.retry_imports()

    assert result.skipped == 2
    service.get_book_by_mam_id.assert_called_once_with(123)
    import_service.process_torrent.assert_not_called()


def test_retry_imports_replaces_timeout_with_failure_tag(
    service, torrent_client, import_service, book
):
    torrent_client.get_torrents.return_value = [tagged_torrent("murid_timeout")]
    service.get_book_by_mam_id = Mock(return_value=book)
    import_service.calibre.contains_book.return_value = False
    import_service.process_torrent.return_value = True

    result = service.retry_imports()

    assert result.failed == 1
    torrent_client.remove_tag.assert_called_once_with("torrent1", "murid_timeout")


@pytest.mark.parametrize("completed", [False, True])
def test_restart_recovers_download_interrupted_before_timeout(book, mam, completed):
    from murid.clients.torrent_clients.qbittorrent import Qbittorrent, QbittorrentConfig

    torrents = []
    api = Mock()

    def add(**kwargs):
        torrents.append(SimpleNamespace(hash="abc123", comment="MID=123", tags=kwargs["tags"]))
        return SimpleNamespace(added_torrent_ids=["abc123"])

    def remove(*, tags, torrent_hashes):
        for torrent in torrents:
            if torrent.hash == torrent_hashes:
                torrent.tags = ",".join(tag for tag in torrent.tags.split(",") if tag != tags)

    api.torrents_add.side_effect = add
    api.torrents_remove_tags.side_effect = remove
    api.torrents_info.side_effect = lambda **kwargs: [
        torrent for torrent in torrents if kwargs["tag"] in torrent.tags.split(",")
    ]
    client = Qbittorrent(QbittorrentConfig(api, "murid", False))
    interrupted = TorrentImportService(TorrentImportConfig(client, Mock(), Mock(), Mock()))
    interrupted._wait_for_imports = Mock(side_effect=KeyboardInterrupt)

    with pytest.raises(KeyboardInterrupt):
        interrupted.import_torrents([(b"torrent", book)])

    assert torrents[0].tags == "murid_pending"
    importer = Mock(dry_run=False)
    importer.calibre.contains_book.side_effect = [False, True] if completed else [False]
    importer.process_torrent.return_value = completed
    mam.search.return_value = [make_torrent(book)]
    restarted = RetryService(client, importer, mam)

    assert restarted.retry_torrents() == (set() if completed else {book})
    importer.process_torrent.assert_called_once_with("abc123", book)
    assert restarted.last_result.imported == int(completed)
    assert restarted.last_result.pending == int(not completed)
    assert ("murid_pending" in torrents[0].tags) is not completed


@pytest.mark.parametrize("already_present", [False, True])
def test_manual_retry_handles_pending_tag(
    service, torrent_client, import_service, book, already_present
):
    torrent_client.get_torrents.return_value = [tagged_torrent("murid_pending")]
    service.get_book_by_mam_id = Mock(return_value=book)
    import_service.calibre.contains_book.side_effect = [True] if already_present else [False, True]
    import_service.process_torrent.return_value = True

    result = service.retry_imports()

    assert result.already_present == int(already_present)
    assert result.imported == int(not already_present)
    torrent_client.remove_tag.assert_called_once_with("torrent1", "murid_pending")
