"""Durable, idempotent copies into a shared audiobook library."""

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict
from pathlib import Path, PurePosixPath, PureWindowsPath

from ..domain.audiobook_files import AUDIO_EXTENSIONS, IMPORT_MARKER, select_audiobook
from ..domain.book import Book
from ..domain.book_matcher import BookMatcher
from .import_filesystem import (
    durable_mkdir,
    ensure_shared_directory,
    import_lock,
    publish_directory,
    sync_directory,
    write_json,
)
from .library import LibraryError


def _relative(value: str) -> Path:
    if not isinstance(value, str) or not value or "\0" in value:
        raise LibraryError("Import journal contains an unsafe relative path")
    path = PurePosixPath(value)
    if not path.parts or path.is_absolute() or path.as_posix() != value:
        raise LibraryError("Import journal contains an unsafe relative path")
    if ".." in path.parts or "\\" in value or PureWindowsPath(value).drive:
        raise LibraryError("Import journal contains an unsafe relative path")
    return Path(*path.parts)


def _component(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", value)
    value = " ".join(value.split()).strip(". ") or "Unknown"
    value = value.encode("utf-8")[:120].decode("utf-8", errors="ignore").rstrip(". ")
    if value.upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(10)),
        *(f"LPT{i}" for i in range(10)),
    }:
        value = "_" + value
    return value


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _read_json(path: Path) -> dict:
    if path.is_symlink():
        raise LibraryError("Import state cannot be a symlink")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise LibraryError(f"Invalid import state in {path}; inspect it before retrying") from None
    if not isinstance(value, dict):
        raise LibraryError(f"Import state in {path} must be a JSON object")
    return value


