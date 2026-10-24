"""Import a local ebook or complete audiobook after resolving its Hardcover work."""

from pathlib import Path

from ..domain.book import Book
from ..domain.book_request import MediaType
from .book_lookup import BookLookupError, find_hardcover_book


class ManualImportError(Exception):
    """The requested book or file cannot be imported safely."""


def add_book(name: str, path: str, factory, *, media_type: MediaType = "ebook") -> Book:
    """Resolve a work and import through its library, retaining explicit ebook overrides."""
    file = Path(path).expanduser()
    if media_type == "ebook" and not file.is_file():
        raise ManualImportError(f"Ebook file does not exist or is not a file: {file}")
    matcher = factory.matcher()
    try:
        book = find_hardcover_book(name, factory)
    except BookLookupError as error:
        raise ManualImportError(str(error)) from error
    library = factory.library(media_type)
    resuming = media_type == "audiobook" and library.has_import_state(book)
    if media_type == "audiobook" and not file.exists() and not resuming:
        raise ManualImportError(f"Audiobook source does not exist: {file}")
    if not resuming and library.contains_book(book, matcher):
        raise ManualImportError(f"{book} is already in {library.name}")
    dry_run = bool(getattr(getattr(factory, "args", None), "dry_run", False))
    if media_type == "audiobook" or not dry_run:
        library.import_book(book, str(file), matcher, explicit_file=media_type == "ebook")
    return book
