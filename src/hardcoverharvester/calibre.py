import logging
import os
import sqlite3
import subprocess

from . import Book

logger = logging.getLogger("HardcoverHarvester")


class CalibreError(Exception):
    pass


class Calibre:
    def __init__(
        self,
        db_path: str,
        db_executable: str = "calibredb",
        run=subprocess.run,
        connect=sqlite3.connect,
    ) -> None:
        self.db_path = db_path
        self.db_executable = db_executable
        self.library_path = os.path.dirname(db_path)
        self.run = run
        self.connect = connect
        self.validate()

    def validate(self) -> None:
        try:
            self.run(
                [self.db_executable, "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as e:
            logger.error(f"Calibre executable not found: {self.db_executable}")
            raise CalibreError(f"Calibre executable not found: {self.db_executable}") from e

        try:
            conn = self.connect(f"file:{self.db_path}?mode=ro", uri=True)
            conn.close()
        except Exception as e:
            logger.error(f"Error connecting to Calibre database: {e}")
            raise CalibreError(f"Error connecting to Calibre database: {e}") from e

    def get_books(self) -> list[Book]:
        try:
            conn = self.connect(f"file:{self.db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
        except Exception as e:
            logger.error(f"Error connecting to Calibre database: {e}")
            raise CalibreError(f"Error connecting to Calibre database: {e}") from e
        cursor = conn.cursor()
        query = """
            SELECT
                b.id,
                b.title,
                GROUP_CONCAT(a.name, ', ') AS authors,
                i.val AS isbn
            FROM books b
            LEFT JOIN books_authors_link bal
                ON b.id = bal.book
            LEFT JOIN authors a
                ON bal.author = a.id
            LEFT JOIN identifiers i
                ON b.id = i.book
                AND i.type = 'isbn'
            GROUP BY b.id
            ORDER BY b.title;
        """
        try:
            cursor.execute(query)
        except Exception as e:
            logger.error(f"Error executing query on Calibre database: {e}")
            raise

        rows = cursor.fetchall()
        conn.close()
        books = [
            Book(
                id=row["id"],
                title=row["title"],
                # authors=row["authors"],
                authors=[a.strip() for a in row["authors"].split(",")] if row["authors"] else [],
                isbn=[row["isbn"]],
                source="calibre",
            )
            for row in rows
        ]
        return books

    def add_book(self, book: Book, path: str) -> None:
        args = [
            self.db_executable,
            "add",
            "--with-library",
            self.library_path,
            "--title",
            f'"{book.title}"',
            "--authors",
            f'"{", ".join(book.authors)}"',
            path,
        ]

        if os.path.isdir(path):
            args.extend(["--recurse", "--one-book-per-directory"])

        try:
            logger.debug(f"Running command: {' '.join(args)}")
            self.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except Exception as e:
            logger.error(f"Error adding book to Calibre: {e}")
            raise CalibreError(f"Error adding book to Calibre: {e}") from e

    def contains_book(self, book: Book, matcher) -> bool:
        existing_books = self.get_books()
        best_match, score = matcher.best_match(book, existing_books)
        if best_match and score >= matcher.threshold:
            return True
        else:
            logger.debug(f"Book {book} does not exist in Calibre. Best similarity: {score:.2f}")
            return False
