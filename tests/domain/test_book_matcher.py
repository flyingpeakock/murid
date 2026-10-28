import logging

import pytest

from murid.domain.book import Book
from murid.domain.book_matcher import BookMatcher


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


def test_normalize_treats_canonically_equivalent_unicode_as_equal():
    assert BookMatcher.normalize("Café") == BookMatcher.normalize("Cafe\u0301")


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


def test_author_similarity_matches_names_inside_joined_calibre_author_value():
    matcher = BookMatcher()

    assert (
        matcher.author_similarity(
            ["Robert Jordan", "Brandon Sanderson"],
            ["Robert Jordan Brandon Sanderson"],
        )
        == 0.85
    )


@pytest.mark.parametrize(
    "authors",
    [["Sam Hughes, qntm"], ["Sam Hughes qntm"], ["Sam Hughes", "qntm"]],
)
def test_mononym_in_combined_author_field_is_assigned(authors):
    matcher = BookMatcher()
    hardcover = make_book(
        title="There Is No Antimemetics Division", authors=["qntm"], source="hardcover"
    )
    calibre = make_book(title=hardcover.title, authors=authors, source="calibre")

    assert matcher.is_match(hardcover, calibre)
    assert matcher.is_match(calibre, hardcover)
    assert matcher.match_books([calibre], [hardcover]) == {
        (calibre, hardcover, matcher.similarity(hardcover, calibre))
    }


@pytest.mark.parametrize(
    ("name", "combined"),
    [("Hughes", "Sam Hughes"), ("S", "S Hughes qntm"), ("qntm", "Sam Hughes qntmx")],
)
def test_mononym_containment_requires_full_token_and_combined_names(name, combined):
    matcher = BookMatcher()

    assert matcher.author_similarity([name], [combined]) == 0.0
    assert matcher.author_similarity([combined], [name]) == 0.0


def test_same_series_book_matches_when_calibre_joins_coauthors():
    hardcover_book = Book(
        id=1,
        title="Towers of Midnight",
        authors=["Brandon Sanderson", "Robert Jordan"],
        isbn=[],
        source="hardcover",
        series="Wheel of Time",
        series_number=13,
    )
    calibre_book = Book(
        id=2,
        title="Towers of Midnight",
        authors=["Robert Jordan Brandon Sanderson"],
        isbn=[],
        source="calibre",
        series="Wheel of Time",
        series_number=13,
    )

    assert BookMatcher(threshold=0.7).is_match(hardcover_book, calibre_book)


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
        title="Dune: The Illustrated Edition",
        authors=["Frank Herbert"],
        isbn=["9780306406157"],
    )

    assert matcher.similarity(a, b) == 1.0


def test_alternative_titles_match_regional_title_variants():
    matcher = BookMatcher()
    hardcover_book = make_book(
        title="Harry Potter and the Philosopher's Stone",
        authors=["J. K. Rowling"],
    )
    hardcover_book.alternative_titles = ["Harry Potter and the Sorcerer's Stone"]
    calibre_book = make_book(
        title="Harry Potter and the Sorcerer's Stone",
        authors=["J. K. Rowling"],
    )

    assert matcher.is_match(hardcover_book, calibre_book)


def test_alternative_title_does_not_override_conflicting_authors():
    matcher = BookMatcher()
    book_a = make_book(title="The Original Title", authors=["Author One"])
    book_a.alternative_titles = ["The Shared Title"]
    book_b = make_book(title="The Shared Title", authors=["Author Two"])

    assert not matcher.is_match(book_a, book_b)


def test_external_catalog_identifiers_match_url_and_raw_ids():
    matcher = BookMatcher()
    hardcover_book = make_book(
        title="The Name of the Wind",
        authors=["Patrick Rothfuss"],
    )
    hardcover_book.identifiers = {
        "Goodreads": "https://www.goodreads.com/book/show/186074.The_Name_of_the_Wind"
    }
    calibre_book = make_book(
        title="The Name of the Wind: Kingkiller Chronicle, Book 1",
        authors=["Patrick Rothfuss"],
    )
    calibre_book.identifiers = {"goodreads": "186074"}

    assert BookMatcher.normalized_identifiers(hardcover_book) == BookMatcher.normalized_identifiers(
        calibre_book
    )
    assert matcher.is_match(hardcover_book, calibre_book)


def test_external_identifier_does_not_override_conflicting_metadata():
    matcher = BookMatcher()
    book_a = make_book(title="The Name of the Wind", authors=["Patrick Rothfuss"])
    book_a.identifiers = {"goodreads": "186074"}
    book_b = make_book(title="The Left Hand of Darkness", authors=["Ursula K. Le Guin"])
    book_b.identifiers = {"goodreads": "186074"}

    assert not matcher.is_match(book_a, book_b)


def test_known_series_prefix_is_removed_from_title_variant():
    matcher = BookMatcher()
    calibre_book = make_book(title="The Way of Kings", authors=["Brandon Sanderson"])
    calibre_book.series = "The Stormlight Archive"
    mam_book = make_book(
        title="The Stormlight Archive 1 The Way of Kings",
        authors=["Brandon Sanderson"],
    )
    mam_book.series = "The Stormlight Archive"

    assert matcher.is_match(calibre_book, mam_book)


