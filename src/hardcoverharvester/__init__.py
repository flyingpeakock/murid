from dataclasses import dataclass

try:
    from ._version import __version__ as __version__
except ImportError:
    __version__ = "unknown"


@dataclass
class Book:
    title: str
    authors: list[str]
    id: int
    isbn: str | None
