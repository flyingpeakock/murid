"""This module defines the RetryService class."""

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from ..clients.myanonamouse import MAMError, MyAnonamouse, MyAnonamouseQuery
from ..clients.torrent_clients import TorrentClient
from ..domain.book import Book
from ..domain.book_request import BookRequest, MediaType
from ..domain.torrent_request import IMPORT_TAGS, read_request_tags
from .torrent_import import TorrentImportService

logger = logging.getLogger("murid")
_IMPORT_TAGS = set(IMPORT_TAGS)


@dataclass(frozen=True)
class RetryImportResult:
    """Counts from a one-time retry of tagged torrents."""

    imported: int = 0
    already_present: int = 0
    pending: int = 0
    failed: int = 0
    skipped: int = 0
    by_media: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RetryRecovery:
    """Lazy access to media backends and persisted Hardcover work metadata."""

    importer: Callable[[MediaType], TorrentImportService]
    book: Callable[[int], Book | None]
    media_type: MediaType | None = None


class RetryService:
    """Service responsible for retrying torrents that previously timed out during import."""

    def __init__(
        self,
        torrent_client: TorrentClient,
        import_service: TorrentImportService | None,
        myanonamouse: MyAnonamouse,
        hardcover_books: Callable[[], Iterable[Book]],
        *,
        recovery: RetryRecovery | None = None,
    ) -> None:
        """Initialize the RetryService with the necessary dependencies."""
        self.torrent_client = torrent_client
        self.myanonamouse = myanonamouse
        self.hardcover_books = hardcover_books
        self._hardcover_books: list[Book] | None = None
        self.last_result = RetryImportResult()
        self._recovery = recovery
        self._import_services = {"ebook": import_service} if import_service is not None else {}

    def retry_torrents(self) -> set[BookRequest]:
        """Recover tagged requests once and suppress duplicate discovery while unresolved."""
        return self._retry()

    def retry_imports(self) -> RetryImportResult:
        """Retry tagged requests without searching for or adding another torrent."""
        self._retry()
        return self.last_result

    def _importer(self, media: MediaType) -> TorrentImportService:
        if media not in self._import_services:
            if self._recovery is None:
                raise ValueError(f"No import backend configured for {media}")
            self._import_services[media] = self._recovery.importer(media)
        return self._import_services[media]

    def _request(self, torrent, tags: set[str]) -> BookRequest | None:
        media, work_id = read_request_tags(tags)
        if work_id is None:
            mam_id = self._mam_id(torrent)
            book = self.get_book_by_mam_id(mam_id) if mam_id is not None else None
        elif self._recovery is not None:
            book = self._recovery.book(work_id)
        else:
            book = next((book for book in self.hardcover_books() if book.id == work_id), None)
        if book is None:
            return None
        if work_id is not None and (book.id != work_id or book.source.lower() != "hardcover"):
            raise ValueError("Recovered book does not match the torrent's Hardcover identity")
        return BookRequest(book, media)

    def _retry(self) -> set[BookRequest]:
        self._hardcover_books = None
        incomplete = set()
        counts = dict.fromkeys(("imported", "already_present", "pending", "failed", "skipped"), 0)
        by_media = {}
        for torrent in self.torrent_client.get_torrents():
            tags = {tag.strip() for tag in (torrent.tags or "").split(",")}
            relevant = tags & _IMPORT_TAGS
            if not relevant:
                continue
            try:
                media, _ = read_request_tags(tags)
                if self._recovery and self._recovery.media_type not in {None, media}:
                    continue
                request = self._request(torrent, tags)
            except ValueError as error:
                logger.error(
                    "Torrent %s: %s; inspect its Murid tags before retrying", torrent.hash, error
                )
                request = None
            if request is None:
                logger.warning("Skipping torrent %s: could not identify its request", torrent.hash)
                counts["skipped"] += 1
                continue
            importer = self._importer(request.media_type)
            outcome = self._retry_request(torrent.hash, request, importer)
            counts[outcome] += 1
            media_counts = by_media.setdefault(
                request.media_type, {"destination": importer.library.name}
            )
            media_counts[outcome] = media_counts.get(outcome, 0) + 1
            logger.info(
                "%s [%s → %s]: %s",
                request.book,
                request.media_type,
                importer.library.name,
                outcome.replace("_", " "),
            )
            if outcome in {"pending", "failed"}:
                incomplete.add(request)
            elif not importer.dry_run:
                for tag in IMPORT_TAGS:
                    if tag in relevant:
                        self.torrent_client.remove_tag(torrent.hash, tag)
        self.last_result = RetryImportResult(**counts, by_media=by_media)
        return incomplete

    @staticmethod
    def _retry_request(torrent_id, request, importer) -> str:
        book = request.book
        # Audio import must verify the journal's exact destination and track inventory;
        # a title match elsewhere cannot complete a copied-but-unverified import.
        if request.media_type == "ebook" and importer.library.contains_book(book, importer.matcher):
            logger.info("%s: already in %s", book, importer.library.name)
            return "already_present"
        if importer.dry_run:
            logger.info("%s [%s]: dry run would retry import", book, request.media_type)
            return "pending"
        if not importer.process_torrent(torrent_id, book):
            return "pending"
        return {"imported": "imported", "failed": "failed"}.get(importer.last_outcome, "pending")

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
            if self._importer("ebook").matcher.is_match(book, mam_book)
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
