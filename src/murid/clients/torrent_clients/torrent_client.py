"""Abstract base class for torrent clients."""

from abc import ABC, abstractmethod

from ...domain.book import Book


class TorrentClient(ABC):
    """Abstract base class for torrent clients."""

    poll_interval: int

    @abstractmethod
    def add_torrent(self, torrent_file: bytes, book: Book) -> str | None:
        """Add a torrent to the client and return its ID."""

    @abstractmethod
    def get_completed_path(self, torrent_id: str) -> str | None:
        """Get the completed path of a torrent by its ID.

        Returns the path if the torrent is completed, or None if it's not yet completed."""

    @abstractmethod
    def add_tag(self, torrent_id: str, tag: str):
        """Add a tag to a torrent by its ID."""
