"""Ebook library operations, including selection within completed downloads."""

from pathlib import Path

from ..clients.calibre import Calibre
from ..domain.book import Book
from ..domain.book_file_selector import BookFileSelector
from ..domain.book_matcher import BookMatcher
from .library import LibraryError


class CalibreLibrary:
    """Adapt the Calibre client to the library contract."""

    name = "Calibre"

    def __init__(self, client: Calibre, filetypes: list[str] | None = None):
        self.client = client
        self.file_selector = BookFileSelector(filetypes)

    def get_books(self) -> set[Book]:
        """Read Calibre metadata without caching failed or stale results."""
        return self.client.get_books()

    def contains_book(self, book: Book, matcher: BookMatcher) -> bool:
        """Check for an existing ebook."""
        return self.client.contains_book(book, matcher)

    def resume_import(self, book: Book, matcher: BookMatcher) -> bool:  # pylint: disable=unused-argument
        """Calibre imports do not have a separate publication journal to resume."""
        return False

    def import_book(
        self,
        book: Book,
        path: str,
        matcher: BookMatcher,
        *,
        explicit_file: bool = False,
    ) -> None:
        """Select one ebook, leaving all source files in place."""
        if explicit_file and not Path(path).is_file():
            raise LibraryError("An explicitly selected ebook path must be an existing file")
        selected = Path(path) if explicit_file else self.file_selector.select(book, path, matcher)
        if selected is None:
            raise LibraryError(
                "could not select a unique ebook file; import an individual ebook "
                "with murid add-book <Hardcover-title> <ebook-file-path>. "
                "After importing, murid retry-import can clear the failed-import tag"
            )
        self.client.add_book(book, str(selected))
