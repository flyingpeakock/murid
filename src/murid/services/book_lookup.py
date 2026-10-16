"""Resolve a user-provided title against the configured Hardcover reading lists."""

from ..domain.book import Book


class BookLookupError(Exception):
    """A title did not identify exactly one Hardcover book."""


def find_hardcover_book(name: str, factory) -> Book:
    """Return the unique Hardcover book matching a title or alternate title."""
    matcher = factory.matcher()
    books = {
        book.id: book for client in factory.hardcover() for book in client.get_books()
    }.values()
    matches = []
    for book in books:
        titles = (book.title, *book.alternative_titles)
        score = max((matcher.title_similarity(name, title) for title in titles if title), default=0)
        if score >= matcher.threshold:
            matches.append((book, score))

    if not matches:
        raise BookLookupError(f"No Hardcover book matched {name!r}")
    if len(matches) > 1:
        titles = ", ".join(book.title for book, _ in sorted(matches, key=lambda pair: -pair[1]))
        raise BookLookupError(f"More than one Hardcover book matched {name!r}: {titles}")

    return matches[0][0]
