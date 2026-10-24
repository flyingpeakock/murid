import json

import pytest

from murid.clients.calibre import Calibre, CalibreConfig, CalibreError
from murid.domain.book import Book
from murid.domain.book_matcher import BookMatcher


class Result:
    def __init__(self, stdout=None):
        self.stdout = stdout or ""


def test_init_success(tmp_path):
    db = tmp_path

    calibre = Calibre(
        CalibreConfig(
            executable="calibredb",
            library=str(db),
        ),
        run=lambda *args, **kwargs: None,
    )

    assert calibre.config.library == str(db)


@pytest.mark.parametrize("library", ["/books", "https://localhost:8080/#books"])
def test_calibredb_uses_library_for_path_or_url(library):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return Result()

    calibre = Calibre(CalibreConfig(executable="calibredb", library=library), run=fake_run)
    calibre._calibredb("list")

    assert calls[-1][:4] == ["calibredb", "--with-library", library, "list"]


def test_missing_executable(tmp_path):
    db = tmp_path

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("calibredb not found")

    with pytest.raises(CalibreError, match="Calibre executable not found"):
        Calibre(CalibreConfig(executable="calibredb", library=str(db)), run=fake_run)


def test_contains_book_uses_match_rules_not_score_alone(tmp_path):
    calibre = Calibre(
        CalibreConfig(executable="calibredb", library=str(tmp_path)),
        run=lambda *args, **kwargs: Result(
            '[{"id": 1, "title": "Dune", "authors": "Someone Else", "isbn": ""'
            ', "formats": ["/library/book.epub"]}]'
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
            library=str(db),
        ),
        run=lambda *a, **k: Result("[]"),
    )

    books = calibre.get_books()

    assert books == set()


@pytest.mark.parametrize("formats", [[], None])
def test_metadata_only_record_does_not_count_as_present(tmp_path, formats):
    record = {
        "id": 1,
        "title": "Dune",
        "authors": "Frank Herbert",
        "identifiers": {"hardcover": "42"},
        "formats": formats,
    }
    calibre = Calibre(
        CalibreConfig("calibredb", str(tmp_path)),
        run=lambda *args, **kwargs: Result(json.dumps([record])),
    )
    requested = Book("Dune", ["Frank Herbert"], 42, [], "hardcover")

    assert calibre.get_books() == set()
    assert not calibre.contains_book(requested, BookMatcher())


