"""The small library contract used by orchestration."""

from typing import Protocol

from ..domain.book import Book
from ..domain.book_matcher import BookMatcher


class LibraryError(Exception):
    """A library could not be read or an import could not be completed."""


class LibraryImportPending(LibraryError):
    """Content was copied, but ingestion must be verified on a subsequent run."""


class Library(Protocol):
    """List usable books, check presence, and import a completed download."""

    name: str

    def get_books(self) -> set[Book]:
        """Read usable library books, raising on lookup failure."""

    def contains_book(self, book: Book, matcher: BookMatcher) -> bool:
        """Check presence in this medium only."""

    def resume_import(self, book: Book, matcher: BookMatcher) -> bool:
        """Verify an existing published import; return False when source files are needed."""

    def import_book(
        self,
        book: Book,
        path: str,
        matcher: BookMatcher,
        *,
        explicit_file: bool = False,
    ) -> None:
        """Import a completed path, or a user-selected file overriding format preferences."""
