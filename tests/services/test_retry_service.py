from types import SimpleNamespace
from unittest.mock import ANY, Mock, call

import pytest

from murid.clients.myanonamouse import MAMError
from murid.domain.book import Book
from murid.domain.book_matcher import BookMatcher
from murid.domain.book_request import BookRequest
from murid.domain.torrent import Torrent, TorrentMetadata
from murid.libraries.calibre import CalibreLibrary
from murid.services.retry_service import RetryRecovery, RetryService
from murid.services.torrent_import import TorrentImportConfig, TorrentImportService


@pytest.fixture
def torrent_client():
    client = Mock()
    client.get_torrents.return_value = []
    return client


@pytest.fixture
def import_service():
    service = Mock()
    service.dry_run = False
    service.last_outcome = "imported"
    service.matcher = BookMatcher()
    return service


@pytest.fixture
def mam():
    return Mock()


@pytest.fixture
def hardcover_books(book):
    return Mock(return_value=[book])


@pytest.fixture
def service(torrent_client, import_service, mam, hardcover_books):
    return RetryService(
        torrent_client=torrent_client,
        import_service=import_service,
        myanonamouse=mam,
        hardcover_books=hardcover_books,
    )


@pytest.fixture
def book():
    return Book(
        title="Dune",
        authors=["Frank Herbert"],
        id=1,
        isbn=[],
        source="hardcover",
    )


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
    torrent_client.get_torrents.return_value = [tagged_torrent("murid,murid-timeout")]

    service.get_book_by_mam_id = Mock(return_value=book)

    import_service.process_torrent.return_value = True
    import_service.library.contains_book.side_effect = [False, True]

    assert service.retry_torrents() == set()

    assert torrent_client.remove_tag.call_args_list == [
        call("torrent1", "murid"),
        call("torrent1", "murid-timeout"),
    ]


def test_retry_torrents_returns_book_while_torrent_is_incomplete(
    service,
    import_service,
    torrent_client,
    book,
):
    torrent_client.get_torrents.return_value = [tagged_torrent("murid,murid-timeout")]

    service.get_book_by_mam_id = Mock(return_value=book)

    import_service.process_torrent.return_value = False
    import_service.library.contains_book.return_value = False

    assert service.retry_torrents() == {BookRequest(book)}

    torrent_client.remove_tag.assert_not_called()


def test_retry_torrents_book_not_found(
    service,
    import_service,
    torrent_client,
):
    torrent_client.get_torrents.return_value = [tagged_torrent("murid,murid-timeout")]

    service.get_book_by_mam_id = Mock(return_value=None)

    assert service.retry_torrents() == set()

    import_service.process_torrent.assert_not_called()
    torrent_client.remove_tag.assert_not_called()


def test_retry_torrents_does_not_import_book_already_in_calibre(
    service, import_service, torrent_client, book
):
    torrent_client.get_torrents.return_value = [tagged_torrent("murid,murid-timeout")]
    service.get_book_by_mam_id = Mock(return_value=book)
    import_service.library.contains_book.return_value = True

    assert service.retry_torrents() == set()

    import_service.process_torrent.assert_not_called()
    assert torrent_client.remove_tag.call_args_list == [
        call("torrent1", "murid"),
        call("torrent1", "murid-timeout"),
    ]


def test_retry_torrents_retains_state_after_failed_import(
    service, import_service, torrent_client, book
):
    torrent_client.get_torrents.return_value = [tagged_torrent("murid,murid-timeout")]
    service.get_book_by_mam_id = Mock(return_value=book)
    import_service.library.contains_book.return_value = False
    import_service.process_torrent.return_value = True
    import_service.last_outcome = "failed"
    assert service.retry_torrents() == {BookRequest(book)}
    assert service.last_result.failed == 1
    torrent_client.remove_tag.assert_not_called()


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
            library=CalibreLibrary(calibre),
            matcher=BookMatcher(),
            notify=Mock(),
        )
    )
    service = RetryService(torrent_client, import_service, mam, lambda: [book])
    torrent_client.get_torrents.return_value = [tagged_torrent("murid,murid-timeout")]
    service.get_book_by_mam_id = Mock(return_value=book)
    monkeypatch.setattr("murid.services.torrent_import.time.sleep", lambda _: None)

    assert service.retry_torrents() == {BookRequest(book)}

    torrent_client.add_tag.assert_called_once_with("torrent1", "murid-import-failed")
    torrent_client.remove_tag.assert_not_called()


