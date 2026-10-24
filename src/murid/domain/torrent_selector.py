"""Class for selecting the best matching torrent for a given book"""

import logging
from collections import Counter
from typing import Iterable

from .book import Book
from .book_matcher import BookMatcher
from .book_request import MediaType
from .torrent import Torrent

logger = logging.getLogger("murid")


class TorrentSelector:  # pylint: disable=too-few-public-methods
    """Class for selecting the best matching torrent for a given book"""

    def __init__(
        self,
        lang_codes: set[str],
        wanted_filetypes: Iterable[str] | None = None,
        blacklist: set[str] | None = None,
        media_type: MediaType = "ebook",
        exclude_vip: bool = False,
    ):
        self.lang_codes = lang_codes
        self.media_type = media_type
        self.exclude_vip = exclude_vip

        if not blacklist:
            blacklist = set()
        self.blacklist = blacklist

        defaults = ("m4b", "mp3") if media_type == "audiobook" else ("epub", "mobi", "azw3")
        formats = wanted_filetypes if wanted_filetypes is not None else defaults
        # Sets remain supported for callers without an explicit format preference.
        if isinstance(formats, (set, frozenset)):
            formats = sorted(formats)
        self.filetype_priority = {
            filetype: index for index, filetype in enumerate(dict.fromkeys(formats))
        }
        self.wanted_filetypes = set(self.filetype_priority)

    def select(
        self, book: Book, torrents: Iterable[Torrent], matcher: BookMatcher
    ) -> Torrent | None:
        """Select the best matching torrent for the given book from the list of torrents"""
        torrents = list(torrents)
        eligible = []
        rejected = Counter()

        for torrent in torrents:
            reasons = self.rejection_reasons(torrent)
            rejected.update(reasons)
            if reasons:
                continue

            eligible.append(torrent)

        logger.debug(
            "%s: torrent filters: input=%d eligible_torrents=%d rejected_language=%d "
            "rejected_filetype=%d rejected_blacklist=%d rejected_vip=%d allowed_languages=%r "
            "wanted_filetypes=%r",
            book,
            len(torrents),
            len(eligible),
            rejected["language"],
            rejected["file type"],
            rejected["blacklisted ID"],
            rejected["VIP"],
            sorted(self.lang_codes),
            sorted(self.wanted_filetypes),
        )

        if not eligible:
            logger.info("%s: no torrents passed configured filters", book)
            return None

        scored = [(torrent, matcher.similarity(book, torrent.book)) for torrent in eligible]
        accepted = [
            (torrent, score)
            for torrent, score in scored
            if score >= matcher.threshold and matcher.is_match(book, torrent.book)
        ]
        if accepted:
            selected, score = min(accepted, key=lambda item: self.preference(*item))
            logger.info(
                "%s: selected torrent %s (match score %.3f, threshold %.3f; "
                "%d seeders, formats %s, freeleech %s)",
                book,
                selected,
                score,
                matcher.threshold,
                selected.metadata.seeders,
                ", ".join(selected.file_types or []),
                selected.metadata.freeleech,
            )
            return selected
        closest, score = max(scored, key=lambda item: item[1])
        logger.info(
            "%s: no acceptable torrent; closest candidate: %s (match score %.3f, "
            "threshold %.3f). Use murid search-book to review candidates",
            book,
            closest.book,
            score,
            matcher.threshold,
        )
        return None

    def preference(self, torrent: Torrent, score: float) -> tuple:
        """Rank valid matches by availability, confidence, format, and download cost."""
        format_rank = min(
            (
                self.filetype_priority[fmt]
                for fmt in torrent.file_types or []
                if fmt in self.filetype_priority
            ),
            default=len(self.filetype_priority),
        )
        return (
            torrent.metadata.seeders <= 0,
            -score,
            format_rank,
            not torrent.metadata.freeleech,
            -torrent.metadata.seeders,
            torrent.book.id,
            torrent.download_hash or "",
        )

    def rejection_reasons(self, torrent: Torrent) -> list[str]:
        """Return the configured filters that reject a torrent before book matching."""
        reasons = []
        if torrent.media_type is not None and torrent.media_type != self.media_type:
            reasons.append("media type")
        if torrent.language is not None and torrent.language not in self.lang_codes:
            reasons.append("language")
        if not self.wanted_filetypes.intersection(torrent.file_types or []):
            reasons.append("file type")
        if self.exclude_vip and torrent.metadata.vip:
            reasons.append("VIP")
        if torrent.book.id in self.blacklist:
            reasons.append("blacklisted ID")
        return reasons
