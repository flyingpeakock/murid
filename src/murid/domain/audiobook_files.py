"""Conservatively identify a complete single-book audio source."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .book import Book
from .book_matcher import BookMatcher

AUDIO_EXTENSIONS = {".m4b", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav", ".wma"}
SIDECAR_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".nfo",
    ".opf",
    ".cue",
    ".txt",
    ".json",
    ".abs",
    ".lrc",
    ".m3u",
    ".m3u8",
}
IMPORT_MARKER = ".murid-import.json"


class AudiobookSelectionError(Exception):
    """The completed source does not clearly represent one supported audiobook."""


@dataclass(frozen=True)
class AudiobookFiles:
    """All selected paths are relative to one source directory."""

    root: Path
    audio: tuple[Path, ...]
    sidecars: tuple[Path, ...]


def _matches_title(book: Book, name: str, matcher: BookMatcher) -> bool:
    for author in book.authors:
        name = re.sub(re.escape(author), " ", name, flags=re.IGNORECASE)
    name = re.sub(r"\b(?:unabridged|audiobook|m4b|mp3)\b", " ", name, flags=re.IGNORECASE)
    name = re.sub(r"\b(?:part|cd|disc|disk)\s*\d+\b", " ", name, flags=re.IGNORECASE)
    return any(
        matcher.title_similarity(title, name.strip(" -_[]()")) >= 0.85
        for title in (book.title, *book.alternative_titles)
        if title
    )


def select_audiobook(
    book: Book,
    source: str,
    matcher: BookMatcher,
    filetypes: list[str],
) -> AudiobookFiles:
    """Accept one M4B or a named book folder containing numbered/book-named tracks."""
    path = Path(source).expanduser()
    if path.is_symlink() or not path.exists():
        raise AudiobookSelectionError("Audio source is missing or is a symlink")
    if path.is_file():
        return _single_file(path, filetypes, book, matcher)
    if not path.is_dir():
        raise AudiobookSelectionError("Audio source must be a regular file or directory")
    root = path.resolve()
    entries = sorted(root.rglob("*"))
    if any(p.is_symlink() or (not p.is_dir() and not p.is_file()) for p in entries):
        raise AudiobookSelectionError("Audio folders cannot contain symlinks or special files")
    if any(p.name == IMPORT_MARKER for p in entries):
        raise AudiobookSelectionError("Source contains a reserved Murid import marker")
    audio = tuple(
        p.relative_to(root) for p in entries if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
    )
    if not audio or any(p.suffix.lower().lstrip(".") not in filetypes for p in audio):
        raise AudiobookSelectionError("Source has no audio or contains unsupported audio formats")
    if len({p.suffix.lower() for p in audio}) != 1:
        raise AudiobookSelectionError(
            "Mixed audio formats are ambiguous; select one complete encoding"
        )
    if any(
        len(p.parts) > 2
        or (
            len(p.parts) == 2
            and not re.fullmatch(
                r"(?:cd|dis[ck])\s*[0-9]{1,3}", p.parts[0], re.IGNORECASE | re.ASCII
            )
        )
        for p in audio
    ):
        raise AudiobookSelectionError(
            "Unsupported audio folders: use one book folder with tracks at its root or in "
            "one level of CD/disc folders named CD1, Disc 2, or Disk 003 (1–3 digits)"
        )
    metadata_title = _metadata_title(root, book, matcher)
    named = _matches_title(book, root.name, matcher) or (
        isinstance(metadata_title, str) and _matches_title(book, metadata_title, matcher)
    )
    named = named or (
        len(audio) == 1
        and audio[0].suffix.lower() == ".m4b"
        and _matches_title(book, audio[0].stem, matcher)
    )
    if not named or any(
        not re.match(r"^(?:(?:track|chapter)[ _-]*)?\d+(?:\b|[_-])", p.stem, re.IGNORECASE)
        and not _matches_title(book, p.stem, matcher)
        for p in audio
    ):
        raise AudiobookSelectionError(
            "Ambiguous audio pack: use one title-matched book folder with numbered "
            "or book-named tracks"
        )
    sidecars = tuple(
        p.relative_to(root)
        for p in entries
        if p.is_file() and p.suffix.lower() in SIDECAR_EXTENSIONS
    )
    return AudiobookFiles(root, audio, sidecars)


def _single_file(
    path: Path, filetypes: list[str], book: Book, matcher: BookMatcher
) -> AudiobookFiles:
    """Keep a selected M4B and its unambiguous sidecars."""
    if path.suffix.lower() != ".m4b" or "m4b" not in filetypes:
        raise AudiobookSelectionError("Select a single M4B or a complete single-book audio folder")
    root = path.parent.resolve()
    siblings = list(root.iterdir())
    single = sum(p.suffix.lower() in AUDIO_EXTENSIONS for p in siblings) == 1
    sidecars = tuple(
        p.relative_to(root)
        for p in siblings
        if p.is_file()
        and not p.is_symlink()
        and p.suffix.lower() in SIDECAR_EXTENSIONS
        and (
            p.stem == path.stem
            or (
                single
                and p.name
                in {
                    "metadata.json",
                    "cover.jpg",
                    "cover.png",
                    "desc.txt",
                    "reader.txt",
                }
            )
        )
    )
    if Path("metadata.json") in sidecars:
        _metadata_title(root, book, matcher)
    return AudiobookFiles(root, (Path(path.name),), sidecars)


def _metadata_title(root: Path, book: Book, matcher: BookMatcher) -> str:
    """Validate the effective title, using Audiobookshelf's legacy nested override."""
    metadata = root / "metadata.json"
    if not metadata.is_file():
        return ""
    try:
        payload = json.loads(metadata.read_text(encoding="utf-8"))
        title = (payload.get("metadata") or {}).get("title", payload.get("title", ""))
    except (ValueError, AttributeError):
        raise AudiobookSelectionError("Source metadata.json must contain a JSON object") from None
    if title and (not isinstance(title, str) or not _matches_title(book, title, matcher)):
        raise AudiobookSelectionError(
            "Source metadata identifies a different book; select one book folder"
        )
    return title or ""
