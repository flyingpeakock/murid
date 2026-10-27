"""Request routing and restart recovery across torrent and library boundaries."""

import shutil
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from murid.clients.torrent_clients.qbittorrent import (
    Qbittorrent,
    QbittorrentConfig,
    QbittorrentError,
)
from murid.domain.book import Book
from murid.domain.book_matcher import BookMatcher
from murid.domain.book_request import BookRequest
from murid.domain.torrent_metadata import TorrentMetainfo
from murid.domain.torrent_request import (
    IMPORT_TAGS,
    read_request,
    read_request_tags,
    request_tags,
    write_request_comment,
)
from murid.libraries.audiobook_store import AudiobookStore
from murid.libraries.audiobookshelf import AudiobookLibraryConfig, AudiobookshelfLibrary
from murid.libraries.library import LibraryImportPending
from murid.services.retry_service import RetryRecovery, RetryService
from murid.services.torrent_import import TorrentImportConfig, TorrentImportService


@pytest.fixture
def book():
    return Book("Dune", ["Frank Herbert"], 42, [], "hardcover")


@pytest.mark.parametrize("media", ["ebook", "audiobook"])
def test_initial_add_persists_identity_before_tracking_is_lost(book, media, qbit_api, torrent_file):
    add = qbit_api.torrents_add.side_effect

    def interrupted(**kwargs):
        add(**kwargs)
        raise KeyboardInterrupt

    qbit_api.torrents_add.side_effect = interrupted
    client = Qbittorrent(QbittorrentConfig(qbit_api, "murid", False))
    with pytest.raises(KeyboardInterrupt):
        client.add_torrent(torrent_file, book, media_type=media)
    assert qbit_api.items[0].tags == "murid"
    assert read_request(qbit_api.items[0]) == (media, 42)


@pytest.mark.parametrize(
    "tags",
    [
        {"murid_media_audiobook"},
        {"murid_media_video"},
        {"murid_media_ebook", "murid_media_audiobook", "murid_hardcover_42"},
        {"murid_hardcover_42", "murid_hardcover_43"},
        {"murid_hardcover_0"},
        {"murid_hardcover_bad"},
    ],
)
def test_invalid_identity_is_not_silently_treated_as_an_ebook(tags):
    with pytest.raises(ValueError):
        read_request_tags(tags)
    client = Mock()
    client.get_torrents.return_value = [
        SimpleNamespace(
            hash="hash",
            comment="MID=123",
            tags=",".join(tags | {"murid"}),
        )
    ]
    importer, lookup, mam = Mock(), Mock(), Mock()
    service = RetryService(client, None, mam, Mock(), recovery=RetryRecovery(importer, lookup))
    assert service.retry_imports().skipped == 1
    importer.assert_not_called()
    lookup.assert_not_called()
    mam.search.assert_not_called()
    client.remove_tag.assert_not_called()


@pytest.mark.parametrize("media", ["ebook", "audiobook"])
@pytest.mark.parametrize("outcome", ["imported", "pending", "failed"])
@pytest.mark.parametrize("storage", ["comment", "legacy_tags"])
def test_removed_list_entries_recover_by_id_and_keep_unresolved_tags(book, media, outcome, storage):
    client = Mock()
    tags = {"murid", "murid-timeout", "murid-import-failed"}
    comment = ""
    if storage == "legacy_tags":
        tags |= request_tags(BookRequest(book, media))
    else:
        comment = write_request_comment("", (media, 42))
    client.get_torrents.return_value = [
        SimpleNamespace(hash="hash", tags=",".join(tags), comment=comment)
    ]
    importer = Mock(dry_run=False, last_outcome=outcome)
    importer.library.contains_book.return_value = False
    importer.process_torrent.return_value = True
    route = Mock(return_value=importer)
    lookup = Mock(return_value=book)
    current_lists = Mock(return_value=[])
    mam = Mock()
    service = RetryService(client, None, mam, current_lists, recovery=RetryRecovery(route, lookup))
    unresolved = service.retry_torrents()
    route.assert_called_once_with(media)
    lookup.assert_called_once_with(42)
    current_lists.assert_not_called()
    mam.search.assert_not_called()
    importer.process_torrent.assert_called_once_with("hash", book)
    assert unresolved == (set() if outcome == "imported" else {BookRequest(book, media)})
    assert getattr(service.last_result, outcome) == 1
    if outcome == "imported":
        assert {call.args[1] for call in client.remove_tag.call_args_list} == set(IMPORT_TAGS)
    else:
        client.remove_tag.assert_not_called()


