import logging
import requests

logger = logging.getLogger("HardcoverHarvester")


class Hardcover:
    def __init__(self, api: str, user_id: str) -> None:
        self.url = "https://api.hardcover.app/v1/graphql"
        self._user_id = user_id
        self._headers = {"Content-Type": "application/json", "Authorization": api}
        self._session = requests.Session()
        logger.debug(f"Initialized Hardcover for user_id: {self._user_id}")

    def fetch_data(self) -> None:
        logger.debug("Fetching hardcover data...")
        query = """
                query GetUserBooks($user_id: Int!) {
                  user_books(
                    where: {
                      user_id: { _eq: $user_id }
                    }
                    distinct_on: book_id
                    offset: 0
                  ) {
                    book {
                      title
                      contributions {
                        author {
                          name
                        }
                      }
                      id
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
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Error fetching data from Hardcover API: {e}")
            raise
        data = response.json()
        if "errors" in data:
            logger.error(f"GraphQL errors: {data['errors']}")
            raise Exception(f"GraphQL errors: {data['errors']}")
        logger.debug(f"Data fetched successfully: {data}")
        return data

    def get_books(self) -> list:
        books = []
        data = self.fetch_data()
        books.extend(data["data"]["user_books"])
        if len(books) > 0:
            logger.debug(
                f"Books extracted: {[book['book']['title'] for book in books]}"
            )
        else:
            logger.warning("No books found for this user.")
        return books
