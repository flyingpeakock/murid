from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from murid.clients.hardcover import HardcoverError
from murid.domain.book import Book
from murid.domain.book_matcher import BookMatcher
from murid.domain.book_request import BookRequest
from murid.libraries.library import LibraryError
from murid.services.sync_service import SyncService


class FakeBook:
    def __init__(self, title, authors=None, series=None, series_number=None, id=1):
        self.title = title
        self.authors = authors or []
        self.series = series
        self.series_number = series_number
        self.id = id


@pytest.fixture
def factory():
    return SimpleNamespace(
        cron_iter=Mock(),
        library=Mock(),
        wanted_requests=Mock(),
        require_ebook_workflow=Mock(),
        matcher=Mock(),
        torrent_discovery=Mock(),
        torrent_import=Mock(),
        retry_service=Mock(),
    )


@pytest.mark.parametrize("present", ["ebook", "audiobook"])
def test_each_request_uses_only_its_own_library(factory, present):
    book = Book("Dune", ["Frank Herbert"], 42, [], "hardcover")
    requests = {BookRequest(book), BookRequest(book, "audiobook")}
    factory.wanted_requests.return_value = requests
    libraries = {
        media: Mock(get_books=Mock(return_value={book} if media == present else set()))
        for media in ("ebook", "audiobook")
    }
    factory.library.side_effect = libraries.__getitem__
    missing = SyncService(factory).get_wanted_requests(BookMatcher())
    assert {r.media_type for r in missing} == ({"ebook", "audiobook"} - {present})
    for library in libraries.values():
        library.get_books.assert_called_once_with()


def test_failed_library_lookup_never_produces_missing_output(factory, capsys):
    book = Book("Dune", [], 42, [], "hardcover")
    factory.wanted_requests.return_value = {BookRequest(book, "audiobook")}
    factory.library.return_value.get_books.side_effect = LibraryError("lookup unavailable")
    with pytest.raises(LibraryError, match="lookup unavailable"):
        SyncService(factory).list_missing(BookMatcher())
    assert capsys.readouterr().out == ""


def test_run_orchestrates_pipeline(factory):
    service = SyncService(factory)

    calibre = Mock()
    calibre.get_books.return_value = []

    factory.wanted_requests.return_value = {
        BookRequest(FakeBook(title="Book", authors=["Author"]))
    }

    matcher = Mock()
    matcher.match_books.return_value = []

    torrent_discovery = Mock()
    torrent_discovery.download_torrents.return_value = []
    torrent_discovery.submit_downloads.return_value = {}
    torrent_discovery.collect_downloads.return_value = []

    torrent_import = Mock()

    retry_service = Mock()
    incomplete = FakeBook("Incomplete")
    retry_service.retry_torrents.return_value = {incomplete}

    factory.library.return_value = calibre
    factory.matcher.return_value = matcher
    factory.torrent_discovery.return_value = torrent_discovery
    factory.torrent_import.return_value = torrent_import
    factory.retry_service.return_value = retry_service

    service.run()

    factory.library.assert_called_once_with("ebook")
    factory.wanted_requests.assert_called_once()
    factory.matcher.assert_called_once()
    factory.torrent_discovery.assert_called_once()
    factory.torrent_import.assert_called_once()
    factory.retry_service.assert_called_once()

    torrent_import.import_torrents.assert_called_once()
    torrent_discovery.download_torrents.assert_called_once()
    assert torrent_discovery.download_torrents.call_args.args[2] == {BookRequest(incomplete)}


def test_list_missing_propagates_hardcover_initialization_failure(factory, capsys):
    factory.wanted_requests.side_effect = HardcoverError("API unavailable")

    with pytest.raises(HardcoverError, match="API unavailable"):
        SyncService(factory).list_missing(factory.matcher.return_value)

    assert capsys.readouterr().out == ""


def test_review_filters_follow_one_to_one_assignments(factory, capsys):
    calibre_book = Book(id=1, title="Dune", authors=["Frank Herbert"], isbn=[], source="calibre")
    hardcover_books = [
        Book(id=101, title="Dune", authors=["Frank Herbert"], isbn=[], source="hardcover"),
        Book(id=102, title="Dune", authors=["Frank Herbert"], isbn=[], source="hardcover"),
    ]
    factory.library.return_value.get_books.return_value = {calibre_book}
    factory.library.return_value.name = "Calibre"
    factory.wanted_requests.return_value = {BookRequest(book) for book in hardcover_books}
    service = SyncService(factory)
    matcher = BookMatcher()

    service.review_matches(matcher, matched=True)
    matched_output = capsys.readouterr().out
    service.review_matches(matcher, matched=False)
    unmatched_output = capsys.readouterr().out
    service.list_missing(matcher)
    missing_output = capsys.readouterr().out

    assert matched_output.count("Hardcover: Dune") == 1
    assert "MATCH: Dune" in matched_output
    assert unmatched_output.count("Hardcover: Dune") == 1
    assert "No Calibre match was assigned." in unmatched_output
    assert missing_output.count("- Dune") == 1


@pytest.mark.parametrize("failure", [RuntimeError("reload failed"), SystemExit(1)])
def test_start_scheduler_recovers_from_failed_cycle(monkeypatch, factory, failure):
    service = SyncService(factory)

    stop_scheduler = RuntimeError("stop scheduler test")
    factory.cron_iter.side_effect = [
        SimpleNamespace(get_next=Mock(return_value=1)),
        SimpleNamespace(get_next=Mock(return_value=2)),
        stop_scheduler,
    ]
    factory.reload = Mock(side_effect=[failure, None])
    service.run = Mock()

    monkeypatch.setattr(
        "murid.services.sync_service.datetime",
        SimpleNamespace(now=lambda: 2),
    )
    monkeypatch.setattr("murid.services.sync_service.time.sleep", Mock())

    with pytest.raises(RuntimeError, match="stop scheduler test"):
        service.start_scheduler()

    assert factory.reload.call_count == 2
    service.run.assert_called_once_with()
