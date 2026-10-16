import logging
from unittest.mock import Mock

import pytest
import requests

from murid.clients.hardcover import Hardcover, HardcoverError, HardcoverUser


@pytest.fixture
def hardcover():
    return Hardcover("api-key", HardcoverUser(id=123, name="Test User"))


def test_extract_isbn_none():
    assert Hardcover._extract_isbn(None) == []


def test_extract_isbn_empty():
    assert Hardcover._extract_isbn([]) == []


def test_extract_isbn_returns_both_isbn_10_and_isbn_13():
    editions = [
        {
            "isbn_10": "1234567890",
            "isbn_13": "9781234567890",
        }
    ]

    assert Hardcover._extract_isbn(editions) == ["9781234567890", "1234567890"]


def test_extract_isbn_falls_back_to_isbn10():
    editions = [
        {
            "isbn_10": "1234567890",
            "isbn_13": None,
        }
    ]

    assert Hardcover._extract_isbn(editions) == ["1234567890"]


def test_extract_isbn_skips_invalid_editions():
    editions = [
        {"isbn_10": None, "isbn_13": None},
        {"isbn_10": "1234567890"},
    ]

    assert Hardcover._extract_isbn(editions) == ["1234567890"]


def test_fetch_data_success(hardcover):
    response = Mock()
    response.json.return_value = {"data": {}}
    response.raise_for_status.return_value = None

    hardcover._session.post = Mock(return_value=response)

    data = hardcover.fetch_data()

    assert data == {"data": {}}


def test_fetch_data_http_error(hardcover):
    hardcover._session.post = Mock(side_effect=requests.RequestException("boom"))

    with pytest.raises(HardcoverError, match="Error making query to Hardcover API: boom"):
        hardcover.fetch_data()


def test_fetch_data_graphql_error(hardcover):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"errors": ["something broke"]}

    hardcover._session.post = Mock(return_value=response)

    with pytest.raises(HardcoverError, match="GraphQL errors"):
        hardcover.fetch_data()


def test_get_books_empty(hardcover, caplog):
    hardcover.fetch_data = Mock(return_value={"data": {"user_books": []}})

    with caplog.at_level(logging.WARNING):
        books = hardcover.get_books()

    assert books == set()
    assert "No books found" in caplog.text


def test_get_books_single_book(hardcover):
    hardcover.fetch_data = Mock(
        return_value={
            "data": {
                "user_books": [
                    {
                        "book": {
                            "id": 1,
                            "title": "Dune",
                            "contributions": [{"author": {"name": "Frank Herbert"}}],
                            "editions": [{"isbn_13": "9780441172719"}],
                        }
                    }
                ]
            }
        }
    )

    books = hardcover.get_books()

    assert len(books) == 1

    book = next(iter(books))
    assert book.id == 1
    assert book.title == "Dune"
    assert book.authors == ["Frank Herbert"]
    assert book.isbn == ["9780441172719"]


def test_extract_alternative_titles_and_identifiers():
    book_data = {
        "title": "Harry Potter and the Philosopher's Stone",
        "subtitle": "A Novel",
        "alternative_titles": {"en-US": "Harry Potter and the Sorcerer's Stone"},
        "book_mappings": [{"external_id": "goodreads-book-id", "platform": {"name": "Goodreads"}}],
    }
    editions = [
        {
            "title": "Harry Potter and the Sorcerer's Stone",
            "subtitle": None,
            "alternative_titles": ["Harry Potter: The US Edition"],
            "isbn_13": "9780439064866",
            "isbn_10": None,
            "asin": "B000FC1SCC",
            "book_mappings": [
                {"external_id": "open-library-id", "platform": {"name": "Open Library"}}
            ],
        }
    ]

    alternatives = Hardcover._extract_alternative_titles(book_data, editions)
    identifiers = Hardcover._extract_identifiers(book_data, editions)

    assert "Harry Potter and the Sorcerer's Stone" in alternatives
    assert "Harry Potter and the Philosopher's Stone: A Novel" in alternatives
    assert "Harry Potter: The US Edition" in alternatives
    assert identifiers == {
        "Goodreads": ["goodreads-book-id"],
        "Amazon": ["B000FC1SCC"],
        "Open Library": ["open-library-id"],
    }


def test_fetch_data_requests_match_metadata(hardcover):
    response = Mock()
    response.json.return_value = {"data": {}}
    response.raise_for_status.return_value = None
    hardcover._session.post = Mock(return_value=response)

    hardcover.fetch_data()

    query = hardcover._session.post.call_args.kwargs["json"]["query"]
    assert "alternative_titles" in query
    assert "book_mappings" in query
    assert "platform {" in query
    assert "asin" in query


def test_get_books_multiple_authors(hardcover):
    hardcover.fetch_data = Mock(
        return_value={
            "data": {
                "user_books": [
                    {
                        "book": {
                            "id": 1,
                            "title": "Good Omens",
                            "contributions": [
                                {"author": {"name": "Neil Gaiman"}},
                                {"author": {"name": "Terry Pratchett"}},
                            ],
                            "editions": [],
                        }
                    }
                ]
            }
        }
    )

    books = hardcover.get_books()
    book = next(iter(books))
    assert book.authors == [
        "Neil Gaiman",
        "Terry Pratchett",
    ]


def test_get_books_ignores_missing_author(hardcover):
    hardcover.fetch_data = Mock(
        return_value={
            "data": {
                "user_books": [
                    {
                        "book": {
                            "id": 1,
                            "title": "Book",
                            "contributions": [
                                {"author": None},
                                {"author": {"name": "Real Author"}},
                            ],
                            "editions": [],
                        }
                    }
                ]
            }
        }
    )

    books = hardcover.get_books()
    book = next(iter(books))
    assert book.authors == ["Real Author"]


def test_get_books_without_isbn(hardcover):
    hardcover.fetch_data = Mock(
        return_value={
            "data": {
                "user_books": [
                    {
                        "book": {
                            "id": 1,
                            "title": "Book",
                            "contributions": [],
                            "editions": [],
                        }
                    }
                ]
            }
        }
    )

    books = hardcover.get_books()
    book = next(iter(books))
    assert book.isbn == []


@pytest.mark.parametrize("error", [requests.RequestException("offline"), None])
def test_get_books_propagates_api_failure(hardcover, error):
    if error:
        hardcover._session.post = Mock(side_effect=error)
    else:
        response = Mock()
        response.json.return_value = {"errors": ["unavailable"]}
        hardcover._session.post = Mock(return_value=response)
    with pytest.raises(HardcoverError):
        hardcover.get_books()