@pytest.mark.parametrize("media", ["ebook", "audiobook"])
def test_recovery_dry_run_never_imports_or_clears_state(book, media):
    client = Mock()
    tags = request_tags(BookRequest(book, media)) | {"murid"}
    client.get_torrents.return_value = [SimpleNamespace(hash="hash", tags=",".join(tags))]
    importer = Mock(dry_run=True)
    importer.library.contains_book.return_value = False
    recovery = RetryRecovery(Mock(return_value=importer), Mock(return_value=book))
    service = RetryService(client, None, Mock(), Mock(), recovery=recovery)
    assert service.retry_torrents() == {BookRequest(book, media)}
    importer.process_torrent.assert_not_called()
    client.remove_tag.assert_not_called()


def test_delayed_audio_ingestion_stays_pending_without_download_timeout(book, monkeypatch):
    client = Mock(poll_interval=0)
    client.add_torrent.return_value = "hash"
    client.get_completed_path.return_value = "/complete"
    library = Mock()
    library.resume_import.return_value = False
    library.import_book.side_effect = LibraryImportPending("scan still running")
    notify = Mock()
    importer = TorrentImportService(
        TorrentImportConfig(
            client,
            library,
            BookMatcher(),
            notify,
            media_type="audiobook",
        )
    )
    monkeypatch.setattr("murid.services.torrent_import.time.sleep", lambda _: None)
    result = importer.import_torrents([(b"torrent", book)])
    assert (result.added, result.imported, result.pending, result.failed) == (1, 0, 1, 0)
    client.remove_tag.assert_not_called()
    client.add_tag.assert_called_once_with("hash", "murid")
    library.contains_book.assert_not_called()
    notify.assert_not_called()


@pytest.mark.parametrize("progress", [1, 0])
@pytest.mark.parametrize("phase", ["copied", "copying"])
def test_real_audio_backend_restarts_with_missing_source_and_no_second_download(
    book, tmp_path, monkeypatch, progress, phase, qbit_api, torrent_file
):
    library_path = tmp_path / "library"
    library_path.mkdir()
    source = tmp_path / "Dune"
    source.mkdir()
    (source / "01.mp3").write_bytes(b"audio")
    clock = {"time": 0, "ingested": False}
    monkeypatch.setattr("time.monotonic", lambda: clock["time"])
    monkeypatch.setattr("time.sleep", lambda seconds: clock.update(time=clock["time"] + seconds))
    abs_client = Mock(library_id="library")
    abs_client.get_library.return_value = {"folders": [{"id": "folder", "fullPath": "/books"}]}
    abs_client.get_libraries.return_value = [abs_client.get_library.return_value]
    abs_client.verify_import.side_effect = lambda *args, **kwargs: clock["ingested"]
    # General presence must never substitute for exact ingestion verification on retries.
    abs_client.get_books.return_value = {book}
    audio = AudiobookshelfLibrary(
        abs_client,
        AudiobookLibraryConfig(
            str(library_path),
            str(tmp_path / "staging"),
            scan_timeout_seconds=1,
        ),
    )
    api = qbit_api
    torrents = api.items
    add = api.torrents_add.side_effect

    def add_with_source(**kwargs):
        result = add(**kwargs)
        torrents[0].content_path = str(source)
        return result

    api.torrents_add.side_effect = add_with_source
    client = Qbittorrent(QbittorrentConfig(api, "murid", False))

    def importer(media):
        assert media == "audiobook"
        return TorrentImportService(
            TorrentImportConfig(
                client,
                audio,
                BookMatcher(),
                Mock(),
                media_type=media,
            )
        )

    first = importer("audiobook").import_torrents([(torrent_file, book)])
    assert first.pending == 1 and first.failed == 0
    # Publication may finish before its new journal phase is persisted.
    store = AudiobookStore(str(library_path), "library", str(tmp_path / "staging"))
    manifest = store.load(book, "folder")
    manifest["phase"] = phase
    store.save(manifest)
    shutil.rmtree(source)
    torrents[0].progress = progress
    monkeypatch.setattr(
        AudiobookStore, "_copy", Mock(side_effect=AssertionError("must not recopy"))
    )
    recovery = RetryRecovery(importer, lambda work_id: book)
    restarted = RetryService(client, None, Mock(), lambda: [], recovery=recovery)
    assert restarted.retry_torrents() == {BookRequest(book, "audiobook")}
    assert "murid" in torrents[0].tags
    clock["ingested"] = True
    assert restarted.retry_imports().imported == 1
    assert torrents[0].tags == ""
    assert read_request(torrents[0]) == ("audiobook", 42)
    assert len(list(library_path.rglob(".murid-import.json"))) == 1
    assert restarted.retry_imports().imported == 0
    api.torrents_add.assert_called_once()
    abs_client.get_books.assert_not_called()


