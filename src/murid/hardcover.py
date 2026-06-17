import logging

import requests

from . import Book

logger = logging.getLogger("murid")


class HardcoverError(Exception):
    """Custom exception for errors related to the Hardcover API."""

    pass


class Hardcover:
    """Class for interacting with the Hardcover API to fetch user book data."""

    def __init__(self, api: str, user_id: str) -> None:
        """Initialize the Hardcover class with the API token and user ID."""
        self.url = "https://api.hardcover.app/v1/graphql"
        self._user_id = user_id
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": api,
        }
        self._session = requests.Session()

        logger.debug(f"Initialized Hardcover for user_id: {self._user_id}")

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

        variables = {"user_id": self._user_id}

        try:
            response = self._session.post(
                self.url,
                json={"query": query, "variables": variables},
                headers=self._headers,
                timeout=30,
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Error fetching data from Hardcover API: {e}")
            raise HardcoverError(f"Error fetching data from Hardcover API: {e}") from e

        data = response.json()

        if "errors" in data:
            logger.error(f"GraphQL errors: {data['errors']}")
            raise HardcoverError(f"GraphQL errors: {data['errors']}")

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

    def get_books(self) -> list[Book]:
        """Fetch the user's "Want to Read" books from the Hardcover API.

        Return them as a list of Book objects.
        """
        data = self.fetch_data()
        items = data.get("data", {}).get("user_books", [])

        books: list[Book] = []

        for item in items:
            book = item.get("book", {})

            authors = [
                c["author"]["name"] for c in book.get("contributions", []) if c.get("author")
            ]

            editions = book.get("editions", [])
            isbn = self._extract_isbn(editions)
            series, series_number = self._extract_series_info(book)

            books.append(
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
            logger.warning(f"No books found for user {self._user_id}.")

        return books
