"""Module for interacting with a Calibre library database."""

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass

from ..domain.book import Book
from ..domain.book_matcher import BookMatcher
from ..libraries.library import LibraryError

logger = logging.getLogger("murid")


class CalibreError(LibraryError):
    """Custom exception for Calibre-related errors."""


@dataclass
class CalibreConfig:
    """Configuration for the Calibre client."""

    executable: str
    library: str
    server_username: str | None = None
    server_password: str | None = None
    command_timeout_seconds: int = 120


class Calibre:
    """Class for interacting with a Calibre library database."""

    def __init__(self, config: CalibreConfig, run=subprocess.run) -> None:
        """Initialize the Calibre client."""
        self.config = config
        self.run = run
        self.validate()

    def validate(self) -> None:
        """Validate that the Calibre executable is available and that the database is accessible."""
        try:
            self.run(
                [self.config.executable, "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                timeout=self.config.command_timeout_seconds,
            )
        except subprocess.TimeoutExpired as e:
            raise CalibreError(
                f"Calibre command timed out after {self.config.command_timeout_seconds} seconds"
            ) from e
        except FileNotFoundError as e:
            raise CalibreError(f"Calibre executable not found: {self.config.executable}") from e
        except subprocess.CalledProcessError as e:
            raise CalibreError(f"Error running Calibre executable: {e}") from e

    def get_books(self) -> set[Book]:
        """Retrieve a list of books from the Calibre database."""
        try:
            stdout = self._calibredb(
                "list",
                "--for-machine",
                "--fields",
                "id,title,authors,isbn,identifiers,series,series_index",
            )
        except subprocess.CalledProcessError as e:
            raise CalibreError(f"Error retrieving books from Calibre server: {e.stderr}") from e

        try:
            data, idx = json.JSONDecoder().raw_decode(stdout)
        except json.JSONDecodeError as e:
            logger.debug(
                "Calibre returned invalid JSON (%d characters); tail=%r; at error position=%r",
                len(stdout),
                stdout[-500:],
                stdout[e.pos : e.pos + 500],
            )
            raise CalibreError(f"Error decoding JSON response from Calibre: {e}") from e

        extra_data = stdout[idx:].strip()
        if extra_data:
            logger.debug("Extra data after JSON response: %r", extra_data)

        books = set()
        for book in data:
            identifiers = book.get("identifiers") or {}
            if not isinstance(identifiers, dict):
                identifiers = {}

            series_number = book.get("series_index")
            try:
                series_number = float(series_number) if series_number is not None else None
            except (TypeError, ValueError):
                series_number = None

            books.add(
                Book(
                    id=book["id"],
                    title=book["title"],
                    authors=[
                        author.strip()
                        for author in re.split(
                            r"\s*(?:,|&)\s*|\s+(?:and|with)\s+",
                            book.get("authors") or "",
                            flags=re.IGNORECASE,
                        )
                        if author.strip()
                    ],
                    isbn=[book.get("isbn")] if book.get("isbn") else [],
                    source="calibre",
                    series=book.get("series") or None,
                    series_number=series_number,
                    identifiers={
                        str(name): str(value)
                        for name, value in identifiers.items()
                        if name and value
                    },
                )
            )
        logger.debug(
            "Loaded %d Calibre books (%d with identifiers, %d with series metadata)",
            len(books),
            sum(bool(book.identifiers) for book in books),
            sum(bool(book.series) for book in books),
        )
        return books

    def add_book(self, book: Book, path: str) -> None:
        """Add a book to the Calibre library using the calibredb command-line tool."""
        if os.path.isdir(path):
            raise CalibreError(
                f"Refusing to add directory '{path}'; select an individual ebook file instead."
            )

        args = ["add", "--title", book.title, "--authors", ", ".join(book.authors)]

        for name, value in self._import_identifiers(book).items():
            args.extend(["--identifier", f"{name}:{value}"])

        if book.series:
            args.extend(["--series", book.series])
        if book.series and book.series_number is not None:
            args.extend(
                [
                    "--series-index",
                    str(book.series_number),
                ]
            )

        args.append(path)
        try:
            self._calibredb(*args)
        except subprocess.CalledProcessError as e:
            raise CalibreError(f"Error adding book to Calibre: {e.stderr}") from e
        except Exception as e:
            raise CalibreError(f"Error adding book to Calibre: {e}") from e

    @staticmethod
    def _import_identifiers(book: Book) -> dict[str, str]:
        """Calibre stores one value per type; preserve the first usable source ID."""
        identifiers = {}
        for platform, values in book.identifiers.items():
            name = BookMatcher.normalize_identifier_platform(platform)
            if not name or ":" in name:
                continue
            if isinstance(values, str):
                values = [values]
            for value in values:
                if value is not None and str(value).strip():
                    identifiers.setdefault(name, str(value).strip())
                    break
        for isbn in book.isbn:
            if normalized := BookMatcher.normalize_isbn(isbn):
                identifiers["isbn"] = normalized
                break
        if book.source == "hardcover":
            identifiers["hardcover"] = str(book.id)
        return identifiers

    def contains_book(self, book: Book, matcher) -> bool:
        """Check if a book already exists in the Calibre library using the provided matcher."""
        existing_books = self.get_books()
        if any(matcher.is_match(book, candidate) for candidate in existing_books):
            return True

        _, score = matcher.best_match(book, existing_books)
        logger.debug("%s: not in Calibre; best match score: %.3f", book, score)
        return False

    def _calibredb(self, *args: str) -> str:
        """Run the calibredb command with the given arguments."""
        command = [
            self.config.executable,
            "--with-library",
            self.config.library,
        ]

        if self.config.server_username:
            command.extend(["--username", self.config.server_username])
        if self.config.server_password:
            command.extend(["--password", "<stdin>"])
        command.extend(args)

        logger.debug("Running command: %s", " ".join(command))

        password = f"{self.config.server_password}\n" if self.config.server_password else None

        try:
            return self.run(
                command,
                input=password,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                timeout=self.config.command_timeout_seconds,
            ).stdout
        except subprocess.TimeoutExpired as e:
            raise CalibreError(
                f"Calibre command timed out after {self.config.command_timeout_seconds} seconds"
            ) from e
