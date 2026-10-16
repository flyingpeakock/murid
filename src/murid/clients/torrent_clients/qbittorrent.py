"""qBittorrent client implementation for Murid."""

import logging
import time
from dataclasses import dataclass
from uuid import uuid4

import qbittorrentapi

from ...domain.book import Book
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

    def __init__(self, config: QbittorrentConfig, poll_interval=2) -> None:
        """Initialize the qBittorrent client with the provided parameters."""
        self.client = config.client
        self.category = config.category
        self.poll_interval = poll_interval
        self.dry_run = config.dry_run
        self.mapping = config.mapping
        self._validate()

    def _validate(self) -> None:
        """Validate the connection to qBittorrent by attempting to log in."""
        try:
            self.client.auth_log_in()
            logger.debug("Successfully authenticated with qBittorrent")
            self.client.auth_log_out()
        except qbittorrentapi.LoginFailed as e:
            logger.error("Failed to authenticate with qBittorrent: %r", e)
            raise SystemExit(1) from e
        logger.debug("qBittorrent: %s", self.client.app.version)
        logger.debug("qBittorrent api: %s", self.client.app.web_api_version)

    def add_torrent(self, torrent_file: bytes, book: Book) -> str | None:
        """Add a torrent to qBittorrent and return its ID."""
        tracking_tag = f"murid_add_{uuid4().hex}"
        try:
            tinfo = self.client.torrents_add(
                torrent_files=torrent_file,
                category=self.category,
                tags=tracking_tag,
            )

            if isinstance(tinfo, str):
                if tinfo.strip() != "Ok.":
                    logger.error("Failed to add %s to qBittorrent: %s", book, tinfo)
                    return None
                # Older APIs acknowledge the add without returning its hash. A unique
                # tag identifies this request even when other downloads arrive concurrently.
                torrent_ids = []
                for _ in range(10):
                    torrents = self.client.torrents_info(category=self.category, tag=tracking_tag)
                    torrent_ids = [torrent.hash for torrent in torrents]
                    if torrent_ids:
                        break
                    time.sleep(self.poll_interval)
            else:
                torrent_ids = tinfo.added_torrent_ids

            if len(torrent_ids) != 1:
                logger.error("Could not identify the added torrent for %s", book)
                return None
            torrent_id = torrent_ids[0]
            self.remove_tag(torrent_id, tracking_tag)
            logger.info("Added %s to qBittorrent", book)
            return torrent_id

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
        torrents = self.client.torrents_info(torrent_hashes=torrent_id)
        if not torrents:
            logger.warning("Torrent %s is no longer available in qBittorrent", torrent_id)
            return None
        if torrents[0].progress < 1:
            return None

        time.sleep(0.3)  # Give qBittorrent a moment to update the content path
        torrents = self.client.torrents_info(torrent_hashes=torrent_id)
        if not torrents or torrents[0].progress < 1:
            return None
        path = torrents[0].content_path

        if (
            self.mapping
            and self.mapping["qbit_path"]
            and self.mapping["murid_path"]
            and path.startswith(self.mapping["qbit_path"])
        ):
            path = path.replace(self.mapping["qbit_path"], self.mapping["murid_path"], 1)

        return path

    def add_tag(self, torrent_id: str, tag: str) -> None:
        """Add a tag to a torrent by its ID."""
        self.client.torrents_add_tags(tags=tag, torrent_hashes=torrent_id)

    def remove_tag(self, torrent_id: str, tag: str) -> None:
        """Remove a tag from a torrent by its ID."""
        self.client.torrents_remove_tags(tags=tag, torrent_hashes=torrent_id)

    def get_torrents_with_tag(self, tag: str) -> list:
        """Get a list of torrent IDs that have the specified tag."""
        torrents = [
            t
            for t in self.client.torrents_info(category=self.category, tag=tag)
            if tag in {value.strip() for value in (t.tags or "").split(",")}
        ]
        return torrents

    def get_torrents(self) -> list:
        """Return torrents in Murid's configured qBittorrent category."""
        return self.client.torrents_info(category=self.category)
