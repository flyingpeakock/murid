"""Factory for creating service instances based on configuration."""

import logging
from concurrent.futures import ThreadPoolExecutor

import qbittorrentapi
from croniter import croniter

from ..clients.calibre import Calibre, CalibreError
from ..clients.hardcover import Hardcover
from ..clients.myanonamouse import MyAnonamouse
from ..clients.torrent_clients.qbittorrent import Qbittorrent, QbittorrentConfig
from ..config.config import Config, ConfigError
from ..domain.book_matcher import BookMatcher
from ..domain.torrent_selector import TorrentSelector
from ..notifications.apprise import init_apprise as apprise
from .sync_service import SyncService
from .torrent_discovery import TorrentDiscoveryService
from .torrent_import import TorrentImportConfig, TorrentImportService

logger = logging.getLogger("murid")


class ServiceFactory:
    """Factory for creating service instances."""

    def __init__(self, args):
        """Initialize the service factory with command-line arguments."""
        self.args = args

    def _load_config(self) -> dict:
        """Load configuration from a file."""
        try:
            with open(self.args.config_file, "r", encoding="utf-8") as f:
                return Config(f)
        except ConfigError as e:
            logger.error("Error loading config: %s", e)
            raise SystemExit(1) from e
        except FileNotFoundError as e:
            logger.error("Config file not found: %s", self.args.config_path)
            raise SystemExit(1) from e
        except Exception as e:
            logger.error("Unexpected error loading config: %s", e)
            raise SystemExit(1) from e

    def matcher(self) -> BookMatcher:
        """Create a BookMatcher instance using the matcher threshold from the configuration."""
        return BookMatcher(self._load_config()["matcher_threshold"])

    def calibre(self):
        """Create a Calibre instance using the configuration file."""
        config = self._load_config()
        try:
            return Calibre(
                config["calibre_db_path"],
                config["calibredb_executable"],
            )
        except CalibreError as e:
            logger.error("Error initializing Calibre: %s", e)
            raise SystemExit(1) from e

    def hardcover(self) -> set[Hardcover]:
        """Create a list of Hardcover instances for each user specified in the configuration."""
        keys = self._load_config()["hardcover_api_keys"]
        with ThreadPoolExecutor(max_workers=min(10, len(keys))) as executor:
            hardcover_clients = set(executor.map(Hardcover, keys))
        return hardcover_clients

    def myanonamouse(self):
        """Create a MyAnonamouse instance using the MAM ID from the configuration."""
        return MyAnonamouse(self._load_config()["mam_id"])

    def qbittorrent(self):
        """Create a Qbittorrent instance using the configuration for qBittorrent."""
        config = self._load_config()
        qbittorrent_config = config["qbittorrent"]
        mapping = qbittorrent_config.pop("mapping", None)
        category = qbittorrent_config.pop("category", "murid")
        qbittorrent_config["VERIFY_WEBUI_CERTIFICATE"] = qbittorrent_config.pop("verify_cert", True)
        client = qbittorrentapi.Client(**qbittorrent_config)
        config = QbittorrentConfig(
            client=client,
            category=category,
            dry_run=self.args.dry_run,
            mapping=mapping,
        )
        return Qbittorrent(config)

    def notifier(self):
        """Create an Apprise instance for notifications or a no-op function."""
        config = self._load_config()
        if not config.get("apprise", None):
            return lambda *args, **kwargs: None
        try:
            return apprise(logger, config["apprise"])
        except Exception as e:
            logger.error("Error initializing Apprise: %s", e)
            raise SystemExit(1) from e

    def torrent_discovery(self):
        """Create a TorrentDiscoveryService instance using the MyAnonamouse client."""
        return TorrentDiscoveryService(
            self.myanonamouse(),
            self._load_config()["lang_codes"],
            self.torrent_selector(),
        )

    def torrent_import(self):
        """Create a TorrentImportService instance"""
        return TorrentImportService(
            TorrentImportConfig(
                torrent_client=self.qbittorrent(),
                calibre=self.calibre(),
                matcher=self.matcher(),
                notify=self.notifier(),
                dry_run=self.args.dry_run,
            )
        )

    def cron_iter(self, base_time):
        """Create a croniter instance for scheduling based on the configuration."""
        return croniter(self._load_config()["schedule"], base_time)

    def sync_service(self):
        """Create a SyncService instance."""
        return SyncService(self)

    def torrent_selector(self):
        """Create a TorrentSelector instance."""
        config = self._load_config()
        return TorrentSelector(
            lang_codes=set(config["lang_codes"]), wanted_filetypes=set(config["filetypes"])
        )
