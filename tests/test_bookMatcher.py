# tests/test_bookmatcher.py

from murid import Book
from murid.book_matcher import BookMatcher


def make_book(
    title="Dune",
    authors=None,
    isbn=None,
    id=1,
    source="test",
):
    return Book(
        id=id,
        title=title,
        authors=authors or ["Frank Herbert"],
        isbn=isbn or [],
        source=source,
    )


def test_normalize_lowercases():
    assert BookMatcher.normalize("DUNE") == "dune"


def test_normalize_removes_punctuation():
    assert BookMatcher.normalize("Dune!!!") == "dune"


def test_normalize_preserves_spaces():
    assert BookMatcher.normalize("Dune Messiah") == "dune messiah"


def test_normalize_trims_whitespace():
    assert BookMatcher.normalize("  Dune  ") == "dune"


def test_title_similarity_identical():
    matcher = BookMatcher()

    assert matcher.title_similarity("Dune", "Dune") == 1.0


def test_title_similarity_case_insensitive():
    matcher = BookMatcher()

    assert matcher.title_similarity("Dune", "dune") == 1.0


def test_title_similarity_different_titles():
    matcher = BookMatcher()

    assert matcher.title_similarity("Dune", "Foundation") < 0.5


def test_author_similarity_identical():
    matcher = BookMatcher()

    assert (
        matcher.author_similarity(
            ["Frank Herbert"],
            ["Frank Herbert"],
        )
        == 1.0
    )


def test_author_similarity_partial_overlap():
    matcher = BookMatcher()

    score = matcher.author_similarity(
        ["Author A", "Author B"],
        ["Author A"],
    )

    assert score == 0.5


def test_author_similarity_no_overlap():
    matcher = BookMatcher()

    assert (
        matcher.author_similarity(
            ["Author A"],
            ["Author B"],
        )
        == 0.0
    )


def test_author_similarity_empty():
    matcher = BookMatcher()

    assert matcher.author_similarity([], ["Author"]) == 0.0
    assert matcher.author_similarity(["Author"], []) == 0.0


def test_similarity_isbn_match_returns_one():
    matcher = BookMatcher()

    a = make_book(isbn=["123"])
    b = make_book(
        title="Completely Different",
        authors=["Someone Else"],
        isbn=["123"],
    )

    assert matcher.similarity(a, b) == 1.0


def test_similarity_similar_books():
    matcher = BookMatcher()

    a = make_book(
        title="Dune",
        authors=["Frank Herbert"],
    )

    b = make_book(
        title="Dune",
        authors=["Frank Herbert"],
    )

    assert matcher.similarity(a, b) == 1.0


def test_similarity_different_books():
    matcher = BookMatcher()

    a = make_book(
        title="Dune",
        authors=["Frank Herbert"],
    )

    b = make_book(
        title="Foundation",
        authors=["Isaac Asimov"],
    )

    assert matcher.similarity(a, b) < 0.5


def test_is_match_true():
    matcher = BookMatcher()

    a = make_book()
    b = make_book()

    assert matcher.is_match(a, b) is True


def test_is_match_false():
    matcher = BookMatcher()

    a = make_book(
        title="Dune",
        authors=["Frank Herbert"],
    )

    b = make_book(
        title="Foundation",
        authors=["Isaac Asimov"],
    )

    assert matcher.is_match(a, b) is False


def test_best_match_returns_best_candidate():
    matcher = BookMatcher()

    target = make_book(
        title="Dune",
        authors=["Frank Herbert"],
    )

    candidates = [
        make_book(
            id=2,
            title="Foundation",
            authors=["Isaac Asimov"],
        ),
        make_book(
            id=3,
            title="Dune",
            authors=["Frank Herbert"],
        ),
    ]

    match, score = matcher.best_match(target, candidates)

    assert match.id == 3
    assert score == 1.0


def test_best_match_empty_candidates():
    matcher = BookMatcher()

    match, score = matcher.best_match(
        make_book(),
        [],
    )

    assert match is None
    assert score == 0.0


def test_match_books():
    matcher = BookMatcher()

    calibre_books = [
        make_book(
            id=1,
            title="Dune",
            authors=["Frank Herbert"],
        )
    ]

    hardcover_books = [
        make_book(
            id=2,
            title="Dune",
            authors=["Frank Herbert"],
        )
    ]

    matches = matcher.match_books(
        calibre_books,
        hardcover_books,
    )

    assert len(matches) == 1

    a, b, score = matches[0]

    assert a.id == 1
    assert b.id == 2
    assert score == 1.0


def test_match_books_no_match():
    matcher = BookMatcher()

    matches = matcher.match_books(
        [
            make_book(
                title="Foundation",
                authors=["Isaac Asimov"],
            )
        ],
        [
            make_book(
                title="Dune",
                authors=["Frank Herbert"],
            )
        ],
    )

    assert matches == []


def test_match_books_threshold():
    matcher = BookMatcher(threshold=1.0)

    matches = matcher.match_books(
        [make_book(title="Dune")],
        [make_book(title="Dune Messiah")],
    )

    assert matches == []


def test_similarity_ignores_none_isbn_values():
    matcher = BookMatcher()

    a = make_book(isbn=[None])
    b = make_book(isbn=[None])

    score = matcher.similarity(a, b)

    assert score == 1.0


def test_canonicalize_removes_article():
    assert BookMatcher.canonicalize_title("The Last Hero") == "last hero"


def test_canonicalize_removes_subtitle():
    assert BookMatcher.canonicalize_title("The Last Hero: A Discworld Fable") == "last hero"


def test_canonicalize_removes_parenthetical():
    assert BookMatcher.canonicalize_title("The Last Hero (Discworld #27)") == "last hero"


def test_canonicalize_combines_rules():
    assert (
        BookMatcher.canonicalize_title("The Last Hero (Discworld #27): A Discworld Fable")
        == "last hero"
    )


def test_canonicalize_torrent_title():
    assert (
        BookMatcher.canonicalize_title(
            "1600 [Wintersmith] (By: Terry Pratchett) [published: October, 2007]"
        )
        == "wintersmith"
    )


def test_white_sand_volume_matches():
    matcher = BookMatcher()

    a = make_book(
        title="White Sand",
        authors=["Brandon Sanderson"],
    )

    b = make_book(
        title="White Sand, Vol. 1 Brandon Sanderson",
        authors=["Brandon Sanderson"],
    )

    assert matcher.is_match(a, b)


def test_canonicalize_does_not_destroy_numeric_titles():
    assert BookMatcher.canonicalize_title("1984") == "1984"
