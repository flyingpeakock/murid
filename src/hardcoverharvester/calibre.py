import sqlite3
import logging

logger = logging.getLogger("HardcoverHarvester")


class Calibre:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def get_books(self) -> list[dict]:
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
        except Exception as e:
            logger.error(f"Error connecting to Calibre database: {e}")
            raise
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
            {
                "id": row["id"],
                "title": row["title"],
                "authors": row["authors"],
                "isbn": row["isbn"],
            }
            for row in rows
        ]
