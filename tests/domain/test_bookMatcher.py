# tests/test_bookmatcher.py

import logging

import pytest

from murid import Book, BookMatcher


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

    assert score == 0.85


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

    a = make_book(isbn=["9780306406157"])
    b = make_book(
        title="Completely Different",
        authors=["Someone Else"],
        isbn=["9780306406157"],
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

    a, b, score = next(iter(matches))

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

    assert matches == set()


def test_match_books_threshold():
    matcher = BookMatcher(threshold=1.0)

    matches = matcher.match_books(
        [make_book(title="Dune")],
        [make_book(title="Dune Messiah")],
    )

    assert matches == set()


def test_similarity_ignores_none_isbn_values():
    matcher = BookMatcher()

    a = make_book(isbn=[None])
    b = make_book(isbn=[None])

    score = matcher.similarity(a, b)

    assert score == 1.0


def test_canonicalize_removes_article():
    assert BookMatcher.canonicalize_title("The Last Hero") == "last hero"


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


# ISBN validation and normalization


@pytest.mark.parametrize(
    ("isbn", "expected"),
    [
        ("0306406152", "9780306406157"),
        ("0-306-40615-2", "9780306406157"),
        ("9780306406157", "9780306406157"),
        ("978-0-306-40615-7", "9780306406157"),
        ("080442957X", "9780804429573"),
        ("9791090636071", "9791090636071"),
    ],
)
def test_normalize_isbn_valid(isbn, expected):
    assert BookMatcher.normalize_isbn(isbn) == expected


@pytest.mark.parametrize(
    "isbn",
    [
        "",
        None,
        "123",
        "0306406153",  # Invalid ISBN-10 checksum
        "9780306406158",  # Invalid ISBN-13 checksum
        "9770306406157",  # Unsupported ISBN prefix
        "ABCDEFGHIJ",
        "978030640615X",  # ISBN-13 must contain digits only
    ],
)
def test_normalize_isbn_invalid(isbn):
    assert BookMatcher.normalize_isbn(isbn) is None


def test_isbn10_and_isbn13_match():
    matcher = BookMatcher()

    a = make_book(
        title="Dune",
        authors=["Frank Herbert"],
        isbn=["0441172717"],
    )
    b = make_book(
        title="Different title",
        authors=["Someone Else"],
        isbn=["9780441172719"],
    )

    assert matcher.is_match(a, b)


def test_invalid_isbns_do_not_create_matches():
    matcher = BookMatcher()

    a = make_book(
        title="Dune",
        authors=["Frank Herbert"],
        isbn=["9780306406158"],
    )
    b = make_book(
        title="Foundation",
        authors=["Isaac Asimov"],
        isbn=["9780306406158"],
    )

    assert matcher.similarity(a, b) < 0.5
    assert not matcher.is_match(a, b)


# Title matching: avoid false positives


def test_title_similarity_ignores_leading_article():
    matcher = BookMatcher()

    assert matcher.title_similarity("The Hobbit", "Hobbit") == 1.0


def test_title_similarity_preserves_meaningful_words():
    matcher = BookMatcher()

    assert matcher.title_similarity("Little Women", "Little Men") < 1.0


def test_little_women_does_not_match_little_men():
    matcher = BookMatcher()

    women = make_book(
        title="Little Women",
        authors=["Louisa May Alcott"],
    )
    men = make_book(
        title="Little Men",
        authors=["Louisa May Alcott"],
    )

    assert not matcher.is_match(women, men)


def test_same_title_with_different_authors_does_not_match():
    matcher = BookMatcher()

    a = make_book(
        title="Dune",
        authors=["Frank Herbert"],
    )
    b = make_book(
        title="Dune",
        authors=["Someone Else"],
    )

    assert not matcher.is_match(a, b)


def test_missing_author_does_not_make_fuzzy_title_match():
    matcher = BookMatcher()

    a = make_book(
        title="Dune",
        authors=[],
    )
    b = make_book(
        title="Dune Messiah",
        authors=[],
    )

    assert not matcher.is_match(a, b)


def test_subtitle_variant_can_match_main_title():
    matcher = BookMatcher()

    a = make_book(
        title="Dune",
        authors=["Frank Herbert"],
    )
    b = make_book(
        title="Dune: The Illustrated Edition",
        authors=["Frank Herbert"],
    )

    assert matcher.is_match(a, b)


def test_volume_annotation_does_not_remove_arbitrary_words():
    BookMatcher()

    assert BookMatcher._remove_volume_annotation("Little Men") == "Little Men"
    assert BookMatcher._remove_volume_annotation("Little Women") == "Little Women"


# One-to-one assignment


def test_match_books_does_not_match_calibre_book_twice():
    matcher = BookMatcher()

    calibre_books = [
        make_book(
            id=1,
            title="Dune",
            authors=["Frank Herbert"],
        ),
    ]
    hardcover_books = [
        make_book(
            id=101,
            title="Dune",
            authors=["Frank Herbert"],
        ),
        make_book(
            id=102,
            title="Dune",
            authors=["Frank Herbert"],
        ),
    ]

    matches = matcher.match_books(calibre_books, hardcover_books)

    assert len(matches) == 1
    assert len({a.id for a, _, _ in matches}) == len(matches)
    assert len({b.id for _, b, _ in matches}) == len(matches)


def test_match_books_does_not_match_hardcover_book_twice():
    matcher = BookMatcher()

    calibre_books = [
        make_book(id=1, title="Dune", authors=["Frank Herbert"]),
        make_book(id=2, title="Dune", authors=["Frank Herbert"]),
    ]
    hardcover_books = [
        make_book(id=101, title="Dune", authors=["Frank Herbert"]),
    ]

    matches = matcher.match_books(calibre_books, hardcover_books)

    assert len(matches) == 1
    assert len({a.id for a, _, _ in matches}) == len(matches)
    assert len({b.id for _, b, _ in matches}) == len(matches)


def test_match_books_matches_multiple_distinct_books():
    matcher = BookMatcher()

    calibre_books = [
        make_book(id=1, title="Dune", authors=["Frank Herbert"]),
        make_book(id=2, title="Foundation", authors=["Isaac Asimov"]),
    ]
    hardcover_books = [
        make_book(id=101, title="Foundation", authors=["Isaac Asimov"]),
        make_book(id=102, title="Dune", authors=["Frank Herbert"]),
    ]

    matches = matcher.match_books(calibre_books, hardcover_books)

    assert len(matches) == 2
    assert {(a.id, b.id) for a, b, _ in matches} == {
        (1, 102),
        (2, 101),
    }


def test_match_books_does_not_assign_one_book_to_two_candidates():
    matcher = BookMatcher()

    calibre_books = [
        make_book(id=1, title="Dune", authors=["Frank Herbert"]),
        make_book(id=2, title="Foundation", authors=["Isaac Asimov"]),
    ]
    hardcover_books = [
        make_book(id=101, title="Dune", authors=["Frank Herbert"]),
        make_book(id=102, title="Dune", authors=["Frank Herbert"]),
    ]

    matches = matcher.match_books(calibre_books, hardcover_books)

    assert len(matches) == 1
    assert len({a.id for a, _, _ in matches}) == 1
    assert len({b.id for _, b, _ in matches}) == 1


def test_match_books_empty_inputs():
    matcher = BookMatcher()

    assert matcher.match_books([], []) == set()
    assert matcher.match_books([make_book()], []) == set()
    assert matcher.match_books([], [make_book()]) == set()


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (
            "[Wintersmith] (By: Terry Pratchett) [published: October, 2007]",
            "Wintersmith",
        ),
        ("Dune [By: Frank Herbert]", "Dune"),
        ("Dune [published: June, 1965]", "Dune"),
        ("The [Winter] King", "The [Winter] King"),
    ],
)
def test_remove_metadata_annotations(title, expected):
    assert BookMatcher._remove_metadata_annotations(title) == expected


# Logging and diagnostics


def test_match_books_logs_when_no_candidates_exist(caplog):
    matcher = BookMatcher()

    with caplog.at_level(logging.DEBUG, logger="murid"):
        matches = matcher.match_books([], [make_book(title="Dune")])

    assert matches == set()
    assert "No candidates available" in caplog.text


def test_match_books_logs_unmatched_book(caplog):
    matcher = BookMatcher()

    calibre_books = [
        make_book(title="Foundation", authors=["Isaac Asimov"]),
    ]
    hardcover_books = [
        make_book(title="Dune", authors=["Frank Herbert"]),
    ]

    with caplog.at_level(logging.DEBUG, logger="murid"):
        matches = matcher.match_books(calibre_books, hardcover_books)

    assert matches == set()
    assert "No match for" in caplog.text
    assert "Foundation" in caplog.text


def test_match_books_logs_successful_match(caplog):
    matcher = BookMatcher()

    with caplog.at_level(logging.DEBUG, logger="murid"):
        matches = matcher.match_books(
            [make_book(id=1, title="Dune")],
            [make_book(id=2, title="Dune")],
        )

    assert len(matches) == 1
    assert "Matched Calibre book" in caplog.text