def test_get_books_single(tmp_path):
    db = tmp_path

    calibre = Calibre(
        CalibreConfig(
            executable="calibredb",
            library=str(db),
        ),
        run=lambda *args, **kwargs: Result(
            '[{"id": 1, "title": "Dune", "authors": "Frank Herbert", "isbn": "1234567890"'
            ', "formats": ["/library/book.epub"]}]'
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
            '"series": "Dune", "series_index": "1.5"'
            ', "formats": ["/library/book.epub"]}]'
        )

    calibre = Calibre(
        CalibreConfig(executable="calibredb", library=str(tmp_path)),
        run=fake_run,
    )

    book = next(iter(calibre.get_books()))

    assert book.series == "Dune"
    assert book.series_number == 1.5
    assert book.identifiers == {"goodreads": "12345", "amazon": "B012345678"}
    assert calls[-1][0][-1] == "id,title,authors,isbn,identifiers,series,series_index,formats"


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
        CalibreConfig(executable="calibredb", library=str(tmp_path)),
        run=lambda *args, **kwargs: Result(
            '[{"id": 14, "title": "A Memory of Light", '
            f'"authors": "{calibre_authors}", "isbn": "", '
            '"series": "The Wheel of Time", "series_index": 14'
            ', "formats": ["/library/book.epub"]}]'
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
            CalibreConfig(executable="calibredb", library=str(db)),
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
            library=str(db),
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
        "--automerge",
        "ignore",
        "--identifier",
        "isbn:9780441172719",
        "/tmp/dune.epub",
    ]


def test_add_book_refuses_directory_import(tmp_path):
    calls = []
    directory = tmp_path / "book-pack"
    directory.mkdir()

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return Result()

    calibre = Calibre(
        CalibreConfig(executable="calibredb", library=str(tmp_path)),
        run=fake_run,
    )
    book = Book(
        id=1,
        title="Dune",
        authors=["Frank Herbert"],
        isbn=[],
        source="test",
    )

    with pytest.raises(CalibreError, match="Refusing to add directory"):
        calibre.add_book(book, str(directory))

    assert len(calls) == 1  # Only the validation command ran.


@pytest.mark.parametrize(
    ("authors", "serialized"),
    [
        (["Neil Gaiman", "Terry Pratchett"], "Neil Gaiman & Terry Pratchett"),
        (["Alice & Bob", "Pratchett, Terry"], "Alice && Bob & Pratchett, Terry"),
    ],
)
def test_add_book_multiple_authors(tmp_path, authors, serialized):
    db = tmp_path

    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return Result()

    calibre = Calibre(
        CalibreConfig(library=str(db), executable="calibredb"),
        run=fake_run,
    )

    book = Book(
        id=1,
        title="Good Omens",
        authors=authors,
        isbn=[],
        source="calibre",
    )

    calibre.add_book(book, "/tmp/book.epub")

    args, _ = calls[1]

    assert "--authors" in args[0]

    idx = args[0].index("--authors")
    assert args[0][idx + 1] == serialized


def test_get_books_preserves_author_boundaries_and_literal_ampersands(tmp_path):
    record = {
        "id": 1,
        "title": "Good Omens",
        "authors": "Alice && Bob & Pratchett, Terry",
        "formats": ["/library/book.epub"],
    }
    calibre = Calibre(
        CalibreConfig("calibredb", str(tmp_path)),
        run=lambda *args, **kwargs: Result(json.dumps([record])),
    )

    assert next(iter(calibre.get_books())).authors == ["Alice & Bob", "Pratchett, Terry"]


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
            library=str(db),
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
            library=str(db),
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
            library=str(db),
        ),
        run=lambda *args, **kwargs: Result(
            '[{"id": 1, "title": "Dune", "authors": "Frank Herbert", "isbn": "1234567890"'
            ', "formats": ["/library/book.epub"]}]\nextra'
        ),
    )

    books = calibre.get_books()

    assert len(books) == 1
    assert "Extra data after JSON response: 'extra'" in caplog.text


def test_import_preserves_source_identifiers_and_unnumbered_series(tmp_path):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return Result()

    calibre = Calibre(CalibreConfig("calibredb", str(tmp_path)), run=run)
    book = Book(
        title="Dune",
        authors=["Frank Herbert"],
        id=123,
        source="hardcover",
        isbn=[None, "invalid", "0-441-17271-7", "9780441013593"],
        identifiers={"Goodreads": ["", "234", "567"], "Amazon": "B0AbCd1234"},
        series="Dune",
    )
    calibre.add_book(book, "/tmp/dune.epub")
    command = calls[-1]
    ids = [command[i + 1] for i, arg in enumerate(command) if arg == "--identifier"]
    assert ids == ["goodreads:234", "amazon:B0AbCd1234", "isbn:9780441172719", "hardcover:123"]
    assert command[command.index("--series") + 1] == "Dune"
    assert "--series-index" not in command
    book.series_number = 0
    calibre.add_book(book, "/tmp/dune.epub")
    assert calls[-1][calls[-1].index("--series-index") + 1] == "0"


@pytest.mark.parametrize("operation", ["validate", "list", "add"])
def test_command_timeout_is_bounded_and_reported(operation, tmp_path):
    import subprocess

    def run(command, **kwargs):
        assert kwargs["timeout"] == 7
        if operation == "validate" or "--version" not in command:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return Result()

    config = CalibreConfig("calibredb", str(tmp_path), command_timeout_seconds=7)
    with pytest.raises(CalibreError, match="timed out after 7 seconds"):
        calibre = Calibre(config, run=run)
        if operation == "list":
            calibre.get_books()
        elif operation == "add":
            calibre.add_book(Book("Dune", ["Frank Herbert"], 1, [], "test"), "/book.epub")
