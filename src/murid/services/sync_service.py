"""Synchronization service for Murid."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from itertools import chain
from typing import Iterable

from ..clients.calibre import Calibre
from ..clients.hardcover import Hardcover
from ..domain.book import Book
from ..domain.book_matcher import BookMatcher, MatchReview
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

            logger.info("Starting murid cycle")
            try:
                # Reload configuration before each run to pick up any changes.
                self.factory.reload()
                self.run()
            except (Exception, SystemExit):  # pylint: disable=broad-exception-caught
                # Client initialization and configuration loading can raise SystemExit.
                # In scheduled mode, keep the process alive so a later cycle can recover.
                logger.exception("Murid cycle failed; it will retry at the next scheduled run")
            else:
                logger.info("Finished murid cycle")
            # Start the next interval from now so missed cron slots are skipped instead
            # of causing immediate back-to-back runs.
            cron_iter = self.factory.cron_iter(datetime.now())
            next_run = cron_iter.get_next(datetime)

    def run(self) -> None:
        """Run the synchronization process."""
        retry_service = self.factory.retry_service()
        incomplete_timed_out_books = retry_service.retry_torrents()

        matcher = self.factory.matcher()

        wanted_books = self.get_wanted_books(matcher)
        if not wanted_books:
            logger.info("No books missing from Calibre library; nothing to do")
            return

        torrent_discovery = self.factory.torrent_discovery()
        wanted_torrents = self.process_books(
            wanted_books,
            torrent_discovery,
            matcher,
            incomplete_timed_out_books,
        )

        torrent_import = self.factory.torrent_import()
        torrent_import.import_torrents(wanted_torrents)

    def get_wanted_books(self, matcher: BookMatcher) -> set[Book]:
        """Get the list of books that are wanted (i.e., not present in Calibre)."""
        calibre = self.factory.calibre()
        calibre_books = self.fetch_calibre_books(calibre)

        hardcover = self.factory.hardcover()
        hardcover_books = self.fetch_hardcover_books(hardcover)

        assigned_matches = self.match_books(calibre_books, hardcover_books, matcher)

        matched_ids = {hardcover.id for _, hardcover, _ in assigned_matches}
        wanted_books = {book for book in hardcover_books if book.id not in matched_ids}

        return wanted_books

    def list_missing(self, matcher: BookMatcher) -> None:
        """Print Hardcover books missing from the Calibre library."""
        missing_books = self.get_wanted_books(matcher)
        if not missing_books:
            print("No books are missing from the Calibre library.")
            return
        print("Books missing from the Calibre library:")
        for book in sorted(missing_books, key=lambda book: (book.title.casefold(), book.id)):
            print(f"- {book}")

    def review_matches(self, matcher: BookMatcher, matched: bool | None = None) -> None:
        """Print comparisons, optionally filtering by whether a candidate is accepted."""
        calibre_books = self.fetch_calibre_books(self.factory.calibre())
        hardcover_books = self.fetch_hardcover_books(self.factory.hardcover())
        reviews = matcher.review_matches(calibre_books, hardcover_books)
        print(f"Match threshold: {matcher.threshold:.3f}")

        for hardcover_book, candidates in sorted(
            reviews, key=lambda item: (item[0].title.casefold(), item[0].id)
        ):
            accepted = any(candidate.accepted for candidate in candidates)
            if matched is not None and accepted != matched:
                continue
            print(f"\n{self._format_match_review(hardcover_book, candidates)}")

    @staticmethod
    def _format_match_review(
        hardcover_book: Book,
        candidates: list[MatchReview],
    ) -> str:
        """Format one Hardcover book and its relevant Calibre candidates."""
        lines = [f"Hardcover: {hardcover_book}"]
        if not candidates:
            return "\n".join((*lines, "  No Calibre candidates."))

        ambiguous = len(candidates) > 1 and candidates[0].score - candidates[1].score <= 0.02
        for index, candidate in enumerate(candidates):
            near_best = candidates[0].score - candidate.score <= 0.02
            if index > 0 and not near_best and not candidate.accepted:
                continue
            status = "MATCH" if candidate.accepted else "candidate"
            if ambiguous and near_best:
                status += ", ambiguous"
            lines.append(f"  {status}: {candidate.calibre_book} [score={candidate.score:.3f}]")
            lines.append(f"    Evidence: {'; '.join(candidate.evidence)}")
        if not any(candidate.accepted for candidate in candidates):
            lines.append("  No Calibre match was assigned.")
        return "\n".join(lines)

    @staticmethod
    def fetch_calibre_books(calibre: Calibre) -> set[Book]:
        """Fetch books from the Calibre library."""
        books = calibre.get_books()
        logger.debug("Calibre library contains %d books", len(books))
        return books

    @staticmethod
    def fetch_hardcover_books(hardcover: list[Hardcover]) -> set[Book]:
        """Fetch books from the Hardcover API."""
        with ThreadPoolExecutor(max_workers=min(10, len(hardcover))) as executor:
            results = executor.map(lambda client: client.get_books(), hardcover)
            books = set(chain.from_iterable(results))
        logger.debug("Hardcover library contains %d books", len(books))
        return books

    @staticmethod
    def match_books(
        calibre_books: Iterable[Book],
        hardcover_books: Iterable[Book],
        matcher: BookMatcher,
    ) -> set[tuple[Book, Book, float]]:
        """Match books from the Hardcover list against the Calibre library."""
        logger.info("Determining which Hardcover books need to be downloaded")
        matches = matcher.match_books(calibre_books, hardcover_books)
        logger.debug("%d books already present in Calibre library", len(matches))
        return matches

    @staticmethod
    def process_books(
        wanted_books: Iterable[Book],
        torrent_discovery: TorrentDiscoveryService,
        matcher: BookMatcher,
        incomplete_timed_out_books: Iterable[Book] = (),
    ) -> set[tuple[bytes, Book]]:
        """Process the matched and unmatched books to find torrents for the missing ones."""

        if not wanted_books:
            return set()
        return torrent_discovery.download_torrents(
            wanted_books, matcher, incomplete_timed_out_books
        )
