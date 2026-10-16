"""Service responsible for importing torrents into the torrent client"""

import logging
import time
from dataclasses import dataclass
from typing import Callable, Iterable

import apprise

from ..clients.calibre import Calibre, CalibreError
from ..clients.torrent_clients.torrent_client import TorrentClient
from ..domain.book import Book
from ..domain.book_file_selector import BookFileSelector
from ..domain.book_matcher import BookMatcher

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
    calibre: Calibre
    matcher: BookMatcher
    notify: Callable[[str, str, apprise.NotifyType], None]
    dry_run: bool = False
    timeout: int = 1800  # 30 minutes
    filetypes: list[str] | None = None


class TorrentImportService:  # pylint: disable=too-many-instance-attributes
    """Service responsible for importing torrents into the torrent client"""

    def __init__(self, config: TorrentImportConfig) -> None:
        """Initialize the TorrentImportService"""
        self.torrent_client = config.torrent_client
        self.notify = config.notify
        self.calibre = config.calibre
        self.dry_run = config.dry_run
        self.matcher = config.matcher
        self.timeout = config.timeout
        self.book_file_selector = BookFileSelector(config.filetypes)
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
            torrent_id = self.torrent_client.add_torrent(torrent_file, book)
            if torrent_id:
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
                        result.imported += 1
                    else:
                        result.failed += 1

            for tid in completed:
                pending.pop(tid, None)

            if pending:
                logger.debug("%d torrents still active", len(pending))
                time.sleep(self.torrent_client.poll_interval)

            if self._is_timeout(start_time, pending):
                break
        result.pending = len(pending)
        return result

    def process_torrent(self, torrent_id: str, book: Book) -> bool:
        """Check if the torrent with the given ID is completed and import it into Calibre."""
        self.last_outcome = "pending"
        path = self.torrent_client.get_completed_path(torrent_id)
        if not path:
            return False

        if self.dry_run:
            logger.info("%s: dry run enabled, not importing into Calibre", book)
            self.last_outcome = "planned"
            return True

        try:
            time.sleep(0.5)  # Give the torrent client a moment to move the files
            path = self.torrent_client.get_completed_path(torrent_id)
            if not path:
                return False

            book_file = self.book_file_selector.select(book, path, self.matcher)
            self.last_outcome = "failed"
            if book_file is None:
                logger.error(
                    "%s: could not select a unique ebook file; import an individual ebook "
                    "with murid add-book <Hardcover-title> <ebook-file-path>. "
                    "After importing, murid retry-import can clear the failed-import tag",
                    book,
                )
                self.torrent_client.add_tag(torrent_id, "murid_import_failed")
                return True

            self.calibre.add_book(book, str(book_file))
            if self.calibre.contains_book(book, self.matcher):
                self.last_outcome = "imported"
                message = f"{book}: imported into Calibre"
                logger.info("%s: imported into Calibre", book)
                self.notify(title="Book Imported", body=message)
            else:
                logger.error(
                    "%s: failed to verify import into Calibre; run murid status, "
                    "inspect the Calibre library, then run murid retry-import",
                    book,
                )
                self.torrent_client.add_tag(torrent_id, "murid_import_failed")
        except CalibreError as error:
            self.last_outcome = "failed"
            logger.error(
                "%s: import failed: %s; run murid status, fix the cause, "
                "then run murid retry-import",
                book,
                error,
            )
            self.torrent_client.add_tag(torrent_id, "murid_import_failed")

        return True

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
                        f"The torrent for {book} did not complete within "
                        f"{self.timeout} seconds. If completed it will be imported "
                        "in the next run, otherwise you may need to investigate the "
                        "torrent client for issues."
                    ),
                )
                self.torrent_client.add_tag(tid, "murid_timeout")
            return True
        return False
