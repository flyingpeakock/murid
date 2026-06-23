"""Class for selecting the best matching torrent for a given book"""

import logging
from typing import Iterable

from .book import Book
from .book_matcher import BookMatcher
from .torrent import Torrent

logger = logging.getLogger("murid")


class TorrentSelector:  # pylint: disable=too-few-public-methods
    """Class for selecting the best matching torrent for a given book"""

    def __init__(
        self,
        lang_codes: set[str],
        wanted_filetypes: set[str] | None = None,
        blacklist: set[str] | None = None,
    ):
        self.lang_codes = lang_codes

        if not blacklist:
            blacklist = set()
        self.blacklist = blacklist

        if not wanted_filetypes:
            wanted_filetypes = {"epub", "mobi", "azw3"}
        self.wanted_filetypes = wanted_filetypes

    def select(
        self, book: Book, torrents: Iterable[Torrent], matcher: BookMatcher
    ) -> Torrent | None:
        """Select the best matching torrent for the given book from the list of torrents"""
        torrent_books = {
            t.book
            for t in torrents
            if (t.language is None or t.language in self.lang_codes)
            and self.wanted_filetypes.intersection(t.file_types or [])
            and t.book.id not in self.blacklist
        }

        if not torrent_books:
            logger.info("No torrents for %s passed language and file type filters", book)
            return None

        best_match, score = matcher.best_match(book, torrent_books)

        if best_match and score >= matcher.threshold:
            ret = next(t for t in torrents if t.book == best_match)
            logger.debug("Best torrent for %s is %s with similarity %.2f", book, ret, score)
            return ret
        logger.info("No good torrent match for %s. Best similarity: %.2f", book, score)
        return None
