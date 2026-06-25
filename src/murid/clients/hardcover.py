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

            logger.debug("Hardcover data fetched successfully for query: %s", query)
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
        logger.debug("Fetched Hardcover user info: %s", user)
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

              contributions {
                author {
                  name
                }
              }

              editions {
                isbn_10
                isbn_13
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

    def get_books(self) -> set[Book]:
        """Fetch the user's "Want to Read" books from the Hardcover API.

        Return them as a list of Book objects.
        """
        books: set[Book] = set()

        try:
            data = self.fetch_data()
            items = data.get("data", {}).get("user_books", [])
        except requests.RequestException:
            return books

        for item in items:
            book = item.get("book", {})

            authors = [
                c["author"]["name"] for c in book.get("contributions", []) if c.get("author")
            ]

            editions = book.get("editions", [])
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
                )
            )

        if not books:
            logger.warning("No books found for user %s", self.user.name)

        return books
