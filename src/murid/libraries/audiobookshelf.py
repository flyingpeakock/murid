"""Audiobook copies and verified ingestion through the shared library folder."""

import logging
import os
import posixpath
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from ..clients.audiobookshelf import Audiobookshelf, AudiobookshelfError
from ..domain.audiobook_files import AudiobookSelectionError
from ..domain.book import Book
from ..domain.book_matcher import BookMatcher
from .audiobook_store import AudiobookStore
from .library import LibraryError, LibraryImportPending

logger = logging.getLogger("murid")


@dataclass
class AudiobookLibraryConfig:
    """Filesystem placement and the separate ingestion verification deadline."""

    library_path: str | None = None
    staging_path: str | None = None
    folder_id: str | None = None
    filetypes: list[str] = field(default_factory=lambda: ["m4b", "mp3"])
    scan_timeout_seconds: int = 120
    dry_run: bool = False


class AudiobookshelfLibrary:
    """Expose usable audio and publish complete copies without altering seed files."""

    name = "Audiobookshelf"

    def __init__(self, client: Audiobookshelf, config: AudiobookLibraryConfig | None = None):
        self.client = client
        self.config = config or AudiobookLibraryConfig()

    def get_books(self) -> set[Book]:
        """Read usable audio items and work-level metadata."""
        return self.client.get_books()

    def contains_book(self, book: Book, matcher: BookMatcher) -> bool:
        """Reuse work matching without ebook-edition identifiers."""
        return any(matcher.is_match(book, candidate) for candidate in self.get_books())

    def has_import_state(self, book: Book) -> bool:
        """Allow manual retries to verify their journal even if general presence matches."""
        if not self.config.library_path:
            return False
        store = AudiobookStore(
            self.config.library_path, self.client.library_id, self.config.staging_path
        )
        return store.has_state(book)

    def check_connection(self) -> str:
        """Inspect import prerequisites without creating directories, copying, or scanning."""
        if not self.config.library_path:
            raise LibraryError("Audiobook import requires a configured shared library_path")
        store = AudiobookStore(
            self.config.library_path, self.client.library_id, self.config.staging_path
        )
        store.validate()
        self.client.require_scan_access()
        folder_id = self._folder(store)
        version = self.client.server_version()
        count = len(self.get_books())
        return (
            f"v{version}; {count} usable audio items; active admin/root; folder {folder_id}; "
            "shared library/staging access checked (mount contents not verified)"
        )

    def _folder(self, store: AudiobookStore) -> str:
        library = self.client.get_library()
        folders = library.get("folders")
        if not isinstance(folders, list) or not folders:
            raise LibraryError("Audiobookshelf library has no configured folders")
        matches = [
            folder
            for folder in folders
            if isinstance(folder, dict)
            and (self.config.folder_id is None or folder.get("id") == self.config.folder_id)
        ]
        if len(matches) != 1:
            raise LibraryError("Set audiobookshelf.folder_id to identify the shared library root")
        folder = matches[0]
        server_root = folder.get("fullPath") or folder.get("path")
        if (
            not isinstance(folder.get("id"), str)
            or not isinstance(server_root, str)
            or not server_root.startswith("/")
        ):
            raise LibraryError("Audiobookshelf returned invalid folder metadata")
        # Translate through the selected shared root, accounting for differing mount paths.
        relative_stage = os.path.relpath(store.staging, store.library).replace(os.sep, "/")
        server_stage = PurePosixPath(
            posixpath.normpath(posixpath.join(server_root, relative_stage))
        )
        for visible in self.client.get_libraries():
            roots = visible.get("folders")
            if not isinstance(roots, list):
                raise LibraryError("Audiobookshelf returned invalid scanned library roots")
            for root in roots:
                if not isinstance(root, dict):
                    raise LibraryError("Audiobookshelf returned invalid scanned library roots")
                root_path = root.get("fullPath") or root.get("path")
                if not isinstance(root_path, str) or not root_path.startswith("/"):
                    raise LibraryError("Audiobookshelf returned invalid scanned folder paths")
                if server_stage.is_relative_to(PurePosixPath(root_path)):
                    raise LibraryError(
                        "staging_path would be inside an Audiobookshelf scanned library"
                    )
        return folder["id"]

    def import_book(
        self,
        book: Book,
        path: str,
        matcher: BookMatcher,
        *,
        explicit_file: bool = False,
    ) -> None:
        """Stage, publish, scan, and verify every track; interrupted state remains retryable."""
        if not self.config.library_path:
            raise LibraryError("Audiobook import requires a configured shared library_path")
        if explicit_file and Path(path).is_dir():
            raise LibraryError("An explicitly selected audio file cannot be a directory")
        store = AudiobookStore(
            self.config.library_path, self.client.library_id, self.config.staging_path
        )
        try:
            store.validate()
            self.client.require_scan_access()
            folder_id = self._folder(store)
            if self.config.dry_run:
                manifest = store.load(book, folder_id) or store.plan(
                    book,
                    path,
                    matcher,
                    self.config.filetypes,
                    folder_id,
                )
                logger.info("%s: would import audio to %s", book, manifest["destination"])
                return
            with store.lock(book):
                manifest = store.load(book, folder_id)
                if manifest is None:
                    manifest = store.plan(book, path, matcher, self.config.filetypes, folder_id)
                    store.save(manifest)
                store.publish(manifest)
                self._verify(manifest)
                manifest["phase"] = "verified"
                store.save(manifest)
        except AudiobookSelectionError as error:
            raise LibraryError(str(error)) from error
        except OSError as error:
            raise LibraryError(f"Audiobook filesystem operation failed: {error}") from error

    def _verify(self, manifest: dict) -> None:
        deadline = time.monotonic() + self.config.scan_timeout_seconds
        try:
            if self.client.verify_import(manifest, deadline=deadline):
                return
            self.client.scan_library(deadline=deadline)
            while time.monotonic() < deadline:
                if self.client.verify_import(manifest, deadline=deadline):
                    return
                time.sleep(min(2, max(0, deadline - time.monotonic())))
        except AudiobookshelfError:
            if time.monotonic() < deadline:
                raise
        raise LibraryImportPending(
            "Audiobook copied but ingestion is not verified; retry this import to check the "
            "existing destination without another copy. Check scan permissions, folder mapping, "
            "tracks, "
            "and metadata tag precedence in Audiobookshelf"
        )
