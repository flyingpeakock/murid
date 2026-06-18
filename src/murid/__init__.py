"""Initialization file for the murid package."""

from .book import Book
from .book_matcher import BookMatcher
from .calibre import Calibre, CalibreError
from .config import Config, ConfigError
from .hardcover import Hardcover, HardcoverError
from .murid_app import MuridApp
from .myanonamouse import MAMError, MyAnonamouse, MyAnonamouseQuery
from .torrent import Torrent, TorrentMetadata
from .torrent_clients import Qbittorrent, QbittorrentConfig, TorrentClient

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
    "MuridApp",
    "MyAnonamouse",
    "MyAnonamouseQuery",
    "Torrent",
    "TorrentMetadata",
    "TorrentClient",
    "Qbittorrent",
    "QbittorrentConfig",
    "__version__",
]
