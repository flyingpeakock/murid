"""Module for interacting with the Hardcover API to fetch user book data."""

import logging
from dataclasses import dataclass

import requests

from ..domain.book import Book

logger = logging.getLogger("murid")


@dataclass
class HardcoverUser:
    """Data class representing a Hardcover user."""

    id: int
    name: str


class HardcoverError(Exception):
    """Custom exception for errors related to the Hardcover API."""


class Hardcover:
    """Class for interacting with the Hardcover API to fetch user book data."""

    def __init__(self, api: str, user: HardcoverUser | None = None) -> None:
        """Initialize the Hardcover class with the API token and user ID."""
        self.url = "https://api.hardcover.app/v1/graphql"
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": api,
        }
        self._session = requests.Session()

        if not user:
            self.user = self.get_user()
        else:
            self.user = user

        logger.debug("Initialized Hardcover for user: %s", self.user.name)

    def make_query(self, query: str, variables: dict | None = None) -> dict:
        """Make a GraphQL query to the Hardcover API."""
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        try:
            response = self._session.post(
                self.url,
                json=payload,
                headers=self._headers,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                logger.error("GraphQL errors: %s", data["errors"])
                raise HardcoverError(f"GraphQL errors: {data['errors']}")

            return data
        except requests.RequestException as e:
            logger.error("Error making query to Hardcover API: %s", e)
            raise HardcoverError(f"Error making query to Hardcover API: {e}") from e

    def get_user(self) -> HardcoverUser:
        """Fetch the current user information from the Hardcover API."""
        query = """
        query  {
            me {
                id
                name
            }
        }
        """
        data = self.make_query(query)
        user = HardcoverUser(**data["data"]["me"][0])
        return user

    def fetch_data(self) -> dict:
        """Fetch book data from the Hardcover API for the specified user."""
        logger.debug("Fetching Hardcover data...")

        query = """
        query GetUserBooks($user_id: Int!) {
          user_books(
              where: { user_id: { _eq: $user_id }, status_id: { _eq: 1 } }
            distinct_on: book_id
          ) {
            book {
              id
              title
              subtitle
              alternative_titles

              book_mappings(limit: 100) {
                external_id
                platform {
                  name
                }
              }

              contributions {
                author {
                  name
                }
              }

              editions {
                title
                subtitle
                alternative_titles
                isbn_10
                isbn_13
                asin

                book_mappings(limit: 100) {
                  external_id
                  platform {
                    name
                  }
                }
              }

              book_series {
                  position
                  series {
                      name
                  }
              }
            }
          }
        }
        """
        variables = {"user_id": self.user.id}
        data = self.make_query(query, variables=variables)
        logger.debug("Hardcover data fetched successfully")
        return data

    @staticmethod
    def _extract_series_info(data: dict) -> tuple[str | None, float | None]:
        """Extract series name and position from the book data."""
        series_info = data.get("book_series", [])
        if not series_info:
            return None, None
        name = series_info[0].get("series", {}).get("name")
        position = series_info[0].get("position")
        return name, position

    @staticmethod
    def _extract_isbn(editions: list[dict] | None) -> list[str | None]:
        """Extract ISBN-10 and ISBN-13 from the editions data."""
        if not editions:
            return []

        isbns = []
        for edition in editions:
            isbn13 = edition.get("isbn_13")
            isbn10 = edition.get("isbn_10")

            if isbn13:
                isbns.append(isbn13)
            if isbn10:
                isbns.append(isbn10)

        return isbns

    @staticmethod
    def _extract_text_values(value) -> list[str]:
        """Extract title strings from Hardcover's JSON alternative-title fields."""
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, list):
            return [text for item in value for text in Hardcover._extract_text_values(item)]
        if isinstance(value, dict):
            preferred = [
                value[key] for key in ("title", "name", "alternative_title") if key in value
            ]
            values = preferred if preferred else list(value.values())
            return [text for item in values for text in Hardcover._extract_text_values(item)]
        return []

    @classmethod
    def _extract_alternative_titles(cls, book: dict, editions: list[dict]) -> list[str]:
        """Collect book and edition titles that can name the same work."""
        titles = []
        if book.get("subtitle"):
            titles.append(f"{book.get('title', '')}: {book['subtitle']}")
        titles.extend(cls._extract_text_values(book.get("alternative_titles")))

        for edition in editions:
            title = edition.get("title")
            subtitle = edition.get("subtitle")
            if title and subtitle:
                titles.append(f"{title}: {subtitle}")
            elif title:
                titles.append(title)
            titles.extend(cls._extract_text_values(edition.get("alternative_titles")))

        primary_title = book.get("title")
        return list(dict.fromkeys(title for title in titles if title and title != primary_title))

    @staticmethod
    def _extract_identifiers(book: dict, editions: list[dict]) -> dict[str, str | list[str]]:
        """Collect external catalog IDs attached to the book and its editions."""
        identifiers: dict[str, list[str]] = {}

        def add(name, value):
            if not name or not value:
                return
            values = identifiers.setdefault(str(name), [])
            value = str(value)
            if value not in values:
                values.append(value)

        for mapping in book.get("book_mappings") or []:
            add((mapping.get("platform") or {}).get("name"), mapping.get("external_id"))

        for edition in editions:
            add("Amazon", edition.get("asin"))
            for mapping in edition.get("book_mappings") or []:
                add((mapping.get("platform") or {}).get("name"), mapping.get("external_id"))

        return dict(identifiers)

    def get_books(self) -> set[Book]:
        """Fetch the user's "Want to Read" books from the Hardcover API.

        Return them as a list of Book objects.
        """
        books: set[Book] = set()

        try:
            data = self.fetch_data()
            items = data.get("data", {}).get("user_books", [])
        except HardcoverError:
            logger.error("Failed to fetch books for user %s", self.user.name)
            return books

        for item in items:
            book = item.get("book", {})

            authors = [
                c["author"]["name"] for c in (book.get("contributions") or []) if c.get("author")
            ]

            editions = book.get("editions") or []
            isbn = self._extract_isbn(editions)
            series, series_number = self._extract_series_info(book)

            books.add(
                Book(
                    id=book.get("id"),
                    title=book.get("title"),
                    authors=authors,
                    isbn=isbn,
                    source="hardcover",
                    series=series,
                    series_number=series_number,
                    alternative_titles=self._extract_alternative_titles(book, editions),
                    identifiers=self._extract_identifiers(book, editions),
                )
            )

        if not books:
            logger.warning("No books found for user %s", self.user.name)
        else:
            logger.debug(
                "Loaded %d Hardcover books (%d with alternate titles, %d with external IDs, "
                "%d with series positions)",
                len(books),
                sum(bool(book.alternative_titles) for book in books),
                sum(bool(book.identifiers) for book in books),
                sum(book.series_number is not None for book in books),
            )

        return books
