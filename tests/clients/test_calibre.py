import pytest

from murid import Book, BookMatcher, Calibre, CalibreConfig, CalibreError


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
        Calibre(CalibreConfig(executable="calibredb", library_path=str(db)), run=fake_run)


def test_contains_book_uses_match_rules_not_score_alone(tmp_path):
    calibre = Calibre(
        CalibreConfig(executable="calibredb", library_path=str(tmp_path)),
        run=lambda *args, **kwargs: Result(
            '[{"id": 1, "title": "Dune", "authors": "Someone Else", "isbn": ""}]'
        ),
    )
    requested = Book(
        id=2,
        title="Dune",
        authors=["Frank Herbert"],
        isbn=[],
        source="hardcover",
    )

    assert not calibre.contains_book(requested, BookMatcher(threshold=0.7))


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


def test_get_books_includes_series_and_external_identifiers(tmp_path):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args)
        return Result(
            '[{"id": 2, "title": "Dune", "authors": "Frank Herbert", "isbn": "", '
            '"identifiers": {"goodreads": "12345", "amazon": "B012345678"}, '
            '"series": "Dune", "series_index": "1.5"}]'
        )

    calibre = Calibre(
        CalibreConfig(executable="calibredb", library_path=str(tmp_path)),
        run=fake_run,
    )

    book = next(iter(calibre.get_books()))

    assert book.series == "Dune"
    assert book.series_number == 1.5
    assert book.identifiers == {"goodreads": "12345", "amazon": "B012345678"}
    assert calls[-1][0][-1] == "id,title,authors,isbn,identifiers,series,series_index"


@pytest.mark.parametrize(
    "calibre_authors",
    [
        "Robert Jordan & Brandon Sanderson",
        "Robert Jordan and Brandon Sanderson",
        "Robert Jordan with Brandon Sanderson",
    ],
)
def test_contains_book_matches_joined_calibre_authors(tmp_path, calibre_authors):
    calibre = Calibre(
        CalibreConfig(executable="calibredb", library_path=str(tmp_path)),
        run=lambda *args, **kwargs: Result(
            '[{"id": 14, "title": "A Memory of Light", '
            f'"authors": "{calibre_authors}", "isbn": "", '
            '"series": "The Wheel of Time", "series_index": 14}]'
        ),
    )
    hardcover_book = Book(
        id=101,
        title="A Memory of Light",
        authors=["Brandon Sanderson", "Robert Jordan"],
        isbn=[],
        source="hardcover",
        series="Wheel of Time",
        series_number=14,
    )

    calibre_book = next(iter(calibre.get_books()))

    assert calibre_book.authors == ["Robert Jordan", "Brandon Sanderson"]
    assert calibre.contains_book(hardcover_book, BookMatcher(threshold=0.7))


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


def test_get_books_extra_data(tmp_path, caplog):
    caplog.set_level("DEBUG")
    db = tmp_path

    calibre = Calibre(
        CalibreConfig(
            executable="calibredb",
            library_path=str(db),
        ),
        run=lambda *args, **kwargs: Result(
            '[{"id": 1, "title": "Dune", "authors": "Frank Herbert", "isbn": "1234567890"}]\nextra'
        ),
    )

    books = calibre.get_books()

    assert len(books) == 1
    assert "Extra data after JSON response: 'extra'" in caplog.text
