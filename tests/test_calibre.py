import sqlite3
from pathlib import Path

import pytest

from hardcoverharvester.calibre import Calibre, CalibreError


def create_db(path: Path):
    conn = sqlite3.connect(path)
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE books (
            id INTEGER PRIMARY KEY,
            title TEXT
        );

        CREATE TABLE authors (
            id INTEGER PRIMARY KEY,
            name TEXT
        );

        CREATE TABLE books_authors_link (
            book INTEGER,
            author INTEGER
        );

        CREATE TABLE identifiers (
            book INTEGER,
            type TEXT,
            val TEXT
        );
    """)

    conn.commit()
    conn.close()


def test_init_success(tmp_path):
    db = tmp_path / "calibre.db"
    create_db(db)

    calibre = Calibre(
        str(db),
        run=lambda *args, **kwargs: None,
    )

    assert calibre.db_path == str(db)
    assert Path(calibre.library_path) == tmp_path


def test_missing_executable(tmp_path):
    db = tmp_path / "calibre.db"
    create_db(db)

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("calibredb not found")

    with pytest.raises(CalibreError, match="Calibre executable not found"):
        Calibre(str(db), run=fake_run)


def test_invalid_db_path(tmp_path):
    db = tmp_path / "missing.db"

    with pytest.raises(CalibreError, match="Error connecting to Calibre database"):
        Calibre(str(db), run=lambda *a, **k: None)


def test_get_books_empty(tmp_path):
    db = tmp_path / "calibre.db"
    create_db(db)

    calibre = Calibre(
        str(db),
        run=lambda *a, **k: None,
    )

    books = calibre.get_books()

    assert books == []


def test_get_books_single(tmp_path):
    db = tmp_path / "calibre.db"
    create_db(db)

    conn = sqlite3.connect(db)
    cur = conn.cursor()

    cur.executescript("""
        INSERT INTO books VALUES (1, 'Dune');
        INSERT INTO authors VALUES (1, 'Frank Herbert');
        INSERT INTO books_authors_link VALUES (1, 1);
        INSERT INTO identifiers VALUES (1, 'isbn', '1234567890');
    """)

    conn.commit()
    conn.close()

    calibre = Calibre(
        str(db),
        run=lambda *a, **k: None,
    )

    books = calibre.get_books()

    assert len(books) == 1
    assert books[0].id == 1
    assert books[0].title == "Dune"
    assert books[0].authors == ["Frank Herbert"]
    assert books[0].isbn == "1234567890"


def test_multiple_authors(tmp_path):
    db = tmp_path / "calibre.db"
    create_db(db)

    conn = sqlite3.connect(db)
    cur = conn.cursor()

    cur.executescript("""
        INSERT INTO books VALUES (1, 'Book');
        INSERT INTO authors VALUES (1, 'A1');
        INSERT INTO authors VALUES (2, 'A2');
        INSERT INTO books_authors_link VALUES (1, 1);
        INSERT INTO books_authors_link VALUES (1, 2);
    """)

    conn.commit()
    conn.close()

    calibre = Calibre(
        str(db),
        run=lambda *a, **k: None,
    )

    books = calibre.get_books()

    assert books[0].authors == ["A1", "A2"]


def test_run_failure(tmp_path):
    db = tmp_path / "calibre.db"
    create_db(db)

    def boom(*args, **kwargs):
        raise FileNotFoundError()

    with pytest.raises(CalibreError):
        Calibre(str(db), run=boom)