def test_retry_torrents_dry_run_does_not_import_or_change_tags(
    service, import_service, torrent_client, book
):
    torrent_client.get_torrents.return_value = [tagged_torrent("murid,murid-timeout")]
    service.get_book_by_mam_id = Mock(return_value=book)
    import_service.library.contains_book.return_value = False
    import_service.dry_run = True

    assert service.retry_torrents() == {BookRequest(book)}

    import_service.process_torrent.assert_not_called()
    torrent_client.remove_tag.assert_not_called()


def tagged_torrent(tags, comment="MID=123", hash="torrent1"):
    return SimpleNamespace(tags=tags, comment=comment, hash=hash)


def test_retry_imports_imports_completed_timeout(service, torrent_client, import_service, book):
    torrent_client.get_torrents.return_value = [tagged_torrent("murid-timeout")]
    service.get_book_by_mam_id = Mock(return_value=book)
    import_service.library.contains_book.side_effect = [False, True]
    import_service.process_torrent.return_value = True

    result = service.retry_imports()

    assert result.imported == 1
    assert result.pending == result.failed == result.skipped == 0
    import_service.process_torrent.assert_called_once_with("torrent1", book)
    torrent_client.remove_tag.assert_called_once_with("torrent1", "murid-timeout")


def test_retry_imports_keeps_failed_tag_on_failure(service, torrent_client, import_service, book):
    torrent_client.get_torrents.return_value = [tagged_torrent("murid-import-failed")]
    service.get_book_by_mam_id = Mock(return_value=book)
    import_service.library.contains_book.return_value = False
    import_service.process_torrent.return_value = True
    import_service.last_outcome = "failed"

    result = service.retry_imports()

    assert result.failed == 1
    torrent_client.remove_tag.assert_not_called()


def test_retry_imports_leaves_incomplete_download_tagged(
    service, torrent_client, import_service, book
):
    torrent_client.get_torrents.return_value = [tagged_torrent("murid-timeout")]
    service.get_book_by_mam_id = Mock(return_value=book)
    import_service.library.contains_book.return_value = False
    import_service.process_torrent.return_value = False

    result = service.retry_imports()

    assert result.pending == 1
    torrent_client.remove_tag.assert_not_called()


def test_retry_imports_clears_tags_when_already_in_calibre(
    service, torrent_client, import_service, book
):
    torrent_client.get_torrents.return_value = [
        tagged_torrent("murid-timeout, murid-import-failed")
    ]
    service.get_book_by_mam_id = Mock(return_value=book)
    import_service.library.contains_book.return_value = True

    result = service.retry_imports()

    assert result.already_present == 1
    import_service.process_torrent.assert_not_called()
    assert {call.args for call in torrent_client.remove_tag.call_args_list} == {
        ("torrent1", "murid-timeout"),
        ("torrent1", "murid-import-failed"),
    }


def test_retry_imports_skips_unknown_torrents(service, torrent_client, import_service):
    torrent_client.get_torrents.return_value = [
        tagged_torrent("other"),
        tagged_torrent("murid-timeout", comment="missing", hash="torrent2"),
        tagged_torrent("murid-import-failed", hash="torrent3"),
    ]
    service.get_book_by_mam_id = Mock(return_value=None)

    result = service.retry_imports()

    assert result.skipped == 2
    service.get_book_by_mam_id.assert_called_once_with(123)
    import_service.process_torrent.assert_not_called()


def test_retry_imports_replaces_timeout_with_failure_tag(
    service, torrent_client, import_service, book
):
    torrent_client.get_torrents.return_value = [tagged_torrent("murid-timeout")]
    service.get_book_by_mam_id = Mock(return_value=book)
    import_service.library.contains_book.return_value = False
    import_service.process_torrent.return_value = True
    import_service.last_outcome = "failed"

    result = service.retry_imports()

    assert result.failed == 1
    torrent_client.remove_tag.assert_not_called()


