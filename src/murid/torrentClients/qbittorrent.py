import logging
import time

import qbittorrentapi

from .. import Book
from .torrentClients import TorrentClient

logger = logging.getLogger("murid")


class Qbittorrent(TorrentClient):
    """Torrent client implementation for qBittorrent."""

    def __init__(self, client, category, dry_run, poll_interval=2, mapping=None):
        """Initialize the qBittorrent client with the provided parameters."""
        self.client = client
        self.category = category
        self.poll_interval = poll_interval
        self.dry_run = dry_run
        self.mapping = mapping
        self._validate()

    def _validate(self):
        """Validate the connection to qBittorrent by attempting to log in."""
        try:
            self.client.auth_log_in()
            logger.debug("Successfully authenticated with qBittorrent")
            self.client.auth_log_out()
        except qbittorrentapi.LoginFailed as e:
            logger.error("Failed to authenticate with qBittorrent: %s", e)
            raise SystemExit(1) from e
        logger.debug(f"qBittorrent: {self.client.app.version}")
        logger.debug(f"qBittorrent api: {self.client.app.web_api_version}")

    def add_torrent(self, torrent_file: bytes, book: Book) -> str | None:
        """Add a torrent to qBittorrent and return its ID."""
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
        """Get the completed path of a torrent by its ID, or None if it's not yet completed."""
        try:
            torrent = self.client.torrents_info(torrent_hashes=torrent_id)[0]
        except Exception:
            logger.error("Torrent %s not found", torrent_id)
            return None

        if not torrent:
            return None

        if not torrent.completed:
            return None

        time.sleep(0.3)  # Give qBittorrent a moment to update the content path
        torrent = self.client.torrents_info(torrent_hashes=torrent_id)[0]
        path = torrent.content_path

        if (
            self.mapping
            and self.mapping["qbit_path"]
            and self.mapping["murid_path"]
            and path.startswith(self.mapping["qbit_path"])
        ):
            path = path.replace(self.mapping["qbit_path"], self.mapping["murid_path"], 1)

        return path

    def add_tag(self, torrent_id: str, tag: str):
        """Add a tag to a torrent by its ID."""
        self.client.torrents_add_tags(tags=tag, torrent_hashes=torrent_id)
