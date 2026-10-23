"""Import an ebook file after resolving its name against Hardcover."""

from pathlib import Path

from ..domain.book import Book
from .book_lookup import BookLookupError, find_hardcover_book


class ManualImportError(Exception):
    """The requested book or file cannot be imported safely."""


def add_book(name: str, path: str, factory) -> Book:
    """Find one Hardcover book by name and add the selected file to Calibre."""
    file = Path(path).expanduser()
    if not file.is_file():
        raise ManualImportError(f"Ebook file does not exist or is not a file: {file}")

    matcher = factory.matcher()
    try:
        book = find_hardcover_book(name, factory)
    except BookLookupError as error:
        raise ManualImportError(str(error)) from error
    library = factory.library("ebook")
    if library.contains_book(book, matcher):
        raise ManualImportError(f"{book} is already in Calibre")
    library.import_book(book, str(file), matcher, explicit_file=True)
    return book