@pytest.mark.parametrize("completed", [False, True])
def test_restart_recovers_download_interrupted_before_timeout(
    book, mam, completed, qbit_api, torrent_file
):
    from murid.clients.torrent_clients.qbittorrent import Qbittorrent, QbittorrentConfig

    api = qbit_api
    torrents = api.items
    client = Qbittorrent(QbittorrentConfig(api, "murid", False))
    interrupted = TorrentImportService(TorrentImportConfig(client, Mock(), Mock(), Mock()))
    interrupted._wait_for_imports = Mock(side_effect=KeyboardInterrupt)

    with pytest.raises(KeyboardInterrupt):
        interrupted.import_torrents([(torrent_file, book)])

    assert torrents[0].tags == "murid"
    importer = Mock(dry_run=False)
    importer.matcher = BookMatcher()
    importer.last_outcome = "imported"
    importer.library.contains_book.side_effect = [False, True] if completed else [False]
    importer.process_torrent.return_value = completed
    mam_book = Book("Dune", ["Frank Herbert"], 123, [], "myanonamouse")
    mam.search.return_value = [make_torrent(mam_book)]
    restarted = RetryService(client, importer, mam, lambda: [book])

    assert restarted.retry_torrents() == (set() if completed else {BookRequest(book)})
    importer.process_torrent.assert_called_once_with(torrents[0].hash, book)
    assert restarted.last_result.imported == int(completed)
    assert restarted.last_result.pending == int(not completed)
    assert ("murid" in torrents[0].tags) is not completed


@pytest.mark.parametrize("manual", [False, True])
def test_recovery_uses_hardcover_metadata(
    service, torrent_client, import_service, mam, hardcover_books, manual
):
    requested = Book(
        "Children of Dune",
        ["Frank Herbert"],
        42,
        ["9780441104024"],
        "hardcover",
        series="Dune",
        series_number=3,
        alternative_titles=["Les Enfants de Dune"],
        identifiers={"hardcover": "42", "goodreads": ["44492285"]},
        search_alternative_titles=["Children of Dune"],
    )
    hardcover_books.return_value = [requested, requested]
    mam_book = Book("Children of Dune", ["Frank Herbert"], 123, [], "myanonamouse")
    mam.search.return_value = [make_torrent(mam_book)]
    torrent = SimpleNamespace(hash="download", comment="MID=123", tags="murid")
    torrent_client.get_torrents.return_value = [torrent]
    torrent_client.get_torrents_with_tag.side_effect = lambda tag: (
        [torrent] if tag == "murid" else []
    )
    import_service.library.contains_book.side_effect = [False, True]
    import_service.process_torrent.return_value = True
    if manual:
        assert service.retry_imports().imported == 1
    else:
        assert service.retry_torrents() == set()
        assert service.last_result.imported == 1
    import_service.process_torrent.assert_called_once_with("download", requested)
    hardcover_books.assert_called_once_with()
    assert requested.source == "hardcover"


@pytest.mark.parametrize("manual", [False, True])
@pytest.mark.parametrize("matches", ["missing", "ambiguous", "wrong_author"])
def test_unresolved_hardcover_identity_is_skipped(
    service, torrent_client, import_service, mam, book, hardcover_books, manual, matches
):
    if matches == "missing":
        hardcover_books.return_value = []
    elif matches == "ambiguous":
        other = Book("Dune", ["Frank Herbert"], 99, [], "hardcover")
        hardcover_books.return_value = [book, other]
    else:
        hardcover_books.return_value = [Book("Dune", ["Someone Else"], 99, [], "hardcover")]
    mam.search.return_value = [make_torrent(book)]
    torrent = SimpleNamespace(hash="abc", comment="MID=123", tags="murid")
    torrent_client.get_torrents.return_value = [torrent]
    torrent_client.get_torrents_with_tag.return_value = [torrent]
    if manual:
        assert service.retry_imports().skipped == 1
    else:
        assert service.retry_torrents() == set()
        assert service.last_result.skipped == 1
    import_service.process_torrent.assert_not_called()
    torrent_client.remove_tag.assert_not_called()


