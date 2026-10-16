"""Module for interacting with the MyAnonamouse website."""

import json
import logging
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
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


def _sanitize_query(text: str) -> str:
    """Keep Unicode words, including their combining marks, without search operators."""
    normalized = unicodedata.normalize("NFC", text)
    if not any(character.isalnum() for character in normalized):
        return ""
    return " ".join(
        "".join(
            character if character.isspace() or unicodedata.category(character)[0] in "LNM" else " "
            for character in normalized
        ).split()
    )


class MyAnonamouse:
    """Class for interacting with the MyAnonamouse website to search for and download torrents."""

    BASE_URL = "https://www.myanonamouse.net"
    SEARCH_URL = f"{BASE_URL}/tor/js/loadSearchJSONbasic.php"
    DOWNLOAD_URL = f"{BASE_URL}/tor/download.php"
    _MIN_REQUEST_INTERVAL = 0.5  # seconds
    _MAX_RATE_LIMIT_RETRIES = 3

    def __init__(self, mam_id: str) -> None:
        """Initialize the MyAnonamouse class with the provided mam_id for authentication."""
        self.session = requests.Session()
        self._mam_id = mam_id
        self.session.cookies.set("mam_id", mam_id, domain=".myanonamouse.net")
        self._lock = threading.Lock()
        self._last_request_time = 0.0

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make a paced request and retry rate limits using the server's cooldown."""
        with self._lock:
            for attempt in range(self._MAX_RATE_LIMIT_RETRIES + 1):
                elapsed = time.monotonic() - self._last_request_time
                if elapsed < self._MIN_REQUEST_INTERVAL:
                    time.sleep(self._MIN_REQUEST_INTERVAL - elapsed)
                self._last_request_time = time.monotonic()
                response = self.session.request(method, url, **kwargs)

                if (
                    getattr(response, "status_code", None) != 429
                    or attempt == self._MAX_RATE_LIMIT_RETRIES
                ):
                    return response

                delay = self._retry_after_seconds(response, attempt)
                logger.warning(
                    "MyAnonamouse rate limited a request; retrying in %.1f seconds",
                    delay,
                )
                time.sleep(delay)

        raise RuntimeError("MyAnonamouse request retry loop exited unexpectedly")

    @staticmethod
    def _retry_after_seconds(response: requests.Response, attempt: int) -> float:
        """Return the server's Retry-After delay, or exponential backoff if absent."""
        retry_after = getattr(response, "headers", {}).get("Retry-After")
        if retry_after is not None:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                except (TypeError, ValueError, OverflowError):
                    pass
                else:
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())

        return float(2**attempt)

    @staticmethod
    def _search_payload(query: MyAnonamouseQuery) -> dict[str, Any]:
        """Build a request, treating generated titles as words rather than search syntax."""
        text = _sanitize_query(query.text)
        return {
            "tor": {
                "text": text,
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

    def check_connection(self) -> None:
        """Check that the search API accepts the configured session cookie."""
        response = self._request(
            "POST",
            self.SEARCH_URL,
            json=self._search_payload(MyAnonamouseQuery(text="murid-connection-check")),
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        # MaM reports an empty search as an API error even when the request succeeded.
        if "error" in data and data["error"] != "Nothing returned, out of 0":
            raise MAMError(f"MyAnonamouse rejected the search: {data['error']}")

    def search(self, query: MyAnonamouseQuery, *, raise_on_error: bool = False) -> set[Torrent]:
        """Search for torrents on MyAnonamouse matching the specified criteria."""

        payload = self._search_payload(query)
        text = payload["tor"]["text"]
        if not text and query.id is None:
            logger.debug("Skipping MyAnonamouse query %r: no searchable words", query.text)
            return set()
        logger.debug("Searching MyAnonamouse for %r", text or query.id)
        try:
            response = self._request(
                "POST",
                self.SEARCH_URL,
                json=payload,
                timeout=120,
            )

            response.raise_for_status()
        except requests.RequestException as e:
            logger.error("Error searching MyAnonamouse: %r", e)
            if raise_on_error:
                raise MAMError(f"Error searching MyAnonamouse: {e}") from e
            return set()

        data = response.json()

        if "error" in data:
            if raise_on_error:
                raise MAMError(f"MyAnonamouse rejected the search: {data['error']}")
            return set()

        if "data" not in data:
            raise MAMError(f"Unexpected response: {data}")

        rows = data["data"]
        if len(rows) > 100:
            logger.debug(
                "MyAnonamouse returned %d rows; parsing only the first 100 (total=%r, "
                "total_found=%r)",
                len(rows),
                data.get("total"),
                data.get("total_found"),
            )

        torrents = {self._parse_torrent(row) for row in rows[:100]}
        logger.info(
            "MyAnonamouse returned %d torrents for the query %r",
            len(torrents),
            query.text or query.id,
        )
        return torrents

    @staticmethod
    def _parse_torrent(data: dict[str, Any]) -> Torrent:
        """Parse a torrent from the raw data returned by the MyAnonamouse API."""
        series_info = json.loads(data.get("series_info", "{}"))
        series_name = None
        series_number = None
        if series_info:
            _, (series_name, _, series_number) = next(iter(series_info.items()))

        raw_filetypes = data.get("filetypes") or data.get("filetype") or ""
        if isinstance(raw_filetypes, list):
            file_types = [str(value).strip().lower().lstrip(".") for value in raw_filetypes]
        else:
            file_types = [
                value.strip().lower().lstrip(".")
                for value in re.split(r"[\s,;/|]+", str(raw_filetypes))
                if value.strip()
            ]

        return Torrent(
            book=Book(
                title=unescape(str(data.get("title", ""))),
                authors=[
                    unescape(str(author)).strip()
                    for author in json.loads(data.get("author_info", "{}")).values()
                ],
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
            file_types=file_types,
            raw=data,
        )

    def search_ebook(self, title: str) -> set[Torrent]:
        """Search for ebooks on MyAnonamouse matching the specified title."""
        result = self.search(
            MyAnonamouseQuery(
                text=title, main_categories=[14], search_fields=["title", "author", "series"]
            )
        )
        return result

    def download_torrent(self, torrent: Torrent) -> bytes | None:
        """Download the torrent file for the specified torrent."""
        try:
            response = self._request(
                "GET", f"{self.DOWNLOAD_URL}/?tid={torrent.book.id}", timeout=120
            )
            response.raise_for_status()
            logger.debug("Torrent for %s downloaded successfully", torrent.book)
            return response.content
        except requests.RequestException as e:
            logger.error("Error downloading torrent for %s: %r", torrent.book, e)
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
