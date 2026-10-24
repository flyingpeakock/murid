import json
from pathlib import Path

import pytest

from murid.domain.audiobook_files import select_audiobook
from murid.domain.book import Book
from murid.domain.book_matcher import BookMatcher


@pytest.mark.parametrize("source_kind", ["folder", "track", "metadata", "legacy_metadata", "m4b"])
@pytest.mark.parametrize("alternative", [False, True])
def test_title_containing_author_is_preserved(tmp_path, source_kind, alternative):
    title = "The Autobiography of Benjamin Franklin"
    book = Book(
        "Vie de Benjamin Franklin" if alternative else title,
        ["Benjamin Franklin"],
        42,
        [],
        "hardcover",
        alternative_titles=[title] if alternative else [],
    )
    root = tmp_path / (title if source_kind in {"folder", "track"} else "download")
    root.mkdir()
    filename = f"{title}.mp3" if source_kind == "track" else "01.mp3"
    if source_kind == "m4b":
        filename = "book.m4b"
    (root / filename).write_bytes(b"audio")
    if source_kind in {"metadata", "legacy_metadata", "m4b"}:
        payload = {"title": title}
        if source_kind == "legacy_metadata":
            payload = {"metadata": payload}
        (root / "metadata.json").write_text(json.dumps(payload))
    source = root / filename if source_kind == "m4b" else root

    selected = select_audiobook(book, str(source), BookMatcher(), ["mp3", "m4b"])

    assert selected.audio == (Path(filename),)
    if source_kind in {"metadata", "legacy_metadata", "m4b"}:
        assert Path("metadata.json") in selected.sidecars


def test_author_and_format_decoration_still_matches_as_fallback(tmp_path):
    root = tmp_path / "Frank Herbert - Dune [Unabridged MP3]"
    root.mkdir()
    (root / "01.mp3").write_bytes(b"audio")
    book = Book("Dune", ["Frank Herbert"], 42, [], "hardcover")

    selected = select_audiobook(book, str(root), BookMatcher(), ["mp3"])

    assert selected.audio == (Path("01.mp3"),)
