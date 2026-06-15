from dataclasses import dataclass
from typing import Any

try:
    from ._version import __version__ as __version__
except ImportError:
    __version__ = "unknown"


@dataclass
class Book:
    title: str
    authors: list[str]
    id: int
    isbn: list[str | None]
    source: str
    series: str | None = None
    series_number: float | None = None

    def __str__(self):
        return f"{self.title} by {', '.join(self.authors)}"


@dataclass(slots=True)
class Torrent:
    book: Book
    category: int
    category_name: str
    main_category: int
    size: int
    seeders: int
    leechers: int
    freeleech: bool
    vip: bool
    download_hash: str | None = None
    narrator_info: dict[str, str] | None = None
    series_info: dict[str, Any] | None = None
    language: str | None = None
    file_types: list[str] | None = None
    raw: dict[str, Any] | None = None

    @property
    def download_url(self) -> str | None:
        if not self.download_hash:
            return None

        return f"https://www.myanonamouse.net/tor/download.php/{self.download_hash}"

    def __str__(self) -> str:
        return f"https://www.myanonamouse.net/t/{self.book.id}"
