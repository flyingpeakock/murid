from concurrent.futures import Future, ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from murid import TorrentDiscoveryService


@pytest.fixture
def mam():
    return Mock()


@pytest.fixture
def matcher():
    return Mock()


def test_find_torrents_sets_series_and_returns(mam):
    book = SimpleNamespace(
        title="Dune",
        authors=["Frank Herbert"],
        series="Dune Saga",
        series_number=1,
    )

    torrent_book = SimpleNamespace(series=None, series_number=None)
    torrent = SimpleNamespace(book=torrent_book)

    mam.search_ebook.return_value = [torrent]

    service = TorrentDiscoveryService(mam, ["eng"], None)

    result_book, torrents = service.find_torrents(book)

    assert result_book == book
    assert torrents == [torrent]

    mam.search_ebook.assert_called_once_with("Dune", "Frank Herbert")

    assert torrent.book.series == "Dune Saga"
    assert torrent.book.series_number == 1


def test_collect_downloads_filters_none():
    service = TorrentDiscoveryService(Mock(), [], None)

    future1 = Future()
    future1.set_result(b"file1")

    future2 = Future()
    future2.set_result(None)

    book1 = SimpleNamespace(title="A")
    book2 = SimpleNamespace(title="B")

    download_futures = {
        future1: book1,
        future2: book2,
    }

    result = service.collect_downloads(download_futures)

    assert result == [(b"file1", book1)]


def test_submit_downloads_happy_path(mam, matcher):
    service = TorrentDiscoveryService(mam, ["eng"], None)
    service.torrent_selector = SimpleNamespace(select=lambda *a, **k: torrent)

    book = SimpleNamespace(title="Dune", authors=["Frank"])
    torrent_book = SimpleNamespace()
    torrent = SimpleNamespace(book=torrent_book)

    search_future = Future()
    search_future.set_result((book, [torrent]))

    search_futures = {search_future: book}

    executor = ThreadPoolExecutor(max_workers=1)

    mam.download_torrent = Mock(return_value=b"torrent-file")

    result = service.submit_downloads(executor, search_futures, matcher)

    assert len(result) == 1
    future = list(result.keys())[0]
    assert result[future] == torrent_book


def test_submit_downloads_skips_empty():
    service = TorrentDiscoveryService(Mock(), [], None)

    book = SimpleNamespace(title="Dune")

    search_future = Future()
    search_future.set_result((book, []))

    executor = ThreadPoolExecutor(max_workers=1)

    result = service.submit_downloads(executor, {search_future: book}, Mock())

    assert result == {}


def test_submit_downloads_rejected_by_selector(mam):
    service = TorrentDiscoveryService(mam, ["eng"], None)
    service.torrent_selector = SimpleNamespace(select=lambda *a, **k: None)

    book = SimpleNamespace(title="Dune")
    torrent = SimpleNamespace(book=SimpleNamespace())

    search_future = Future()
    search_future.set_result((book, [torrent]))

    executor = ThreadPoolExecutor(max_workers=1)

    result = service.submit_downloads(executor, {search_future: book}, Mock())

    assert result == {}

def test_download_torrents_happy_path(mam, matcher):
    service = TorrentDiscoveryService(mam, ["eng"], None)
    service.find_torrents = Mock(return_value=(SimpleNamespace(), ["torrent"]))
    service.submit_downloads = Mock(return_value={"future": "torrent"})
    service.collect_downloads = Mock(return_value=[(b"file", SimpleNamespace())])

    books = [SimpleNamespace(title="Dune")]

    result = service.download_torrents(books, matcher)

    assert result == [(b"file", SimpleNamespace())]
