"""This module defines the RetryService class."""

import logging
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

from ..clients.myanonamouse import MAMError, MyAnonamouse, MyAnonamouseQuery
from ..clients.torrent_clients import TorrentClient
from ..domain.book import Book
from .torrent_import import TorrentImportService

logger = logging.getLogger("murid")
_IMPORT_TAGS = {"murid_pending", "murid_timeout", "murid_import_failed"}


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
        hardcover_books: Callable[[], Iterable[Book]],
    ) -> None:
        """Initialize the RetryService with the necessary dependencies."""
        self.torrent_client = torrent_client
        self.import_service = import_service
        self.myanonamouse = myanonamouse
        self.hardcover_books = hardcover_books
        self._hardcover_books: list[Book] | None = None
        self.last_result = RetryImportResult()

    def retry_torrents(self) -> set[Book]:
        """Retry timed-out torrents and return books whose torrents remain incomplete."""
        incomplete_books = set()
        self._hardcover_books = None
        imported = already_present = pending = failed = skipped = 0
        calibre = self.import_service.calibre
        matcher = self.import_service.matcher
        for torrent_id, mam_id in self.fetch_previous_torrents():
            book = self.get_book_by_mam_id(mam_id) if mam_id is not None else None
            if book is None:
                skipped += 1
                continue

            if calibre.contains_book(book, matcher):
                already_present += 1
                if not self.import_service.dry_run:
                    self.torrent_client.remove_tag(torrent_id, "murid_timeout")
                    self.torrent_client.remove_tag(torrent_id, "murid_pending")
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
            self.torrent_client.remove_tag(torrent_id, "murid_pending")
        self.last_result = RetryImportResult(imported, already_present, pending, failed, skipped)
        return incomplete_books

    def retry_imports(self) -> RetryImportResult:
        """Retry tagged downloads once without searching for or adding new torrents."""
        imported = already_present = pending = failed = skipped = 0
        self._hardcover_books = None
        calibre = self.import_service.calibre
        matcher = self.import_service.matcher

        for torrent in self.torrent_client.get_torrents():
            tags = {tag.strip() for tag in (torrent.tags or "").split(",")}
            relevant_tags = tags & _IMPORT_TAGS
            if not relevant_tags:
                continue

            mam_id = self._mam_id(torrent)
            book = self.get_book_by_mam_id(mam_id) if mam_id is not None else None
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
                if "murid_pending" in relevant_tags:
                    self.torrent_client.remove_tag(torrent.hash, "murid_pending")
                failed += 1

        return RetryImportResult(imported, already_present, pending, failed, skipped)

    def fetch_previous_torrents(self) -> Iterator[tuple[str, int | None]]:
        """Fetch unfinished imports, including downloads interrupted before their timeout."""
        previous_torrents = {
            torrent.hash: torrent
            for tag in ("murid_timeout", "murid_pending")
            for torrent in self.torrent_client.get_torrents_with_tag(tag)
        }.values()
        if not previous_torrents:
            return
        logger.debug(
            "Found %d torrents with unfinished imports",
            len(previous_torrents),
        )
        for torrent in previous_torrents:
            yield torrent.hash, self._mam_id(torrent)

    @staticmethod
    def _mam_id(torrent) -> int | None:
        """Read the MyAnonamouse identity from the original torrent comment."""
        match = re.search(r"MID=(\d+)", torrent.comment or "")
        if match:
            return int(match.group(1))
        logger.warning("Skipping torrent %s: no MyAnonamouse ID", torrent.hash)
        return None

    def get_book_by_mam_id(self, mam_id: int) -> Book | None:
        """Identify the torrent on MaM, then recover its metadata from Hardcover."""
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
            return self._match_hardcover_book(torrent.book)

        except MAMError as e:
            logger.error("Cannot look up MyAnonamouse ID %d: %s", mam_id, e)
            return None

    def _match_hardcover_book(self, mam_book: Book) -> Book | None:
        """Require one matching work across all configured Hardcover reading lists."""
        if self._hardcover_books is None:
            self._hardcover_books = list(
                {book.id: book for book in self.hardcover_books()}.values()
            )
        matches = [
            book
            for book in self._hardcover_books
            if self.import_service.matcher.is_match(book, mam_book)
        ]
        if len(matches) == 1:
            return matches[0]
        logger.warning(
            "%s: %s Hardcover match in configured Want to Read lists; "
            "check the reading lists or import the ebook with murid add-book",
            mam_book,
            "no" if not matches else "ambiguous",
        )
        return None
