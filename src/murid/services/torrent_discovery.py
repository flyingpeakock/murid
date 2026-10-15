"""Service for discovering torrents for books using MyAnonamouse."""

import logging
import re
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Iterable

from ..clients.myanonamouse import MyAnonamouse
from ..clients.torrent_clients import TorrentClient
from ..domain.book import Book
from ..domain.book_matcher import BookMatcher
from ..domain.torrent import Torrent
from ..domain.torrent_selector import TorrentSelector

logger = logging.getLogger("murid")


class TorrentDiscoveryService:
    """Service for discovering torrents for books using MyAnonamouse."""

    def __init__(
        self,
        mam: MyAnonamouse,
        lang_codes: list[str],
        torrent_selector: TorrentSelector,
        torrent_client: TorrentClient | None = None,
    ) -> None:
        """Service for discovering torrents for books using MyAnonamouse."""
        self.mam = mam
        self.lang_codes = set(lang_codes)
        self.torrent_selector = torrent_selector
        self.torrent_client = torrent_client

    def _mam_ids_with_tag(self, tag: str) -> set[str]:
        """Return MAM IDs for torrents carrying the specified client tag."""
        if self.torrent_client is None:
            return set()

        mam_ids = set()
        tagged_torrents = self.torrent_client.get_torrents_with_tag(tag)
        for torrent in tagged_torrents:
            comment = getattr(torrent, "comment", None) or ""
            # qBittorrent keeps the MAM torrent ID in the .torrent comment.
            match = re.search(r"MID=(\d+)", comment)
            if match:
                mam_ids.add(match.group(1))
        return mam_ids

    def find_torrents(self, book: Book) -> tuple[Book, set[Torrent]]:
        """Find torrents for a given book."""
        mam_books = self._search_titles(book)

        for torrent in mam_books:
            # Prefer series info from Hardcover if available,
            # as MyAnonamouse's data can be inconsistent.
            torrent.book.series = book.series
            torrent.book.series_number = book.series_number
        return book, mam_books

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

    def _search_titles(self, book: Book) -> set[Torrent]:
        """Search each distinct main or alternate title without an author filter."""
        results: set[Torrent] = set()
        for title in self._titles_to_search(book):
            logger.debug(
                "Searching MyAnonamouse by title only: %r",
                title,
            )
            results.update(self.mam.search_ebook(title))
        return results

    def submit_downloads(
        self,
        executor: ThreadPoolExecutor,
        search_futures: dict[Future, Book],
        matcher: BookMatcher,
    ) -> dict[Future, Book]:
        """Download the best matching torrent for each book once the search futures complete."""

        download_futures = {}
        failed_import_mam_ids = self._mam_ids_with_tag("murid_import_failed")

        for future in as_completed(search_futures):
            book = search_futures[future]
            _, tor_list = future.result()

            if failed_import_mam_ids:
                tor_list = {
                    torrent
                    for torrent in tor_list
                    if str(torrent.book.id) not in failed_import_mam_ids
                }

            if not tor_list:
                continue

            torrent = self.torrent_selector.select(book, tor_list, matcher)

            if not torrent:
                continue

            logger.info("Selected torrent for %s: %s", book, torrent)
            download_future = executor.submit(self.mam.download_torrent, torrent)
            download_futures[download_future] = torrent.book
        return download_futures

    def collect_downloads(
        self,
        download_futures: dict[Future, Book],
    ) -> set[tuple[bytes, Book]]:
        """Collect the downloaded torrent data once the download futures complete."""

        torrent_files = set()
        for future in as_completed(download_futures):
            book = download_futures[future]
            torrent_file = future.result()
            if torrent_file:
                torrent_files.add((torrent_file, book))

        return torrent_files

    def download_torrents(
        self,
        books: Iterable[Book],
        matcher: BookMatcher,
        incomplete_timed_out_books: Iterable[Book] = (),
    ) -> set[tuple[bytes, Book]]:
        """Find and download torrents for a list of books."""
        books = list(books)
        incomplete_timed_out_books = list(incomplete_timed_out_books)
        books_to_search = [
            book
            for book in books
            if not any(
                matcher.similarity(book, timed_out_book) >= matcher.threshold
                for timed_out_book in incomplete_timed_out_books
            )
        ]
        skipped_count = len(books) - len(books_to_search)
        logger.info(
            "Searching for torrents for %d book%s",
            len(books_to_search),
            "s" if len(books_to_search) != 1 else "",
        )
        if skipped_count:
            logger.info(
                "Skipping search for %d book%s with an incomplete timed-out torrent",
                skipped_count,
                "s" if skipped_count != 1 else "",
            )
        if not books_to_search:
            return set()

        with ThreadPoolExecutor(max_workers=min(10, len(books_to_search))) as executor:
            search_futures = {
                executor.submit(self.find_torrents, book): book for book in books_to_search
            }

            download_futures = self.submit_downloads(executor, search_futures, matcher)

            if not download_futures:
                return set()
            return self.collect_downloads(download_futures)
