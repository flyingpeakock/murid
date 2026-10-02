import pytest

from murid import Book, Calibre, CalibreConfig, CalibreError


class Result:
    def __init__(self, stdout=None):
        self.stdout = stdout or ""


def test_init_success(tmp_path):
    db = tmp_path

    calibre = Calibre(
        CalibreConfig(
            executable="calibredb",
            library_path=str(db),
        ),
        run=lambda *args, **kwargs: None,
    )

    assert calibre.config.library_path == str(db)


def test_missing_executable(tmp_path):
    db = tmp_path

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("calibredb not found")

    with pytest.raises(CalibreError, match="Calibre executable not found"):
        Calibre(CalibreConfig(executable="calibredb", library_path=str(db)))


def test_get_books_empty(tmp_path):
    db = tmp_path

    calibre = Calibre(
        CalibreConfig(
            executable="calibredb",
            library_path=str(db),
        ),
        run=lambda *a, **k: Result("[]"),
    )

    books = calibre.get_books()

    assert books == set()


def test_get_books_single(tmp_path):
    db = tmp_path

    calibre = Calibre(
        CalibreConfig(
            executable="calibredb",
            library_path=str(db),
        ),
        run=lambda *args, **kwargs: Result(
            '[{"id": 1, "title": "Dune", "authors": "Frank Herbert", "isbn": "1234567890"}]'
        ),
    )

    books = calibre.get_books()

    book = next(iter(books))
    assert book.id == 1
    assert book.title == "Dune"
    assert book.authors == ["Frank Herbert"]
    assert book.isbn == ["1234567890"]


def test_run_failure(tmp_path):
    db = tmp_path

    def boom(*args, **kwargs):
        raise FileNotFoundError()

    with pytest.raises(CalibreError):
        Calibre(
            CalibreConfig(executable="calibredb", library_path=str(db)),
            run=boom,
        )


def test_add_book(tmp_path):
    db = tmp_path

    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return Result()

    calibre = Calibre(
        CalibreConfig(
            executable="calibredb",
            library_path=str(db),
        ),
        run=fake_run,
    )

    book = Book(
        id=1,
        title="Dune",
        authors=["Frank Herbert"],
        isbn=["9780441172719"],
        source="calibre",
    )

    calibre.add_book(book, "/tmp/dune.epub")

    assert len(calls) == 2

    args, kwargs = calls[1]  # first call is validate()

    assert args[0] == [
        "calibredb",
        "--with-library",
        str(tmp_path),
        "add",
        "--title",
        "Dune",
        "--authors",
        "Frank Herbert",
        "/tmp/dune.epub",
    ]


def test_add_book_multiple_authors(tmp_path):
    db = tmp_path

    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return Result()

    calibre = Calibre(
        CalibreConfig(library_path=str(db), executable="calibredb"),
        run=fake_run,
    )

    book = Book(
        id=1,
        title="Good Omens",
        authors=["Neil Gaiman", "Terry Pratchett"],
        isbn=[],
        source="calibre",
    )

    calibre.add_book(book, "/tmp/book.epub")

    args, _ = calls[1]

    assert "--authors" in args[0]

    idx = args[0].index("--authors")
    assert args[0][idx + 1] == "Neil Gaiman, Terry Pratchett"


def test_add_book_failure(tmp_path):
    db = tmp_path

    call_count = 0

    def fake_run(*args, **kwargs):
        nonlocal call_count
        call_count += 1

        # validate() succeeds
        if call_count == 1:
            return

        raise RuntimeError("boom")

    calibre = Calibre(
        CalibreConfig(
            executable="calibredb",
            library_path=str(db),
        ),
        run=fake_run,
    )

    book = Book(
        id=1,
        title="Dune",
        authors=["Frank Herbert"],
        isbn=[],
        source="calibre",
    )

    with pytest.raises(
        CalibreError,
        match="Error adding book to Calibre",
    ):
        calibre.add_book(book, "/tmp/dune.epub")


def test_password_is_via_stdin(tmp_path):
    db = tmp_path

    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return Result()

    calibre = Calibre(
        CalibreConfig(
            executable="calibredb",
            library_path=str(db),
            server_password="secret",
        ),
        run=fake_run,
    )

    calibre._calibredb()

    args, kwargs = calls[1]  # first call is validate()

    assert kwargs["input"] == "secret\n"
    assert "secret" not in args[0]  # password should not be in command-line arguments
    assert "<stdin>" in args[0]  # password should be indicated as coming from stdin
