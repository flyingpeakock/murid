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


def test_default_list_uses_want_to_read_status(hardcover):
    hardcover.make_query = Mock(return_value={"data": {"user_books": []}})
    hardcover.fetch_data()
    query = hardcover.make_query.call_args.args[0]
    assert "status_id: { _eq: 1 }" in query
    assert hardcover.make_query.call_args.kwargs["variables"] == {"user_id": 123}


def test_custom_list_fetches_books_and_preserves_metadata(hardcover):
    hardcover.list_slug = "download-queue"
    hardcover.make_query = Mock(
        return_value={
            "data": {
                "lists": [
                    {
                        "list_books": [
                            {
                                "book": {
                                    "id": 42,
                                    "title": "Dune",
                                    "contributions": [{"author": {"name": "Frank Herbert"}}],
                                    "editions": [{"isbn_13": "9780441172719"}],
                                    "book_series": [{"position": 1, "series": {"name": "Dune"}}],
                                    "alternative_titles": ["Dune Chronicles"],
                                },
                            }
                        ]
                    }
                ]
            }
        }
    )

    (book,) = hardcover.get_books()

    assert (book.id, book.title, book.authors) == (42, "Dune", ["Frank Herbert"])
    assert book.isbn == ["9780441172719"]
    assert book.series == "Dune"
    assert "Dune Chronicles" in book.alternative_titles
    query = hardcover.make_query.call_args.args[0]
    assert "status_id" not in query
    assert "user_id: {_eq: $user_id}" in query
    assert "slug: {_eq: $slug}" in query
    assert "book_mappings" in query
    assert hardcover.make_query.call_args.kwargs["variables"] == {
        "user_id": 123,
        "slug": "download-queue",
        "limit": 100,
        "offset": 0,
    }


def test_custom_list_paginates(hardcover):
    hardcover.list_slug = "large-list"
    rows = [{"book": {"id": i, "title": f"Book {i}"}} for i in range(101)]
    hardcover.make_query = Mock(
        side_effect=[
            {"data": {"lists": [{"list_books": rows[:100]}]}},
            {"data": {"lists": [{"list_books": rows[100:]}]}},
        ]
    )
    assert len(hardcover.get_books()) == 101
    assert [call.kwargs["variables"]["offset"] for call in hardcover.make_query.call_args_list] == [
        0,
        100,
    ]


def test_custom_empty_list_does_not_fall_back(hardcover):
    hardcover.list_slug = "empty"
    hardcover.make_query = Mock(return_value={"data": {"lists": [{"list_books": []}]}})
    assert hardcover.get_books() == set()
    hardcover.make_query.assert_called_once()


def test_custom_missing_list_raises(hardcover):
    hardcover.list_slug = "missing"
    hardcover.make_query = Mock(return_value={"data": {"lists": []}})
    with pytest.raises(HardcoverError, match="Cannot fetch books.*List 'missing'.*not found"):
        hardcover.get_books()
    hardcover.make_query.assert_called_once()


def test_custom_list_api_failure_propagates(hardcover):
    hardcover.list_slug = "private-list"
    hardcover.make_query = Mock(side_effect=HardcoverError("permission denied"))
    with pytest.raises(HardcoverError, match="Cannot fetch books.*permission denied"):
        hardcover.get_books()


def test_get_book_recovers_metadata_without_reading_a_list(hardcover):
    hardcover.make_query = Mock(
        return_value={
            "data": {
                "books": [
                    {
                        "id": 42,
                        "title": "Dune",
                        "contributions": [{"author": {"name": "Frank Herbert"}}],
                        "book_series": [{"position": 0, "series": {"name": "Dune"}}],
                    }
                ]
            }
        }
    )
    book = hardcover.get_book(42)
    assert (book.id, book.source, book.title, book.series_number) == (42, "hardcover", "Dune", 0)
    query = hardcover.make_query.call_args.args[0]
    assert "books(where:" in query and "user_books" not in query
    assert hardcover.make_query.call_args.kwargs["variables"] == {"book_id": 42}


@pytest.mark.parametrize("books", [[], [{"id": 99}], [{"id": 42}, {"id": 43}], "invalid"])
def test_get_book_does_not_substitute_a_different_work(hardcover, books):
    hardcover.make_query = Mock(return_value={"data": {"books": books}})
    if books == []:
        assert hardcover.get_book(42) is None
    else:
        with pytest.raises(HardcoverError):
            hardcover.get_book(42)
