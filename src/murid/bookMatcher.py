import logging
import re

from rapidfuzz import fuzz

from . import Book

logger = logging.getLogger("murid")


class BookMatcher:
    """Class for matching books based on title and author similarity."""

    def __init__(self, threshold: float = 0.92):
        """Initialize the BookMatcher with a similarity threshold."""
        self.threshold = threshold

    @staticmethod
    def normalize(text: str) -> str:
        """Normalize text by lowercasing and removing non-alphanumeric characters."""
        return "".join(c.lower() for c in text if c.isalnum() or c.isspace()).strip()

    @staticmethod
    def canonicalize_title(title: str) -> str:
        """Canonicalize a book title by applying various transformations to improve matching."""
        title = title.lower()

        # Remove leading articles
        for prefix in ("the ", "a ", "an "):
            if title.startswith(prefix):
                title = title[len(prefix) :]
                break

        # Prefer bracketed title if present
        match = re.search(r"\[([^\]]+)\]", title)
        if match:
            title = match.group(1)

        # Remove parenthetical metadata
        title = re.sub(r"\([^)]*\)", "", title)

        # Remove subtitles
        if ":" in title:
            title = title.split(":", 1)[0]

        # Get title before comma
        if "," in title:
            title = title.split(",", 1)[0]

        return BookMatcher.normalize(title)

    def title_similarity(self, a: str, b: str) -> float:
        """Calculate the similarity between two book titles using fuzzy matching."""
        return (
            fuzz.ratio(
                self.canonicalize_title(a),
                self.canonicalize_title(b),
            )
            / 100
        )

    def author_similarity(
        self,
        a: list[str],
        b: list[str],
    ) -> float:
        """Calculate the similarity between two lists of authors using Jaccard similarity."""
        set_a = {self.normalize(x) for x in a}
        set_b = {self.normalize(x) for x in b}

        if not set_a or not set_b:
            return 0.0

        return len(set_a & set_b) / len(set_a | set_b)

    def similarity(self, a: Book, b: Book) -> float:
        """Calculate the overall similarity between two books based on total similarity."""
        # Strong signal: ISBN match
        if set(filter(None, a.isbn)) & set(filter(None, b.isbn)):
            return 1.0

        t = self.title_similarity(a.title, b.title)
        au = self.author_similarity(a.authors, b.authors)

        return 0.7 * t + 0.3 * au

    def is_match(self, a: Book, b: Book) -> bool:
        """Determine if two books are a match based on their similarity score and the threshold."""
        return self.similarity(a, b) >= self.threshold

    def best_match(self, book: Book, candidates: list[Book]) -> tuple[Book | None, float]:
        """Find the best matching book from a list of candidates."""
        best_match = None
        best_score = 0.0

        for candidate in candidates:
            sim = self.similarity(book, candidate)
            if sim > best_score:
                best_score = sim
                best_match = candidate

        return best_match, best_score

    def match_books(
        self,
        books_a: list[Book],
        books_b: list[Book],
    ) -> list[tuple[Book, Book, float]]:
        """Match books from two lists and return a list of matched pairs and their similarity."""

        matches = []

        for book_b in books_b:
            match, score = self.best_match(book_b, books_a)
            if match and score >= self.threshold:
                matches.append((match, book_b, score))
            else:
                logger.debug(f"No match for {book_b} in calibre db. Best similarity: {score:.2f}")

        return matches
