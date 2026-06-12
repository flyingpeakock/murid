from dataclasses import dataclass

from rapidfuzz import fuzz


@dataclass
class Book:
    title: str
    authors: list[str]
    id: int
    isbn: str | None


class BookMatcher:
    def __init__(self, threshold: float = 0.92):
        self.threshold = threshold

    @staticmethod
    def normalize(text: str) -> str:
        return "".join(c.lower() for c in text if c.isalnum() or c.isspace()).strip()

    def title_similarity(self, a: str, b: str) -> float:
        return (
            fuzz.token_set_ratio(
                self.normalize(a),
                self.normalize(b),
            )
            / 100
        )

    def author_similarity(
        self,
        a: list[str],
        b: list[str],
    ) -> float:
        set_a = {self.normalize(x) for x in a}
        set_b = {self.normalize(x) for x in b}

        if not set_a or not set_b:
            return 0.0

        return len(set_a & set_b) / len(set_a | set_b)

    def similarity(self, a: Book, b: Book) -> float:
        # Strong signal: ISBN match
        if a.isbn and b.isbn and a.isbn == b.isbn:
            return 1.0

        t = self.title_similarity(a.title, b.title)
        au = self.author_similarity(a.authors, b.authors)

        return 0.7 * t + 0.3 * au

    def is_match(self, a: Book, b: Book) -> bool:
        return self.similarity(a, b) >= self.threshold

    def match_books(
        self, books_a: list[Book], books_b: list[Book]
    ) -> list[tuple[Book, Book, float]]:
        matches = []
        for book_a in books_a:
            for book_b in books_b:
                sim = self.similarity(book_a, book_b)
                if sim >= self.threshold:
                    matches.append((book_a, book_b, sim))
        return matches
