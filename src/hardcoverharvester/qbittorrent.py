import logging

import qbittorrentapi

from . import Book

logger = logging.getLogger("HardcoverHarvester")


class Qbittorrent:
    def __init__(self, client, category, dry_run, poll_interval=2):
        self.client = client
        self.category = category
        self.poll_interval = poll_interval
        self.dry_run = dry_run
        self._validate()

    def _validate(self):
        try:
            self.client.auth_log_in()
            logger.debug("Successfully authenticated with qBittorrent")
            self.client.auth_log_out()
        except qbittorrentapi.LoginFailed as e:
            logger.error("Failed to authenticate with qBittorrent: %s", e)
            raise SystemExit(1) from e
        logger.debug(f"qBittorrent: {self.client.app.version}")
        logger.debug(f"qBittorrent api: {self.client.app.web_api_version}")

    def add_torrent(self, torrent_file: bytes, book: "Book") -> str | None:
        try:
            tinfo = self.client.torrents_add(
                torrent_files=torrent_file,
                category=self.category,
            )

            logger.info(f"Added {book} to qBittorrent")
            logger.debug("Response: %s", tinfo)

            return tinfo.added_torrent_ids[0]

        except Exception as e:
            logger.error(f"Failed adding {book} to qBittorrent: {e}")
            return None

    def get_completed_path(self, torrent_id: str) -> str | None:
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

    def add_tag(self, torrent_id: str, tag: str):
        self.client.torrents_add_tags(tags=tag, torrent_hashes=torrent_id)
