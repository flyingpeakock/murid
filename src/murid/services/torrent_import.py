"""Service responsible for importing torrents into the torrent client"""

import logging
import time
from dataclasses import dataclass
from typing import Callable, Iterable

import apprise

from ..clients.torrent_clients.torrent_client import TorrentClient
from ..domain.book import Book
from ..domain.book_matcher import BookMatcher
from ..domain.book_request import MediaType
from ..domain.torrent_request import IMPORT_TAGS
from ..libraries.library import Library, LibraryError, LibraryImportPending

logger = logging.getLogger("murid")


@dataclass
class ImportResult:
    """Outcome counts for one batch of torrent imports."""

    added: int = 0
    imported: int = 0
    pending: int = 0
    failed: int = 0
    planned: int = 0


@dataclass
class TorrentImportConfig:
    """Configuration for the TorrentImportService"""

    torrent_client: TorrentClient
    library: Library
    matcher: BookMatcher
    notify: Callable[[str, str, apprise.NotifyType], None]
    dry_run: bool = False
    timeout: int = 1800  # 30 minutes
    media_type: MediaType = "ebook"


class TorrentImportService:  # pylint: disable=too-many-instance-attributes
    """Service responsible for importing torrents into the torrent client"""

    def __init__(self, config: TorrentImportConfig) -> None:
        """Initialize the TorrentImportService"""
        self.torrent_client = config.torrent_client
        self.notify = config.notify
        self.library = config.library
        self.dry_run = config.dry_run
        self.matcher = config.matcher
        self.timeout = config.timeout
        self.media_type = config.media_type
        self.last_outcome = "pending"

    def import_torrents(self, torrent_files: Iterable[tuple[bytes, Book]]) -> ImportResult:
        """Import the given torrent files into the torrent client and track their completion."""
        torrent_files = list(torrent_files)
        result = ImportResult()
        if not torrent_files:
            logger.info("No torrents to import")
            return result

        logger.info(
            "Preparing %d torrent%s for import",
            len(torrent_files),
            "s" if len(torrent_files) != 1 else "",
        )

        if self.dry_run:
            logger.info("Dry run enabled, not adding any torrents to torrent client")
            for _, book in torrent_files:
                logger.info("%s: would add to torrent client", book)
            result.planned = len(torrent_files)
            return result

        pending = {}  # torrent_id -> book

        for torrent_file, book in torrent_files:
            torrent_id = self.torrent_client.add_torrent(
                torrent_file, book, media_type=self.media_type
            )
            if torrent_id:
                if torrent_id in pending:
                    logger.error(
                        "%s: torrent %s is already assigned to %s; import this book "
                        "separately with murid add-book",
                        book,
                        torrent_id,
                        pending[torrent_id],
                    )
                    result.failed += 1
                    continue
                pending[torrent_id] = book
                result.added += 1
            else:
                result.failed += 1
        if not pending:
            logger.warning("No torrents were successfully added to the torrent client")
            return result

        logger.info("Tracking %d torrents for completion", len(pending))
        return self._wait_for_imports(pending, result)

    def _wait_for_imports(self, pending: dict[str, Book], result: ImportResult) -> ImportResult:
        """Poll accepted downloads and count terminal import outcomes."""
        start_time = time.time()
        while pending:
            completed = []

            for torrent_id, book in pending.items():
                if self.process_torrent(torrent_id, book):
                    completed.append(torrent_id)
                    if self.last_outcome == "imported":
                        self.clear_import_tags(torrent_id)
                        result.imported += 1
                    elif self.last_outcome == "pending":
                        result.pending += 1
                    else:
                        result.failed += 1

            for tid in completed:
                pending.pop(tid, None)

            if pending:
                time.sleep(self.torrent_client.poll_interval)

            if self._is_timeout(start_time, pending):
                break
        result.pending += len(pending)
        return result

    def process_torrent(self, torrent_id: str, book: Book) -> bool:
        """Resume published content or import a completed path through its library."""
        self.last_outcome = "pending"
        if self.dry_run:
            if not self.torrent_client.get_completed_path(torrent_id):
                return False
            logger.info("%s: dry run enabled, not importing into %s", book, self.library.name)
            self.last_outcome = "planned"
            return True

        try:
            if not self.library.resume_import(book, self.matcher):
                path = self.torrent_client.get_completed_path(torrent_id)
                if not path:
                    return False
                time.sleep(0.5)  # Give the torrent client a moment to move the files
                path = self.torrent_client.get_completed_path(torrent_id)
                if not path:
                    return False
                self.library.import_book(book, path, self.matcher)
            self.last_outcome = "failed"
            # Audio import/resume returns only after exact destination/track verification.
            # Calibre still needs a presence check after its import command returns.
            if self.media_type == "audiobook" or self.library.contains_book(book, self.matcher):
                self.last_outcome = "imported"
                message = f"{book}: imported into {self.library.name} [{self.media_type}]"
                logger.info("%s: imported into %s", book, self.library.name)
                self.notify(title="Book Imported", body=message)
            else:
                logger.error(
                    "%s: failed to verify import into %s; run murid status, "
                    "inspect the library, then run murid retry-import",
                    book,
                    self.library.name,
                )
                self.torrent_client.add_tag(torrent_id, "murid-import-failed")
        except LibraryImportPending as error:
            self.last_outcome = "pending"
            self.torrent_client.add_tag(torrent_id, "murid")
            logger.warning("%s: %s; ingestion will be checked next run", book, error)
        except LibraryError as error:
            self.last_outcome = "failed"
            logger.error(
                "%s: import failed: %s; run murid status, fix the cause, "
                "then run murid retry-import",
                book,
                error,
            )
            self.torrent_client.add_tag(torrent_id, "murid-import-failed")

        return True

    def clear_import_tags(self, torrent_id: str) -> None:
        """Clear lifecycle state only after the destination library confirms success."""
        if not self.dry_run:
            for tag in IMPORT_TAGS:
                self.torrent_client.remove_tag(torrent_id, tag)

    def _is_timeout(self, start_time: float, pending: dict) -> bool:
        """Check if the timeout has been reached since the given start time."""
        if pending and time.time() - start_time > self.timeout:
            logger.warning(
                "Download timeout after %d seconds: %d pending. Run murid status; "
                "completed downloads can be imported with murid retry-import",
                self.timeout,
                len(pending),
            )
            for tid, book in pending.items():
                logger.warning("%s: still pending (torrent ID %s)", book, tid)
                self.notify(
                    title="Murid - Torrent download timeout",
                    body=(
                        f"The {self.media_type} torrent for {book} → {self.library.name} "
                        "did not complete within "
                        f"{self.timeout} seconds. If completed it will be imported "
                        "in the next run, otherwise you may need to investigate the "
                        "torrent client for issues."
                    ),
                )
                self.torrent_client.add_tag(tid, "murid-timeout")
            return True
        return False
