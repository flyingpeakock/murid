import logging

from rapidfuzz import fuzz

from . import Book, Torrent
from .calibre import Calibre, CalibreError
from .config import Config, ConfigError
from .hardcover import Hardcover
from .myanonamouse import MyAnonamouse
from .qbittorrent import Qbittorrent

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
        self.qbit = init_qbittorrent(self.config.get("qbittorrent"))

        calibre_books = self.fetch_calibre_books()
        hardcover_books = self.fetch_hardcover_books()

        matches = self.match_books(calibre_books, hardcover_books)
        toFetch = self.process_matches(matches, hardcover_books)
        torrentFiles = [(self.mam.download_torrent(torrent), torrent.book) for torrent in toFetch]
        if not self.args.dry_run:
            self.qbit.add_torrents(torrentFiles)
        else:
            logger.info("Dry run enabled, not adding torrents to qBittorrent")

    def fetch_calibre_books(self):
        books = self.calibre.get_books()
        logger.info(f"Fetched {len(books)} books from Calibre database")
        return books

    def fetch_hardcover_books(self):
        books = [book for client in self.hardcover_clients for book in client.get_books()]
        logger.info(f"Fetched {len(books)} books from Hardcover API")
        return books

    def match_books(self, calibre_books, hardcover_books):
        matches = self.matcher.match_books(calibre_books, hardcover_books)
        logger.info(f"{len(matches)} books already in Calibre")
        if matches:
            logger.debug(
                "Hardcover books already in calibre db:\n%s",
                "\n".join([match.title for match, _, _ in matches]),
            )
        return matches

    def process_matches(self, matches, hardcover_books):
        matched_ids = {h.id for _, h, _ in matches}
        books = [h for h in hardcover_books if h.id not in matched_ids]

        if books:
            count = len(books)
            logger.info(f"{count} book{'' if count == 1 else 's'} missing from Calibre")

        found = [
            (book, self.mam.search_ebook(book.title, book.authors[0] if book.authors else None))
            for book in books
        ]
        if len(found) == 0:
            logger.warning("No torrents found for wanted books")
        else:
            for tor in found:
                (book, tor_list) = tor
                logger.debug(
                    f"Torrents found for {book.title}:\n%s",
                    [torrent.download_url for torrent in tor_list],
                )

        torrents_to_download = [
            x
            for book, tor_list in found
            for x in [self.get_best_torrent_for_book(book, tor_list)]
            if x and (x.language in self.config.get("lang_codes") or x.language is None)
        ]
        return torrents_to_download

    def get_best_torrent_for_book(self, book: Book, torrents: list[Torrent]) -> Torrent | None:
        torrent_books = [t.book for t in torrents]
        best_match, score = self.matcher.best_match(book, torrent_books)
        if best_match and score >= self.matcher.threshold:
            ret = next(t for t in torrents if t.book == best_match)
            logger.debug(
                f"Best torrent for {book.title} is {ret.download_url} with similarity {score:.2f}"
            )
            return ret
        else:
            logger.info(f"No good torrent match for {book.title}. Best similarity: {score:.2f}")
            return None


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
        if set(filter(None, a.isbn)) & set(filter(None, b.isbn)):
            return 1.0

        t = self.title_similarity(a.title, b.title)
        au = self.author_similarity(a.authors, b.authors)

        return 0.7 * t + 0.3 * au

    def is_match(self, a: Book, b: Book) -> bool:
        return self.similarity(a, b) >= self.threshold

    def best_match(self, book: Book, candidates: list[Book]) -> tuple[Book | None, float]:
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

        matches = []

        for book_b in books_b:
            match, score = self.best_match(book_b, books_a)
            if match and score >= self.threshold:
                matches.append((match, book_b, score))
            else:
                logger.debug(
                    f"No match for {book_b.title} in calibre db. Best similarity: {score:.2f}"
                )

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


def init_qbittorrent(qbittorrent_config: dict):
    return Qbittorrent(qbittorrent_config)
