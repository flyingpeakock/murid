"""This module defines the RetryService class."""

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass

from ..clients.myanonamouse import MAMError, MyAnonamouse, MyAnonamouseQuery
from ..clients.torrent_clients import TorrentClient
from ..domain.book import Book
from .torrent_import import TorrentImportService

logger = logging.getLogger("murid")
_IMPORT_TAGS = {"murid_timeout", "murid_import_failed"}


@dataclass(frozen=True)
class RetryImportResult:
    """Counts from a one-time retry of tagged torrents."""

    imported: int = 0
    already_present: int = 0
    pending: int = 0
    failed: int = 0
    skipped: int = 0


class RetryService:
    """Service responsible for retrying torrents that previously timed out during import."""

    def __init__(
        self,
        torrent_client: TorrentClient,
        import_service: TorrentImportService,
        myanonamouse: MyAnonamouse,
    ) -> None:
        """Initialize the RetryService with the necessary dependencies."""
        self.torrent_client = torrent_client
        self.import_service = import_service
        self.myanonamouse = myanonamouse
        self.last_result = RetryImportResult()

    def retry_torrents(self) -> set[Book]:
        """Retry timed-out torrents and return books whose torrents remain incomplete."""
        incomplete_books = set()
        imported = already_present = pending = failed = skipped = 0
        calibre = self.import_service.calibre
        matcher = self.import_service.matcher
        for torrent_id, mam_id in self.fetch_previous_torrents():
            book = self.get_book_by_mam_id(mam_id)
            if book is None:
                skipped += 1
                continue

            if calibre.contains_book(book, matcher):
                already_present += 1
                if not self.import_service.dry_run:
                    self.torrent_client.remove_tag(torrent_id, "murid_timeout")
                continue

            if self.import_service.dry_run:
                logger.info("%s: dry run would retry import", book)
                incomplete_books.add(book)
                pending += 1
                continue

            if not self.import_service.process_torrent(torrent_id, book):
                logger.info("%s: still downloading; will check again next run", book)
                incomplete_books.add(book)
                pending += 1
                continue

            if calibre.contains_book(book, matcher):
                imported += 1
            else:
                # process_torrent marks completed downloads with failed imports.
                failed += 1
            self.torrent_client.remove_tag(torrent_id, "murid_timeout")
        self.last_result = RetryImportResult(imported, already_present, pending, failed, skipped)
        return incomplete_books

    def retry_imports(self) -> RetryImportResult:
        """Retry tagged downloads once without searching for or adding new torrents."""
        imported = already_present = pending = failed = skipped = 0
        calibre = self.import_service.calibre
        matcher = self.import_service.matcher

        for torrent in self.torrent_client.get_torrents():
            tags = {tag.strip() for tag in (torrent.tags or "").split(",")}
            relevant_tags = tags & _IMPORT_TAGS
            if not relevant_tags:
                continue

            match = re.search(r"MID=(\d+)", torrent.comment or "")
            if not match:
                logger.warning(
                    "Skipping torrent %s: no MyAnonamouse ID in its comment", torrent.hash
                )
                skipped += 1
                continue

            book = self.get_book_by_mam_id(int(match.group(1)))
            if book is None:
                logger.warning("Skipping torrent %s: could not identify its book", torrent.hash)
                skipped += 1
                continue

            if calibre.contains_book(book, matcher):
                logger.info("%s: already in Calibre", book)
                for tag in relevant_tags:
                    self.torrent_client.remove_tag(torrent.hash, tag)
                already_present += 1
                continue

            if not self.import_service.process_torrent(torrent.hash, book):
                logger.info("%s: still downloading", book)
                pending += 1
                continue

            if calibre.contains_book(book, matcher):
                for tag in relevant_tags:
                    self.torrent_client.remove_tag(torrent.hash, tag)
                imported += 1
            else:
                if "murid_timeout" in relevant_tags:
                    self.torrent_client.remove_tag(torrent.hash, "murid_timeout")
                failed += 1

        return RetryImportResult(imported, already_present, pending, failed, skipped)

    def fetch_previous_torrents(self) -> Iterator[tuple[str, int]]:
        """Fetch torrents that previously timed out during import."""
        previous_torrents = self.torrent_client.get_torrents_with_tag("murid_timeout")
        if not previous_torrents:
            return
        logger.debug(
            "Found %d previously timed out torrents with tag 'murid_timeout'",
            len(previous_torrents),
        )
        for torrent in previous_torrents:
            match = re.search(r"MID=(\d+)", torrent.comment or "")
            if match:
                mam_id = int(match.group(1))
                yield (torrent.hash, mam_id)

    def get_book_by_mam_id(self, mam_id: int) -> Book | None:
        """Fetch the book information from MyAnonamouse using the provided mam_id."""
        try:
            result = self.myanonamouse.search(MyAnonamouseQuery(text="", id=mam_id))
            if not result:
                logger.warning("No torrent found on MyAnonamouse for ID %d", mam_id)
                return None

            if len(result) > 1:
                logger.warning(
                    "Multiple torrents found on MyAnonamouse for ID %d, expected only one", mam_id
                )
                return None

            torrent = next(iter(result))
            return torrent.book

        except MAMError as e:
            logger.error("Cannot look up MyAnonamouse ID %d: %s", mam_id, e)
            return None
