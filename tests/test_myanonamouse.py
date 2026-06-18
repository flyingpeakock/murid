import time
from unittest.mock import patch

import pytest
import requests

from murid import (
    MAMError,
    MyAnonamouse,
    MyAnonamouseQuery,
)
from murid.myanonamouse import parse_size


@pytest.fixture
def mam():
    return MyAnonamouse("fake-cookie")


def test_parse_size_empty():
    assert parse_size("") == 0
    assert parse_size(None) == 0


def test_parse_size_bytes():
    assert parse_size("123 B") == 123


def test_parse_size_mb():
    assert parse_size("10 MB") == 10 * 1024 * 1024


def test_parse_size_gib():
    assert parse_size("1.5 GiB") == int(1.5 * 1024**3)


def test_parse_size_with_comma():
    assert parse_size("1,024 KB") == 1024 * 1024


def test_parse_size_invalid():
    assert parse_size("potato") == 0
    assert parse_size("1 XB") == 0


def test_parse_torrent():
    torrent = MyAnonamouse._parse_torrent(
        {
            "id": "123",
            "title": "Dune",
            "author_info": '{"1":"Frank Herbert"}',
            "isbn": "9780441172719",
            "category": "60",
            "catname": "eBooks",
            "main_cat": "14",
            "size": "10 MB",
            "seeders": "5",
            "leechers": "2",
            "free": "1",
            "vip": "0",
            "dl": "hash123",
            "narrator_info": "{}",
            "series_info": "{}",
            "lang_code": "en",
        }
    )

    assert torrent.book.title == "Dune"
    assert torrent.book.authors == ["Frank Herbert"]
    assert torrent.book.id == 123
    assert torrent.language == "en"

    assert torrent.metadata.category == 60
    assert torrent.metadata.seeders == 5
    assert torrent.metadata.leechers == 2
    assert torrent.metadata.freeleech is True
    assert torrent.metadata.vip is False


def test_search_success(mam):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "data": [
                    {
                        "id": "1",
                        "title": "Dune",
                        "author_info": '{"1":"Frank Herbert"}',
                    }
                ]
            }

    mam.session.request = lambda *a, **k: Response()

    results = mam.search(MyAnonamouseQuery(text="Dune"))

    assert len(results) == 1
    assert results[0].book.title == "Dune"


def test_search_request_error_returns_empty_list(mam):
    def boom(*args, **kwargs):
        raise requests.RequestException("boom")

    mam.session.post = boom

    assert mam.search(MyAnonamouseQuery(text="Dune")) == []


def test_search_missing_data_raises(mam):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"unexpected": True}

    mam.session.request = lambda *a, **k: Response()

    with pytest.raises(MAMError, match="Unexpected response"):
        mam.search(MyAnonamouseQuery(text="Dune"))


def test_search_ebook_title_only(mam):
    captured = {}

    def fake_search(query):
        captured["query"] = query
        return []

    mam.search = fake_search

    mam.search_ebook("Dune")

    assert captured["query"].text == "Dune"


def test_search_ebook_title_and_author(mam):
    captured = {}

    def fake_search(query):
        captured["query"] = query
        return []

    mam.search = fake_search

    mam.search_ebook(
        "Dune",
        "Frank Herbert",
    )

    assert captured["query"].text == "Dune Frank Herbert"


def test_search_ebook_logs_found(mam, caplog):
    mam.search = lambda *a, **k: [object(), object()]

    with caplog.at_level("INFO"):
        mam.search_ebook("Dune")

    assert "Found 2 potential torrents for" in caplog.text


def test_search_ebook_logs_not_found(mam, caplog):
    mam.search = lambda *a, **k: []

    with caplog.at_level("INFO"):
        mam.search_ebook("Dune")

    assert "No potential torrents found for" in caplog.text


def test_parse_torrent_multiple_authors():
    torrent = MyAnonamouse._parse_torrent({"author_info": '{"1":"Author One","2":"Author Two"}'})

    assert torrent.book.authors == [
        "Author One",
        "Author Two",
    ]


def test_search_uses_request_wrapper(mam):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": []}

    called = False

    def fake_request(*args, **kwargs):
        nonlocal called
        called = True
        return Response()

    mam._request = fake_request

    mam.search(MyAnonamouseQuery(text="Dune"))

    assert called


def test_rate_limit_enforced(mam):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": []}

    calls = []

    def fake_request(*args, **kwargs):
        calls.append(time.monotonic())
        return Response()

    mam.session.request = fake_request

    with patch("time.monotonic", side_effect=[0, 0.0, 0.3, 0.3, 0.6, 0.6]):
        with patch("time.sleep") as sleep:
            mam._request("GET", "url")
            mam._request("GET", "url")

    assert sleep.called


def test_book_title_is_string(mam):
    torrent = MyAnonamouse._parse_torrent({"title": 123, "author_info": "{}"})

    assert torrent.book.title == "123"

    torrent = MyAnonamouse._parse_torrent({"title": "123", "author_info": "{}"})
    assert torrent.book.title == "123"
