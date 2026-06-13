import logging

import qbittorrentapi
from rich.pretty import pretty_repr

from . import Book

logger = logging.getLogger("HardcoverHarvester")


class QbittorrentError(Exception):
    pass


class Qbittorrent:
    def __init__(self, conn_info: dict) -> None:
        self.conn_info = conn_info
        self.conn_info["VERIFY_WEBUI_CERTIFICATE"] = conn_info.pop("verify_cert", True)
        self.category = conn_info.pop("category", "hardcoverharvester")
        self.client = qbittorrentapi.Client(**conn_info)

        try:
            self.client.auth_log_in()
        except qbittorrentapi.LoginFailed as e:
            logging.error(f"Failed to log in to qBittorrent: {e}")
            raise QbittorrentError(f"Failed to log in to qBittorrent: {e}") from e
        self.client.auth_log_out()
        logger.info(f"Connected to qBittorrent version: {self.client.app.version}")
        logger.debug(f"qBittorrent Web API version: {self.client.app.web_api_version}")
        logger.debug(
            "qBittorrent build info:%s",
            pretty_repr([{k: v} for k, v in self.client.app.build_info.items()]),
        )

    def add_torrents(self, torrent_files: list[tuple[bytes, Book]]) -> list[tuple[Book, int]]:
        ids = []
        for torrent_file, book in torrent_files:
            try:
                tInfo = self.client.torrents_add(
                    torrent_files=torrent_file,
                    category=self.category,
                    is_paused=True,  # Only for testing, should be False in production
                )
                logger.info(f"Added {book.title} torrent to qBittorrent")
                ids.append((book, tInfo.added_torrent_ids[0]))
            except qbittorrentapi.UnsupportedMediaType415Error as e:
                logger.error(f"File is not a valid torrent: {e}")
            except qbittorrentapi.TorrentFileNotFoundError as e:
                logger.error(f"Torrent file not found: {e}")
            except qbittorrentapi.TorrentFilePermissionError as e:
                logger.error(f"Permission error adding torrent: {e}")
            except qbittorrentapi.Conflict409Error as e:
                logger.error(f"Torrent already exists: {e}")
        logger.debug(f"Got torrent IDs: {pretty_repr(ids)}")
        return ids
