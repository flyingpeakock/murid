"""Tests for selecting one ebook file from a completed torrent."""

from murid import Book, BookMatcher
from murid.domain.book_file_selector import BookFileSelector


def make_book(title="Dune", authors=None):
    """Build a book for selector tests."""
    return Book(
        title=title,
        authors=authors or ["Frank Herbert"],
        id=1,
        isbn=[],
        source="test",
    )


def test_selects_requested_book_from_multi_book_torrent(tmp_path):
    """Select the file whose name matches the requested title and author."""
    root = tmp_path / "pack"
    root.mkdir()
    requested_file = root / "Frank Herbert - Dune.epub"
    requested_file.touch()
    (root / "Frank Herbert - Dune Messiah.epub").touch()
    (root / "readme.txt").touch()

    selector = BookFileSelector(["epub", "mobi"])

    selected = selector.select(make_book(), str(root), BookMatcher())

    assert selected == requested_file


def test_prefers_configured_format_for_equivalent_files(tmp_path):
    """Use the configured format order when filenames identify the same book."""
    root = tmp_path / "pack"
    root.mkdir()
    (root / "Dune.epub").touch()
    mobi_file = root / "Dune.mobi"
    mobi_file.touch()

    selector = BookFileSelector(["mobi", "epub"])

    selected = selector.select(make_book(), str(root), BookMatcher())

    assert selected == mobi_file


def test_returns_none_when_no_filename_matches_requested_book(tmp_path):
    """Decline to import a pack when none of its filenames match the book."""
    root = tmp_path / "pack"
    root.mkdir()
    (root / "Foundation.epub").touch()
    (root / "Hyperion.epub").touch()

    selector = BookFileSelector(["epub"])

    selected = selector.select(make_book(), str(root), BookMatcher())

    assert selected is None


def test_returns_none_when_similarly_scored_titles_are_ambiguous(tmp_path):
    """Decline to guess when distinct titles have nearly identical match scores."""

    class AmbiguousMatcher(BookMatcher):  # pylint: disable=too-few-public-methods
        """Return close scores for the two candidate titles."""

        def title_similarity(self, a, b):
            """Give each filename a score used to exercise the ambiguity guard."""
            return 1.0 if a and b == "dune" else 0.98

    root = tmp_path / "pack"
    root.mkdir()
    (root / "Dune.epub").touch()
    (root / "Dune Messiah.epub").touch()

    selector = BookFileSelector(["epub"])

    selected = selector.select(make_book(), str(root), AmbiguousMatcher())

    assert selected is None


def test_selects_single_supported_file_without_name_match(tmp_path):
    """Select the only supported ebook in a directory without filename matching."""
    root = tmp_path / "pack"
    root.mkdir()
    only_file = root / "downloaded-book.epub"
    only_file.touch()

    selector = BookFileSelector(["epub"])

    selected = selector.select(make_book(), str(root), BookMatcher())

    assert selected == only_file


def test_single_file_path_must_use_supported_format(tmp_path):
    """Reject a direct file path whose extension is not configured."""
    path = tmp_path / "book.txt"
    path.touch()

    selector = BookFileSelector(["epub"])

    assert selector.select(make_book(), str(path), BookMatcher()) is None


def test_matches_release_names_with_parenthetical_series_and_catalog_id(tmp_path):
    """Ignore trailing series metadata and Amazon IDs in release filenames."""
    root = tmp_path / "pack"
    root.mkdir()
    target = root / "Caliban's War (The Expanse Book 2) - B005SCRR1A.azw3"
    target.touch()
    (root / "Leviathan Wakes (The Expanse Book 1) - B004G8Q1FT.azw3").touch()

    book = Book(
        title="Caliban's War",
        authors=["James S. A. Corey"],
        series="The Expanse",
        series_number=2,
        id=2,
        isbn=[],
        source="test",
    )

    selected = BookFileSelector().select(book, str(root), BookMatcher())

    assert selected == target


def test_matches_title_with_author_suffix_and_malformed_extension_text(tmp_path):
    """Recognize a title when the author follows it in the filename."""
    root = tmp_path / "pack"
    root.mkdir()
    target = root / "Abaddon's Gate - S.A. Corey.epub"
    target.touch()
    (root / "Cibola Burn - James S.A. Corey.azw3").touch()

    book = Book(
        title="Abaddon's Gate",
        authors=["James S. A. Corey"],
        id=3,
        isbn=[],
        source="test",
    )

    selected = BookFileSelector().select(book, str(root), BookMatcher())

    assert selected == target


def test_preserves_parenthetical_title_text(tmp_path):
    """Keep edition wording that is part of a book title."""
    root = tmp_path / "pack"
    root.mkdir()
    target = root / "The Hobbit (Illustrated Edition).epub"
    target.touch()
    (root / "The Hobbit.epub").touch()

    book = make_book("The Hobbit (Illustrated Edition)")
    selected = BookFileSelector().select(book, str(root), BookMatcher())

    assert selected == target


def test_equivalent_author_suffix_variants_do_not_look_ambiguous(tmp_path):
    """Treat author suffixes as metadata when identifying candidate titles."""
    root = tmp_path / "pack"
    root.mkdir()
    target = root / "Dune - Frank Herbert.epub"
    target.touch()
    (root / "Dune.epub").touch()

    selected = BookFileSelector().select(make_book(), str(root), BookMatcher())

    assert selected == target
