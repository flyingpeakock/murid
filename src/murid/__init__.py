"""Initialization file for the murid package."""

from .clients.calibre import Calibre, CalibreError
from .clients.hardcover import Hardcover, HardcoverError
from .clients.myanonamouse import MAMError, MyAnonamouse, MyAnonamouseQuery
from .clients.torrent_clients import Qbittorrent, QbittorrentConfig, TorrentClient
from .config.config import Config, ConfigError
from .domain.book import Book
from .domain.book_matcher import BookMatcher
from .domain.torrent import Torrent, TorrentMetadata

try:
    from ._version import __version__
except ImportError:
    __version__ = "unknown"

__all__ = [
    "Book",
    "BookMatcher",
    "Calibre",
    "CalibreError",
    "Config",
    "ConfigError",
    "Hardcover",
    "HardcoverError",
    "MAMError",
    "MyAnonamouse",
    "MyAnonamouseQuery",
    "Torrent",
    "TorrentMetadata",
    "TorrentClient",
    "Qbittorrent",
    "QbittorrentConfig",
    "__version__",
]
