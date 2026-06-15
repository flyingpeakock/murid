from unittest.mock import MagicMock

import pytest

from hardcoverharvester import Book, Torrent
from hardcoverharvester.hardcoverHarvesterApp import HardcoverHarvesterApp


def make_book(id=1, title="Dune"):
    return Book(id=id, title=title, authors=["Author"], isbn=["123"], source="test")


def make_torrent(book):
    return Torrent(
        book=book,
        category=1,
        category_name="cat",
        main_category=1,
        size=100,
        seeders=1,
        leechers=1,
        freeleech=False,
        vip=False,
        download_hash="abc",
        narrator_info={},
        series_info={},
        language="ENG",
        raw={},
    )


def test_init_hardcover_clients():
    config = MagicMock()
    config.get.return_value = [
        {"api_key": "key1", "id": 1},
        {"api_key": "key2", "id": 2},
    ]

    from hardcoverharvester.hardcoverHarvesterApp import init_hardcover_clients

    clients = init_hardcover_clients(config)

    assert len(clients) == 2


def test_load_config_file_not_found():
    from hardcoverharvester.hardcoverHarvesterApp import load_config

    with pytest.raises(SystemExit):
        load_config("does_not_exist.yaml")


def test_fetch_calibre_books():
    calibre = MagicMock()
    calibre.get_books.return_value = [make_book()]

    app = MagicMock()
    app.calibre = calibre
    app.fetch_calibre_books = HardcoverHarvesterApp.fetch_calibre_books.__get__(app)

    books = app.fetch_calibre_books()

    assert len(books) == 1
    calibre.get_books.assert_called_once()


def test_fetch_hardcover_books():
    client1 = MagicMock()
    client1.get_books.return_value = [make_book(1)]

    client2 = MagicMock()
    client2.get_books.return_value = [make_book(2)]

    app = MagicMock()
    app.hardcover_clients = [client1, client2]

    app.fetch_hardcover_books = HardcoverHarvesterApp.fetch_hardcover_books.__get__(app)

    books = app.fetch_hardcover_books()

    assert len(books) == 2


def test_match_books_delegates():
    matcher = MagicMock()
    matcher.match_books.return_value = [("a", "b", 1.0)]

    app = MagicMock()
    app.matcher = matcher
    app.match_books = HardcoverHarvesterApp.match_books.__get__(app)

    result = app.match_books(["a"], ["b"])

    assert result == [("a", "b", 1.0)]


def test_get_best_torrent_for_book():
    book = make_book()
    torrent_book = make_book()

    torrent = make_torrent(torrent_book)

    matcher = MagicMock()
    matcher.threshold = 0.5
    matcher.best_match.return_value = (torrent_book, 0.9)

    app = MagicMock()
    app.matcher = matcher
    app.get_best_torrent_for_book = HardcoverHarvesterApp.get_best_torrent_for_book.__get__(app)

    result = app.get_best_torrent_for_book(book, [torrent], ["ENG"])

    assert result == torrent


def test_get_best_torrent_for_book_none():
    book = make_book()
    torrent_book = make_book()

    torrent = make_torrent(torrent_book)

    matcher = MagicMock()
    matcher.threshold = 0.9
    matcher.best_match.return_value = (torrent_book, 0.5)

    app = MagicMock()
    app.matcher = matcher
    app.get_best_torrent_for_book = HardcoverHarvesterApp.get_best_torrent_for_book.__get__(app)

    result = app.get_best_torrent_for_book(book, [torrent], ["ENG"])

    assert result is None


def test_handle_torrents_dry_run():
    qbit = MagicMock()

    app = MagicMock()
    app.args = MagicMock(dry_run=True)
    app.qbit = qbit

    app.handle_torrents = HardcoverHarvesterApp.handle_torrents.__get__(app)

    app.handle_torrents([(b"file", make_book())])

    qbit.add_torrent.assert_not_called()


def test_handle_torrents_empty():
    app = MagicMock()
    app.args = MagicMock(dry_run=False)

    app.handle_torrents = HardcoverHarvesterApp.handle_torrents.__get__(app)

    result = app.handle_torrents([])

    assert result is None or result == []


def test_handle_torrents_adds_torrents():
    book = make_book()

    qbit = MagicMock()
    qbit.add_torrent.return_value = "hash123"
    qbit.get_completed_path.return_value = "/books/dune.epub"
    qbit.poll_interval = 0

    calibre = MagicMock()
    calibre.add_book.return_value = None

    app = MagicMock()
    app.args = MagicMock(dry_run=False)
    app.qbit = qbit
    app.calibre = calibre

    app.handle_torrents = HardcoverHarvesterApp.handle_torrents.__get__(app)

    # break loop immediately by removing pending after first iteration
    def fake_get_completed_path(_):
        app.handle_torrents_running = False
        return "/books/dune.epub"

    qbit.get_completed_path.side_effect = fake_get_completed_path

    app.handle_torrents([(b"file", book)])

    qbit.add_torrent.assert_called_once()
    calibre.add_book.assert_called()
