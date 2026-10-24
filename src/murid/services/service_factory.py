"""Factory for creating service instances based on configuration."""

import logging
from concurrent.futures import ThreadPoolExecutor

import qbittorrentapi
from croniter import croniter

from ..clients.audiobookshelf import Audiobookshelf
from ..clients.calibre import Calibre, CalibreConfig
from ..clients.hardcover import Hardcover
from ..clients.myanonamouse import MyAnonamouse
from ..clients.torrent_clients.qbittorrent import Qbittorrent, QbittorrentConfig
from ..config import Config, ConfigError, hardcover_list_settings, requested_media_types
from ..domain.book import Book
from ..domain.book_matcher import BookMatcher
from ..domain.book_request import BookRequest, MediaType
from ..domain.torrent_selector import TorrentSelector
from ..libraries.audiobookshelf import AudiobookLibraryConfig, AudiobookshelfLibrary
from ..libraries.calibre import CalibreLibrary
from ..libraries.library import Library
from ..notifications.apprise import AppriseHandler
from ..notifications.apprise import init_apprise as apprise
from .retry_service import RetryRecovery, RetryService
from .sync_service import SyncService
from .torrent_discovery import TorrentDiscoveryService
from .torrent_import import TorrentImportConfig, TorrentImportService

logger = logging.getLogger("murid")


