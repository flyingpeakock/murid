import pytest
import requests

from hardcoverharvester.myanonamouse import (
    MAMError,
    MyAnonamouse,
    parse_size,
)


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

    assert torrent.category == 60
    assert torrent.main_category == 14

    assert torrent.seeders == 5
    assert torrent.leechers == 2

    assert torrent.freeleech is True
    assert torrent.vip is False

    assert torrent.language == "en"


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

    mam.session.post = lambda *a, **k: Response()

    results = mam.search("Dune")

    assert len(results) == 1
    assert results[0].book.title == "Dune"


def test_search_respects_per_page(mam):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "data": [
                    {"id": "1", "title": "A", "author_info": "{}"},
                    {"id": "2", "title": "B", "author_info": "{}"},
                    {"id": "3", "title": "C", "author_info": "{}"},
                ]
            }

    mam.session.post = lambda *a, **k: Response()

    results = mam.search("test", per_page=2)

    assert len(results) == 2


def test_search_request_error_returns_empty_list(mam):
    def boom(*args, **kwargs):
        raise requests.RequestException("boom")

    mam.session.post = boom

    assert mam.search("Dune") == []


def test_search_missing_data_raises(mam):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"unexpected": True}

    mam.session.post = lambda *a, **k: Response()

    with pytest.raises(MAMError, match="Unexpected response"):
        mam.search("Dune")


def test_search_include_description(mam):
    payloads = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": []}

    def fake_post(*args, **kwargs):
        payloads.append(kwargs["json"])
        return Response()

    mam.session.post = fake_post

    mam.search(
        "Dune",
        include_description=True,
    )

    assert payloads[0]["description"] == "true"


def test_get_torrent_found(mam):
    torrent = MyAnonamouse._parse_torrent(
        {
            "id": "123",
            "title": "Dune",
            "author_info": "{}",
        }
    )

    mam.search = lambda *a, **k: [torrent]

    result = mam.get_torrent(123)

    assert result is torrent


def test_get_torrent_not_found(mam):
    mam.search = lambda *a, **k: []

    assert mam.get_torrent(123) is None


def test_search_ebook_title_only(mam):
    captured = {}

    def fake_search(query, **kwargs):
        captured["query"] = query
        captured["kwargs"] = kwargs
        return []

    mam.search = fake_search

    mam.search_ebook("Dune")

    assert captured["query"] == "Dune"
    assert captured["kwargs"]["main_categories"] == [14]


def test_search_ebook_title_and_author(mam):
    captured = {}

    def fake_search(query, **kwargs):
        captured["query"] = query
        return []

    mam.search = fake_search

    mam.search_ebook(
        "Dune",
        "Frank Herbert",
    )

    assert captured["query"] == "Dune Frank Herbert"


def test_search_ebook_logs_found(mam, caplog):
    mam.search = lambda *a, **k: [object(), object()]

    with caplog.at_level("INFO"):
        mam.search_ebook("Dune")

    assert "Found 2 results" in caplog.text


def test_search_ebook_logs_not_found(mam, caplog):
    mam.search = lambda *a, **k: []

    with caplog.at_level("INFO"):
        mam.search_ebook("Dune")

    assert "No results found" in caplog.text


def test_parse_torrent_multiple_authors():
    torrent = MyAnonamouse._parse_torrent({"author_info": '{"1":"Author One","2":"Author Two"}'})

    assert torrent.book.authors == [
        "Author One",
        "Author Two",
    ]
