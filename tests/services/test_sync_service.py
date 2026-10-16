from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from murid import Book, BookMatcher, SyncService
from murid.clients.hardcover import HardcoverError


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
        calibre=Mock(),
        hardcover=Mock(),
        matcher=Mock(),
        torrent_discovery=Mock(),
        torrent_import=Mock(),
        retry_service=Mock(),
    )


def test_fetch_calibre_books_logs_and_returns():
    calibre = Mock()
    calibre.get_books.return_value = ["book1", "book2"]

    result = SyncService.fetch_calibre_books(calibre)

    assert result == ["book1", "book2"]
    calibre.get_books.assert_called_once()


def test_fetch_hardcover_books_flattens_results():
    client1 = Mock()
    client1.get_books.return_value = ["a", "b"]

    client2 = Mock()
    client2.get_books.return_value = ["c"]

    result = SyncService.fetch_hardcover_books([client1, client2])

    assert sorted(result) == ["a", "b", "c"]


def test_match_books_calls_matcher():
    matcher = Mock()
    matcher.match_books.return_value = [("match")]

    calibre = ["a"]
    hardcover = ["b"]

    result = SyncService.match_books(calibre, hardcover, matcher)

    assert result == ["match"]
    matcher.match_books.assert_called_once_with(calibre, hardcover)


def test_run_orchestrates_pipeline(factory):
    service = SyncService(factory)

    calibre = Mock()
    calibre.get_books.return_value = []

    hardcover_client = Mock()
    hardcover_client.get_books.return_value = [FakeBook(title="Book", authors=["Author"])]

    matcher = Mock()
    matcher.match_books.return_value = []

    torrent_discovery = Mock()
    torrent_discovery.find_torrents.return_value = []
    torrent_discovery.submit_downloads.return_value = {}
    torrent_discovery.collect_downloads.return_value = []

    torrent_import = Mock()

    retry_service = Mock()
    retry_service.retry_torrents.return_value = {"incomplete-book"}

    factory.calibre.return_value = calibre
    factory.hardcover.return_value = [hardcover_client]
    factory.matcher.return_value = matcher
    factory.torrent_discovery.return_value = torrent_discovery
    factory.torrent_import.return_value = torrent_import
    factory.retry_service.return_value = retry_service

    service.run()

    factory.calibre.assert_called_once()
    factory.hardcover.assert_called_once()
    factory.matcher.assert_called_once()
    factory.torrent_discovery.assert_called_once()
    factory.torrent_import.assert_called_once()
    factory.retry_service.assert_called_once()

    torrent_import.import_torrents.assert_called_once()
    torrent_discovery.download_torrents.assert_called_once()
    assert torrent_discovery.download_torrents.call_args.args[2] == {"incomplete-book"}


def test_list_missing_propagates_hardcover_initialization_failure(factory, capsys):
    factory.calibre.return_value.get_books.return_value = []
    factory.hardcover.side_effect = HardcoverError("API unavailable")

    with pytest.raises(HardcoverError, match="API unavailable"):
        SyncService(factory).list_missing(factory.matcher.return_value)

    assert capsys.readouterr().out == ""


def test_review_filters_follow_one_to_one_assignments(factory, capsys):
    calibre_book = Book(id=1, title="Dune", authors=["Frank Herbert"], isbn=[], source="calibre")
    hardcover_books = [
        Book(id=101, title="Dune", authors=["Frank Herbert"], isbn=[], source="hardcover"),
        Book(id=102, title="Dune", authors=["Frank Herbert"], isbn=[], source="hardcover"),
    ]
    factory.calibre.return_value.get_books.return_value = {calibre_book}
    factory.hardcover.return_value = [SimpleNamespace(get_books=lambda: hardcover_books)]
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
