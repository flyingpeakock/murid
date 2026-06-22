"""Module for interacting with the MyAnonamouse website."""

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import requests

from ..domain.book import Book
from ..domain.torrent import Torrent, TorrentMetadata

logger = logging.getLogger("murid")


@dataclass
class MyAnonamouseQuery:
    """Data class representing a search query for MyAnonamouse."""

    text: str
    categories: list[int] | None = None
    search_fields: list[str] | None = None
    main_categories: list[int] | None = None
    id: int | None = None


class MAMError(Exception):
    """Custom exception for errors related to MyAnonamouse interactions."""


class MyAnonamouse:
    """Class for interacting with the MyAnonamouse website to search for and download torrents."""

    BASE_URL = "https://www.myanonamouse.net"
    SEARCH_URL = f"{BASE_URL}/tor/js/loadSearchJSONbasic.php"
    DOWNLOAD_URL = f"{BASE_URL}/tor/download.php"
    _MIN_REQUEST_INTERVAL = 0.5  # seconds

    def __init__(self, mam_id: str) -> None:
        """Initialize the MyAnonamouse class with the provided mam_id for authentication."""
        self.session = requests.Session()
        self._mam_id = mam_id
        self.session.cookies.set("mam_id", mam_id, domain=".myanonamouse.net")
        self._lock = threading.Lock()
        self._last_request_time = 0.0

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make a request to the MyAnonamouse API, ensuring that we respect the minimum interval."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._MIN_REQUEST_INTERVAL:
                time.sleep(self._MIN_REQUEST_INTERVAL - elapsed)
            self._last_request_time = time.monotonic()
            return self.session.request(method, url, **kwargs)

    def search(self, query: MyAnonamouseQuery) -> set[Torrent]:
        """Search for torrents on MyAnonamouse matching the specified criteria."""

        payload = {
            "tor": {
                "text": query.text,
                "cat": query.categories or [0],
                "main_cat": query.main_categories or [],
                "srchIn": query.search_fields
                or [
                    "title",
                    "author",
                    "narrator",
                ],
                "searchType": "all",
                "searchIn": "torrents",
                "sortType": "default",
                "startNumber": str(0),
                "id": str(query.id) if query.id is not None else "",
            },
            "dlLink": "true",
            "isbn": "true",
        }

        logger.debug("Searching MyAnonamouse for %s", query.text if query.text else str(query.id))
        try:
            response = self.session.post(
                self.SEARCH_URL,
                json=payload,
                timeout=30,
            )

            response.raise_for_status()
        except requests.RequestException as e:
            logger.error("Error searching MyAnonamouse: %s", e)
            return set()

        data = response.json()

        if "error" in data:
            return set()

        if "data" not in data:
            raise MAMError(f"Unexpected response: {data}")

        return {self._parse_torrent(row) for row in data["data"][:100]}

    @staticmethod
    def _parse_torrent(data: dict[str, Any]) -> Torrent:
        """Parse a torrent from the raw data returned by the MyAnonamouse API."""
        series_info = json.loads(data.get("series_info", "{}"))
        series_name = None
        series_number = None
        if series_info:
            _, (series_name, _, series_number) = next(iter(series_info.items()))

        return Torrent(
            book=Book(
                title=str(data.get("title", "")),
                authors=[a.strip() for _, a in json.loads(data.get("author_info", "{}")).items()],
                id=int(data.get("id", 0)),
                isbn=[data.get("isbn", None)],
                source="myanonamouse",
                series=series_name,
                series_number=series_number,
            ),
            metadata=TorrentMetadata(
                category=int(data.get("category", 0)),
                size=parse_size(data.get("size", "")),
                seeders=int(data.get("seeders", 0)),
                leechers=int(data.get("leechers", 0)),
                freeleech=bool(int(data.get("free", 0))),
                vip=bool(int(data.get("vip", 0))),
            ),
            download_hash=data.get("dl"),
            series_info=json.loads(data.get("series_info", "{}")),
            language=data.get("lang_code", None),
            file_types=data.get("filetype", "").split() if data.get("filetype") else [],
            raw=data,
        )

    def search_ebook(self, title: str, author: str | None = None) -> set[Torrent]:
        """Search for ebooks on MyAnonamouse matching the specified title and optional author."""
        query = title
        if author:
            query += f" {author}"

        result = self.search(
            MyAnonamouseQuery(
                text=query, main_categories=[14], search_fields=["title", "author", "series"]
            )
        )
        if not result:
            logger.info("No potential torrents found for %s", query)
        else:
            count = len(result)
            logger.info(
                "Found %d potential torrent%s for %s", count, "" if count == 1 else "s", query
            )
        return result

    def download_torrent(self, torrent: Torrent) -> bytes | None:
        """Download the torrent file for the specified torrent."""
        try:
            response = self._request(
                "GET", f"{self.DOWNLOAD_URL}/?tid={torrent.book.id}", timeout=30
            )
            response.raise_for_status()
            logger.debug("Torrent for %s downloaded successfully", torrent.book)
            return response.content
        except requests.RequestException as e:
            logger.error("Error downloading torrent for %s: %s", torrent.book, e)
            return None


def parse_size(size: str) -> int:
    """Parse a human-readable file size (e.g. "1.5 GB") into bytes."""
    if not size:
        return 0

    units = {
        "B": 1,
        "KB": 1024,
        "MB": 1024**2,
        "GB": 1024**3,
        "TB": 1024**4,
        "KiB": 1024,
        "MiB": 1024**2,
        "GiB": 1024**3,
        "TiB": 1024**4,
    }

    try:
        value, unit = size.strip().split()
        value = value.replace(",", "")
        return int(float(value) * units[unit])
    except (ValueError, KeyError):
        logger.warning("Could not parse torrent size %r", size)
        return 0
