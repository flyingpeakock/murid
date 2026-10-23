from dataclasses import replace

import pytest

from murid.domain.book import Book
from murid.domain.book_request import BookRequest


def test_request_identity_uses_work_and_medium():
    book = Book("Title", ["Author"], 42, [], "Hardcover")
    updated = replace(book, title="New title", isbn=["other-edition"])
    assert len({BookRequest(book), BookRequest(updated), BookRequest(book, "audiobook")}) == 2
    assert BookRequest(book).identity == (42, "ebook")
    assert BookRequest(book) != BookRequest(replace(book, id=43))


def test_unknown_medium_rejected():
    with pytest.raises(ValueError, match="Unknown media type"):
        BookRequest(Book("Title", [], 42, [], "Hardcover"), "video")
