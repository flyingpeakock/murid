import requests
import logging

logger = logging.getLogger("HardcoverHarvester")


class Hardcover:
    def __init__(self, api: str, user_id: str) -> None:
        self.url = "https://api.hardcover.app/v1/graphql"
        self._user_id = user_id
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": api,
        }
        self._session = requests.Session()

        logger.debug(f"Initialized Hardcover for user_id: {self._user_id}")

    def fetch_data(self) -> dict:
        logger.debug("Fetching Hardcover data...")

        query = """
        query GetUserBooks($user_id: Int!) {
          user_books(
            where: { user_id: { _eq: $user_id } }
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
            raise

        data = response.json()

        if "errors" in data:
            logger.error(f"GraphQL errors: {data['errors']}")
            raise Exception(f"GraphQL errors: {data['errors']}")

        logger.debug("Data fetched successfully")
        return data

    @staticmethod
    def _extract_isbn(editions: list[dict] | None) -> str | None:
        if not editions:
            return None

        for edition in editions:
            isbn13 = edition.get("isbn_13")
            isbn10 = edition.get("isbn_10")

            if isbn13:
                return isbn13
            if isbn10:
                return isbn10

        return None

    def get_books(self) -> list[dict]:
        data = self.fetch_data()
        items = data.get("data", {}).get("user_books", [])

        books: list[dict] = []

        for item in items:
            book = item.get("book", {})

            authors = [
                c["author"]["name"]
                for c in book.get("contributions", [])
                if c.get("author")
            ]

            editions = book.get("editions", [])
            isbn = self._extract_isbn(editions)

            books.append(
                {
                    "id": book.get("id"),
                    "title": book.get("title"),
                    "authors": authors,
                    "isbn": isbn,
                }
            )

        if books:
            logger.debug(
                "Books extracted: %s",
                [b["title"] for b in books],
            )
        else:
            logger.warning("No books found for this user.")

        return books
