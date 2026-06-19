"""Synchronization service for Murid."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from ..clients.calibre import Calibre
from ..clients.hardcover import Hardcover
from ..domain.book import Book
from ..domain.book_matcher import BookMatcher
from .torrent_discovery import TorrentDiscoveryService

logger = logging.getLogger("murid")


class SyncService:
    """Service responsible for orchestrating the synchronization process"""

    def __init__(self, factory) -> None:
        """Initializes the synchronization service."""
        self.factory = factory

    def start_scheduler(self) -> None:
        """Start the scheduler to run the synchronization process at regular intervals."""
        base_time = datetime.now()
        cron_iter = self.factory.cron_iter(base_time)

        next_run = cron_iter.get_next(datetime)

        while True:
            logger.info("Next murid cycle scheduled for %s", next_run)
            while True:
                now = datetime.now()
                if now >= next_run:
                    break
                time.sleep(max(1, (next_run - now).total_seconds() / 2))

            self.run()
            next_run = cron_iter.get_next(datetime)

    def run(self) -> None:
        """Run the synchronization process."""
        logger.info("Starting murid cycle")

        calibre = self.factory.calibre()
        calibre_books = self.fetch_calibre_books(calibre)

        hardcover = self.factory.hardcover()
        hardcover_books = self.fetch_hardcover_books(hardcover)

        matcher = self.factory.matcher()
        present_books = self.match_books(calibre_books, hardcover_books, matcher)

        torrent_discovery = self.factory.torrent_discovery()
        wanted_torrents = self.process_books(
            present_books, hardcover_books, torrent_discovery, matcher
        )

        torrent_import = self.factory.torrent_import()
        torrent_import.import_torrents(wanted_torrents)

        logger.info("Finished murid cycle")

    @staticmethod
    def fetch_calibre_books(calibre: Calibre) -> list[Book]:
        """Fetch books from the Calibre library."""
        books = calibre.get_books()
        logger.info("Feched %d books from Calibre database", len(books))
        return books

    @staticmethod
    def fetch_hardcover_books(hardcover: list[Hardcover]) -> list[Book]:
        """Fetch books from the Hardcover API."""
        with ThreadPoolExecutor(max_workers=min(10, len(hardcover))) as executor:
            results = executor.map(lambda client: client.get_books(), hardcover)
        books = [book for result in results for book in result]
        logger.info("Fetched %d books from Hardcover API", len(books))
        return books

    @staticmethod
    def match_books(
        calibre_books: list[Book],
        hardcover_books: list[Book],
        matcher: BookMatcher,
    ) -> list[tuple[Book, Book, float]]:
        """Match books from the Hardcover list against the Calibre library."""
        matches = matcher.match_books(calibre_books, hardcover_books)
        logger.debug("%d books already present in Calibre library", len(matches))
        return matches

    @staticmethod
    def process_books(
        present_books: list[tuple[Book, Book, float]],
        wanted_books: list[Book],
        torrent_discovery: TorrentDiscoveryService,
        matcher: BookMatcher,
    ) -> list[tuple[bytes, Book]]:
        """Process the matched and unmatched books to find torrents for the missing ones."""
        matched_ids = {h.id for _, h, _ in present_books}
        missing_books = [h for h in wanted_books if h.id not in matched_ids]

        if not missing_books:
            return []
        return torrent_discovery.download_torrents(missing_books, matcher)
