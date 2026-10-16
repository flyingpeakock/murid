from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from murid.domain.book import Book
from murid.domain.book_matcher import BookMatcher
from murid.services.manual_import import ManualImportError, add_book


def book(id, title, alternative_titles=None):
    return Book(
        id=id,
        title=title,
        authors=["Frank Herbert"],
        isbn=[],
        source="hardcover",
        alternative_titles=alternative_titles or [],
    )


def factory(books):
    calibre = Mock()
    calibre.contains_book.return_value = False
    return SimpleNamespace(
        matcher=lambda: BookMatcher(0.85),
        hardcover=lambda: [SimpleNamespace(get_books=lambda: books)],
        calibre=lambda: calibre,
    )


def test_add_book_matches_misspelling_and_uses_hardcover_metadata(tmp_path):
    file = tmp_path / "file.epub"
    file.write_bytes(b"ebook")
    matched = book(1, "Children of Dune")
    services = factory({matched})

    result = add_book("Children of Dunee", str(file), services)

    assert result is matched
    services.calibre().add_book.assert_called_once_with(matched, str(file))


def test_add_book_matches_alternative_title(tmp_path):
    file = tmp_path / "file.epub"
    file.write_bytes(b"ebook")
    matched = book(1, "The Long Title", ["A Different Name"])
    services = factory({matched})

    assert add_book("A Different Name", str(file), services) is matched


def test_add_book_rejects_ambiguous_name(tmp_path):
    file = tmp_path / "file.epub"
    file.write_bytes(b"ebook")
    services = factory({book(1, "Dune"), book(2, "Dune", ["Another title"])})

    with pytest.raises(ManualImportError, match="More than one Hardcover book"):
        add_book("Dune", str(file), services)

    services.calibre().add_book.assert_not_called()


def test_add_book_rejects_unknown_name(tmp_path):
    file = tmp_path / "file.epub"
    file.write_bytes(b"ebook")
    services = factory({book(1, "Dune")})

    with pytest.raises(ManualImportError, match="No Hardcover book matched"):
        add_book("Unknown book", str(file), services)

    services.calibre().add_book.assert_not_called()


def test_add_book_rejects_duplicate(tmp_path):
    file = tmp_path / "file.epub"
    file.write_bytes(b"ebook")
    services = factory({book(1, "Dune")})
    services.calibre().contains_book.return_value = True

    with pytest.raises(ManualImportError, match="already in Calibre"):
        add_book("Dune", str(file), services)

    services.calibre().add_book.assert_not_called()


def test_add_book_rejects_missing_file_before_loading_clients(tmp_path):
    services = factory({book(1, "Dune")})

    with pytest.raises(ManualImportError, match="does not exist"):
        add_book("Dune", str(tmp_path / "missing.epub"), services)

    services.calibre().add_book.assert_not_called()
