"""Service for discovering torrents for books using MyAnonamouse."""

import logging
import re
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Iterable

from ..clients.myanonamouse import MAMSearchError, MyAnonamouse
from ..clients.torrent_clients import TorrentClient
from ..domain.book import Book
from ..domain.book_matcher import BookMatcher
from ..domain.book_request import BookRequest, MediaType
from ..domain.torrent import Torrent
from ..domain.torrent_request import read_request
from ..domain.torrent_selector import TorrentSelector

logger = logging.getLogger("murid")


class TorrentDiscoveryService:
    """Service for discovering torrents for books using MyAnonamouse."""

    def __init__(
        self,
        mam: MyAnonamouse,
        torrent_selectors: dict[MediaType, TorrentSelector],
        torrent_client: TorrentClient | None = None,
    ) -> None:
        """Service for discovering torrents for books using MyAnonamouse."""
        self.mam = mam
        self.torrent_selectors = torrent_selectors
        self.torrent_client = torrent_client
        self.last_counts = {"searched": 0, "skipped": 0, "selected": 0, "failed": 0}

    def mam_ids_with_tag(self, tag: str, media_type: MediaType = "ebook") -> set[str]:
        """Return MAM IDs for torrents carrying the specified client tag."""
        if self.torrent_client is None:
            return set()

        mam_ids = set()
        tagged_torrents = self.torrent_client.get_torrents_with_tag(tag)
        for torrent in tagged_torrents:
            try:
                medium, _ = read_request(torrent)
            except ValueError as error:
                logger.warning(
                    "Torrent %s: invalid Murid request identity: %s; skipping failed-import "
                    "filter for this torrent; inspect it with murid status",
                    getattr(torrent, "hash", "unknown"),
                    error,
                )
                continue
            if medium != media_type:
                continue
            comment = getattr(torrent, "comment", None) or ""
            # qBittorrent keeps the MAM torrent ID in the .torrent comment.
            match = re.search(r"MID=(\d+)", comment)
            if match:
                mam_ids.add(match.group(1))
        return mam_ids

    def find_torrents(self, request: BookRequest) -> tuple[BookRequest, set[Torrent]]:
        """Find candidates within the requested medium, retaining work identity."""
        book = request.book
        mam_books = self._search_titles(request)

        for torrent in mam_books:
            # Fill missing metadata without erasing evidence of a different volume.
            if not torrent.book.series:
                torrent.book.series = book.series
                torrent.book.series_number = book.series_number
        return request, mam_books

    @staticmethod
    def _request_sort_key(request: BookRequest) -> tuple:
        """Return a stable ordering key for user-visible discovery work."""
        book = request.book
        return (
            book.title.casefold(),
            tuple(author.casefold() for author in getattr(book, "authors", [])),
            book.id,
            request.media_type,
        )

    @staticmethod
    def _titles_to_search(book: Book) -> list[str]:
        alternative_titles = getattr(book, "search_alternative_titles", None)
        if alternative_titles is None:
            alternative_titles = getattr(book, "alternative_titles", None)

        titles = []
        seen_titles = set()
        for title in [book.title, *(alternative_titles or [])]:
            normalized_title = BookMatcher.canonicalize_title(title)
            if normalized_title and normalized_title not in seen_titles:
                seen_titles.add(normalized_title)
                titles.append(title)
        return titles

    def _search_titles(self, request: BookRequest) -> set[Torrent]:
        """Scope main title, author fallback, and alternate titles to one medium."""
        book = request.book
        results: set[Torrent] = set()
        rejected = 0
        titles = self._titles_to_search(book)
        if titles:
            title = titles[0]
            logger.debug(
                "%s: searching MyAnonamouse by title only: %r",
                book,
                title,
            )
            title_results = set()
            try:
                title_results = self.mam.search_title(title, request.media_type)
                results.update(title_results)
            except MAMSearchError as error:
                rejected += 1
                logger.warning(
                    "%s: title query %r rejected: %s; skipping this title", book, title, error
                )

            if not title_results:
                for author in getattr(book, "authors", []) or []:
                    logger.debug(
                        "%s: searching MyAnonamouse by author only: %r",
                        book,
                        author,
                    )
                    try:
                        results.update(self.mam.search_author(author, request.media_type))
                    except MAMSearchError as error:
                        rejected += 1
                        logger.warning(
                            "%s: author query %r rejected: %s; skipping this author",
                            book,
                            author,
                            error,
                        )

        for title in titles[1:]:
            logger.debug(
                "%s: searching MyAnonamouse by alternate title only: %r",
                book,
                title,
            )
            try:
                results.update(self.mam.search_title(title, request.media_type))
            except MAMSearchError as error:
                rejected += 1
                logger.warning(
                    "%s: title query %r rejected: %s; skipping this title", book, title, error
                )

        attempted = len(titles) + (len(getattr(book, "authors", []) or []) if titles else 0)
        if attempted and rejected == attempted:
            raise MAMSearchError(
                f"{book}: all {rejected} title queries were rejected; "
                "review the titles on Hardcover and MyAnonamouse"
            )
        return results

    def submit_downloads(
        self,
        executor: ThreadPoolExecutor,
        search_futures: dict[Future, BookRequest],
        matcher: BookMatcher,
    ) -> dict[Future, BookRequest]:
        """Download the best matching torrent for each book once the search futures complete."""

        download_futures = {}
        failed_import_mam_ids = {
            media: self.mam_ids_with_tag("murid-import-failed", media)
            for media in {request.media_type for request in search_futures.values()}
        }

        # Searches may finish in any order. Consume the futures in submission order
        # so selection messages and download requests remain reproducible.
        for future, request in search_futures.items():
            book = request.book
            try:
                _, tor_list = future.result()
            except (Exception, SystemExit) as error:  # pylint: disable=broad-exception-caught
                self.last_counts["failed"] += 1
                self.last_counts["search_failed"] = self.last_counts.get("search_failed", 0) + 1
                logger.error(
                    "%s [%s]: search failed: %s; continuing with other books",
                    book,
                    request.media_type,
                    error,
                    exc_info=logger.isEnabledFor(logging.DEBUG),
                )
                continue

            try:
                failed_ids = failed_import_mam_ids[request.media_type]
                if failed_ids:
                    tor_list = {
                        torrent for torrent in tor_list if str(torrent.book.id) not in failed_ids
                    }

                if not tor_list:
                    logger.info(
                        "%s: no eligible torrents found; use murid search-book to investigate", book
                    )
                    continue

                torrent = self.torrent_selectors[request.media_type].select(book, tor_list, matcher)

                if not torrent:
                    continue

                download_future = executor.submit(self.mam.download_torrent, torrent)
                self.last_counts["selected"] += 1
                download_futures[download_future] = request
            except (Exception, SystemExit) as error:  # pylint: disable=broad-exception-caught
                self.last_counts["failed"] += 1
                logger.error(
                    "%s [%s]: torrent selection failed: %s",
                    book,
                    request.media_type,
                    error,
                    exc_info=logger.isEnabledFor(logging.DEBUG),
                )

        return download_futures

    def collect_downloads(
        self,
        download_futures: dict[Future, BookRequest],
    ) -> list[tuple[bytes, BookRequest]]:
        """Collect the downloaded torrent data once the download futures complete."""

        torrent_files = []
        seen = set()
        # As above, preserve the order in which downloads were submitted.
        for future, request in download_futures.items():
            try:
                torrent_file = future.result()
            except (Exception, SystemExit) as error:  # pylint: disable=broad-exception-caught
                self.last_counts["failed"] += 1
                logger.error(
                    "%s [%s]: torrent download failed: %s",
                    request.book,
                    request.media_type,
                    error,
                    exc_info=logger.isEnabledFor(logging.DEBUG),
                )
                continue
            if torrent_file:
                download = (torrent_file, request)
                if download not in seen:
                    torrent_files.append(download)
                    seen.add(download)
            else:
                self.last_counts["failed"] += 1

        return torrent_files

    def download_torrents(
        self,
        requests: Iterable[BookRequest],
        matcher: BookMatcher,
        incomplete_requests: Iterable[BookRequest] = (),
    ) -> list[tuple[bytes, BookRequest]]:
        """Find torrent files for independent work/media requests."""
        requests = sorted(set(requests), key=self._request_sort_key)
        incomplete = set(incomplete_requests)
        requests_to_search = [request for request in requests if request not in incomplete]
        skipped_count = len(requests) - len(requests_to_search)
        self.last_counts = {
            "searched": len(requests_to_search),
            "skipped": skipped_count,
            "selected": 0,
            "failed": 0,
        }
        logger.info("%d requests missing; searching for %d", len(requests), len(requests_to_search))
        for request in requests_to_search:
            logger.debug("%s [%s]: queued for search", request.book, request.media_type)
        if skipped_count:
            logger.info("Skipping %d requests with an incomplete torrent", skipped_count)
        if not requests_to_search:
            return []
        with ThreadPoolExecutor(max_workers=min(10, len(requests_to_search))) as executor:
            search_futures = {
                executor.submit(self.find_torrents, request): request
                for request in requests_to_search
            }
            download_futures = self.submit_downloads(executor, search_futures, matcher)
            if not download_futures:
                return []
            return self.collect_downloads(download_futures)
