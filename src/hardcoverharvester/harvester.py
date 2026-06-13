import logging

from rapidfuzz import fuzz
from rich.pretty import pretty_repr

from . import Book, Torrent
from .calibre import Calibre, CalibreError
from .config import Config, ConfigError
from .hardcover import Hardcover
from .myanonamouse import MyAnonamouse

logger = logging.getLogger("HardcoverHarvester")


class HardcoverHarvesterApp:
    def __init__(self, args):
        self.args = args
        self.config = None
        self.calibre = None
        self.hardcover_clients = []
        self.mam = None
        self.matcher = None

    def run(self):
        self.config = load_config(self.args.config_file)
        self.calibre = init_calibre(self.config)
        self.hardcover_clients = init_hardcover_clients(self.config)
        self.matcher = BookMatcher(self.config.get("matcher_threshold"))
        self.mam = init_MyAnonamouse_client(self.config.get("mam_id"))

        calibre_books = self.fetch_calibre_books()
        hardcover_books = self.fetch_hardcover_books()

        matches = self.match_books(calibre_books, hardcover_books)
        toFetch = self.process_matches(matches, hardcover_books)
        torrents = self.search_mam_for_books(toFetch)
        if len(torrents) == 0:
            logger.warning("No torrents found for wanted books")

    def fetch_calibre_books(self):
        books = self.calibre.get_books()
        logger.info(f"Fetched {len(books)} books from Calibre database")
        return books

    def fetch_hardcover_books(self):
        books = [book for client in self.hardcover_clients for book in client.get_books()]
        logger.info(f"Fetched {len(books)} books from Hardcover API")
        logger.debug("Hardcover books:\n%s", pretty_repr(books))
        return books

    def match_books(self, calibre_books, hardcover_books):
        matches = self.matcher.match_books(calibre_books, hardcover_books)
        logger.info(f"{len(matches)} books already in Calibre")
        if matches:
            logger.debug("Matched books:\n%s", pretty_repr(matches))
        return matches

    def process_matches(self, matches, hardcover_books):
        matched_ids = {h.id for _, h, _ in matches}
        to_fetch = [h for h in hardcover_books if h.id not in matched_ids]

        if to_fetch:
            count = len(to_fetch)
            logger.info(f"{count} book{'' if count == 1 else 's'} missing from Calibre")
        return to_fetch

    def search_mam_for_books(self, books) -> list[Torrent]:
        found = [
            self.mam.search_ebook(book.title, book.authors[0] if book.authors else None)
            for book in books
        ]
        logger.debug("Search results for missing books:\n%s", pretty_repr(found))
        return found


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
        self,
        books_a: list[Book],
        books_b: list[Book],
    ) -> list[tuple[Book, Book, float]]:

        matches = []

        for book_b in books_b:
            best_match = None
            best_score = 0.0

            for book_a in books_a:
                sim = self.similarity(book_a, book_b)

                if sim > best_score:
                    best_score = sim
                    best_match = book_a

            if best_match and best_score >= self.threshold:
                matches.append((best_match, book_b, best_score))
            else:
                logger.debug(f"No match for {book_b.title}. Best similarity: {best_score:.2f}")

        return matches


def load_config(path: str):
    try:
        with open(path, "r") as f:
            return Config(f)
    except ConfigError as e:
        logger.error(f"Error loading config: {e}")
        raise SystemExit(1) from e
    except FileNotFoundError as e:
        logger.error(f"Config file not found: {path}")
        raise SystemExit(1) from e
    except Exception as e:
        logger.error(f"Unexpected error loading config: {e}")
        raise SystemExit(1) from e


def init_calibre(config):
    try:
        return Calibre(config.get("calibre_db_path"))
    except CalibreError as e:
        logger.error(f"Error initializing Calibre: {e}")
        raise SystemExit(1) from e


def init_hardcover_clients(config):
    return [Hardcover(user["api_key"], user["id"]) for user in config.get("users")]


def init_MyAnonamouse_client(mam_id: str):
    return MyAnonamouse(mam_id)
