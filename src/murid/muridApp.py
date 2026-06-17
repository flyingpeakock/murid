import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import qbittorrentapi
from croniter import croniter

from . import Book, Torrent
from .apprise import init_apprise as apprise
from .bookMatcher import BookMatcher
from .calibre import Calibre, CalibreError
from .config import Config, ConfigError
from .hardcover import Hardcover
from .myanonamouse import MyAnonamouse
from .torrentClients.qbittorrent import Qbittorrent

logger = logging.getLogger("murid")


class MuridApp:
    def __init__(self, args):
        self.args = args
        self.config = load_config(self.args.config_file)
        self.notify = init_apprise(self.config)

        self.calibre = None
        self.hardcover_clients = None
        self.matcher = None
        self.mam = None
        self.torrent_client = None

    def start_scheduler(self):
        base_time = datetime.now()
        iter = croniter(self.config.get("schedule"), base_time)

        executor = ThreadPoolExecutor(max_workers=5)

        while True:
            next_run = iter.get_next(datetime)
            logger.info(f"Next run scheduled for {next_run}")
            while datetime.now() < next_run:
                sleep_time = ((next_run - datetime.now()).total_seconds()) / 2 or 1
                time.sleep(sleep_time)
            executor.submit(self.run)

    def run(self):
        self.calibre = init_calibre(self.config)
        self.hardcover_clients = init_hardcover_clients(self.config)
        self.matcher = BookMatcher(self.config.get("matcher_threshold"))
        self.mam = init_MyAnonamouse_client(self.config.get("mam_id"))
        self.torrent_client = init_qbittorrent(
            self.config.get("qbittorrent"),
            self.args.dry_run,
        )

        logger.info("Starting murid cycle")
        calibre_books = self.fetch_calibre_books()
        hardcover_books = self.fetch_hardcover_books()

        matches = self.match_books(calibre_books, hardcover_books)
        toFetch = self.process_matches(matches, hardcover_books)
        self.handle_torrents(toFetch)
        logger.info("murid cycle complete")

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

        def search_book(book):
            mam_books = self.mam.search_ebook(
                book.title,
                book.authors[0] if book.authors else None,
            )
            for torrent in mam_books:
                # Prefer series info from Hardcover if available,
                # as MyAnonamouse data can be inconsistent
                torrent.book.series = book.series
                torrent.book.series_number = book.series_number
            return book, mam_books

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
                    "Potential torrents found for %s:\n%s",
                    book,
                    [str(torrent) for torrent in tor_list],
                )

                torrent = self.get_best_torrent_for_book(book, tor_list)

                if not torrent:
                    continue

                download_future = executor.submit(
                    self.mam.download_torrent,
                    torrent,
                )

                download_futures[download_future] = torrent.book

            if not download_futures:
                return []

            for future in as_completed(download_futures):
                book = download_futures[future]

                try:
                    torrent_file = future.result()
                    if torrent_file:
                        torrent_files.append((torrent_file, book))
                except Exception:
                    logger.exception(
                        "Failed downloading torrent for %s",
                        book,
                    )

        return torrent_files

    def get_best_torrent_for_book(self, book: Book, torrents: list[Torrent]) -> Torrent | None:
        wanted_filetypes = {
            "epub",
            "mobi",
            "azw3",
        }
        torrent_books = [
            t.book
            for t in torrents
            if (t.language is None or t.language in self.config.get("lang_codes", []))
            and wanted_filetypes.intersection(set(t.file_types or []))
        ]

        if not torrent_books:
            logger.debug(f"No torrents for {book} passed language and filetype filters")
            logger.debug(torrents)
            return None

        best_match, score = self.matcher.best_match(book, torrent_books)
        if best_match and score >= self.matcher.threshold:
            ret = next(t for t in torrents if t.book == best_match)
            logger.debug(f"Best torrent for {book} is {ret} with similarity {score:.2f}")
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
            logger.info("Dry run enabled, not adding torrents to torrent client")
            for _, book in torrent_files:
                logger.info(f"Would add {book} to torrent client")
            return

        pending = {}  # torrent_id -> book

        for torrent_file, book in torrent_files:
            torrent_id = self.torrent_client.add_torrent(torrent_file, book)
            if torrent_id:
                pending[torrent_id] = book

        if not pending:
            logger.warning("No torrents were successfully added to torrent client")
            return

        logger.info(f"Tracking {len(pending)} torrents for completion")

        while pending:
            completed = []

            for torrent_id, book in pending.items():
                try:
                    path = self.torrent_client.get_completed_path(torrent_id)
                    if path:
                        try:
                            self.calibre.add_book(book, path)
                            if self.calibre.contains_book(book, self.matcher):
                                message = f"Successfully imported {book} into Calibre"
                                logger.info(message)
                                self.notify(title="Book Imported", body=message)
                            else:
                                logger.error(
                                    f"Failed to verify import of {book} into Calibre."
                                    "\nManual intervention is likely required.",
                                )
                                self.torrent_client.add_tag(torrent_id, "import_failed")
                        except Exception:
                            logger.error(f"Error importing {book} into Calibre")
                            self.torrent_client.add_tag(torrent_id, "import_failed")
                        completed.append(torrent_id)
                        continue
                except Exception:
                    logger.error(f"Error checking torrent for {book}")

            for tid in completed:
                pending.pop(tid, None)

            if pending:
                logger.debug(f"{len(pending)} torrents still active")
                time.sleep(self.torrent_client.poll_interval)

    def test_notification(self):
        self.notify(
            title="Test notification from murid",
            body="Hello from murid!",
        )


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
    category = conn_info.pop("category", "murid")
    client = qbittorrentapi.Client(**conn_info)
    return Qbittorrent(client, category, dryRun, mapping=mapping)


def init_apprise(config):
    if not config.get("apprise", None):
        return lambda *args, **kwargs: None
    try:
        return apprise(logger, config.get("apprise"))
    except Exception as e:
        logger.error(f"Error initializing Apprise: {e}")
        raise SystemExit(1) from e