def test_matching_series_position_supports_close_title_variant():
    matcher = BookMatcher()
    with_matching_position = Book(
        title="The Martian: A Novel",
        authors=[],
        id=1,
        isbn=[],
        source="hardcover",
        series="Science Fiction Collection",
        series_number=1,
    )
    same_position = Book(
        title="The Martian",
        authors=[],
        id=2,
        isbn=[],
        source="calibre",
        series="Science Fiction Collection",
        series_number=1.0,
    )
    different_position = Book(
        title="The Martian",
        authors=[],
        id=3,
        isbn=[],
        source="calibre",
        series="Science Fiction Collection",
        series_number=2,
    )

    assert matcher.is_match(with_matching_position, same_position)
    assert not matcher.is_match(with_matching_position, different_position)


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
        ("306406152", "9780306406157"),
        ("306-40615-2", "9780306406157"),
        ("80442957x", "9780804429573"),
        ("0-306-40615-2", "9780306406157"),
        ("9780306406157", "9780306406157"),
        ("978-0-306-40615-7", "9780306406157"),
        ("080442957X", "9780804429573"),
        ("0-8044-2957-x", "9780804429573"),
        ("  0 306 40615 2  ", "9780306406157"),
        ("ISBN: 978.0.306.40615.7", "9780306406157"),
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
        "306406153",  # Invalid nine-digit SBN checksum.
        "X04429570",  # SBN check digits must also be at the end.
        "0-8044-2957-0",  # Invalid ISBN-10 checksum despite valid formatting.
        "X804429570",  # X is only allowed as the final ISBN-10 check digit.
        "97803064061570",  # Extra digits must not be truncated.
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
        title="Dune: The Illustrated Edition",
        authors=["Frank Herbert"],
        isbn=["9780441172719"],
    )

    assert matcher.is_match(a, b)


def test_reused_isbn_does_not_override_conflicting_title_and_author():
    matcher = BookMatcher()
    a = make_book(
        title="Dune",
        authors=["Frank Herbert"],
        isbn=["9780441172719"],
    )
    b = make_book(
        title="The Joy of Cooking",
        authors=["Irma S. Rombauer"],
        isbn=["9780441172719"],
    )

    assert not matcher.is_match(a, b)


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
    matcher = BookMatcher(threshold=0.7)

    a = make_book(
        title="Dune",
        authors=["Frank Herbert"],
    )
    b = make_book(
        title="Dune",
        authors=["Someone Else"],
    )

    assert not matcher.is_match(a, b)


def test_same_initial_and_surname_does_not_make_different_authors_match():
    matcher = BookMatcher(threshold=0.7)
    james = make_book(title="Dune", authors=["James Smith"])
    john = make_book(title="Dune", authors=["John Smith"])

    assert not matcher.is_match(james, john)


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


def test_omnibus_variant_matches_trilogy_title():
    matcher = BookMatcher()
    trilogy = make_book(
        title="The Farseer Trilogy",
        authors=["Robin Hobb"],
        source="hardcover",
    )
    omnibus = make_book(
        title="The Farseer Trilogy Omnibus",
        authors=["Robin Hobb"],
        source="calibre",
    )

    assert matcher.is_match(trilogy, omnibus)


def test_split_part_annotation_matches_the_complete_book_title():
    matcher = BookMatcher()
    split_part = Book(
        id=1,
        title="The Shadow Rising, Part 1 of 3",
        authors=["Robert Jordan", "Uwe Luserke"],
        isbn=[],
        source="hardcover",
    )
    complete_book = Book(
        id=2,
        title="The Shadow Rising",
        authors=["Robert Jordan"],
        isbn=[],
        source="calibre",
    )

    assert matcher.is_match(split_part, complete_book)


@pytest.mark.parametrize(
    ("full_title", "short_title"),
    [
        (
            "Alcatraz versus the Knights of Crystallia",
            "The Knights of Crystallia",
        ),
        (
            "Harry Potter and the Prisoner of Azkaban",
            "The Prisoner of Azkaban",
        ),
        (
            "Alcatraz vs. the Evil Librarians",
            "Alcatraz versus the Evil Librarians",
        ),
    ],
)
def test_series_prefix_variants_match(full_title, short_title):
    matcher = BookMatcher()
    full = make_book(title=full_title, authors=["Brandon Sanderson"])
    short = make_book(title=short_title, authors=["Brandon Sanderson"])

    assert matcher.is_match(full, short)


def test_ordinary_title_with_and_the_does_not_create_short_title_match():
    matcher = BookMatcher()
    full_title = make_book(title="The Girl and the Sea", authors=["Author Name"])
    short_title = make_book(title="The Sea", authors=["Author Name"])

    assert not matcher.is_match(full_title, short_title)


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


def test_review_matches_accepts_only_assigned_pair():
    matcher = BookMatcher()
    calibre_book = make_book(id=1, title="Dune", authors=["Frank Herbert"])
    hardcover_books = [
        make_book(id=101, title="Dune", authors=["Frank Herbert"]),
        make_book(id=102, title="Dune", authors=["Frank Herbert"]),
    ]

    reviews = matcher.review_matches(iter([calibre_book]), iter(hardcover_books))
    assigned = matcher.match_books([calibre_book], hardcover_books)

    assert len(reviews) == 2
    assert sum(candidate.accepted for _, candidates in reviews for candidate in candidates) == 1
    assert {
        (candidate.calibre_book.id, hardcover.id)
        for hardcover, candidates in reviews
        for candidate in candidates
        if candidate.accepted
    } == {(calibre.id, hardcover.id) for calibre, hardcover, _ in assigned}


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
    assert "no candidates available" in caplog.text


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
    assert "no Calibre match" in caplog.text
    assert "Foundation" in caplog.text


def test_match_books_logs_successful_match(caplog):
    matcher = BookMatcher()

    with caplog.at_level(logging.DEBUG, logger="murid"):
        matches = matcher.match_books(
            [make_book(id=1, title="Dune")],
            [make_book(id=2, title="Dune")],
        )

    assert len(matches) == 1
    assert "matched Calibre book" in caplog.text