class ServiceFactory:
    """Factory for creating service instances."""

    def __init__(self, args, config=None, *, initialize_notifier=True):
        """Initialize the service factory with command-line arguments."""
        self.args = args
        self._set_config(config or self._load_config())
        self.notify = self._init_apprise() if initialize_notifier else lambda *args, **kwargs: None

    def _set_config(self, config):
        """Reuse normalized Config settings or normalize supplied dictionaries once."""
        self.config = config
        self.hardcover_lists = (
            config.hardcover_lists
            if isinstance(config, Config)
            else hardcover_list_settings(config["hardcover_api_keys"])
        )

    def _init_apprise(self):
        """Initialize the Apprise notifier."""
        if not self.config.get("apprise", None):
            for handler in list(logger.handlers):
                if isinstance(handler, AppriseHandler):
                    logger.removeHandler(handler)
                    handler.close()
            return lambda *args, **kwargs: None
        try:
            return apprise(logger, self.config["apprise"])
        except Exception as e:
            logger.error("Cannot initialize Apprise: %s", e)
            raise SystemExit(1) from e

    def reload(self):
        """Reload the configuration from the file."""
        self._set_config(self._load_config())
        self.notify = self._init_apprise()

    def _load_config(self) -> dict:
        """Load configuration from a file."""
        try:
            with open(self.args.config_file, "r", encoding="utf-8") as f:
                return Config(f)
        except ConfigError as e:
            logger.error("Cannot load configuration: %s", e)
            raise SystemExit(1) from e
        except FileNotFoundError as e:
            logger.error("Config file not found: %r", self.args.config_file)
            raise SystemExit(1) from e
        except Exception as e:
            logger.error("Cannot load configuration: %s", e)
            raise SystemExit(1) from e

    def matcher(self) -> BookMatcher:
        """Create a BookMatcher instance using the matcher threshold from the configuration."""
        return BookMatcher(self.config["matcher_threshold"])

    def calibre(self):
        """Create a Calibre instance using the configuration file."""
        if not (self.config.get("calibre") or {}).get("library"):
            raise ConfigError("This operation requires Calibre configuration")
        return Calibre(
            CalibreConfig(
                executable=self.config["calibre"]["calibredb_executable"],
                library=self.config["calibre"]["library"],
                server_username=self.config["calibre"].get("server_username"),
                server_password=self.config["calibre"].get("server_password"),
                command_timeout_seconds=self.config["calibre"].get("command_timeout_seconds", 120),
            )
        )

    def hardcover(self) -> set[Hardcover]:
        """Create a Hardcover client for each normalized reading list."""
        with ThreadPoolExecutor(max_workers=min(10, len(self.hardcover_lists))) as executor:
            return set(executor.map(self._hardcover_client, self.hardcover_lists))

    def library(self, media_type: MediaType) -> Library:
        """Construct only the backend for the requested medium."""
        if media_type == "ebook":
            return CalibreLibrary(self.calibre(), self.config.get("filetypes"))
        if media_type == "audiobook":
            settings = self.config.get("audiobookshelf")
            if not settings:
                raise ConfigError("Audiobook requests require 'audiobookshelf' configuration")
            return AudiobookshelfLibrary(
                Audiobookshelf(
                    settings["url"],
                    settings["api_key"],
                    settings["library_id"],
                ),
                AudiobookLibraryConfig(
                    library_path=settings.get("library_path"),
                    staging_path=settings.get("staging_path"),
                    folder_id=settings.get("folder_id"),
                    filetypes=settings.get("filetypes", ["m4b", "mp3"]),
                    scan_timeout_seconds=settings.get("scan_timeout_seconds", 120),
                    dry_run=getattr(self.args, "dry_run", False),
                ),
            )
        raise ConfigError(f"Unknown media type: {media_type!r}")

    def _hardcover_client(self, entry: dict) -> Hardcover:
        return Hardcover(
            entry["api_key"], list_slug=entry["list"], lang_codes=self.config["lang_codes"]
        )

    def wanted_requests(self) -> set[BookRequest]:
        """Fetch lists as independent requests, combining overlapping work identities."""
        selected = getattr(self.args, "media_type", None)
        entries = [
            entry
            for entry in self.hardcover_lists
            if not selected or selected in entry["media_types"]
        ]
        if not entries:
            return set()

        def fetch(entry):
            return {
                BookRequest(book, media)
                for book in self._hardcover_client(entry).get_books()
                for media in entry["media_types"]
                if not selected or media == selected
            }

        with ThreadPoolExecutor(max_workers=min(10, len(entries))) as executor:
            return set().union(*executor.map(fetch, entries))

    def myanonamouse(self):
        """Create a MyAnonamouse instance using the MAM ID from the configuration."""
        return MyAnonamouse(self.config["mam_id"])

    def qbittorrent(self):
        """Create a Qbittorrent instance using the configuration for qBittorrent."""
        # config = self.config.copy()  # Make a copy to avoid modifying the original config
        qbittorrent_config = self.config[
            "qbittorrent"
        ].copy()  # Make a copy to avoid modifying the original config
        mapping = qbittorrent_config.pop("mapping", None)
        category = qbittorrent_config.pop("category", "murid")
        qbittorrent_config["VERIFY_WEBUI_CERTIFICATE"] = qbittorrent_config.pop("verify_cert", True)
        client = qbittorrentapi.Client(**qbittorrent_config)
        config = QbittorrentConfig(
            client=client,
            category=category,
            dry_run=getattr(self.args, "dry_run", False),
            mapping=mapping,
        )
        return Qbittorrent(config)

    def notifier(self):
        """Get the Apprise notify function."""
        return self.notify

    def torrent_discovery(self, media_type: MediaType | None = None):
        """Create a TorrentDiscoveryService instance using the MyAnonamouse client."""
        media_type = media_type or getattr(self.args, "media_type", None)
        media_types = (
            {media_type} if media_type else requested_media_types(self.hardcover_lists)
        )
        return TorrentDiscoveryService(
            self.myanonamouse(),
            {media: self.torrent_selector(media) for media in media_types},
            self.qbittorrent(),
        )

    def torrent_import(self, media_type: MediaType = "ebook"):
        """Create an importer for one destination, including recovery of older requests."""
        return TorrentImportService(
            TorrentImportConfig(
                torrent_client=self.qbittorrent(),
                library=self.library(media_type),
                matcher=self.matcher(),
                notify=self.notifier(),
                dry_run=getattr(self.args, "dry_run", False),
                timeout=self.config["torrent_timeout_seconds"],
                media_type=media_type,
            )
        )

    def cron_iter(self, base_time):
        """Create a croniter instance for scheduling based on the configuration."""
        return croniter(self.config["schedule"], base_time)

    def sync_service(self):
        """Create a SyncService instance."""
        return SyncService(self)

    def torrent_selector(self, media_type: MediaType = "ebook"):
        """Create a TorrentSelector instance."""
        if media_type == "audiobook" and not self.config.get("audiobookshelf"):
            raise ConfigError("Audiobook operations require 'audiobookshelf' configuration")
        return TorrentSelector(
            lang_codes=set(self.config["lang_codes"]),
            wanted_filetypes=(
                self.config["audiobookshelf"]["filetypes"]
                if media_type == "audiobook"
                else self.config["filetypes"]
            ),
            blacklist=set(self.config["blacklisted_torrent_ids"]),
            exclude_vip=self.config.get("exclude_vip", False),
            media_type=media_type,
        )

    def recovery_book(self, book_id: int) -> Book | None:
        """Fetch a persisted work independently of its current reading-list membership."""
        selected = getattr(self.args, "media_type", None)
        entry = next(
            (entry for entry in self.hardcover_lists if selected in entry["media_types"]),
            # Recovery remains available after the last list for a medium is removed.
            self.hardcover_lists[0],
        )
        return self._hardcover_client(entry).get_book(book_id)

    def retry_service(self):
        """Route persisted requests lazily, without initializing unrelated libraries."""
        return RetryService(
            self.qbittorrent(),
            None,
            self.myanonamouse(),
            lambda: (request.book for request in self.wanted_requests()),
            recovery=RetryRecovery(
                self.torrent_import, self.recovery_book, getattr(self.args, "media_type", None)
            ),
        )
