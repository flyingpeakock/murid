"""Inspect Audiobookshelf v2.37.1 libraries and verify shared-folder imports."""

import math
import time
from urllib.parse import quote

import requests

from ..domain.book import Book
from ..libraries.library import LibraryError


class AudiobookshelfError(LibraryError):
    """Audiobookshelf is unavailable or returned an unusable response."""


class Audiobookshelf:
    """Authenticated library inspection and scan requests; files use the shared mount."""

    PAGE_SIZE = 100

    def __init__(self, url: str, api_key: str, library_id: str, *, session=None):
        self.url = url.rstrip("/")
        self.library_id = library_id
        self.session = session if session is not None else requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}"})

    @staticmethod
    def _timeout(deadline: float | None) -> float:
        remaining = 30 if deadline is None else min(30, deadline - time.monotonic())
        if remaining <= 0:
            raise AudiobookshelfError("Audiobookshelf verification deadline expired")
        return remaining

    def _get(self, path: str, *, deadline: float | None = None, **params) -> dict:
        try:
            response = self.session.get(
                f"{self.url}{path}",
                params=params,
                timeout=self._timeout(deadline),
                allow_redirects=False,
            )
        except requests.RequestException:
            # Request exception strings can contain URLs, headers, and credentials.
            raise AudiobookshelfError(
                "Audiobookshelf request failed; check server access"
            ) from None
        if response.status_code != 200:
            raise AudiobookshelfError(f"Audiobookshelf returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            raise AudiobookshelfError("Audiobookshelf returned invalid JSON") from None
        if not isinstance(payload, dict):
            raise AudiobookshelfError("Audiobookshelf returned an invalid response object")
        return payload

    def server_version(self) -> str:
        """Read the server version without requiring library mutations."""
        version = self._get("/status").get("serverVersion")
        if not isinstance(version, str) or not version:
            raise AudiobookshelfError("Audiobookshelf returned an invalid server version")
        return version

    def get_library(self, *, deadline: float | None = None) -> dict:
        """Require the configured book library, rather than assuming an empty library."""
        library = self._get(f"/api/libraries/{quote(self.library_id, safe='')}", deadline=deadline)
        if library.get("id") != self.library_id or library.get("mediaType") != "book":
            raise AudiobookshelfError("Audiobookshelf target must be the configured book library")
        return library

    def _items(self, *, deadline: float | None = None) -> list[dict]:
        self.get_library(deadline=deadline)
        items = []
        seen = set()
        total = None
        page = 0
        while True:
            payload = self._get(
                f"/api/libraries/{quote(self.library_id, safe='')}/items",
                limit=self.PAGE_SIZE,
                page=page,
                sort="addedAt",
                collapseseries=0,
                deadline=deadline,
            )
            results, count = payload.get("results"), payload.get("total")
            valid_count = isinstance(count, int) and not isinstance(count, bool) and count >= 0
            if (
                not isinstance(results, list)
                or not valid_count
                or (total is not None and count != total)
                or len(results) > self.PAGE_SIZE
            ):
                raise AudiobookshelfError("Audiobookshelf returned inconsistent pagination")
            total = count
            for item in results:
                item_id = item.get("id") if isinstance(item, dict) else None
                if not isinstance(item_id, str) or not item_id or item_id in seen:
                    raise AudiobookshelfError(
                        "Audiobookshelf returned invalid or repeated item IDs"
                    )
                seen.add(item_id)
            items.extend(results)
            if len(items) > total or (not results and len(items) < total):
                raise AudiobookshelfError("Audiobookshelf pagination ended inconsistently")
            if len(items) == total:
                return items
            page += 1

    def _usable_item(self, item: dict) -> bool:
        if item.get("libraryId") != self.library_id or item.get("mediaType") != "book":
            raise AudiobookshelfError("Audiobookshelf returned an item from an unexpected library")
        if any(not isinstance(item.get(flag), bool) for flag in ("isMissing", "isInvalid")):
            raise AudiobookshelfError("Audiobookshelf item is missing validity flags")
        if item["isMissing"] or item["isInvalid"]:
            return False
        media = item.get("media")
        if (
            not isinstance(media, dict)
            or not isinstance(media.get("numTracks"), int)
            or isinstance(media.get("numTracks"), bool)
        ):
            raise AudiobookshelfError("Audiobookshelf item is missing audio track information")
        if media["numTracks"] < 0:
            raise AudiobookshelfError("Audiobookshelf returned an invalid audio track count")
        return media["numTracks"] > 0

    def get_books(self) -> set[Book]:
        """Read usable audio; expanded details preserve author boundaries and track state."""
        books = set()
        for item in self._items():
            if not self._usable_item(item):
                continue
            detail = self._get(f"/api/items/{quote(item['id'], safe='')}", expanded=1)
            if detail.get("id") != item["id"]:
                raise AudiobookshelfError("Audiobookshelf returned an unexpected item identity")
            if not self._usable_item(detail):
                continue
            tracks = detail["media"].get("tracks")
            if not isinstance(tracks, list):
                raise AudiobookshelfError("Audiobookshelf expanded item is missing audio tracks")
            if not tracks:
                continue
            if not all(
                isinstance(track, dict)
                and isinstance(track.get("duration"), (int, float))
                and not isinstance(track["duration"], bool)
                and math.isfinite(track["duration"])
                and track["duration"] > 0
                and not track.get("exclude", False)
                for track in tracks
            ):
                continue
            books.add(self._book(detail))
        return books

    def require_scan_access(self) -> None:
        """Reject insufficient permissions before copying into the shared library."""
        user = self._get("/api/me")
        if user.get("type") not in {"admin", "root"} or user.get("isActive") is not True:
            raise AudiobookshelfError("Audiobook import requires an active admin/root API user")

    def get_libraries(self) -> list[dict]:
        """Read visible library roots so staging can remain outside scanned directories."""
        libraries = self._get("/api/libraries").get("libraries")
        if not isinstance(libraries, list) or not all(isinstance(lib, dict) for lib in libraries):
            raise AudiobookshelfError("Audiobookshelf returned invalid library roots")
        return libraries

    def scan_library(self, *, deadline: float | None = None) -> None:
        """Request a scan; HTTP 200 means accepted, never verified ingestion."""
        try:
            response = self.session.post(
                f"{self.url}/api/libraries/{quote(self.library_id, safe='')}/scan",
                timeout=self._timeout(deadline),
                allow_redirects=False,
            )
        except requests.RequestException:
            raise AudiobookshelfError(
                "Audiobookshelf scan request failed; retry verification"
            ) from None
        if response.status_code != 200:
            raise AudiobookshelfError(f"Audiobookshelf scan returned HTTP {response.status_code}")

    def verify_import(self, manifest: dict, *, deadline: float | None = None) -> bool:
        """Verify the exact destination, included tracks, sizes, and work identity tag."""
        candidates = [
            item
            for item in self._items(deadline=deadline)
            if item.get("folderId") == manifest["folder_id"]
            and item.get("relPath") == manifest["destination"]
        ]
        if len(candidates) > 1:
            raise AudiobookshelfError("Multiple Audiobookshelf items occupy the import destination")
        if not candidates or not self._usable_item(candidates[0]):
            return False
        item_id = candidates[0]["id"]
        detail = self._get(f"/api/items/{quote(item_id, safe='')}", expanded=1, deadline=deadline)
        if (
            detail.get("id") != item_id
            or detail.get("folderId") != manifest["folder_id"]
            or detail.get("relPath") != manifest["destination"]
        ):
            raise AudiobookshelfError(
                "Audiobookshelf destination identity changed during verification"
            )
        if not self._usable_item(detail):
            return False
        media = detail["media"]
        tracks = media.get("tracks")
        expected = {entry["path"]: entry["size"] for entry in manifest["files"] if entry["audio"]}
        if (
            not isinstance(tracks, list)
            or len(tracks) != len(expected)
            or media["numTracks"] != len(expected)
        ):
            return False
        observed = self._track_inventory(tracks)
        tags = media.get("tags")
        return (
            observed == expected
            and isinstance(tags, list)
            and f"murid:hardcover:{manifest['hardcover_id']}" in tags
        )

    @staticmethod
    def _track_inventory(tracks: list) -> dict | None:
        """Keep included, playable track paths and sizes; reject duplicates."""
        observed = {}
        for track in tracks:
            if (
                not isinstance(track, dict)
                or not isinstance(track.get("duration"), (int, float))
                or isinstance(track["duration"], bool)
                or not math.isfinite(track["duration"])
                or track["duration"] <= 0
            ):
                return None
            if track.get("exclude"):
                return None
            metadata = track.get("metadata")
            if not isinstance(metadata, dict) or not isinstance(metadata.get("relPath"), str):
                return None
            relative = metadata["relPath"]
            if (
                relative in observed
                or not isinstance(metadata.get("size"), int)
                or isinstance(metadata["size"], bool)
            ):
                return None
            observed[relative] = metadata.get("size")
        return observed

    @staticmethod
    def _book(item: dict) -> Book:
        media = item["media"]
        metadata, tags = media.get("metadata"), media.get("tags")
        if not isinstance(metadata, dict) or not isinstance(tags, list):
            raise AudiobookshelfError("Audiobookshelf item is missing book metadata")
        title, authors = metadata.get("title"), metadata.get("authors")
        if not isinstance(title, str) or not title or not isinstance(authors, list):
            raise AudiobookshelfError("Audiobookshelf returned invalid title or authors")
        if not all(
            isinstance(author, dict) and isinstance(author.get("name"), str) for author in authors
        ):
            raise AudiobookshelfError("Audiobookshelf returned invalid author metadata")
        hardcover_ids = [
            tag.removeprefix("murid:hardcover:")
            for tag in tags
            if isinstance(tag, str)
            and tag.startswith("murid:hardcover:")
            and tag.removeprefix("murid:hardcover:").isdigit()
        ]
        series, series_number = Audiobookshelf._series(metadata)
        # Do not compare ebook-edition ISBNs/ASINs to audiobook-edition identifiers.
        # Work identity tags and existing title/author matching are sufficient here.
        return Book(
            id=item["id"],
            title=title,
            authors=[author["name"] for author in authors],
            isbn=[],
            source="audiobookshelf",
            series=series,
            series_number=series_number,
            identifiers={"hardcover": hardcover_ids} if hardcover_ids else {},
        )

    @staticmethod
    def _series(metadata: dict) -> tuple[str | None, float | None]:
        """Map the first series, consistent with Hardcover's single-series Book metadata."""
        entries = metadata.get("series")
        if entries is None or entries == []:
            return None, None
        if not isinstance(entries, list) or not isinstance(entries[0], dict):
            raise AudiobookshelfError("Audiobookshelf returned invalid series metadata")
        series = entries[0]
        name = series.get("name")
        if not isinstance(name, str) or not name.strip():
            raise AudiobookshelfError("Audiobookshelf returned invalid series name")
        sequence = series.get("sequence")
        try:
            number = (
                float(sequence) if sequence is not None and not isinstance(sequence, bool) else None
            )
        except (TypeError, ValueError):
            number = None
        if number is not None and not math.isfinite(number):
            number = None
        return name, number
