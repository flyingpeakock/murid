"""Initialization file for the murid package."""

from .clients.calibre import Calibre, CalibreError
from .clients.hardcover import Hardcover, HardcoverError
from .clients.myanonamouse import MAMError, MyAnonamouse, MyAnonamouseQuery
from .clients.torrent_clients import Qbittorrent, QbittorrentConfig, TorrentClient
from .config.config import Config, ConfigError
from .domain.book import Book
from .domain.book_matcher import BookMatcher
from .domain.torrent import Torrent, TorrentMetadata
from .domain.torrent_selector import TorrentSelector
from .notifications.apprise import AppriseHandler, init_apprise, send_test_notification
from .services.service_factory import ServiceFactory
from .services.sync_service import SyncService
from .services.torrent_discovery import TorrentDiscoveryService

try:
    from ._version import __version__
except ImportError:
    __version__ = "unknown"

__all__ = [
    "AppriseHandler",
    "Book",
    "BookMatcher",
    "Calibre",
    "CalibreError",
    "Config",
    "ConfigError",
    "Hardcover",
    "HardcoverError",
    "init_apprise",
    "MAMError",
    "MyAnonamouse",
    "MyAnonamouseQuery",
    "send_test_notification",
    "ServiceFactory",
    "SyncService",
    "Torrent",
    "TorrentDiscoveryService",
    "TorrentMetadata",
    "TorrentClient",
    "TorrentSelector",
    "Qbittorrent",
    "QbittorrentConfig",
    "__version__",
]
