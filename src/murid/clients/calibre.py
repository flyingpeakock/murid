"""Module for interacting with a Calibre library database."""

import json
import logging
import os
import subprocess
from dataclasses import dataclass

from ..domain.book import Book

logger = logging.getLogger("murid")


class CalibreError(Exception):
    """Custom exception for Calibre-related errors."""


@dataclass
class CalibreConfig:
    """Configuration for the Calibre client."""

    executable: str
    library_path: str | None = None
    server_url: str | None = None
    server_username: str | None = None
    server_password: str | None = None


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
            )
        except FileNotFoundError as e:
            logger.error("Calibre executable not found: %s", self.config.executable)
            raise CalibreError(f"Calibre executable not found: {self.config.executable}") from e
        except subprocess.CalledProcessError as e:
            logger.error("Error running Calibre executable: %s", e)
            raise CalibreError(f"Error running Calibre executable: {e}") from e

    def get_books(self) -> set[Book]:
        """Retrieve a list of books from the Calibre database."""
        args = self._calibredb_args(
            "list",
            "--for-machine",
            "--fields",
            "id,title,authors,isbn",
        )
        try:
            response = self.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            logger.error("Error retrieving books from Calibre server: %s", e.stderr)
            raise CalibreError(f"Error retrieving books from Calibre server: {e.stderr}") from e

        try:
            data = json.loads(response.stdout)
        except json.JSONDecodeError as e:
            logger.error("JSON error: %s", e)
            logger.error("stdout length: %d", len(response.stdout))
            logger.error("stdout tail: %r", response.stdout[-500:])
            logger.error("at error position: %r", response.stdout[e.pos : e.pos + 500])
            raise CalibreError(f"Error decoding JSON response from Calibre: {e}") from e
        books = {
            Book(
                id=book["id"],
                title=book["title"],
                authors=[a.strip() for a in book["authors"].split(",")] if book["authors"] else [],
                isbn=[book.get("isbn")] if book.get("isbn") else [],
                source="calibre",
            )
            for book in data
        }
        return books

    def add_book(self, book: Book, path: str) -> None:
        """Add a book to the Calibre library using the calibredb command-line tool."""
        args = self._calibredb_args(
            "add", "--title", book.title, "--authors", ", ".join(book.authors)
        )

        if os.path.isdir(path):
            args.extend(["--recurse", "--one-book-per-directory"])

        if book.series and book.series_number:
            args.extend(
                [
                    "--series",
                    book.series,
                    "--series-index",
                    str(book.series_number),
                ]
            )

        args.append(path)
        try:
            logger.debug("Running command: %s", " ".join(args))
            stdout = self.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            ).stdout
            logger.debug("Calibre output: %s", stdout)
        except subprocess.CalledProcessError as e:
            logger.error("Error adding book to Calibre: %s", e.stderr)
            raise CalibreError(f"Error adding book to Calibre: {e.stderr}") from e
        except Exception as e:
            logger.error("Error adding book to Calibre: %s", e)
            raise CalibreError(f"Error adding book to Calibre: {e}") from e

    def contains_book(self, book: Book, matcher) -> bool:
        """Check if a book already exists in the Calibre library using the provided matcher."""
        existing_books = self.get_books()
        best_match, score = matcher.best_match(book, existing_books)
        if best_match and score >= matcher.threshold:
            return True
        logger.debug("Book %s does not exist in Calibre. Best similarity: %.2f", book, score)
        return False

    def _calibredb_args(self, *args: str) -> list[str]:
        """Construct the command-line arguments for calibredb."""
        if self.config.library_path:
            library = self.config.library_path
        elif self.config.server_url:
            library = self.config.server_url
        else:
            raise CalibreError(
                "Calibre requires either a library path or a server URL to be specified."
            )

        command = [
            self.config.executable,
            "--with-library",
            library,
        ]

        if self.config.server_username:
            command.extend(["--username", self.config.server_username])
        if self.config.server_password:
            command.extend(["--password", self.config.server_password])
        command.extend(args)
        return command
