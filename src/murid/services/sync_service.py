"""Synchronization service for Murid."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from itertools import chain
from typing import Iterable

from ..clients.calibre import Calibre
from ..clients.hardcover import Hardcover
from ..domain.book import Book
from ..domain.book_matcher import BookMatcher, MatchReview
from ..ui import book_data, colored, labeled, match_review, output
from .torrent_discovery import TorrentDiscoveryService
from .torrent_import import ImportResult

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
                success = self.run()
            except (Exception, SystemExit) as error:  # pylint: disable=broad-exception-caught
                # Client initialization and configuration loading can raise SystemExit.
                # In scheduled mode, keep the process alive so a later cycle can recover.
                reason = error.__cause__ if isinstance(error, SystemExit) else error
                logger.error(
                    "Murid cycle failed: %s; retrying at the next scheduled run",
                    reason or "initialization failed",
                    exc_info=logger.isEnabledFor(logging.DEBUG),
                )
            else:
                if success is False:
                    logger.warning("Murid cycle completed with unresolved downloads or imports")
                else:
                    logger.info("Finished murid cycle")
            # Start the next interval from now so missed cron slots are skipped instead
            # of causing immediate back-to-back runs.
            cron_iter = self.factory.cron_iter(datetime.now())
            next_run = cron_iter.get_next(datetime)

    def run(self) -> bool:
        """Run the synchronization process."""
        try:
            return self._run()
        except (Exception, SystemExit):  # pylint: disable=broad-exception-caught
            output(
                labeled("Sync aborted: ", "see the error diagnostic for the cause", "bold red"),
                kind="sync_summary",
                data={"ok": False, "aborted": True},
            )
            raise

    def _run(self) -> bool:
        """Retry earlier downloads, discover missing books, and import available ebooks."""
        retry_service = self.factory.retry_service()
        incomplete_timed_out_books = retry_service.retry_torrents()

        matcher = self.factory.matcher()

        wanted_books = self.get_wanted_books(matcher)
        if not wanted_books:
            logger.info("No books missing from Calibre library; nothing to do")
            return self._summary(0, {}, ImportResult(), retry_service)

        torrent_discovery = self.factory.torrent_discovery()
        wanted_torrents = self.process_books(
            wanted_books,
            torrent_discovery,
            matcher,
            incomplete_timed_out_books,
        )

        torrent_import = self.factory.torrent_import()
        result = torrent_import.import_torrents(wanted_torrents)
        return self._summary(
            len(wanted_books), torrent_discovery.last_counts, result, retry_service
        )

    def _summary(self, missing, discovery, imports, retry_service) -> bool:
        """Report completed work and distinguish unresolved outcomes from success."""
        # Services return counts; absent results from alternate implementations are empty.
        counts = {
            "missing": missing,
            "searched": 0,
            "search_failed": 0,
            "skipped": 0,
            "selected": 0,
            "deferred": 0,
            "added": 0,
            "imported": 0,
            "pending": 0,
            "failed": 0,
            "planned": 0,
        }
        if isinstance(discovery, dict):
            counts.update(discovery)
            counts["deferred"] = discovery.get("skipped", 0)
            counts["skipped"] = 0
        if isinstance(imports, ImportResult):
            for key, value in asdict(imports).items():
                counts[key] += value
        retry = getattr(retry_service, "last_result", None)
        if retry is not None and hasattr(type(retry), "__dataclass_fields__"):
            for key in ("imported", "pending", "failed", "skipped"):
                counts[key] += getattr(retry, key)
        counts["unavailable"] = counts["searched"] - counts["selected"] - counts["search_failed"]
        dry_run = bool(getattr(getattr(self.factory, "args", None), "dry_run", False))
        success = not (
            counts["failed"]
            or counts["skipped"]
            or counts["unavailable"]
            or (counts["pending"] and not dry_run)
        )
        output(
            labeled(
                "Dry-run summary: " if dry_run else "Sync summary: ",
                (
                    f"{counts['imported']} imported, {counts['pending']} pending, "
                    f"{counts['failed']} failed\n"
                    f"  Books: {missing} missing, {counts['searched']} searched, "
                    f"{counts['unavailable']} without a torrent, "
                    f"{counts['search_failed']} searches failed\n"
                    f"  Torrents: {counts['selected']} selected, {counts['added']} added, "
                    f"{counts['planned']} planned\n"
                    f"  Follow-up: {counts['deferred']} searches deferred, "
                    f"{counts['skipped']} lookups skipped"
                ),
                "bold green" if success else "bold yellow",
            ),
            kind="sync_summary",
            data={**counts, "ok": success, "dry_run": dry_run},
        )
        return success

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
            output(
                "[bold green]No books are missing from the Calibre library.[/]",
                kind="missing_summary",
                data={"count": 0},
            )
            return
        output(
            f"[bold yellow]Books missing from the Calibre library: {len(missing_books)}[/]",
            kind="missing_summary",
            data={"count": len(missing_books)},
        )
        for book in sorted(missing_books, key=lambda book: (book.title.casefold(), book.id)):
            output(
                colored(f"- {book}", "cyan"), kind="missing_book", data={"book": book_data(book)}
            )

    def review_matches(self, matcher: BookMatcher, matched: bool | None = None) -> None:
        """Print comparisons, optionally filtering by whether a candidate is accepted."""
        calibre_books = self.fetch_calibre_books(self.factory.calibre())
        hardcover_books = self.fetch_hardcover_books(self.factory.hardcover())
        reviews = matcher.review_matches(calibre_books, hardcover_books)
        output(f"[bold cyan]Match threshold:[/] {matcher.threshold:.3f}")

        shown = 0
        for hardcover_book, candidates in sorted(
            reviews, key=lambda item: (item[0].title.casefold(), item[0].id)
        ):
            accepted = any(candidate.accepted for candidate in candidates)
            if matched is not None and accepted != matched:
                continue
            shown += 1
            output()
            output(
                match_review(self._format_match_review(hardcover_book, candidates)),
                kind="match_review",
                data={
                    "book": book_data(hardcover_book),
                    "threshold": matcher.threshold,
                    "matched": accepted,
                    "candidates": [
                        {
                            "book": book_data(candidate.calibre_book),
                            "score": candidate.score,
                            "accepted": candidate.accepted,
                            "evidence": list(candidate.evidence),
                        }
                        for candidate in candidates
                    ],
                },
            )

        output(
            labeled("Match reviews shown: ", str(shown), "bold cyan"),
            kind="review_summary",
            data={"count": shown, "filter_matched": matched, "threshold": matcher.threshold},
        )

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
