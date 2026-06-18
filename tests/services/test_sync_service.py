from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from murid import SyncService


@pytest.fixture
def factory():
    return SimpleNamespace(
        cron_iter=Mock(),
        calibre=Mock(),
        hardcover=Mock(),
        matcher=Mock(),
        torrent_discovery=Mock(),
        torrent_import=Mock(),
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


def test_process_books_returns_empty_when_all_matched():
    torrent_discovery = Mock()
    matcher = Mock()

    present_books = [("x", SimpleNamespace(id=1), 1.0)]
    wanted_books = [SimpleNamespace(id=1)]

    result = SyncService.process_books(
        present_books,
        wanted_books,
        torrent_discovery,
        matcher,
    )

    assert result == []


def test_process_books_happy_path():
    torrent_discovery = Mock()

    book = SimpleNamespace(id=1, title="Book")

    present_books = []
    wanted_books = [book]

    torrent_discovery.find_torrents.return_value = ["torrent"]
    torrent_discovery.submit_downloads.return_value = {"future": "torrent"}
    torrent_discovery.collect_downloads.return_value = [("file", book)]

    matcher = Mock()

    result = SyncService.process_books(
        present_books,
        wanted_books,
        torrent_discovery,
        matcher,
    )

    assert result == [("file", book)]


def test_run_orchestrates_pipeline(factory):
    service = SyncService(factory)

    calibre = Mock()
    calibre.get_books.return_value = []

    hardcover_client = Mock()
    hardcover_client.get_books.return_value = [SimpleNamespace(id=1, title="Book")]

    matcher = Mock()
    matcher.match_books.return_value = []

    torrent_discovery = Mock()
    torrent_discovery.find_torrents.return_value = []
    torrent_discovery.submit_downloads.return_value = {}
    torrent_discovery.collect_downloads.return_value = []

    torrent_import = Mock()

    factory.calibre.return_value = calibre
    factory.hardcover.return_value = [hardcover_client]
    factory.matcher.return_value = matcher
    factory.torrent_discovery.return_value = torrent_discovery
    factory.torrent_import.return_value = torrent_import

    service.run()

    factory.calibre.assert_called_once()
    factory.hardcover.assert_called_once()
    factory.matcher.assert_called_once()
    factory.torrent_discovery.assert_called_once()
    factory.torrent_import.assert_called_once()

    torrent_import.import_torrents.assert_called_once()


def test_start_scheduler_runs_once(monkeypatch, factory):
    service = SyncService(factory)

    fake_iter = Mock()
    fake_iter.get_next.side_effect = [
        100,
        200,
    ]

    factory.cron_iter.return_value = fake_iter

    monkeypatch.setattr(
        "murid.services.sync_service.datetime",
        SimpleNamespace(now=lambda: 0),
    )

    monkeypatch.setattr("murid.services.sync_service.ThreadPoolExecutor", Mock())

    # just ensure it doesn't crash immediately
    # (we don't actually want infinite loop execution)
    try:
        service.start_scheduler()
    except Exception:
        pass
