"""Service for discovering torrents for books using MyAnonamouse."""

import logging
from concurrent.futures import Future, ThreadPoolExecutor, as_completed

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

    def find_torrents(self, book: Book) -> tuple[Book, list[Torrent]]:
        """Find torrents for a given book."""
        mam_books = self.mam.search_ebook(book.title, book.authors[0] if book.authors else None)

        for torrent in mam_books:
            # Prefer series info from Hardcover if available,
            # as MyAnonamouse's data can be inconsistent.
            torrent.book.series = book.series
            torrent.book.series_number = book.series_number
        return book, mam_books

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
            logger.debug(
                "Potential torrents found for %s:\n%s",
                book,
                [str(torrent) for torrent in tor_list],
            )

            torrent = self.torrent_selector.select(book, tor_list, matcher)

            if not torrent:
                continue

            download_future = executor.submit(self.mam.download_torrent, torrent)
            download_futures[download_future] = torrent.book
        return download_futures

    def collect_downloads(
        self,
        download_futures: dict[Future, Book],
    ) -> list[tuple[bytes, Book]]:
        """Collect the downloaded torrent data once the download futures complete."""

        torrent_files = []
        for future in as_completed(download_futures):
            book = download_futures[future]
            torrent_file = future.result()
            if torrent_file:
                torrent_files.append((torrent_file, book))

        return torrent_files

    def download_torrents(
        self, books: list[Book], matcher: BookMatcher
    ) -> list[tuple[bytes, Book]]:
        """Find and download torrents for a list of books."""
        logger.info(
            "Searching for torrents for %d book%s", len(books), "s" if len(books) != 1 else ""
        )
        with ThreadPoolExecutor(max_workers=min(10, len(books))) as executor:
            search_futures = {executor.submit(self.find_torrents, book): book for book in books}

            download_futures = self.submit_downloads(executor, search_futures, matcher)

            if not download_futures:
                return []
            return self.collect_downloads(download_futures)
