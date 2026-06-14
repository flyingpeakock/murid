import logging
import time

from . import Book

logger = logging.getLogger("HardcoverHarvester")


class Qbittorrent:
    def __init__(self, client, calibre, category, dry_run, poll_interval=2, timeout=3600):
        self.client = client
        self.calibre = calibre
        self.category = category
        self.poll_interval = poll_interval
        self.dry_run = dry_run
        self.timeout = timeout

    def handle_torrents(self, torrent_files: list[tuple[bytes, "Book"]]):
        if not torrent_files:
            return []

        if self.dry_run:
            logger.info("Dry run enabled, not adding torrents to qBittorrent")
            return []

        pending = {}  # torrent_id -> (book, start_time)

        for torrent_file, book in torrent_files:
            torrent_id = self._add_torrent(torrent_file, book)
            if torrent_id:
                pending[torrent_id] = (book, time.time())

        if not pending:
            logger.warning("No torrents were successfully added")
            return []

        logger.info("Tracking %d torrents for completion", len(pending))

        while pending:
            now = time.time()
            completed = []
            timed_out = []

            for torrent_id, (book, start_time) in pending.items():
                try:
                    path = self._get_completed_path(torrent_id)

                    if path:
                        self._send_to_calibre(book, path)
                        completed.append(torrent_id)
                        continue

                    if now - start_time > self.timeout:
                        logger.warning(
                            "Torrent timed out: %s (%s)",
                            book.title,
                            torrent_id,
                        )
                        timed_out.append(torrent_id)

                except Exception:
                    logger.error("Error checking torrent %s", torrent_id)

            for tid in completed + timed_out:
                pending.pop(tid, None)

            if pending:
                logger.debug(
                    "%d torrents still active (%d timed out)",
                    len(pending),
                    len(timed_out),
                )
                time.sleep(self.poll_interval)

    def _send_to_calibre(self, book, path):
        try:
            self.calibre.add_book(book, path)
            logger.info("Added %s to calibre", book.title)
        except Exception:
            logger.error("Failed adding %s to calibre", book.title)

    def _add_torrent(self, torrent_file: tuple[bytes, "Book"], book: "Book") -> str | None:
        try:
            tinfo = self.client.torrents_add(
                torrent_files=torrent_file,
                category=self.category,
            )

            logger.info("Added %s to qBittorrent", book.title)
            logger.debug("Response: %s", tinfo)

            return tinfo.added_torrent_ids[0]

        except Exception as e:
            logger.error("Failed adding %s: %s", book.title, e)
            return None

    def _get_completed_path(self, torrent_id: str) -> str | None:
        try:
            torrent = self.client.torrents_info(torrent_hashes=torrent_id)[0]
        except Exception:
            logger.error("Torrent %s not found", torrent_id)
            return None

        if not torrent:
            return None

        if not torrent.completed:
            return None

        return torrent.content_path
