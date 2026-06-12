import logging
import os
import sqlite3
import subprocess

from .harvester import Book

logger = logging.getLogger("HardcoverHarvester")


class CalibreError(Exception):
    pass


class Calibre:
    def __init__(self, db_path: str, db_executable: str = "calibredb") -> None:
        self.db_path = db_path
        self.db_executable = db_executable
        self.library_path = os.path.dirname(db_path)
        self.validate()

    def validate(self) -> None:
        try:
            subprocess.run(
                [self.db_executable, "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as e:
            logger.error(f"Calibre executable not found: {self.db_executable}")
            raise CalibreError(f"Calibre executable not found: {self.db_executable}") from e
        except Exception as e:
            logger.error(f"Error checking Calibre executable: {e}")
            raise CalibreError(f"Error checking Calibre executable: {e}") from e

        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            conn.close()
        except Exception as e:
            logger.error(f"Error connecting to Calibre database: {e}")
            raise CalibreError(f"Error connecting to Calibre database: {e}") from e

    def get_books(self) -> list[Book]:
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
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
        return [
            Book(
                id=row["id"],
                title=row["title"],
                # authors=row["authors"],
                authors=[a.strip() for a in row["authors"].split(",")] if row["authors"] else [],
                isbn=row["isbn"],
            )
            for row in rows
        ]
