"""Module for interacting with the Hardcover API to fetch user book data."""

import logging
from dataclasses import dataclass

import pycountry
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

    # These familiar names differ from pycountry's qualified ISO language names.
    _LANGUAGE_NAME_ALIASES = {"greek": "el", "malay": "ms"}

    def __init__(
        self,
        api: str,
        user: HardcoverUser | None = None,
        lang_codes: list[str] | None = None,
        list_slug: str = "want-to-read",
    ) -> None:
        """Initialize the Hardcover class with the API token and user ID."""
        self.url = "https://api.hardcover.app/v1/graphql"
        self.lang_codes = lang_codes
        self.list_slug = list_slug
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
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                raise HardcoverError(f"GraphQL errors: {data['errors']}")

            return data
        except requests.RequestException as e:
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

    _BOOK_FIELDS = """
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
                language {
                  language
                }
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
    """

    def fetch_data(self) -> dict:
        """Fetch book data from the Hardcover API for the specified user."""
        logger.debug("Fetching Hardcover list %s for %s", self.list_slug, self.user.name)
        if self.list_slug != "want-to-read":
            return self._fetch_list_data()

        query = """
        query GetUserBooks($user_id: Int!) {
          user_books(
              where: { user_id: { _eq: $user_id }, status_id: { _eq: 1 } }
            distinct_on: book_id
          ) {
            book {
              BOOK_FIELDS
            }
          }
        }
        """
        query = query.replace("BOOK_FIELDS", self._BOOK_FIELDS)
        variables = {"user_id": self.user.id}
        data = self.make_query(query, variables=variables)
        logger.debug("Hardcover data fetched successfully")
        return data

    def _fetch_list_data(self) -> dict:
        """Fetch every page of a custom list owned by the configured user."""
        query = """
        query GetListBooks($user_id: Int!, $slug: String!, $limit: Int!, $offset: Int!) {
          lists(where: {user_id: {_eq: $user_id}, slug: {_eq: $slug}}) {
            list_books(limit: $limit, offset: $offset, order_by: {id: asc}) {
              book {
                BOOK_FIELDS
              }
            }
          }
        }
        """.replace("BOOK_FIELDS", self._BOOK_FIELDS)
        items = []
        page_size = 100
        while True:
            data = self.make_query(
                query,
                variables={
                    "user_id": self.user.id,
                    "slug": self.list_slug,
                    "limit": page_size,
                    "offset": len(items),
                },
            )
            lists = data["data"]["lists"]
            if not lists:
                raise HardcoverError(
                    f"List '{self.list_slug}' was not found or is inaccessible for {self.user.name}"
                )
            page = lists[0]["list_books"]
            items.extend(page)
            if len(page) < page_size:
                return {"data": {"user_books": items}}

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

        return [
            isbn
            for edition in editions
            for isbn in (edition.get("isbn_13"), edition.get("isbn_10"))
            if isbn
        ]

    @classmethod
    def _extract_text_values(cls, value, lang_codes: list[str] | None = None) -> list[str]:
        """Extract title strings from Hardcover's JSON alternative-title fields."""
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, list):
            return [
                text
                for item in value
                for text in cls._extract_text_values(item, lang_codes=lang_codes)
            ]
        if isinstance(value, dict):
            if lang_codes is not None and "language" in value:
                language_matches = cls._language_value_matches(value["language"], lang_codes)
                if language_matches is False:
                    return []
            language_keys = [key for key in value if cls._is_language_tag(key)]
            if language_keys:
                return [
                    text
                    for key, item in value.items()
                    if key in language_keys
                    and (
                        lang_codes is None
                        or cls._language_tag_matches(key, lang_codes) is not False
                    )
                    for text in cls._extract_text_values(item, lang_codes=lang_codes)
                ]
            preferred = [
                value[key] for key in ("title", "name", "alternative_title") if key in value
            ]
            values = preferred if preferred else list(value.values())
            return [
                text
                for item in values
                for text in cls._extract_text_values(item, lang_codes=lang_codes)
            ]
        return []

    @classmethod
    def _extract_alternative_titles(
        cls,
        book: dict,
        editions: list[dict],
        lang_codes: list[str] | None = None,
    ) -> list[str]:
        """Collect book and edition titles that can name the same work."""
        titles = []
        if book.get("subtitle"):
            titles.append(f"{book.get('title', '')}: {book['subtitle']}")
        titles.extend(cls._extract_text_values(book.get("alternative_titles"), lang_codes))

        for edition in editions:
            if (
                lang_codes is not None
                and edition.get("language")
                and cls._language_value_matches(edition["language"], lang_codes) is False
            ):
                continue

            title = edition.get("title")
            subtitle = edition.get("subtitle")
            if title and subtitle:
                titles.append(f"{title}: {subtitle}")
            elif title:
                titles.append(title)
            titles.extend(cls._extract_text_values(edition.get("alternative_titles"), lang_codes))

        primary_title = book.get("title")
        return list(dict.fromkeys(title for title in titles if title and title != primary_title))

    @staticmethod
    def _is_language_tag(value) -> bool:
        """Return whether a key looks like a BCP 47 locale or ISO language code."""
        if not isinstance(value, str):
            return False
        parts = value.replace("_", "-").split("-")
        return (
            len(parts[0]) in (2, 3)
            and parts[0].isalpha()
            and all(part.isalnum() and 2 <= len(part) <= 8 for part in parts[1:])
        )

    @classmethod
    def _language_tag_matches(cls, language_tag: str, lang_codes: list[str]) -> bool | None:
        """Match language names and locale tags against configured ISO 639 codes."""
        language = language_tag.strip().lower()
        language = cls._LANGUAGE_NAME_ALIASES.get(language, language)
        if cls._is_language_tag(language):
            language = language.replace("_", "-").split("-", maxsplit=1)[0]
        configured = {code.strip().upper() for code in lang_codes}
        if language.upper() in configured:
            return True
        # Prefer codes: "en" is also the name of a different language in ISO 639.
        entry = (
            pycountry.languages.get(alpha_2=language)
            or pycountry.languages.get(alpha_3=language)
            or pycountry.languages.get(bibliographic=language)
        )
        if entry is None:
            try:
                entry = pycountry.languages.lookup(language)
            except LookupError:
                return None
        aliases = {
            code.upper()
            for field in ("alpha_2", "alpha_3", "bibliographic")
            if (code := getattr(entry, field, None))
        }
        return bool(aliases & configured)

    @classmethod
    def _language_value_matches(cls, value, lang_codes: list[str]) -> bool | None:
        """Match a Hardcover edition language name or code to configured language codes."""
        if isinstance(value, dict):
            value = value.get("language")
        if not isinstance(value, str):
            return None
        return cls._language_tag_matches(value, lang_codes)

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

        return identifiers

    def get_books(self) -> set[Book]:
        """Fetch the user's selected list as a set of Book objects."""
        try:
            data = self.fetch_data()
            items = data.get("data", {}).get("user_books", [])
        except HardcoverError as error:
            raise HardcoverError(f"Cannot fetch books for {self.user.name}: {error}") from error

        books = {self._book(item.get("book", {})) for item in items}

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

    def _book(self, book: dict) -> Book:
        """Map the same work metadata for list inspection and restart recovery."""
        authors = [
            c["author"]["name"] for c in (book.get("contributions") or []) if c.get("author")
        ]

        editions = book.get("editions") or []
        isbn = self._extract_isbn(editions)
        series, series_number = self._extract_series_info(book)
        return Book(
            id=book.get("id"),
            title=book.get("title"),
            authors=authors,
            isbn=isbn,
            source="hardcover",
            series=series,
            series_number=series_number,
            alternative_titles=self._extract_alternative_titles(book, editions),
            search_alternative_titles=(
                self._extract_alternative_titles(book, editions, self.lang_codes)
                if self.lang_codes is not None
                else None
            ),
            identifiers=self._extract_identifiers(book, editions),
        )

    def get_book(self, book_id: int) -> Book | None:
        """Recover a work by its persisted ID even after it leaves every reading list."""
        query = """
        query GetBook($book_id: Int!) {
          books(where: {id: {_eq: $book_id}}) { BOOK_FIELDS }
        }
        """.replace("BOOK_FIELDS", self._BOOK_FIELDS)
        books = self.make_query(query, variables={"book_id": book_id})["data"]["books"]
        if not isinstance(books, list) or len(books) > 1:
            raise HardcoverError("Hardcover returned an invalid work lookup")
        if not books:
            return None
        book = self._book(books[0])
        if book.id != book_id:
            raise HardcoverError("Hardcover returned an unexpected work identity")
        return book
