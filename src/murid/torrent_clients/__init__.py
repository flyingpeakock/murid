"""Torrent clients for Murid."""

from .qbittorrent import Qbittorrent, QbittorrentConfig
from .torrent_client import TorrentClient

__all__ = ["TorrentClient", "Qbittorrent", "QbittorrentConfig"]
