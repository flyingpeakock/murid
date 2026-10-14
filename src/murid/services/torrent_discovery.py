"""Service for discovering torrents for books using MyAnonamouse."""

import logging
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Iterable

from ..clients.myanonamouse import MyAnonamouse
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
    ) -> None:
        """Service for discovering torrents for books using MyAnonamouse."""
        self.mam = mam
        self.lang_codes = set(lang_codes)
        self.torrent_selector = torrent_selector

    def find_torrents(self, book: Book) -> tuple[Book, set[Torrent]]:
        """Find torrents for a given book."""
        author = book.authors[0] if book.authors else None
        mam_books = self.mam.search_ebook(book.title, author)

        if not mam_books:
            mam_books = self._search_without_author(book, author)

        for torrent in mam_books:
            # Prefer series info from Hardcover if available,
            # as MyAnonamouse's data can be inconsistent.
            torrent.book.series = book.series
            torrent.book.series_number = book.series_number
        return book, mam_books

    @staticmethod
    def _search_titles(book: Book) -> list[str]:
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

    def _search_without_author(self, book: Book, author: str | None) -> set[Torrent]:
        """Search the main and alternate titles without an author filter."""
        results: set[Torrent] = set()
        for title in self._search_titles(book):
            logger.debug(
                "No MyAnonamouse results for %r by %r; retrying with title-only search %r",
                book.title,
                author,
                title,
            )
            results.update(self.mam.search_ebook(title, None))
        return results

    def submit_downloads(
        self,
        executor: ThreadPoolExecutor,
        search_futures: dict[Future, Book],
        matcher: BookMatcher,
    ) -> dict[Future, Book]:
        """Download the best matching torrent for each book once the search futures complete."""

        download_futures = {}

        for future in as_completed(search_futures):
            book = search_futures[future]
            _, tor_list = future.result()

            if not tor_list:
                continue

            torrent = self.torrent_selector.select(book, tor_list, matcher)

            if not torrent:
                logger.info(
                    "No suitable torrent found for %s; retrying title-only searches",
                    book,
                )
                title_only_torrents = self._search_without_author(
                    book, book.authors[0] if book.authors else None
                )
                if title_only_torrents:
                    torrent = self.torrent_selector.select(book, title_only_torrents, matcher)

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
        self, books: Iterable[Book], matcher: BookMatcher
    ) -> set[tuple[bytes, Book]]:
        """Find and download torrents for a list of books."""
        logger.info(
            "Searching for torrents for %d book%s", len(books), "s" if len(books) != 1 else ""
        )
        with ThreadPoolExecutor(max_workers=min(10, len(books))) as executor:
            search_futures = {executor.submit(self.find_torrents, book): book for book in books}

            download_futures = self.submit_downloads(executor, search_futures, matcher)

            if not download_futures:
                return set()
            return self.collect_downloads(download_futures)
