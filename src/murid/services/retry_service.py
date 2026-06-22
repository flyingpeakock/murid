"""This module defines the RetryService class."""

import logging
import re
from collections.abc import Iterator

from ..clients.myanonamouse import MAMError, MyAnonamouse, MyAnonamouseQuery
from ..clients.torrent_clients import TorrentClient
from ..domain.book import Book
from .torrent_import import TorrentImportService

logger = logging.getLogger("murid")


class RetryService:
    """Service responsible for retrying torrents that previously timed out during import."""

    def __init__(
        self,
        torrent_client: TorrentClient,
        import_service: TorrentImportService,
        myanonamouse: MyAnonamouse,
    ) -> None:
        """Initialize the RetryService with the necessary dependencies."""
        self.torrent_client = torrent_client
        self.import_service = import_service
        self.myanonamouse = myanonamouse

    def retry_torrents(self) -> None:
        """Retry torrents that previously timed out during import."""
        for torrent_id, mam_id in self.fetch_previous_torrents():
            book = self.get_book_by_mam_id(mam_id)
            if book:
                if self.import_service.process_torrent(torrent_id, book):
                    self.torrent_client.remove_tag(torrent_id, "murid_timeout")
                else:
                    logger.warning("Could not import %s, will retry later", book)

    def fetch_previous_torrents(self) -> Iterator[tuple[str, int]]:
        """Fetch torrents that previously timed out during import."""
        previous_torrents = self.torrent_client.get_torrents_with_tag("murid_timeout")
        if not previous_torrents:
            logger.debug("No previously timed out torrents found with tag 'murid_timeout'")
            return
        logger.debug(
            "Found %d previously timed out torrents with tag 'murid_timeout'",
            len(previous_torrents),
        )
        for torrent in previous_torrents:
            match = re.search(r"MID=(\d+)", torrent.comment or "")
            if match:
                mam_id = int(match.group(1))
                yield (torrent.hash, mam_id)

    def get_book_by_mam_id(self, mam_id: int) -> Book | None:
        """Fetch the book information from MyAnonamouse using the provided mam_id."""
        try:
            result = self.myanonamouse.search(MyAnonamouseQuery(text="", id=mam_id))
            if not result:
                logger.warning("No torrent found on MyAnonamouse for ID %d", mam_id)
                return None

            if len(result) > 1:
                logger.warning(
                    "Multiple torrents found on MyAnonamouse for ID %d, expected only one", mam_id
                )
                return None

            torrent = next(iter(result))
            return torrent.book

        except MAMError as e:
            logger.error("Error searching MyAnonamouse for ID %d: %s", mam_id, e)
            return None
