"""Select the file for a requested book from a completed torrent."""

import logging
import re
from pathlib import Path
from typing import Iterable

from .book import Book
from .book_matcher import BookMatcher

logger = logging.getLogger("murid")

_DEFAULT_FILETYPES = ("epub", "mobi", "azw3", "azw")
_MIN_TITLE_SIMILARITY = 0.75
_AMBIGUITY_MARGIN = 0.04


class BookFileSelector:  # pylint: disable=too-few-public-methods
    """Choose one supported ebook file for a book from a completed torrent."""

    def __init__(self, filetypes: Iterable[str] | None = None) -> None:
        normalized = filetypes or _DEFAULT_FILETYPES
        self.filetypes = tuple(
            dict.fromkeys(str(filetype).strip().lower().lstrip(".") for filetype in normalized)
        )
        self._filetype_priority = {filetype: index for index, filetype in enumerate(self.filetypes)}

    def select(self, book: Book, completed_path: str, matcher: BookMatcher) -> Path | None:
        """Return the matching ebook path, or None when a multi-book pack is ambiguous."""
        root = Path(completed_path)

        # Keep the existing error path for inaccessible download locations. Calibre will
        # report the underlying path problem, while an accessible directory is always
        # inspected before it can be passed to Calibre.
        if not root.exists():
            logger.warning("%s: completed torrent path is not accessible: %r", book, completed_path)
            return root

        if root.is_file():
            if self._supported(root):
                return root
            logger.warning("%s: completed torrent file has an unsupported format: %s", book, root)
            return None

        return self._select_from_directory(book, root, matcher)

    def _select_from_directory(
        self,
        book: Book,
        root: Path,
        matcher: BookMatcher,
    ) -> Path | None:
        """Find a matching file among supported ebooks below a torrent directory."""
        try:
            candidates = sorted(
                (path for path in root.rglob("*") if path.is_file() and self._supported(path)),
                key=lambda path: str(path).casefold(),
            )
        except OSError as error:
            logger.warning(
                "%s: could not inspect completed torrent directory %s: %s",
                book,
                root,
                error,
            )
            return None
        if not candidates:
            logger.warning("%s: no supported ebook files found under %s", book, root)
            return None

        if len(candidates) == 1:
            logger.info("%s: selected the only ebook file: %s", book, candidates[0])
            return candidates[0]

        return self._select_best_candidate(book, root, candidates, matcher)

    def _select_best_candidate(
        self,
        book: Book,
        root: Path,
        candidates: list[Path],
        matcher: BookMatcher,
    ) -> Path | None:
        """Select a uniquely matching candidate from a multi-book pack."""
        scored = [(self._score(book, path, matcher), path) for path in candidates]
        scored = [(score, path) for score, path in scored if score is not None]
        scored.sort(key=lambda item: item[0][0], reverse=True)

        if not scored or scored[0][0][0] < _MIN_TITLE_SIMILARITY:
            logger.warning(
                "%s: could not match an ebook filename in %r; candidates: %r",
                book,
                root,
                ", ".join(str(path.relative_to(root)) for path in candidates),
            )
            return None

        best_score, best_key = scored[0][0]
        close_matches = [
            (score, path, key)
            for (score, key), path in scored
            if best_score - score <= _AMBIGUITY_MARGIN
        ]
        distinct_titles = {key for _, _, key in close_matches}
        if len(distinct_titles) > 1:
            logger.warning(
                "%s: ambiguous ebook files in %r; refusing to import: %r",
                book,
                root,
                ", ".join(str(path.relative_to(root)) for _, path, _ in close_matches),
            )
            return None

        selected = min(
            (path for _, path, key in close_matches if key == best_key),
            key=self._preference,
        )
        logger.info(
            "%s: selected %s (title score %.3f)",
            book,
            selected,
            best_score,
        )
        return selected

    def _supported(self, path: Path) -> bool:
        return path.suffix.lower().lstrip(".") in self._filetype_priority

    def _preference(self, path: Path) -> tuple[int, str]:
        return (
            self._filetype_priority.get(path.suffix.lower().lstrip("."), len(self.filetypes)),
            str(path).casefold(),
        )

    @classmethod
    def _score(
        cls,
        book: Book,
        path: Path,
        matcher: BookMatcher,
    ) -> tuple[float, str] | None:
        title_names = [book.title, *(book.alternative_titles or [])]
        filename_titles = cls._filename_title_variants(book, path.stem)
        best_score = -1.0
        best_key: str | None = None

        for title in title_names:
            if not title:
                continue
            for candidate_title in sorted(filename_titles):
                score = matcher.title_similarity(title, candidate_title)
                key = matcher.canonicalize_title(candidate_title)
                if score > best_score:
                    best_score = score
                    best_key = key

        return (best_score, best_key) if best_key is not None else None

    @classmethod
    def _filename_title_variants(cls, book: Book, stem: str) -> set[str]:
        """Remove known author and series labels around a filename's title."""
        # Release filenames commonly append series/volume labels and catalog IDs
        # after the actual title. Remove those before fuzzy matching so they do
        # not dilute otherwise exact title matches.
        cleaned_stem = re.sub(r"\s+-\s+[A-Z0-9]{8,}(?=\s|$)", "", stem)
        cleaned_stem = re.sub(
            r"\s*\((?=[^)]*(?:\bbook\s*#?\d+|\bvol(?:ume)?\s*#?\d+|"
            r"\bpart\s*#?\d+|\bthe\s+expanse\b))[^)]*\)",
            "",
            cleaned_stem,
            flags=re.IGNORECASE,
        )
        title = BookMatcher.normalize(cleaned_stem)
        if not title:
            return set()

        variants = cls._strip_author_names(book, cls._with_numbered_variant(title, cleaned_stem))
        return cls._strip_series_prefix(book, variants)

    @staticmethod
    def _with_numbered_variant(title: str, stem: str) -> set[str]:
        """Include a title without a leading file sequence number."""
        variants = {title}
        numbered_title = re.sub(r"^\s*\d{1,3}\s*[-._]+\s*", "", stem)
        normalized_numbered_title = BookMatcher.normalize(numbered_title)
        if normalized_numbered_title and normalized_numbered_title != title:
            variants.add(normalized_numbered_title)
        return variants

    @staticmethod
    def _strip_author_names(book: Book, variants: set[str]) -> set[str]:
        """Add filename variants without a known author prefix or suffix."""
        author_names = set()
        for author in book.authors or []:
            author_name = BookMatcher.normalize(author)
            if author_name:
                author_names.add(author_name)
            if "," in author:
                surname, given = author.split(",", 1)
                reversed_name = BookMatcher.normalize(f"{given} {surname}")
                if reversed_name:
                    author_names.add(reversed_name)

        for author in author_names:
            for value in tuple(variants):
                if value.startswith(f"{author} "):
                    variants.add(value[len(author) :].strip())
                if value.endswith(f" {author}"):
                    variants.add(value[: -len(author)].strip())
                by_author = f" by {author}"
                if value.endswith(by_author):
                    variants.add(value[: -len(by_author)].strip())

                # Some release names abbreviate middle names or omit periods,
                # so also remove a suffix when its word sequence matches the
                # trailing portion of the known author name.
                author_words = author.split()
                value_words = value.split()
                for count in range(2, len(author_words) + 1):
                    suffix = author_words[-count:]
                    if value_words[-count:] == suffix and len(value_words) > count:
                        stripped = " ".join(value_words[:-count])
                        variants.discard(value)
                        variants.add(stripped)

        return variants

    @staticmethod
    def _strip_series_prefix(book: Book, variants: set[str]) -> set[str]:
        """Add filename variants without the requested book's series prefix."""
        series = BookMatcher.normalize(book.series or "")
        if series:
            for value in tuple(variants):
                if value.startswith(f"{series} "):
                    remainder = value[len(series) :].strip()
                    remainder = re.sub(
                        r"^(?:(?:book|vol(?:ume)?|part)\s*)?#?\d+(?:\.\d+)?\s+",
                        "",
                        remainder,
                    )
                    if remainder:
                        variants.add(remainder)

        return {value for value in variants if value}
