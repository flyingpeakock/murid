"""Defines the Torrent class"""

from dataclasses import dataclass
from typing import Any

from .book import Book
from .book_request import MediaType


@dataclass
class TorrentMetadata:
    """Represents metadata for a torrent, including its category and size."""

    category: int
    size: int
    seeders: int
    leechers: int
    freeleech: bool
    vip: bool


@dataclass(slots=True)
class Torrent:  # pylint: disable=too-many-instance-attributes
    """Represents a torrent with its metadata and associated book."""

    book: Book
    metadata: TorrentMetadata
    download_hash: str | None = None
    series_info: dict[str, Any] | None = None
    language: str | None = None
    file_types: list[str] | None = None
    raw: dict[str, Any] | None = None
    media_type: MediaType | None = None

    @property
    def download_url(self) -> str | None:
        """Construct the download URL for the torrent based on its download hash."""
        if not self.download_hash:
            return None

        return f"https://www.myanonamouse.net/tor/download.php/{self.download_hash}"

    def __str__(self) -> str:
        """Return a string representation of the torrent as a link to the torrents page."""
        return f"https://www.myanonamouse.net/t/{self.book.id}"

    def __hash__(self) -> int:
        return hash((self.book.source, self.book.id))

    def __eq__(self, other) -> bool:
        if not isinstance(other, Torrent):
            return NotImplemented

        return (self.book.source, self.book.id) == (other.book.source, other.book.id)
