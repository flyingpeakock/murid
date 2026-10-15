from concurrent.futures import Future, ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from murid import TorrentDiscoveryService


class FakeBook:
    def __init__(self, title, authors=None, series=None, series_number=None):
        self.title = title
        self.authors = authors or []
        self.series = series
        self.series_number = series_number


class FakeTorrent:
    def __init__(self, book):
        self.book = book


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
    torrent = Mock()
    torrent.book = torrent_book

    mam.search_ebook.return_value = [torrent]

    service = TorrentDiscoveryService(mam, ["eng"], None)

    result_book, torrents = service.find_torrents(book)

    assert result_book == book
    assert torrents == {torrent}

    mam.search_ebook.assert_called_once_with("Dune")

    assert torrent.book.series == "Dune Saga"
    assert torrent.book.series_number == 1


def test_find_torrents_searches_main_and_alternate_titles_without_author(mam):
    book = SimpleNamespace(
        title="Main title",
        authors=["Author"],
        series=None,
        series_number=None,
        alternative_titles=["Alternate title"],
    )
    torrent = Mock()
    torrent.book = SimpleNamespace(series=None, series_number=None)
    mam.search_ebook.side_effect = [[torrent], []]

    service = TorrentDiscoveryService(mam, ["eng"], None)

    _, torrents = service.find_torrents(book)

    assert torrents == {torrent}
    assert mam.search_ebook.call_args_list == [
        call("Main title"),
        call("Alternate title"),
    ]


def test_collect_downloads_filters_none():
    service = TorrentDiscoveryService(Mock(), [], None)

    future1 = Future()
    future1.set_result(b"file1")

    future2 = Future()
    future2.set_result(None)

    book1 = FakeBook(title="A")
    book2 = FakeBook(title="B")

    download_futures = {
        future1: book1,
        future2: book2,
    }

    result = service.collect_downloads(download_futures)

    assert result == {(b"file1", book1)}


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


def test_submit_downloads_skips_torrent_tagged_import_failed(mam, matcher):
    failed_torrent = Mock()
    failed_torrent.book.id = 123
    available_torrent = Mock()
    available_torrent.book.id = 456

    torrent_client = Mock()
    torrent_client.get_torrents_with_tag.side_effect = lambda tag: (
        [SimpleNamespace(comment="MyAnonamouse MID=123")] if tag == "murid_import_failed" else []
    )
    service = TorrentDiscoveryService(mam, ["eng"], None, torrent_client)
    service.torrent_selector = SimpleNamespace(select=Mock(return_value=available_torrent))
    mam.download_torrent.return_value = b"torrent-file"

    book = SimpleNamespace(title="Dune", authors=["Frank"])
    search_future = Future()
    search_future.set_result((book, {failed_torrent, available_torrent}))

    with ThreadPoolExecutor(max_workers=1) as executor:
        result = service.submit_downloads(executor, {search_future: book}, matcher)

    torrent_client.get_torrents_with_tag.assert_called_once_with("murid_import_failed")
    service.torrent_selector.select.assert_called_once_with(book, {available_torrent}, matcher)
    assert len(result) == 1
    mam.download_torrent.assert_called_once_with(available_torrent)


def test_download_torrents_skips_books_with_incomplete_timed_out_torrent(mam, matcher):
    service = TorrentDiscoveryService(mam, ["eng"], None)
    service.find_torrents = Mock()
    matcher.threshold = 0.9
    matcher.similarity.return_value = 0.99

    book = SimpleNamespace(id=456, title="Dune", authors=["Frank"])
    timed_out_book = SimpleNamespace(id=123, title="Dune", authors=["Frank"])

    result = service.download_torrents([book], matcher, [timed_out_book])

    assert result == set()
    service.find_torrents.assert_not_called()
    mam.search_ebook.assert_not_called()
    matcher.similarity.assert_called_once_with(book, timed_out_book)
    mam.download_torrent.assert_not_called()


def test_submit_downloads_does_not_retry_after_selector_rejects(mam, matcher):
    original_torrent = Mock()
    original_torrent.book.id = 111

    service = TorrentDiscoveryService(mam, ["eng"], None)
    service.torrent_selector = SimpleNamespace(select=Mock(return_value=None))
    book = SimpleNamespace(title="Dune", authors=["Frank"])
    search_future = Future()
    search_future.set_result((book, {original_torrent}))

    with ThreadPoolExecutor(max_workers=1) as executor:
        result = service.submit_downloads(executor, {search_future: book}, matcher)

    assert result == {}
    service.torrent_selector.select.assert_called_once_with(book, {original_torrent}, matcher)
    mam.search_ebook.assert_not_called()
    mam.download_torrent.assert_not_called()


def test_submit_downloads_does_not_repeat_title_searches_when_matcher_rejects(mam, matcher):
    service = TorrentDiscoveryService(mam, ["eng"], None)
    original_torrent = Mock()
    service.torrent_selector = SimpleNamespace(select=Mock(return_value=None))

    book = SimpleNamespace(
        title="Main title",
        authors=["Author"],
        alternative_titles=["Alternate title"],
    )
    search_future = Future()
    search_future.set_result((book, [original_torrent]))

    with ThreadPoolExecutor(max_workers=1) as executor:
        result = service.submit_downloads(executor, {search_future: book}, matcher)
        assert result == {}

    service.torrent_selector.select.assert_called_once_with(book, [original_torrent], matcher)
    mam.search_ebook.assert_not_called()


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
    mam.search_ebook.return_value = []

    book = FakeBook(title="Dune")
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

    books = [SimpleNamespace(id=42, title="Dune")]

    result = service.download_torrents(books, matcher)

    assert result == [(b"file", SimpleNamespace())]
