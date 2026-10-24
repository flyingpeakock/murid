"""Match books using ISBNs, normalized titles, and author similarity."""

import logging
import math
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from rapidfuzz import fuzz
from stdnum import isbn as stdnum_isbn
from stdnum.exceptions import ValidationError

from .book import Book

logger = logging.getLogger("murid")

_MIN_TITLE_SIMILARITY = 0.85
_SERIES_POSITION_BONUS = 0.04
_TITLE_VARIANT_PENALTIES = {
    "volume": 0.97,
    "subtitle": 0.94,
    "omnibus": 0.97,
}


@dataclass(frozen=True)
class _BookFeatures:  # pylint: disable=too-many-instance-attributes
    """Preprocessed metadata used during book comparisons."""

    book: Book
    title: str
    titles: frozenset[str]
    title_variants: tuple[tuple[str, float], ...]
    authors: frozenset[str]
    isbns: frozenset[str]
    identifiers: frozenset[tuple[str, str]]
    series: str
    series_number: float | None


@dataclass(frozen=True)
class MatchReview:
    """Diagnostic comparison; accepted means the candidate was assigned to the book."""

    calibre_book: Book
    score: float
    accepted: bool
    evidence: tuple[str, ...]


class BookMatcher:
    """Match books conservatively using identifiers and metadata."""

    def __init__(self, threshold: float = 0.92):
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between 0.0 and 1.0")
        self.threshold = threshold

    @staticmethod
    def normalize(text: str) -> str:
        """Normalize text without discarding Unicode letters or digits."""
        text = unicodedata.normalize("NFC", text)
        text = text.casefold()
        text = "".join(char if char.isalnum() else " " for char in text)
        return " ".join(text.split())

    @classmethod
    def canonicalize_title(cls, title: str) -> str:
        """Normalize a title while preserving meaningful title words."""
        normalized = cls.normalize(title or "")
        normalized = re.sub(r"\bvs\b", "versus", normalized)
        return cls._remove_article(normalized)

    @staticmethod
    def _remove_article(title: str) -> str:
        """Remove a leading English article."""
        for prefix in ("the ", "an ", "a "):
            if title.startswith(prefix):
                return title[len(prefix) :]
        return title

    @classmethod
    def _normalize_author(cls, author: str) -> str:
        """Normalize an author name, including 'Surname, Given' notation."""
        if "," in author:
            surname, given = author.split(",", 1)
            if surname.strip() and given.strip():
                author = f"{given} {surname}"
        return cls.normalize(author)

    @staticmethod
    def normalize_isbn(isbn: str | None) -> str | None:
        """Validate an ISBN or legacy SBN and normalize it to ISBN-13."""
        if not isbn:
            return None

        isbn = re.sub(r"[^0-9Xx]", "", str(isbn)).upper()

        try:
            return stdnum_isbn.validate(isbn, convert=True)
        except ValidationError:
            return None

    @classmethod
    def normalized_isbns(cls, book: Book) -> set[str]:
        """Return valid, canonicalized ISBNs from a book."""
        return {
            normalized
            for isbn in book.isbn
            if (normalized := cls.normalize_isbn(isbn)) is not None
        }

    @classmethod
    def normalize_identifier_platform(cls, platform: str) -> str:
        """Normalize catalog names shared between Hardcover and Calibre."""
        name = cls.normalize(platform).replace(" ", "")
        aliases = {
            "asin": "amazon",
            "amazoncom": "amazon",
            "amazoncouk": "amazon",
            "amazonca": "amazon",
            "amazonde": "amazon",
            "amazonfr": "amazon",
            "amazonkindle": "amazon",
            "goodreadscom": "goodreads",
            "openlibraryorg": "openlibrary",
            "google": "googlebooks",
            "googlebooks": "googlebooks",
            "booksgoogle": "googlebooks",
            "librarythingcom": "librarything",
        }
        return aliases.get(name, name)

    @classmethod
    def _normalize_identifier_value(cls, platform: str, value: str) -> str:
        """Normalize a raw external ID or a URL containing that ID."""
        value = value.strip()
        if not value:
            return ""

        platform = cls.normalize_identifier_platform(platform)
        parsed = urlsplit(value)
        if parsed.scheme and parsed.netloc:
            path = unquote(parsed.path).rstrip("/")

            if platform == "goodreads":
                match = re.search(r"/(?:book/show|work/editions)/([0-9]+)", path)
                if match:
                    return match.group(1)
            elif platform == "amazon":
                match = re.search(r"/(?:dp|gp/product)/([A-Za-z0-9]{10})", path)
                if match:
                    return match.group(1).casefold()
            elif platform == "googlebooks":
                query_id = dict(
                    pair.split("=", 1) for pair in parsed.query.split("&") if "=" in pair
                ).get("id")
                if query_id:
                    return unquote(query_id).casefold()

            value = path.rsplit("/", 1)[-1]

        return value.strip().casefold()

    @classmethod
    def normalized_identifiers(cls, book: Book) -> set[tuple[str, str]]:
        """Return comparable catalog platform and ID pairs."""
        identifiers = set()
        if book.source == "hardcover":
            identifiers.add(("hardcover", str(book.id)))
        for platform, values in book.identifiers.items():
            if isinstance(values, str):
                values = [values]
            elif not isinstance(values, (list, tuple, set)):
                continue

            normalized_platform = cls.normalize_identifier_platform(str(platform))
            if not normalized_platform:
                continue

            for value in values:
                if value is None:
                    continue
                normalized_value = cls._normalize_identifier_value(
                    normalized_platform,
                    str(value),
                )
                if normalized_value:
                    identifiers.add((normalized_platform, normalized_value))

        return identifiers

    @staticmethod
    def _remove_metadata_annotations(title: str) -> str:
        """Remove recognized metadata annotations embedded in a title."""
        patterns = (
            r"\s*\[\s*published\s*:\s*[^\]]*\]",
            r"\s*\[\s*By\s*:\s*[^\]]*\]",
            r"\s*\(\s*By\s*:\s*[^)]*\)",
        )

        for pattern in patterns:
            title = re.sub(pattern, " ", title, flags=re.IGNORECASE)

        title = " ".join(title.split()).strip()

        # Remove outer brackets only when they enclose the entire title.
        if title.startswith("[") and title.endswith("]"):
            title = title[1:-1].strip()

        return title

    @classmethod
    def _title_variants(
        cls,
        title: str,
        authors: frozenset[str] = frozenset(),
        alternative_titles: Iterable[str] = (),
        series: str | None = None,
    ) -> tuple[tuple[str, float], ...]:
        """Generate conservative title variants with evidence penalties."""
        original = cls._remove_metadata_annotations(title or "")
        full = cls.canonicalize_title(original)

        if not full:
            return ()

        variants: dict[str, float] = {full: 1.0}
        cls._add_connector_title_variant(variants, full)
        cls._add_core_title_variant(variants, full, authors)
        cls._add_omnibus_title_variant(variants, full)
        cls._add_subtitle_variant(variants, original, full)
        cls._add_series_title_variant(variants, full, series)
        cls._add_alternative_title_variants(variants, alternative_titles, authors, series)

        return tuple(variants.items())

    @staticmethod
    def _add_omnibus_title_variant(variants: dict[str, float], full: str) -> None:
        """Treat a trailing omnibus label as packaging metadata."""
        match = re.search(r"\s+omnibus(?: edition)?$", full)
        if match:
            core = full[: match.start()].strip()
            if core:
                variants[core] = _TITLE_VARIANT_PENALTIES["omnibus"]

    @classmethod
    def _add_connector_title_variant(cls, variants: dict[str, float], full: str) -> None:
        """Add a short title variant when a series name precedes it."""

        # Some sources include a series name before a short book title, such as
        # "Harry Potter and the Prisoner of Azkaban" or "Alcatraz versus the
        # Knights of Crystallia", while others list only the short title.
        suffix_match = re.search(r"^(.*?)\b(versus|and)\s+(the|a|an)\s+(.+)$", full)
        if not suffix_match:
            return

        short_title = cls._remove_article(f"{suffix_match.group(3)} {suffix_match.group(4)}")
        prefix_words = suffix_match.group(1).split()
        suffix_words = short_title.split()
        connector = suffix_match.group(2)
        is_series_prefix = len(suffix_words) >= 2 and (
            connector == "versus" or len(prefix_words) >= 2
        )
        if short_title != full and is_series_prefix:
            variants[short_title] = _TITLE_VARIANT_PENALTIES["subtitle"]

    @classmethod
    def _add_core_title_variant(
        cls,
        variants: dict[str, float],
        full: str,
        authors: frozenset[str],
    ) -> None:
        """Add a variant without a confirmed author suffix or volume marker."""
        core = cls._remove_author_suffix(full, authors)
        core = cls._remove_volume_annotation(core)
        core = cls._remove_article(core)

        if core and core != full:
            variants[core] = _TITLE_VARIANT_PENALTIES["volume"]

    @classmethod
    def _add_subtitle_variant(
        cls,
        variants: dict[str, float],
        original: str,
        full: str,
    ) -> None:
        """Add the part before a colon as a penalized subtitle variant."""
        if ":" in original:
            main_title = cls.canonicalize_title(original.split(":", 1)[0])
            if main_title and main_title != full:
                variants[main_title] = max(
                    variants.get(main_title, 0.0),
                    _TITLE_VARIANT_PENALTIES["subtitle"],
                )

    @classmethod
    def _add_series_title_variant(
        cls,
        variants: dict[str, float],
        full: str,
        series: str | None,
    ) -> None:
        """Add a title with its leading series name removed."""
        normalized_series = cls.canonicalize_title(series or "")
        if normalized_series and full.startswith(f"{normalized_series} "):
            series_suffix = full[len(normalized_series) :].strip()
            series_suffix = re.sub(r"^(?:book\s+)?#?\d+(?:\.\d+)?\s+", "", series_suffix)
            series_suffix = re.sub(r"^and\s+", "", series_suffix)
            series_suffix = cls._remove_article(series_suffix)
            if len(series_suffix.split()) >= 2:
                variants[series_suffix] = max(
                    variants.get(series_suffix, 0.0),
                    _TITLE_VARIANT_PENALTIES["volume"],
                )

    @classmethod
    def _add_alternative_title_variants(
        cls,
        variants: dict[str, float],
        alternative_titles: Iterable[str],
        authors: frozenset[str],
        series: str | None,
    ) -> None:
        """Add variants derived from alternate titles at a reduced confidence."""
        for alternative_title in alternative_titles:
            for variant, penalty in cls._title_variants(alternative_title, authors, series=series):
                variants[variant] = max(variants.get(variant, 0.0), 0.98 * penalty)

    @staticmethod
    def _remove_author_suffix(
        title: str,
        authors: frozenset[str],
    ) -> str:
        """Remove a trailing author name only when metadata confirms it."""
        for author in sorted(authors, key=len, reverse=True):
            suffix = f" {author}"
            if title.endswith(suffix) and title[: -len(suffix)].strip():
                return title[: -len(suffix)].strip()
        return title

    @staticmethod
    def _remove_volume_annotation(title: str) -> str:
        """Remove an explicit trailing volume, book, or part number."""
        return re.sub(
            r"\s+(?:vol(?:ume)?\.?|book|part)\s+\d+(?:\s+of\s+\d+)?\s*$",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip()

    @classmethod
    def _prepare(cls, book: Book) -> _BookFeatures:
        """Precompute metadata once per book."""
        authors = cls._prepared_authors(book)
        title = cls.canonicalize_title(book.title)
        alternative_titles = cls._alternative_titles(book)
        title_names = cls._prepared_title_names(book, alternative_titles)

        features = _BookFeatures(
            book=book,
            title=title,
            titles=title_names,
            title_variants=cls._title_variants(
                book.title or "",
                authors,
                alternative_titles,
                book.series,
            ),
            authors=authors,
            isbns=frozenset(cls.normalized_isbns(book)),
            identifiers=frozenset(cls.normalized_identifiers(book)),
            series=cls.canonicalize_title(book.series or ""),
            series_number=cls._normalize_series_number(book.series_number),
        )
        return features

    @classmethod
    def _prepared_authors(cls, book: Book) -> frozenset[str]:
        """Normalize the authors present on a book."""
        return frozenset(
            normalized
            for name in book.authors
            if name and (normalized := cls._normalize_author(name))
        )

    @staticmethod
    def _alternative_titles(book: Book) -> list[str]:
        """Return nonempty alternate titles as strings."""
        return [str(value) for value in book.alternative_titles if value]

    @classmethod
    def _prepared_title_names(
        cls,
        book: Book,
        alternative_titles: list[str],
    ) -> frozenset[str]:
        """Normalize the main and alternate titles present on a book."""
        return frozenset(
            canonical
            for value in [book.title or "", *alternative_titles]
            if (canonical := cls.canonicalize_title(value))
        )

    @staticmethod
    def _normalize_series_number(value) -> float | None:
        """Convert a series position to a number when the source provides one."""
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _contains_author_tokens(tokens_a: list[str], tokens_b: list[str]) -> bool:
        """Check whether one multiword author value occurs inside the other."""
        a_in_b = (
            len(tokens_a) >= 2
            and len(tokens_a) <= len(tokens_b)
            and any(
                tokens_b[index : index + len(tokens_a)] == tokens_a
                for index in range(len(tokens_b) - len(tokens_a) + 1)
            )
        )
        b_in_a = (
            len(tokens_b) >= 2
            and len(tokens_b) <= len(tokens_a)
            and any(
                tokens_a[index : index + len(tokens_b)] == tokens_b
                for index in range(len(tokens_a) - len(tokens_b) + 1)
            )
        )
        return a_in_b or b_in_a

    @staticmethod
    def _author_initials_match(given_a: list[str], given_b: list[str]) -> bool:
        """Compare fully abbreviated or singly abbreviated given names."""
        all_initials_match = (
            given_a
            and given_b
            and all(len(token) == 1 for token in given_a)
            and all(len(token) == 1 for token in given_b)
            and "".join(given_a) == "".join(given_b)
        )
        first_initial_matches = (
            len(given_a) == 1 and len(given_a[0]) == 1 and given_b and given_a[0] == given_b[0][0]
        )
        second_initial_matches = (
            len(given_b) == 1 and len(given_b[0]) == 1 and given_a and given_b[0] == given_a[0][0]
        )
        return bool(all_initials_match or first_initial_matches or second_initial_matches)

    @classmethod
    def _author_names_match(cls, a: str, b: str) -> bool:
        """Recognize exact names, joined author values, initials, and spelling variants."""
        if a == b:
            return True

        tokens_a = a.split()
        tokens_b = b.split()

        if not tokens_a or not tokens_b:
            return False

        if cls._contains_author_tokens(tokens_a, tokens_b):
            return True

        if tokens_a[-1] == tokens_b[-1]:
            if cls._author_initials_match(tokens_a[:-1], tokens_b[:-1]):
                return True

        return fuzz.ratio(a, b) >= 90

    @classmethod
    def _author_similarity(
        cls,
        authors_a: frozenset[str],
        authors_b: frozenset[str],
    ) -> float:
        """Compare author lists while tolerating additional contributors."""
        if not authors_a or not authors_b:
            return 0.0

        remaining = set(authors_b)
        matched = 0

        for author_a in sorted(authors_a):
            match = next(
                (
                    author_b
                    for author_b in sorted(remaining)
                    if cls._author_names_match(author_a, author_b)
                ),
                None,
            )
            if match is not None:
                remaining.remove(match)
                matched += 1

        overlap = matched / min(len(authors_a), len(authors_b))
        jaccard = matched / (len(authors_a) + len(authors_b) - matched)

        return 0.7 * overlap + 0.3 * jaccard

    @staticmethod
    def _title_similarity_features(
        a: _BookFeatures,
        b: _BookFeatures,
    ) -> float:
        """Compare full titles and penalized title variants."""
        if not a.title_variants or not b.title_variants:
            return 0.0

        best_score = 0.0

        for title_a, penalty_a in a.title_variants:
            for title_b, penalty_b in b.title_variants:
                if title_a == title_b:
                    score = 1.0
                else:
                    score = (
                        max(
                            fuzz.ratio(title_a, title_b),
                            fuzz.token_sort_ratio(title_a, title_b),
                        )
                        / 100
                    )

                score *= min(penalty_a, penalty_b)
                best_score = max(best_score, score)

        return best_score

    @classmethod
    def _similarity(
        cls,
        a: _BookFeatures,
        b: _BookFeatures,
    ) -> float:
        """Calculate a score from 0 to 1."""
        shared_isbns = a.isbns & b.isbns
        shared_catalog_ids = a.identifiers & b.identifiers
        shared_identifier = bool(shared_isbns or shared_catalog_ids)
        conflicting_identifiers = shared_identifier and cls._conflicting_identifier_metadata(a, b)
        if shared_identifier and not conflicting_identifiers:
            return 1.0
        if conflicting_identifiers:
            logger.debug(
                "%s: shared identifier conflicts with metadata for %s; scoring by title/authors",
                a.book,
                b.book,
            )

        title_score = cls._title_similarity_features(a, b)
        author_score = cls._author_similarity(a.authors, b.authors)

        if not a.authors or not b.authors:
            score = 0.94 * title_score
        else:
            score = 0.85 * title_score + 0.15 * author_score

        same_series_position = (
            a.series
            and a.series == b.series
            and a.series_number is not None
            and b.series_number is not None
            and math.isclose(a.series_number, b.series_number)
        )
        if same_series_position and title_score >= _MIN_TITLE_SIMILARITY:
            score = min(1.0, score + _SERIES_POSITION_BONUS)

        return score

    @classmethod
    def _conflicting_identifier_metadata(
        cls,
        a: _BookFeatures,
        b: _BookFeatures,
    ) -> bool:
        """Detect a reused book identifier contradicted by title and author metadata."""
        if not a.title or not b.title or not a.authors or not b.authors:
            return False

        return (
            cls._title_similarity_features(a, b) < 0.35
            and cls._author_similarity(a.authors, b.authors) == 0.0
        )

    @classmethod
    def _is_match(
        cls,
        a: _BookFeatures,
        b: _BookFeatures,
        score: float,
        threshold: float,
    ) -> bool:
        """Apply both the title-similarity floor and overall threshold."""
        return cls._rejection_reason(a, b, score, threshold) is None

    @classmethod
    def _rejection_reason(
        cls, a: _BookFeatures, b: _BookFeatures, score: float, threshold: float
    ) -> str | None:
        """Describe the first failed matching rule, or accept the comparison."""
        if a.isbns & b.isbns or a.identifiers & b.identifiers:
            conflict = cls._conflicting_identifier_metadata(a, b)
            return (
                "shared identifier conflicts with title and author metadata" if conflict else None
            )

        series_position_conflict = bool(
            a.series
            and a.series == b.series
            and a.series_number is not None
            and b.series_number is not None
            and not math.isclose(a.series_number, b.series_number)
        )

        if series_position_conflict:
            return f"different series positions ({a.series_number:g} vs {b.series_number:g})"
        if cls._conflicting_title_words(a.title, b.title) and not a.titles & b.titles:
            return "titles differ by a meaningful word"

        if a.authors and b.authors and cls._author_similarity(a.authors, b.authors) == 0.0:
            return "authors do not overlap"

        title_score = cls._title_similarity_features(a, b)
        if title_score < _MIN_TITLE_SIMILARITY:
            return f"title score {title_score:.3f} is below minimum {_MIN_TITLE_SIMILARITY:.3f}"
        return (
            f"match score {score:.3f} is below threshold {threshold:.3f}"
            if score < threshold
            else None
        )

    def title_similarity(self, a: str, b: str) -> float:
        """Return title-only similarity."""
        features_a = _BookFeatures(
            book=None,  # type: ignore[arg-type]
            title=self.canonicalize_title(a),
            titles=(
                frozenset({self.canonicalize_title(a)})
                if self.canonicalize_title(a)
                else frozenset()
            ),
            title_variants=self._title_variants(a),
            authors=frozenset(),
            isbns=frozenset(),
            identifiers=frozenset(),
            series="",
            series_number=None,
        )
        features_b = _BookFeatures(
            book=None,  # type: ignore[arg-type]
            title=self.canonicalize_title(b),
            titles=(
                frozenset({self.canonicalize_title(b)})
                if self.canonicalize_title(b)
                else frozenset()
            ),
            title_variants=self._title_variants(b),
            authors=frozenset(),
            isbns=frozenset(),
            identifiers=frozenset(),
            series="",
            series_number=None,
        )
        return self._title_similarity_features(features_a, features_b)

    def author_similarity(self, a: list[str], b: list[str]) -> float:
        """Return author-only similarity."""
        authors_a = frozenset(
            normalized for name in a if name and (normalized := self._normalize_author(name))
        )
        authors_b = frozenset(
            normalized for name in b if name and (normalized := self._normalize_author(name))
        )
        return self._author_similarity(authors_a, authors_b)

    def similarity(self, a: Book, b: Book) -> float:
        """Return the similarity score between two books."""
        return self._similarity(self._prepare(a), self._prepare(b))

    @classmethod
    def _conflicting_title_words(cls, a: str, b: str) -> bool:
        """Detect titles that differ by one meaningful word."""
        words_a = cls.canonicalize_title(a).split()
        words_b = cls.canonicalize_title(b).split()

        if len(words_a) != len(words_b) or len(words_a) < 2:
            return False

        differences = sum(
            word_a != word_b for word_a, word_b in zip(words_a, words_b, strict=False)
        )
        return differences == 1

    def is_match(self, a: Book, b: Book) -> bool:
        """Return whether two books satisfy the matching rules."""
        features_a = self._prepare(a)
        features_b = self._prepare(b)
        score = self._similarity(features_a, features_b)
        return self._is_match(
            features_a,
            features_b,
            score,
            self.threshold,
        )

    def rejection_reason(self, a: Book, b: Book) -> str | None:
        """Explain the matching rule rejecting a candidate without changing selection."""
        features_a = self._prepare(a)
        features_b = self._prepare(b)
        return self._rejection_reason(
            features_a, features_b, self._similarity(features_a, features_b), self.threshold
        )

    def best_match(
        self,
        book: Book,
        candidates: Iterable[Book],
    ) -> tuple[Book | None, float]:
        """Return the highest-scoring candidate, even below threshold."""
        target = self._prepare(book)
        best_candidate = None
        best_score = -1.0

        for candidate in candidates:
            prepared = self._prepare(candidate)
            score = self._similarity(target, prepared)

            if score > best_score:
                best_candidate = candidate
                best_score = score

        if best_candidate is None:
            logger.debug("%s: no candidates available to compare", book)
            return None, 0.0

        logger.debug(
            "%s: best candidate is %s with score %.3f",
            book,
            best_candidate,
            best_score,
        )
        return best_candidate, best_score

    def _score_candidates(
        self,
        target: _BookFeatures,
        candidates: list[_BookFeatures],
    ) -> list[tuple[_BookFeatures, float]]:
        """Score candidates and return them in descending score order."""
        scored = [(candidate, self._similarity(target, candidate)) for candidate in candidates]
        return sorted(
            scored,
            key=lambda item: item[1],
            reverse=True,
        )

    @classmethod
    def _match_evidence(cls, hardcover: _BookFeatures, calibre: _BookFeatures) -> tuple[str, ...]:
        """Describe the metadata contributing to a comparison score."""
        evidence = []
        shared_isbns = sorted(hardcover.isbns & calibre.isbns)
        if shared_isbns:
            evidence.append("ISBN " + ", ".join(shared_isbns))
        shared_ids = sorted(hardcover.identifiers & calibre.identifiers)
        if shared_ids:
            evidence.append(
                "identifier " + ", ".join(f"{platform}:{value}" for platform, value in shared_ids)
            )
        if hardcover.titles & calibre.titles:
            evidence.append("exact normalized title")
        elif cls._title_similarity_features(hardcover, calibre):
            evidence.append(
                f"title similarity {cls._title_similarity_features(hardcover, calibre):.3f}"
            )
        if cls._author_similarity(hardcover.authors, calibre.authors):
            author_score = cls._author_similarity(hardcover.authors, calibre.authors)
            evidence.append(f"author similarity {author_score:.3f}")
        if (
            hardcover.series
            and hardcover.series == calibre.series
            and hardcover.series_number is not None
            and hardcover.series_number == calibre.series_number
        ):
            evidence.append(f"same series position ({hardcover.series_number:g})")
        return tuple(evidence) or ("no matching metadata",)

    def review_matches(
        self,
        calibre_books: Iterable[Book],
        hardcover_books: Iterable[Book],
    ) -> list[tuple[Book, list[MatchReview]]]:
        """Return score-ordered diagnostics using the normal one-to-one assignments."""
        calibre_books = list(calibre_books)
        hardcover_books = list(hardcover_books)
        assigned_pairs = {
            (id(calibre), id(hardcover))
            for calibre, hardcover, _ in self.match_books(calibre_books, hardcover_books)
        }
        candidates = [self._prepare(book) for book in calibre_books]
        reviews = []
        for hardcover_book in hardcover_books:
            target = self._prepare(hardcover_book)
            scored = self._score_candidates(target, candidates)
            reviews.append(
                (
                    hardcover_book,
                    [
                        MatchReview(
                            calibre_book=candidate.book,
                            score=score,
                            accepted=(id(candidate.book), id(hardcover_book)) in assigned_pairs,
                            evidence=self._match_evidence(target, candidate),
                        )
                        for candidate, score in scored
                    ],
                )
            )
        return reviews

    def _log_ambiguity(
        self,
        target: _BookFeatures,
        scored: list[tuple[_BookFeatures, float]],
    ) -> None:
        """Log similarly scoring candidates with different metadata."""
        if not scored:
            return

        best, best_score = scored[0]

        for other, other_score in scored[1:]:
            if best_score - other_score > 0.02:
                break

            equivalent = best.title == other.title and best.authors == other.authors
            if equivalent:
                continue

            logger.debug(
                "%s: ambiguous match: best=%s (%.3f), alternative=%s (%.3f)",
                target.book,
                best.book,
                best_score,
                other.book,
                other_score,
            )
            break

    def _assign_matches(
        self,
        scored_pairs: list[tuple[float, _BookFeatures, _BookFeatures]],
    ) -> set[tuple[Book, Book, float]]:
        """Assign strongest pairs without matching either book twice."""
        matches: set[tuple[Book, Book, float]] = set()
        assigned_candidates: set[int] = set()
        assigned_targets: set[int] = set()

        for score, candidate, target in sorted(
            scored_pairs,
            key=lambda item: item[0],
            reverse=True,
        ):
            candidate_id = id(candidate.book)
            target_id = id(target.book)

            if candidate_id in assigned_candidates or target_id in assigned_targets:
                continue

            matches.add((candidate.book, target.book, score))
            assigned_candidates.add(candidate_id)
            assigned_targets.add(target_id)

            logger.debug(
                "%s: matched Calibre book %s (score %.3f)",
                target.book,
                candidate.book,
                score,
            )

        return matches

    def match_books(
        self,
        calibre_books: Iterable[Book],
        hardcover_books: Iterable[Book],
    ) -> set[tuple[Book, Book, float]]:
        """Match books one-to-one using the strongest qualifying pairs."""
        candidates = [self._prepare(book) for book in calibre_books]
        targets = [self._prepare(book) for book in hardcover_books]
        scored_pairs: list[tuple[float, _BookFeatures, _BookFeatures]] = []

        for target in targets:
            scored = self._score_candidates(target, candidates)

            if not scored:
                logger.debug(
                    "%s: no candidates available",
                    target.book,
                )
                continue

            qualifying = [
                (candidate, score)
                for candidate, score in scored
                if self._is_match(target, candidate, score, self.threshold)
            ]

            if not qualifying:
                best, score = scored[0]
                logger.debug(
                    "%s: no Calibre match; best candidate: %s (score %.3f)",
                    target.book,
                    best.book,
                    score,
                )
                continue

            self._log_ambiguity(target, scored)

            scored_pairs.extend(
                (candidate_score, candidate, target) for candidate, candidate_score in qualifying
            )

        return self._assign_matches(scored_pairs)
