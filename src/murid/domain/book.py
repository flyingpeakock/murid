"""Defines the Book class, which represents a book with its metadata."""

from dataclasses import dataclass, field


@dataclass
class Book:  # pylint: disable=too-many-instance-attributes
    """Represents a book with its metadata."""

    title: str
    authors: list[str]
    id: int
    isbn: list[str | None]
    source: str
    series: str | None = None
    series_number: float | None = None
    alternative_titles: list[str] = field(default_factory=list)
    identifiers: dict[str, str | list[str]] = field(default_factory=dict)

    def __str__(self):
        return f"{self.title} by {', '.join(self.authors)}"

    def __hash__(self):
        return hash(
            (
                self.title,
                tuple(self.authors),
                self.id,
                self.source,
                self.series,
                self.series_number,
                tuple(self.isbn),
                tuple(self.alternative_titles),
                tuple(
                    sorted(
                        (name, value)
                        for name, values in self.identifiers.items()
                        for value in (
                            values if isinstance(values, (list, tuple, set)) else [values]
                        )
                    )
                ),
            )
        )

    def __eq__(self, other):
        if not isinstance(other, Book):
            return NotImplemented

        return (
            self.title == other.title
            and self.authors == other.authors
            and self.id == other.id
            and self.isbn == other.isbn
            and self.source == other.source
            and self.series == other.series
            and self.series_number == other.series_number
            and self.alternative_titles == other.alternative_titles
            and self.identifiers == other.identifiers
        )