@pytest.mark.parametrize("resuming", [False, True])
def test_verified_audio_import_does_not_check_general_library_presence(book, monkeypatch, resuming):
    client = Mock(poll_interval=0)
    client.get_completed_path.return_value = "/complete"
    library = Mock()
    library.resume_import.return_value = resuming
    library.contains_book.side_effect = AssertionError("Must not reread the library")
    notify = Mock()
    importer = TorrentImportService(
        TorrentImportConfig(client, library, BookMatcher(), notify, media_type="audiobook")
    )
    monkeypatch.setattr("murid.services.torrent_import.time.sleep", lambda _: None)

    assert importer.process_torrent("hash", book)
    assert importer.last_outcome == "imported"
    if resuming:
        library.import_book.assert_not_called()
        client.get_completed_path.assert_not_called()
    else:
        library.import_book.assert_called_once_with(book, "/complete", importer.matcher)
    library.contains_book.assert_not_called()
    notify.assert_called_once()
    client.add_tag.assert_not_called()


@pytest.mark.parametrize(
    "other_tags",
    [
        "murid,murid_media_audiobook,murid_media_ebook,murid_hardcover_42",
        "murid,murid_media_audiobook,murid_hardcover_42,murid_hardcover_99",
        "murid,murid_media_audiobook",
        "murid,murid_hardcover_42",
    ],
)
def test_adding_shared_or_unidentified_torrent_cannot_start_import(
    book, other_tags, qbit_api, torrent_file
):
    api = qbit_api
    api.items = [
        SimpleNamespace(
            hash=TorrentMetainfo(torrent_file).hashes[0],
            category="murid",
            comment="",
            tags=other_tags,
        )
    ]
    client = Qbittorrent(QbittorrentConfig(api, "murid", False))
    with pytest.raises(QbittorrentError):
        client.add_torrent(torrent_file, book, media_type="audiobook")
    api.torrents_add.assert_not_called()


def test_conflicting_shared_hash_rejects_only_conflicting_work(
    book, qbit_api, torrent_file
):
    api = qbit_api
    client = Qbittorrent(QbittorrentConfig(api, "murid", False))
    library = Mock()
    library.resume_import.return_value = False
    importer = TorrentImportService(TorrentImportConfig(client, library, BookMatcher(), Mock()))
    other = Book("Dune Messiah", book.authors, 99, [], "hardcover")
    result = importer.import_torrents([(torrent_file, book), (torrent_file, other)])
    assert (result.added, result.imported, result.failed) == (1, 1, 1)
    library.import_book.assert_called_once_with(book, "/downloads/Dune", importer.matcher)
    assert read_request(api.items[0]) == ("ebook", 42)
    api.torrents_add.assert_called_once()