def test_hardcover_books_are_loaded_once_per_retry_batch(
    service, torrent_client, import_service, mam, book, hardcover_books
):
    torrent_client.get_torrents.return_value = [
        SimpleNamespace(hash="first", comment="MID=123", tags="murid"),
        SimpleNamespace(hash="second", comment="MID=124", tags="murid-timeout"),
    ]
    mam.search.return_value = [make_torrent(book)]
    import_service.library.contains_book.return_value = True
    assert service.retry_imports().already_present == 2
    hardcover_books.assert_called_once_with()
    hardcover_books.return_value = []
    assert service.retry_imports().skipped == 2
    assert hardcover_books.call_count == 2


def test_hardcover_failure_keeps_downloads_tagged(
    service, torrent_client, import_service, mam, book, hardcover_books
):
    from murid.clients.hardcover import HardcoverError

    torrent_client.get_torrents.return_value = [
        SimpleNamespace(hash="abc", comment="MID=123", tags="murid")
    ]
    mam.search.return_value = [make_torrent(book)]
    hardcover_books.side_effect = HardcoverError("unavailable")
    assert service.retry_imports().skipped == 1
    import_service.process_torrent.assert_not_called()
    torrent_client.remove_tag.assert_not_called()


@pytest.mark.parametrize("already_present", [False, True])
def test_manual_retry_handles_pending_tag(
    service, torrent_client, import_service, book, already_present
):
    torrent_client.get_torrents.return_value = [tagged_torrent("murid")]
    service.get_book_by_mam_id = Mock(return_value=book)
    import_service.library.contains_book.side_effect = [True] if already_present else [False, True]
    import_service.process_torrent.return_value = True

    result = service.retry_imports()

    assert result.already_present == int(already_present)
    assert result.imported == int(not already_present)
    torrent_client.remove_tag.assert_called_once_with("torrent1", "murid")


@pytest.mark.parametrize("media", ["ebook", "audiobook"])
def test_filtered_retry_does_not_resolve_or_modify_other_media(service, torrent_client, media):
    other = "audiobook" if media == "ebook" else "ebook"
    torrent_client.get_torrents.return_value = [
        SimpleNamespace(hash="other", tags=f"murid,murid_media_{other},murid_hardcover_42"),
    ]
    service._recovery = RetryRecovery(Mock(), Mock(), media_type=media)
    service._request = Mock(side_effect=AssertionError("Excluded request resolved"))
    result = service.retry_imports()
    assert result == type(result)()
    torrent_client.get_torrents.assert_called_once_with(
        migrate=True, media_type=media, on_error=ANY
    )
    service._request.assert_not_called()
    torrent_client.remove_tag.assert_not_called()


def test_audio_retry_does_not_resolve_legacy_ebook(service, torrent_client):
    torrent_client.get_torrents.return_value = [
        SimpleNamespace(hash="legacy", tags="murid"),
    ]
    service._recovery = RetryRecovery(Mock(), Mock(), media_type="audiobook")
    service._request = Mock(side_effect=AssertionError("Legacy ebook resolved"))
    assert service.retry_imports().skipped == 0
    service._request.assert_not_called()


@pytest.mark.parametrize("stage", ["lookup", "presence", "import", "cleanup"])
@pytest.mark.parametrize("error", [RuntimeError("unexpected"), SystemExit(1)])
def test_retry_error_does_not_stop_next_torrent(
    service, torrent_client, import_service, book, stage, error, caplog
):
    first = SimpleNamespace(hash="bad", tags="murid", comment="")
    second = SimpleNamespace(hash="good", tags="murid", comment="")
    torrent_client.get_torrents.return_value = [first, second]
    request = BookRequest(book)
    service._request = Mock(
        side_effect=[error, request] if stage == "lookup" else [request, request]
    )
    import_service.library.contains_book.return_value = False
    import_service.process_torrent.return_value = True
    if stage == "presence":
        import_service.library.contains_book.side_effect = [error, False]
    elif stage == "import":
        import_service.process_torrent.side_effect = [error, True]
    elif stage == "cleanup":
        torrent_client.remove_tag.side_effect = [error, None]

    incomplete = service.retry_torrents()

    assert service.last_result.imported == 1
    assert service.last_result.skipped == (1 if stage == "lookup" else 0)
    assert service.last_result.failed == (0 if stage == "lookup" else 1)
    assert (request in incomplete) == (stage != "lookup")
    assert ("good", "murid") in [call.args for call in torrent_client.remove_tag.call_args_list]
    assert "retry failed" in caplog.text
