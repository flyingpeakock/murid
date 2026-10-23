"""A wanted book in a specific medium, independent of its metadata."""

from dataclasses import dataclass
from typing import Literal

from .book import Book

MediaType = Literal["ebook", "audiobook"]


@dataclass(frozen=True, eq=False)
class BookRequest:
    """Identify a Hardcover request by work ID and media type."""

    book: Book
    media_type: MediaType = "ebook"

    def __post_init__(self):
        if self.media_type not in ("ebook", "audiobook"):
            raise ValueError(f"Unknown media type: {self.media_type!r}")

    @property
    def identity(self) -> tuple[int, MediaType]:
        """Stable identity even when metadata differs between lists."""
        return self.book.id, self.media_type

    def __hash__(self):
        return hash(self.identity)

    def __eq__(self, other):
        if not isinstance(other, BookRequest):
            return NotImplemented
        return self.identity == other.identity
