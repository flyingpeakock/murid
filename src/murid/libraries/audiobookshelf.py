"""Audiobook library operations; filesystem import is implemented in a later phase."""

from ..clients.audiobookshelf import Audiobookshelf
from ..domain.book import Book
from ..domain.book_matcher import BookMatcher
from .library import LibraryError


class AudiobookshelfLibrary:
    """Expose only usable audio as library presence."""

    name = "Audiobookshelf"

    def __init__(self, client: Audiobookshelf):
        self.client = client

    def get_books(self) -> set[Book]:
        """Read usable audio items and work-level metadata."""
        return self.client.get_books()

    def contains_book(self, book: Book, matcher: BookMatcher) -> bool:
        """Reuse work matching without ebook-edition identifiers."""
        return any(matcher.is_match(book, candidate) for candidate in self.get_books())

    def import_book(
        self, book: Book, path: str, matcher: BookMatcher, *, explicit_file: bool = False,
    ) -> None:
        """Never send audio paths through the ebook file selector."""
        raise LibraryError("Audiobook import is not supported yet; shared-folder import is pending")
