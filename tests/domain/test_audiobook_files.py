import json
from pathlib import Path

import pytest

from murid.domain.audiobook_files import AudiobookSelectionError, select_audiobook
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


@pytest.mark.parametrize(
    "filenames",
    [
        ["01 - Dune.m4b", "02 - Dune Messiah.m4b"],
        ["01.m4b", "02.m4b"],
        ["Dune.m4b", "Dune Messiah.m4b"],
    ],
)
@pytest.mark.parametrize("metadata", [False, True])
def test_multi_m4b_requires_each_file_to_match_the_book(tmp_path, filenames, metadata):
    root = tmp_path / "Dune"
    root.mkdir()
    for filename in filenames:
        (root / filename).write_bytes(b"complete audiobook")
    if metadata:
        (root / "metadata.json").write_text(json.dumps({"title": "Dune"}))
    book = Book("Dune", ["Frank Herbert"], 42, [], "hardcover")

    with pytest.raises(AudiobookSelectionError, match="multi-M4B"):
        select_audiobook(book, str(root), BookMatcher(), ["m4b"])


@pytest.mark.parametrize("prefix", ["", "01 - "])
def test_title_matched_m4b_parts_are_supported(tmp_path, prefix):
    root = tmp_path / "Dune"
    root.mkdir()
    filenames = [f"{prefix}Dune Part {number}.m4b" for number in (1, 2)]
    for filename in filenames:
        (root / filename).write_bytes(b"audiobook part")
    book = Book("Dune", ["Frank Herbert"], 42, [], "hardcover")

    selection = select_audiobook(book, str(root), BookMatcher(), ["m4b"])

    assert selection.audio == tuple(Path(name) for name in filenames)


@pytest.mark.parametrize(
    "extension", ["mp4", "aiff", "AIFF", "aifc", "oga", "ape", "au", "aax", "mka"]
)
@pytest.mark.parametrize("nested", [False, True])
def test_unsupported_audio_tracks_are_not_silently_omitted(tmp_path, extension, nested):
    root = tmp_path / "Dune"
    root.mkdir()
    (root / "01.mp3").write_bytes(b"first audio track")
    parent = root / "CD2" if nested else root
    parent.mkdir(exist_ok=True)
    (parent / f"02.{extension}").write_bytes(b"unsupported second audio track")
    book = Book("Dune", ["Frank Herbert"], 42, [], "hardcover")

    with pytest.raises(AudiobookSelectionError, match="unsupported audio formats"):
        select_audiobook(book, str(root), BookMatcher(), ["mp3", "m4b"])


def test_playlists_remain_sidecars(tmp_path):
    root = tmp_path / "Dune"
    root.mkdir()
    (root / "01.mp3").write_bytes(b"audio")
    (root / "playlist.m3u").write_text("01.mp3\n")
    book = Book("Dune", ["Frank Herbert"], 42, [], "hardcover")

    selection = select_audiobook(book, str(root), BookMatcher(), ["mp3"])

    assert selection.audio == (Path("01.mp3"),)
    assert selection.sidecars == (Path("playlist.m3u"),)


def test_single_m4b_does_not_claim_generic_sidecars_when_other_audio_is_present(tmp_path):
    audio = tmp_path / "Dune.m4b"
    audio.write_bytes(b"Dune audiobook")
    (tmp_path / "Other Book.mp4").write_bytes(b"another audiobook")
    (tmp_path / "cover.jpg").write_bytes(b"ambiguous cover")
    book = Book("Dune", ["Frank Herbert"], 42, [], "hardcover")

    selection = select_audiobook(book, str(audio), BookMatcher(), ["m4b"])

    assert selection.audio == (Path("Dune.m4b"),)
    assert selection.sidecars == ()
