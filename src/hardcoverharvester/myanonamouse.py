import json
import logging
from typing import Any

import requests

from . import Book, Torrent

logger = logging.getLogger("HardcoverHarvester")


class MAMError(Exception):
    pass


class MyAnonamouse:
    BASE_URL = "https://www.myanonamouse.net"
    SEARCH_URL = f"{BASE_URL}/tor/js/loadSearchJSONbasic.php"
    DOWNLOAD_URL = f"{BASE_URL}/tor/download.php"

    def __init__(self, mam_id: str) -> None:
        self.session = requests.Session()
        self._mam_id = mam_id
        self.session.cookies.set("mam_id", mam_id, domain=".myanonamouse.net")

    def search(
        self,
        text: str,
        *,
        categories: list[int] | None = None,
        search_fields: list[str] | None = None,
        main_categories: list[int] | None = None,
        search_type: str = "all",
        per_page: int = 100,
        start: int = 0,
        include_description: bool = False,
        include_download_link: bool = True,
        include_isbn: bool = True,
    ) -> list[Torrent]:

        payload = {
            "tor": {
                "text": text,
                "cat": categories or [0],
                "main_cat": main_categories or [],
                "srchIn": search_fields
                or [
                    "title",
                    "author",
                    "narrator",
                ],
                "searchType": search_type,
                "searchIn": "torrents",
                "sortType": "default",
                "startNumber": str(start),
            },
            "dlLink": "true" if include_download_link else "",
            "isbn": "true" if include_isbn else "",
        }

        if include_description:
            payload["description"] = "true"

        logger.debug(f"Searching MyAnonamouse for {text}")
        try:
            response = self.session.post(
                self.SEARCH_URL,
                json=payload,
                timeout=30,
            )

            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Error searching MyAnonamouse: {e}")
            return []

        data = response.json()

        if "data" not in data:
            raise MAMError(f"Unexpected response: {data}")

        return [self._parse_torrent(row) for row in data["data"][:per_page]]

    def get_torrent(self, torrent_id: int) -> Torrent | None:
        results = self.search(
            "",
            include_description=True,
        )

        return next(
            (t for t in results if t.book.id == torrent_id),
            None,
        )

    @staticmethod
    def _parse_torrent(data: dict[str, Any]) -> Torrent:
        return Torrent(
            book=Book(
                title=data.get("title", ""),
                authors=[a.strip() for _, a in json.loads(data.get("author_info", "{}")).items()],
                id=int(data.get("id", 0)),
                isbn=[data.get("isbn", None)],
            ),
            category=int(data.get("category", 0)),
            category_name=data.get("catname", ""),
            main_category=int(data.get("main_cat", 0)),
            size=parse_size(data.get("size", "")),
            seeders=int(data.get("seeders", 0)),
            leechers=int(data.get("leechers", 0)),
            freeleech=bool(int(data.get("free", 0))),
            vip=bool(int(data.get("vip", 0))),
            download_hash=data.get("dl"),
            narrator_info=json.loads(data.get("narrator_info", "{}")),
            series_info=json.loads(data.get("series_info", "{}")),
            language=data.get("lang_code", None),
            raw=data,
        )

    def search_ebook(self, title: str, author: str | None = None) -> list[Torrent]:
        query = title
        if author:
            query += f" {author}"

        result = self.search(
            query, main_categories=[14], search_fields=["title", "author", "series"]
        )
        if not result:
            logger.info(f"No results found for {query}")
        else:
            count = len(result)
            logger.info(f"Found {count} result{'s' if count != 1 else ''} for {query}")
        return result

    def download_torrent(self, torrent: Torrent) -> bytes | None:
        try:
            response = self.session.get(f"{self.DOWNLOAD_URL}/?tid={torrent.book.id}")
            response.raise_for_status()
            logger.debug(f"Torrent for {torrent.book.title} downloaded successfully")
            return response.content
        except requests.RequestException as e:
            logger.error(f"Error downloading torrent for {torrent.book.title}: {e}")
            return None


def parse_size(size: str) -> int:
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
