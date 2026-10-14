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
        torrents = list(torrents)
        torrent_books = set()
        rejected_by_language = 0
        rejected_by_filetype = 0
        rejected_by_blacklist = 0

        for torrent in torrents:
            rejected = False
            if torrent.language is not None and torrent.language not in self.lang_codes:
                rejected_by_language += 1
                rejected = True

            matching_filetypes = self.wanted_filetypes.intersection(torrent.file_types or [])
            if not matching_filetypes:
                rejected_by_filetype += 1
                rejected = True

            if torrent.book.id in self.blacklist:
                rejected_by_blacklist += 1
                rejected = True

            if rejected:
                continue

            torrent_books.add(torrent.book)

        logger.debug(
            "Torrent filters for %r: input=%d eligible_books=%d rejected_language=%d "
            "rejected_filetype=%d rejected_blacklist=%d allowed_languages=%r "
            "wanted_filetypes=%r",
            book.title,
            len(torrents),
            len(torrent_books),
            rejected_by_language,
            rejected_by_filetype,
            rejected_by_blacklist,
            sorted(self.lang_codes),
            sorted(self.wanted_filetypes),
        )

        if not torrent_books:
            logger.info("No torrents for %s passed language and file type filters", book)
            return None

        best_match, score = matcher.best_match(book, torrent_books)

        if best_match and score >= matcher.threshold and matcher.is_match(book, best_match):
            ret = next(t for t in torrents if t.book == best_match)
            logger.debug("Best torrent for %s is %s with similarity %.2f", book, ret, score)
            return ret
        logger.info("No good torrent match for %s. Best similarity: %.2f", book, score)
        return None
