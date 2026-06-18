"""Defines the Book class, which represents a book with its metadata."""

from dataclasses import dataclass


@dataclass
class Book:
    """Represents a book with its metadata."""

    title: str
    authors: list[str]
    id: int
    isbn: list[str | None]
    source: str
    series: str | None = None
    series_number: float | None = None

    def __str__(self):
        return f"{self.title} by {', '.join(self.authors)}"
