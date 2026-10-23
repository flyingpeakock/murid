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
from ..domain.book_request import MediaType
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


class MAMSearchError(MAMError):
    """MyAnonamouse rejected an individual query's search syntax."""


def _error_text(value: Any) -> str:
    """Convert API HTML error messages to readable terminal text."""
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", str(value))).split())


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
    # Verified against authenticated search responses: main_cat and catname.
    MAIN_CATEGORIES = {"ebook": 14, "audiobook": 13}
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
            raise MAMError(f"MyAnonamouse rejected the search: {_error_text(data['error'])}")

    def search(self, query: MyAnonamouseQuery, *, raise_on_error: bool = True) -> set[Torrent]:
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
            if raise_on_error:
                raise MAMError(f"Error searching MyAnonamouse: {e}") from e
            logger.error("MyAnonamouse search failed: %s", e)
            return set()

        try:
            data = response.json()
        except ValueError as error:
            raise MAMError("MyAnonamouse returned an invalid JSON search response") from error

        if "error" in data:
            if data["error"] == "Nothing returned, out of 0":
                return set()
            reason = _error_text(data["error"])
            context = f"query {query.text!r}" if query.id is None else f"torrent ID {query.id}"
            if raise_on_error:
                error_type = MAMSearchError if "Search returned an error" in reason else MAMError
                raise error_type(f"MyAnonamouse rejected {context}: {reason}")
            logger.error("MyAnonamouse rejected %s: %s", context, reason)
            return set()

        if "data" not in data:
            logger.debug("Unexpected MyAnonamouse response: %r", data)
            raise MAMError("Unexpected response from MyAnonamouse: missing search results")

        rows = data["data"] or []
        total = max(
            [
                len(rows),
                *(
                    int(data[key])
                    for key in ("total", "total_found")
                    if str(data.get(key, "")).isdigit()
                ),
            ]
        )
        if total > 100:
            logger.warning(
                "MyAnonamouse search for %r is limited to %d of %d results; "
                "refine the title if the desired edition is missing",
                query.text or query.id,
                min(len(rows), 100),
                total,
            )

        torrents = {self._parse_torrent(row) for row in rows[:100]}
        logger.debug(
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
            media_type={"13": "audiobook", "14": "ebook"}.get(str(data.get("main_cat"))),
        )

    def search_ebook(self, title: str) -> set[Torrent]:
        """Search for ebooks on MyAnonamouse matching the specified title."""
        return self.search_title(title, "ebook")

    def search_title(self, title: str, media_type: MediaType = "ebook") -> set[Torrent]:
        """Search titles, authors, and series within one requested medium."""
        query = MyAnonamouseQuery(
            text=title,
            main_categories=[self.MAIN_CATEGORIES[media_type]],
            search_fields=["title", "author", "series"],
        )
        return self.search(query)

    def search_author(self, author: str, media_type: MediaType = "ebook") -> set[Torrent]:
        """Search authors within one requested medium."""
        query = MyAnonamouseQuery(
            text=author,
            main_categories=[self.MAIN_CATEGORIES[media_type]],
            search_fields=["author"],
        )
        return self.search(query)

    def download_torrent(self, torrent: Torrent) -> bytes | None:
        """Download the torrent file for the specified torrent."""
        try:
            response = self._request(
                "GET", f"{self.DOWNLOAD_URL}/?tid={torrent.book.id}", timeout=120
            )
            response.raise_for_status()
            logger.debug("%s: torrent downloaded successfully", torrent.book)
            return response.content
        except requests.RequestException as e:
            logger.error("%s: could not download torrent: %s", torrent.book, e)
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
