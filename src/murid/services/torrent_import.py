"""Service responsible for importing torrents into the torrent client"""

import logging
import time
from dataclasses import dataclass
from typing import Callable, Iterable

import apprise

from ..clients.calibre import Calibre, CalibreError
from ..clients.torrent_clients.torrent_client import TorrentClient
from ..domain.book import Book
from ..domain.book_matcher import BookMatcher

logger = logging.getLogger("murid")


@dataclass
class TorrentImportConfig:
    """Configuration for the TorrentImportService"""

    torrent_client: TorrentClient
    calibre: Calibre
    matcher: BookMatcher
    notify: Callable[[str, str, apprise.NotifyType], None]
    dry_run: bool = False


class TorrentImportService:
    """Service responsible for importing torrents into the torrent client"""

    def __init__(self, config: TorrentImportConfig) -> None:
        """Initialize the TorrentImportService"""
        self.torrent_client = config.torrent_client
        self.notify = config.notify
        self.calibre = config.calibre
        self.dry_run = config.dry_run
        self.matcher = config.matcher

    def import_torrents(self, torrent_files: Iterable[tuple[bytes, Book]]) -> None:
        """Import the given torrent files into the torrent client and track their completion."""
        if not torrent_files:
            logger.info("No torrents to import")
            return

        logger.info("Handling %d torrents", len(torrent_files))

        if self.dry_run:
            logger.info("Dry run enabled, not adding any torrents to torrent client")
            for _, book in torrent_files:
                logger.info("Would add %s to torrent client", book)
            return

        pending = {}  # torrent_id -> book

        for torrent_file, book in torrent_files:
            torrent_id = self.torrent_client.add_torrent(torrent_file, book)
            if torrent_id:
                pending[torrent_id] = book
        if not pending:
            logger.warning("No torrents were successfully added to the torrent client")
            return

        logger.info("Tracking %d torrents for completion", len(pending))

        while pending:
            completed = []

            for torrent_id, book in pending.items():
                if self.process_torrent(torrent_id, book):
                    completed.append(torrent_id)

            for tid in completed:
                pending.pop(tid, None)

            if pending:
                logger.debug("%d torrents still active", len(pending))
                time.sleep(self.torrent_client.poll_interval)

    def process_torrent(self, torrent_id: str, book: Book) -> bool:
        """Check if the torrent with the given ID is completed and import it into Calibre."""
        path = self.torrent_client.get_completed_path(torrent_id)
        if not path:
            return False
        try:
            time.sleep(0.5)  # Give the torrent client a moment to move the files
            path = self.torrent_client.get_completed_path(torrent_id)
            self.calibre.add_book(book, path)
            if self.calibre.contains_book(book, self.matcher):
                message = f"Successfully imported {book} into Calibre"
                logger.info(message)
                self.notify(title="Book Imported", body=message)
            else:
                logger.error(
                    "Failed to verify import of %s into Calibre."
                    "\nManual intervention is likely required.",
                    book,
                )
                self.torrent_client.add_tag(torrent_id, "import_failed")
        except CalibreError:
            logger.error("Error importing %s into Calibre", book)
            self.torrent_client.add_tag(torrent_id, "import_failed")

        return True
