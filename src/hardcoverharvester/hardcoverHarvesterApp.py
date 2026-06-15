import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import qbittorrentapi
from croniter import croniter

from . import Book, Torrent
from .bookMatcher import BookMatcher
from .calibre import Calibre, CalibreError
from .config import Config, ConfigError
from .hardcover import Hardcover
from .myanonamouse import MyAnonamouse
from .qbittorrent import Qbittorrent

logger = logging.getLogger("HardcoverHarvester")


class HardcoverHarvesterApp:
    def __init__(self, args):
        self.args = args
        self.config = load_config(self.args.config_file)
        self.calibre = init_calibre(self.config)
        self.hardcover_clients = init_hardcover_clients(self.config)
        self.matcher = BookMatcher(self.config.get("matcher_threshold"))
        self.mam = init_MyAnonamouse_client(self.config.get("mam_id"))
        self.qbit = init_qbittorrent(
            self.config.get("qbittorrent"),
            self.args.dry_run,
        )
        self.schedule = self.config.get("schedule")

    def start_scheduler(self):
        base_time = datetime.now()
        iter = croniter(self.schedule, base_time)

        executor = ThreadPoolExecutor(max_workers=5)

        while True:
            next_run = iter.get_next(datetime)
            logger.info(f"Next run scheduled for {next_run}")
            while datetime.now() < next_run:
                time.sleep(30)
            executor.submit(self.run)

    def run(self):
        logger.info("Starting HardcoverHarvester cycle")
        calibre_books = self.fetch_calibre_books()
        hardcover_books = self.fetch_hardcover_books()

        matches = self.match_books(calibre_books, hardcover_books)
        toFetch = self.process_matches(matches, hardcover_books)
        self.handle_torrents(toFetch)
        logger.info("HardcoverHarvester cycle complete")

    def fetch_calibre_books(self):
        books = self.calibre.get_books()
        logger.info(f"Fetched {len(books)} books from Calibre database")
        return books

    def fetch_hardcover_books(self):
        with ThreadPoolExecutor(max_workers=min(10, len(self.hardcover_clients))) as executor:
            results = executor.map(lambda client: client.get_books(), self.hardcover_clients)
        books = [book for result in results for book in result]
        logger.info(f"Fetched {len(books)} books from Hardcover API")
        return books

    def match_books(self, calibre_books, hardcover_books):
        matches = self.matcher.match_books(calibre_books, hardcover_books)
        return matches

    def process_matches(self, matches, hardcover_books):
        matched_ids = {h.id for _, h, _ in matches}
        books = [h for h in hardcover_books if h.id not in matched_ids]

        if books:
            count = len(books)
            logger.info(f"{count} book{'' if count == 1 else 's'} missing from Calibre")

        lang_codes = set(self.config.get("lang_codes"))

        def search_book(book):
            return (
                book,
                self.mam.search_ebook(
                    book.title,
                    book.authors[0] if book.authors else None,
                ),
            )

        torrent_files = []

        with ThreadPoolExecutor(max_workers=min(20, max(1, len(books)))) as executor:
            search_futures = {executor.submit(search_book, book): book for book in books}

            download_futures = {}

            for future in as_completed(search_futures):
                book = search_futures[future]

                try:
                    _, tor_list = future.result()
                except Exception:
                    logger.exception(f"Failed searching for {book}")
                    continue

                if not tor_list:
                    continue
                logger.debug(
                    "Torrents found for %s:\n%s",
                    book,
                    [torrent.download_url for torrent in tor_list],
                )

                torrent = self.get_best_torrent_for_book(book, tor_list)

                if not torrent:
                    continue

                if torrent.language is not None and torrent.language not in lang_codes:
                    continue

                download_future = executor.submit(
                    self.mam.download_torrent,
                    torrent,
                )

                download_futures[download_future] = torrent.book

            if not download_futures:
                logger.warning("No torrents found for wanted books")
                return []

            for future in as_completed(download_futures):
                book = download_futures[future]

                try:
                    torrent_file = future.result()
                    torrent_files.append((torrent_file, book))
                except Exception:
                    logger.exception(
                        "Failed downloading torrent for %s",
                        book,
                    )

        return torrent_files

    def get_best_torrent_for_book(self, book: Book, torrents: list[Torrent]) -> Torrent | None:
        torrent_books = [t.book for t in torrents]
        best_match, score = self.matcher.best_match(book, torrent_books)
        if best_match and score >= self.matcher.threshold:
            ret = next(t for t in torrents if t.book == best_match)
            logger.debug(
                f"Best torrent for {book} is {ret.download_url} with similarity {score:.2f}"
            )
            return ret
        else:
            logger.info(f"No good torrent match for {book}. Best similarity: {score:.2f}")
            return None

    def handle_torrents(self, torrent_files: list[tuple[bytes, Book]]):
        if not torrent_files:
            logger.info("No torrents to handle")
            return

        logger.info(f"Handling {len(torrent_files)} torrents")

        if self.args.dry_run:
            logger.info("Dry run enabled, not adding torrents to qBittorrent")
            for _, book in torrent_files:
                logger.info(f"Would add {book} to qBittorrent")
            return

        pending = {}  # torrent_id -> book

        for torrent_file, book in torrent_files:
            torrent_id = self.qbit.add_torrent(torrent_file, book)
            if torrent_id:
                pending[torrent_id] = book

        if not pending:
            logger.warning("No torrents were successfully added to qBittorrent")
            return

        logger.info(f"Tracking {len(pending)} torrents for completion")

        while pending:
            completed = []

            for torrent_id, book in pending.items():
                try:
                    path = self.qbit.get_completed_path(torrent_id)
                    if path:
                        try:
                            self.calibre.add_book(book, path)
                        except Exception:
                            self.qbit.add_tag(torrent_id, "import_failed")
                        completed.append(torrent_id)
                        continue
                except Exception:
                    logger.error(f"Error checking torrent for {book}")

            for tid in completed:
                pending.pop(tid, None)

            if pending:
                logger.debug(f"{len(pending)} torrents still active")
                time.sleep(self.qbit.poll_interval)


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
        return Calibre(
            config.get("calibre_db_path"),
            config.get("calibredb_executable", "calibredb"),
        )
    except CalibreError as e:
        logger.error(f"Error initializing Calibre: {e}")
        raise SystemExit(1) from e


def init_hardcover_clients(config):
    return [Hardcover(user["api_key"], user["id"]) for user in config.get("users")]


def init_MyAnonamouse_client(mam_id: str):
    return MyAnonamouse(mam_id)


def init_qbittorrent(qbittorrent_config: dict, dryRun: bool = False):
    mapping = qbittorrent_config.pop("mapping", None)
    conn_info = qbittorrent_config
    conn_info["VERIFY_WEBUI_CERTIFICATE"] = conn_info.pop("verify_cert", True)
    category = conn_info.pop("category", "hardcoverharvester")
    client = qbittorrentapi.Client(**conn_info)
    return Qbittorrent(client, category, dryRun, mapping=mapping)
