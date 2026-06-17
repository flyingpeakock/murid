"""qBittorrent client implementation for Murid."""

import logging
import time
from dataclasses import dataclass

import qbittorrentapi

from .. import Book
from .torrent_client import TorrentClient

logger = logging.getLogger("murid")


@dataclass
class QbittorrentConfig:
    """Configuration for the qBittorrent client."""

    client: qbittorrentapi.Client
    category: str
    dry_run: bool
    mapping: dict[str, str] | None = None


class Qbittorrent(TorrentClient):
    """Torrent client implementation for qBittorrent."""

    def __init__(self, config: QbittorrentConfig, poll_interval=2):
        """Initialize the qBittorrent client with the provided parameters."""
        self.client = config.client
        self.category = config.category
        self.poll_interval = poll_interval
        self.dry_run = config.dry_run
        self.mapping = config.mapping
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
        logger.debug("qBittorrent: %s", self.client.app.version)
        logger.debug("qBittorrent api: %s", self.client.app.web_api_version)

    def add_torrent(self, torrent_file: bytes, book: Book) -> str | None:
        """Add a torrent to qBittorrent and return its ID."""
        try:
            tinfo = self.client.torrents_add(
                torrent_files=torrent_file,
                category=self.category,
            )

            logger.info("Added %s to qBittorrent", book)
            logger.debug("Response: %s", tinfo)

            return tinfo.added_torrent_ids[0]

        except qbittorrentapi.UnsupportedMediaType415Error:
            logger.error("Failed to add %s to qBittorrent: Unsupported media type", book)
        except qbittorrentapi.TorrentFileNotFoundError:
            logger.error("Failed to add %s to qBittorrent: Torrent file not found", book)
        except qbittorrentapi.TorrentFilePermissionError:
            logger.error("Failed to add %s to qBittorrent: Torrent file permission error", book)
        except qbittorrentapi.Conflict409Error:
            logger.error("Failed to add %s to qBittorrent: Torrent already downloaded", book)
        return None

    def get_completed_path(self, torrent_id: str) -> str | None:
        """Get the completed path of a torrent by its ID, or None if it's not yet completed."""
        torrent = self.client.torrents_info(torrent_hashes=torrent_id)[0]

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
