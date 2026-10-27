"""Synchronization service for Murid."""

import logging
import time
from dataclasses import asdict
from datetime import datetime
from typing import Iterable

from ..domain.book import Book
from ..domain.book_matcher import BookMatcher, MatchReview
from ..domain.book_request import BookRequest
from ..ui import book_data, colored, labeled, match_review, output
from .retry_service import RetryImportResult
from .torrent_discovery import TorrentDiscoveryService
from .torrent_import import ImportResult

logger = logging.getLogger("murid")


class SyncService:
    """Service responsible for orchestrating the synchronization process"""

    def __init__(self, factory) -> None:
        """Initializes the synchronization service."""
        self.factory = factory
        self.media_counts = {}

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
        """Retry earlier downloads, discover missing requests, and route completed downloads."""
        self.media_counts = {}
        retry_service = self.factory.retry_service()
        incomplete_requests = retry_service.retry_torrents()
        if isinstance(retry_service.last_result, RetryImportResult):
            for media, counts in retry_service.last_result.by_media.items():
                self._record_media(media, counts)
        if (
            isinstance(retry_service.last_result, RetryImportResult)
            and retry_service.last_result.skipped
        ):
            logger.error("Request recovery is incomplete; continuing discovery for other books")

        matcher = self.factory.matcher()

        wanted_requests = self.get_wanted_requests(matcher)
        for request in wanted_requests:
            self._record_media(request.media_type, {"missing": 1})
        if not wanted_requests:
            logger.info("No requests missing from their destination libraries; nothing to do")
            return self._summary(0, {}, ImportResult(), retry_service)

        torrent_discovery = self.factory.torrent_discovery()
        wanted_torrents = self.process_requests(
            wanted_requests,
            torrent_discovery,
            matcher,
            incomplete_requests,
        )

        result = ImportResult()
        for media in sorted({request.media_type for _, request in wanted_torrents}):
            torrent_import = self.factory.torrent_import(media)
            imported = torrent_import.import_torrents(
                (data, request.book)
                for data, request in wanted_torrents
                if request.media_type == media
            )
            self._record_media(media, asdict(imported))
            for key, count in asdict(imported).items():
                setattr(result, key, getattr(result, key) + count)
        return self._summary(
            len(wanted_requests), torrent_discovery.last_counts, result, retry_service
        )

    def _record_media(self, media, counts):
        target = self.media_counts.setdefault(
            media, {"destination": "Audiobookshelf" if media == "audiobook" else "Calibre"}
        )
        for key, count in counts.items():
            if isinstance(count, int):
                target[key] = target.get(key, 0) + count

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
            data={**counts, "ok": success, "dry_run": dry_run, "by_media": self.media_counts},
        )
        for media, detail in sorted(self.media_counts.items()):
            output(
                f"  {media} → {detail['destination']}: "
                + ", ".join(
                    f"{count} {key.replace('_', ' ')}"
                    for key, count in detail.items()
                    if key != "destination"
                ),
                kind="media_summary",
                data={"media_type": media, **detail},
            )
        return success

    def _library_groups(self):
        requests = self.factory.wanted_requests()
        for media in sorted({request.media_type for request in requests}):
            group = {request for request in requests if request.media_type == media}
            yield media, group, self.factory.library(media)

    def get_wanted_requests(self, matcher: BookMatcher) -> set[BookRequest]:
        """Compare each request only with its own library, preserving work/media identity."""
        missing = set()
        for _, requests, library in self._library_groups():
            books = library.get_books()
            matches = matcher.match_books(books, [request.book for request in requests])
            present = {book.id for _, book, _ in matches}
            missing.update(request for request in requests if request.book.id not in present)
        return missing

    def list_missing(self, matcher: BookMatcher) -> None:
        """Print requests missing from their respective libraries."""
        missing = self.get_wanted_requests(matcher)
        output(
            f"[bold yellow]Missing book requests: {len(missing)}[/]"
            if missing
            else "[bold green]No books are missing from the requested libraries.[/]",
            kind="missing_summary",
            data={"count": len(missing)},
        )
        for request in sorted(
            missing, key=lambda r: (r.book.title.casefold(), r.book.id, r.media_type)
        ):
            destination = "Calibre" if request.media_type == "ebook" else "Audiobookshelf"
            output(
                colored(f"- {request.book} [{request.media_type} → {destination}]", "cyan"),
                kind="missing_book",
                data={
                    "book": book_data(request.book),
                    "media_type": request.media_type,
                    "destination": destination,
                },
            )

    def review_matches(self, matcher: BookMatcher, matched: bool | None = None) -> None:
        """Print comparisons, optionally filtering by whether a candidate is accepted."""
        # Complete all lookups before printing, so a failed backend is never shown as missing.
        reviews = [
            (book, candidates, media, library.name)
            for media, requests, library in self._library_groups()
            for book, candidates in matcher.review_matches(
                library.get_books(),
                [request.book for request in requests],
            )
        ]
        output(f"[bold cyan]Match threshold:[/] {matcher.threshold:.3f}")

        shown = 0
        for hardcover_book, candidates, media, destination in sorted(
            reviews, key=lambda item: (item[0].title.casefold(), item[0].id, item[2])
        ):
            accepted = any(candidate.accepted for candidate in candidates)
            if matched is not None and accepted != matched:
                continue
            shown += 1
            output()
            output(
                match_review(
                    self._format_match_review(hardcover_book, candidates, destination)
                    + f"\n  Media: {media} → {destination}"
                ),
                kind="match_review",
                data={
                    "book": book_data(hardcover_book),
                    "media_type": media,
                    "destination": destination,
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
        destination: str = "Calibre",
    ) -> str:
        """Format a requested book and candidates from its destination library."""
        lines = [f"Hardcover: {hardcover_book}"]
        if not candidates:
            return "\n".join((*lines, f"  No {destination} candidates."))

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
            lines.append(f"  No {destination} match was assigned.")
        return "\n".join(lines)

    @staticmethod
    def process_requests(
        wanted_requests: Iterable[BookRequest],
        torrent_discovery: TorrentDiscoveryService,
        matcher: BookMatcher,
        incomplete_requests: Iterable[BookRequest] = (),
    ) -> list[tuple[bytes, BookRequest]]:
        """Process the matched and unmatched books to find torrents for the missing ones."""

        if not wanted_requests:
            return []
        return torrent_discovery.download_torrents(wanted_requests, matcher, incomplete_requests)