class AudiobookStore:
    """A journal and private staging directory per Hardcover work and library."""

    def __init__(self, library_path: str, library_id: str, staging_path: str | None = None):
        self.library = Path(library_path).resolve()
        self.staging = (
            Path(staging_path)
            if staging_path
            else self.library.parent / f".murid-staging-{self.library.name}"
        ).resolve()
        self.library_id = library_id

    def key(self, book: Book) -> str:
        """Never use arbitrary source identifiers as filesystem paths."""
        if (
            book.source != "hardcover"
            or not str(book.id).isascii()
            or not str(book.id).isdigit()
            or int(book.id) <= 0
        ):
            raise LibraryError("Audiobook import requires a positive Hardcover work ID")
        library_key = hashlib.sha256(self.library_id.encode()).hexdigest()[:16]
        return f"{library_key}-hardcover-{book.id}"

    def validate(self) -> None:
        """Check actual filesystem placement before copying anything."""
        if not self.library.is_dir():
            raise LibraryError("Audiobook library_path must be an existing shared directory")
        if not os.access(self.library, os.R_OK | os.W_OK | os.X_OK):
            raise LibraryError("Audiobook library_path must be readable and writable by Murid")
        if self.staging.is_relative_to(self.library):
            raise LibraryError("Audiobook staging_path must be outside the scanned library")
        ancestor = self.staging
        while not ancestor.exists():
            if ancestor.parent == ancestor:
                raise LibraryError("The staging filesystem is not accessible")
            ancestor = ancestor.parent
        if ancestor.stat().st_dev != self.library.stat().st_dev:
            raise LibraryError("staging_path and library_path must be on the same filesystem")

    def lock(self, book: Book):
        """Serialize a work across processes, including scan verification."""
        self.validate()
        durable_mkdir(self.staging)
        path = self.staging / f"{self.key(book)}.lock"
        if path.is_symlink():
            raise LibraryError("Import lock cannot be a symlink")
        return import_lock(path)

    def _journal(self, book: Book) -> Path:
        return self.staging / f"{self.key(book)}.json"

    def _partial(self, manifest: dict) -> Path:
        return self.staging / (manifest["key"] + ".partial")

    def load(self, book: Book, folder_id: str) -> dict | None:
        """Use the persisted destination even if the source or book title has changed."""
        journal = self._journal(book)
        if not journal.exists() and not journal.is_symlink():
            return None
        manifest = _read_json(journal)
        expected = {
            "version": 1,
            "key": self.key(book),
            "library_id": self.library_id,
            "folder_id": folder_id,
            "hardcover_id": str(book.id),
            "media_type": "audiobook",
            "library_path": str(self.library),
        }
        if any(manifest.get(key) != value for key, value in expected.items()):
            raise LibraryError(
                "Import journal identity or folder mapping changed; inspect it before retrying"
            )
        if manifest.get("phase") not in {"copying", "copied", "verified"}:
            raise LibraryError("Import journal has an unknown phase")
        _relative(manifest.get("destination", ""))
        if not isinstance(manifest.get("files"), list) or not manifest["files"]:
            raise LibraryError("Import journal has no expected files")
        for entry in manifest["files"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise LibraryError("Import journal contains invalid file paths")
            _relative(entry["path"])
            valid_size = (
                isinstance(entry.get("size"), int)
                and not isinstance(entry["size"], bool)
                and entry["size"] >= 0
            )
            valid_digest = isinstance(entry.get("sha256"), str) and re.fullmatch(
                r"[0-9a-f]{64}", entry["sha256"]
            )
            if not valid_size or not valid_digest or not isinstance(entry.get("audio"), bool):
                raise LibraryError("Import journal has invalid file fingerprints")
        if not any(entry.get("audio") for entry in manifest["files"]):
            raise LibraryError("Import journal has no expected audio")
        if len({entry["path"] for entry in manifest["files"]}) != len(manifest["files"]):
            raise LibraryError("Import journal contains duplicate file paths")
        if (
            not isinstance(manifest.get("source_root"), str)
            or not Path(manifest["source_root"]).is_absolute()
            or not isinstance(manifest.get("metadata"), dict)
        ):
            raise LibraryError("Import journal contains invalid source or metadata")
        return manifest

    def plan(
        self, book: Book, source: str, matcher: BookMatcher, filetypes: list[str], folder_id: str
    ) -> dict:
        """Build a complete immutable source inventory before writing the journal."""
        if (self.staging / (self.key(book) + ".partial")).exists():
            raise LibraryError(
                "Unowned staging directory exists without a journal; inspect it first"
            )
        selection = select_audiobook(book, source, matcher, filetypes)
        if selection.root.is_relative_to(self.library) or selection.root.is_relative_to(
            self.staging
        ):
            raise LibraryError(
                "Audio source must be outside Murid's destination and staging directories"
            )
        if self.library.is_relative_to(selection.root) or self.staging.is_relative_to(
            selection.root
        ):
            raise LibraryError("Audio source must not contain destination or staging directories")
        files = []
        for relative in (*selection.audio, *selection.sidecars):
            _relative(relative.as_posix())
            path = selection.root / relative
            size = path.stat().st_size
            if relative in selection.audio and size == 0:
                raise LibraryError("Audio source contains an empty track")
            files.append(
                {
                    "path": relative.as_posix(),
                    "size": size,
                    "sha256": _digest(path),
                    "audio": relative in selection.audio,
                }
            )
        author = _component(book.authors[0] if book.authors else "Unknown Author")
        destination = f"{author}/{_component(book.title)} [hardcover-{book.id}]"
        return {
            "version": 1,
            "key": self.key(book),
            "library_id": self.library_id,
            "folder_id": folder_id,
            "hardcover_id": str(book.id),
            "media_type": "audiobook",
            "library_path": str(self.library),
            "book": asdict(book),
            "destination": destination,
            "files": files,
            "source_root": str(selection.root),
            "metadata": self._metadata(book, selection),
            "phase": "copying",
        }

    @staticmethod
    def _metadata(book: Book, selection) -> dict:
        """Keep supplied edition metadata; add work defaults and a stable identity tag."""
        metadata = {}
        if Path("metadata.json") in selection.sidecars:
            metadata = _read_json(selection.root / "metadata.json")
        nested = metadata.get("metadata") or {}
        if not isinstance(nested, dict):
            raise LibraryError("Source metadata.json metadata must be an object")
        for key, value in {"title": book.title, "authors": book.authors}.items():
            if key not in metadata and key not in nested:
                metadata[key] = value
        if book.series and "series" not in metadata and "series" not in nested:
            position = f" #{book.series_number:g}" if book.series_number is not None else ""
            metadata["series"] = [book.series + position]
        tag_groups = [metadata.get("tags", []), nested.get("tags", [])]
        if not all(
            isinstance(tags, list) and all(isinstance(tag, str) for tag in tags)
            for tags in tag_groups
        ):
            raise LibraryError("Source metadata tags must be a list of strings")
        tags = tag_groups[0] + tag_groups[1]
        metadata["tags"] = list(dict.fromkeys([*tags, f"murid:hardcover:{book.id}"]))
        if "tags" in nested:
            metadata["metadata"] = {**nested, "tags": metadata["tags"]}
        return metadata

    def save(self, manifest: dict) -> None:
        """A journal survives interrupted copies and delayed or failed scans."""
        write_json(self.staging / (manifest["key"] + ".json"), manifest)

    @staticmethod
    def _marker(manifest: dict) -> dict:
        return {
            key: manifest[key]
            for key in (
                "version",
                "library_id",
                "folder_id",
                "hardcover_id",
                "media_type",
                "destination",
            )
        } | {"audio_files": [entry for entry in manifest["files"] if entry["audio"]]}

    def _owned(self, destination: Path, manifest: dict) -> None:
        """Existing directories must have our exact identity and unchanged audio."""
        if destination.is_symlink() or not destination.is_dir():
            raise LibraryError(f"Audiobook destination collision at {destination}")
        marker = destination / IMPORT_MARKER
        if not marker.is_file() or _read_json(marker) != self._marker(manifest):
            raise LibraryError(f"Unrelated content at {destination}; refusing to overwrite it")
        expected = {entry["path"] for entry in manifest["files"] if entry["audio"]}
        actual = {
            p.relative_to(destination).as_posix()
            for p in destination.rglob("*")
            if p.suffix.lower() in AUDIO_EXTENSIONS and p.is_file()
        }
        if actual != expected:
            raise LibraryError("Published audio no longer matches the import manifest")
        for entry in manifest["files"]:
            if entry["audio"] and not self._matches(destination / _relative(entry["path"]), entry):
                raise LibraryError(
                    "Published audio changed; inspect the destination before retrying"
                )

    @staticmethod
    def _matches(path: Path, entry: dict) -> bool:
        return (
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_size == entry["size"]
            and _digest(path) == entry["sha256"]
        )

    @staticmethod
    def _copy(source: Path, target: Path, entry: dict) -> None:
        if source.is_symlink() or not source.is_file():
            raise LibraryError(f"Source track or sidecar is unavailable: {source}")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=target.parent, prefix=".murid-copy-", suffix=".tmp", delete=False
            ) as stream:
                temporary = Path(stream.name)
                digest = hashlib.sha256()
                with source.open("rb") as incoming:
                    while chunk := incoming.read(1024 * 1024):
                        stream.write(chunk)
                        digest.update(chunk)
                stream.flush()
                os.chmod(temporary, 0o644)
                os.fsync(stream.fileno())
            if temporary.stat().st_size != entry["size"] or digest.hexdigest() != entry["sha256"]:
                raise LibraryError(
                    "Audio source changed after planning; inspect it before retrying"
                )
            os.replace(temporary, target)
            sync_directory(target.parent)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def publish(self, manifest: dict) -> Path:
        """Resume our staged files, then publish a complete folder without replacement."""
        destination = self.library / _relative(manifest["destination"])
        if destination.parent.is_symlink():
            raise LibraryError("Destination author directory cannot be a symlink")
        if destination.exists() or destination.is_symlink():
            self._owned(destination, manifest)
            # A previous rename may have completed before its parent sync did.
            sync_directory(destination.parent)
        else:
            partial = self._stage(manifest, destination)
            publish_directory(partial, destination)
        manifest["phase"] = "copied"
        self.save(manifest)
        return destination

    def _stage(self, manifest: dict, destination: Path) -> Path:
        """Recover our private copy, leaving incomplete content outside the library."""
        partial = self._partial(manifest)
        if partial.is_symlink():
            raise LibraryError("Staging directory cannot be a symlink")
        partial.mkdir(exist_ok=True)
        partial.chmod(0o755)
        if any(p.is_symlink() for p in partial.rglob("*")):
            raise LibraryError("Staging content cannot contain symlinks")
        ensure_shared_directory(destination.parent, self.staging / (manifest["key"] + ".author"))
        if destination.parent.stat().st_dev != partial.stat().st_dev:
            raise LibraryError("Staging and destination must be on the same filesystem")
        # Root metadata.json is generated from the durable manifest, not copied source bytes.
        source_files = [entry for entry in manifest["files"] if entry["path"] != "metadata.json"]
        for entry in source_files:
            relative = _relative(entry["path"])
            target = partial / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            for parent in target.parents:
                if parent == partial:
                    break
                parent.chmod(0o755)
            if not self._matches(target, entry):
                self._copy(Path(manifest["source_root"]) / relative, target, entry)
        allowed = {entry["path"] for entry in manifest["files"]} | {
            "metadata.json",
            IMPORT_MARKER,
        }
        self._clean_temporary_files(partial, allowed)
        if any(
            p.is_file() and p.relative_to(partial).as_posix() not in allowed
            for p in partial.rglob("*")
        ):
            raise LibraryError("Unexpected staging content; inspect it before retrying")
        write_json(partial / "metadata.json", manifest["metadata"], mode=0o644)
        write_json(partial / IMPORT_MARKER, self._marker(manifest), mode=0o644)
        for directory in sorted((p for p in partial.rglob("*") if p.is_dir()), reverse=True):
            sync_directory(directory)
        sync_directory(partial)
        return partial

    @staticmethod
    def _clean_temporary_files(partial: Path, allowed: set[str]) -> None:
        """Remove interrupted writes from our private staging area, preserving source files."""
        candidates = set(partial.glob(".murid-*")) | set(partial.rglob(".murid-copy-*.tmp"))
        for orphan in candidates:
            if orphan.is_file() and orphan.relative_to(partial).as_posix() not in allowed:
                orphan.unlink()
