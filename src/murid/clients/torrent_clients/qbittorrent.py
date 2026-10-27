"""qBittorrent client implementation for Murid."""

import logging
import ntpath
import re
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

import qbittorrentapi

from ...domain.book import Book
from ...domain.book_request import BookRequest, MediaType
from ...domain.torrent_metadata import TorrentMetainfo
from ...domain.torrent_request import (
    TAG_ALIASES,
    read_request,
    read_request_comment,
    request_identity,
    torrent_tags,
    write_request_comment,
)
from .torrent_client import TorrentClient, TorrentClientError

logger = logging.getLogger("murid")


class QbittorrentError(TorrentClientError):
    """A qBittorrent operation failed before it could start."""


@dataclass
class QbittorrentConfig:
    """Configuration for the qBittorrent client."""

    client: qbittorrentapi.Client
    category: str
    dry_run: bool
    mapping: dict[str, str] | None = None


class Qbittorrent(TorrentClient):
    """Torrent client implementation for qBittorrent."""

    def __init__(self, config: QbittorrentConfig, poll_interval=2) -> None:
        """Initialize the qBittorrent client with the provided parameters."""
        self.client = config.client
        self.category = config.category
        self.poll_interval = poll_interval
        self.dry_run = config.dry_run
        self.mapping = config.mapping
        self._cleaned_tags = False
        self._validate()

    def _validate(self) -> None:
        """Validate the connection to qBittorrent by attempting to log in."""
        try:
            self.client.auth_log_in()
            logger.debug("Successfully authenticated with qBittorrent")
            self.client.auth_log_out()
        except qbittorrentapi.LoginFailed as e:
            raise QbittorrentError(f"Failed to authenticate with qBittorrent: {e}") from e
        logger.debug("qBittorrent version: %s", self.client.app.version)
        logger.debug("qBittorrent API version: %s", self.client.app.web_api_version)

    def add_torrent(
        self, torrent_file: bytes, book: Book, *, media_type: MediaType = "ebook"
    ) -> str | None:
        """Add a torrent to qBittorrent and return its ID."""
        if self.dry_run:
            return None
        identity = request_identity(BookRequest(book, media_type))
        try:
            metainfo = TorrentMetainfo(torrent_file)
            torrent_file = metainfo.with_identity(identity)
        except ValueError as error:
            raise QbittorrentError(f"Invalid torrent metainfo: {error}") from error
        if not self._cleaned_tags:
            self.get_torrents(migrate=True, media_type=media_type)
        hashes = "|".join(metainfo.hashes)
        existing = self._existing_torrent(hashes, identity)
        if existing is not None:
            return existing
        try:
            tinfo = self.client.torrents_add(
                torrent_files=torrent_file,
                category=self.category,
                tags="murid",
            )

            if isinstance(tinfo, str):
                if tinfo.strip() != "Ok.":
                    logger.error("%s: failed to add to qBittorrent: %s", book, tinfo)
                    return None
            elif len(tinfo.added_torrent_ids) != 1:
                logger.error("%s: could not identify the added torrent", book)
                return None

            torrent_id = self._await_torrent(hashes, identity)
            if torrent_id is not None:
                logger.info("%s: added to qBittorrent", book)
                return torrent_id
            logger.error("%s: could not identify the added torrent", book)

        except qbittorrentapi.UnsupportedMediaType415Error:
            logger.error("%s: failed to add to qBittorrent: unsupported media type", book)
        except qbittorrentapi.TorrentFileNotFoundError:
            logger.error("%s: failed to add to qBittorrent: torrent file not found", book)
        except qbittorrentapi.TorrentFilePermissionError:
            logger.error("%s: failed to add to qBittorrent: torrent file permission error", book)
        except qbittorrentapi.Conflict409Error:
            logger.error("%s: failed to add to qBittorrent: torrent already downloaded", book)
        return None

    def _existing_torrent(self, hashes, identity) -> str | None:
        """Reuse a matching request without overwriting another book or category."""
        existing = self.client.torrents_info(torrent_hashes=hashes)
        if not existing:
            return None
        if len(existing) != 1:
            raise QbittorrentError("Multiple torrents match the request's info hashes")
        torrent = existing[0]
        self._load_comment(torrent)
        try:
            if read_request(torrent) != identity or (
                read_request_comment(torrent.comment) is None
                and not any(tag.startswith("murid_media_") for tag in torrent_tags(torrent))
            ):
                raise ValueError("Torrent has conflicting or missing Murid request identity")
        except ValueError as error:
            raise QbittorrentError(f"{error}; inspect torrent {torrent.hash}") from error
        if torrent.category != self.category:
            raise QbittorrentError(f"Torrent {torrent.hash} already belongs to another category")
        self._migrate_torrent(torrent)
        self.add_tag(torrent.hash, "murid")
        return torrent.hash

    def _await_torrent(self, hashes, identity) -> str | None:
        """Resolve adds by their exact hash, including APIs that only return 'Ok.'."""
        for attempt in range(10):
            torrents = self.client.torrents_info(category=self.category, torrent_hashes=hashes)
            if torrents:
                if len(torrents) != 1:
                    raise QbittorrentError("Multiple torrents match the added request")
                torrent = torrents[0]
                self._load_comment(torrent)
                try:
                    if (
                        read_request_comment(torrent.comment) != identity
                        or read_request(torrent) != identity
                        or "murid" not in torrent_tags(torrent)
                    ):
                        raise ValueError("Request identity was not persisted")
                except ValueError as error:
                    raise QbittorrentError(f"{error}; inspect torrent {torrent.hash}") from error
                return torrent.hash
            if attempt < 9:
                time.sleep(self.poll_interval)
        return None

    def _load_comment(self, torrent) -> None:
        """Older list endpoints omit comments; read the torrent's properties instead."""
        if not isinstance(getattr(torrent, "comment", None), str):
            torrent.comment = self.client.torrents_properties(torrent_hash=torrent.hash).comment

    @staticmethod
    def _obsolete_tag(tag: str) -> bool:
        return tag in TAG_ALIASES or bool(
            re.fullmatch(
                r"murid_(?:add_[0-9a-f]{32}|hardcover_[1-9][0-9]*|media_(?:ebook|audiobook))", tag
            )
        )

    def _migrate_torrent(self, torrent) -> None:
        """Publish and verify identity before removing its legacy representation."""
        tags = torrent_tags(torrent)
        identity_tags = {
            tag for tag in tags if tag.startswith(("murid_media_", "murid_hardcover_"))
        }
        identity = read_request(torrent)
        if identity_tags or tags & (set(TAG_ALIASES) | set(TAG_ALIASES.values())):
            comment = write_request_comment(torrent.comment, identity)
            if comment != torrent.comment:
                self.client.torrents_set_comment(comment=comment, torrent_hashes=torrent.hash)
                persisted = self.client.torrents_properties(torrent_hash=torrent.hash).comment
                if persisted != comment.strip() or read_request_comment(persisted) != identity:
                    raise QbittorrentError(
                        f"Comment migration was not persisted for torrent {torrent.hash}; "
                        "qBittorrent must support Web API 2.12.1 or newer"
                    )
                torrent.comment = persisted
        for old, new in TAG_ALIASES.items():
            if old in tags:
                self.add_tag(torrent.hash, new)
                tags.add(new)
        required = {new for old, new in TAG_ALIASES.items() if old in tags}
        if required:
            persisted = self.client.torrents_info(torrent_hashes=torrent.hash)
            if len(persisted) != 1 or not required <= torrent_tags(persisted[0]):
                raise QbittorrentError(
                    f"Lifecycle tag migration was not persisted for {torrent.hash}"
                )
        obsolete = identity_tags | {
            tag
            for tag in tags
            if tag in TAG_ALIASES or re.fullmatch(r"murid_add_[0-9a-f]{32}", tag)
        }
        for tag in sorted(obsolete):
            self.remove_tag(torrent.hash, tag)
        torrent.tags = ",".join(sorted(tags - obsolete))

    def _cleanup_tags(self) -> None:
        """Delete only unused legacy definitions, checking torrents in all categories."""
        obsolete = {tag for tag in self.client.torrents_tags() if self._obsolete_tag(tag)}
        if obsolete:
            used = set().union(*(torrent_tags(t) for t in self.client.torrents_info()))
            unused = obsolete - used
            if unused:
                self.client.torrents_delete_tags(tags=",".join(sorted(unused)))
        self._cleaned_tags = True

    def get_completed_path(self, torrent_id: str) -> str | None:
        """Get the completed path of a torrent by its ID, or None if it's not yet completed."""
        torrents = self.client.torrents_info(torrent_hashes=torrent_id)
        if not torrents:
            logger.warning("Torrent %s is no longer available in qBittorrent", torrent_id)
            return None
        if torrents[0].progress < 1:
            return None

        time.sleep(0.3)  # Give qBittorrent a moment to update the content path
        torrents = self.client.torrents_info(torrent_hashes=torrent_id)
        if not torrents or torrents[0].progress < 1:
            return None
        path = torrents[0].content_path

        if self.mapping and self.mapping["qbit_path"] and self.mapping["murid_path"]:
            # qBittorrent may run on a different OS from Murid. Parse its path
            # lexically using the source syntax, then join using the local OS.
            source = self.mapping["qbit_path"]
            windows_path = bool(ntpath.splitdrive(source)[0]) or "\\" in source
            path_type = PureWindowsPath if windows_path else PurePosixPath
            try:
                relative = path_type(path).relative_to(path_type(source))
            except ValueError:
                pass
            else:
                if ".." not in relative.parts:
                    path = str(Path(self.mapping["murid_path"]).joinpath(*relative.parts))

        return path

    def add_tag(self, torrent_id: str, tag: str) -> None:
        """Add a tag to a torrent by its ID."""
        if not self.dry_run:
            self.client.torrents_add_tags(tags=TAG_ALIASES.get(tag, tag), torrent_hashes=torrent_id)

    def remove_tag(self, torrent_id: str, tag: str) -> None:
        """Remove a tag from a torrent by its ID."""
        if not self.dry_run:
            self.client.torrents_remove_tags(tags=tag, torrent_hashes=torrent_id)

    def get_torrents_with_tag(self, tag: str) -> list:
        """Get a list of torrent IDs that have the specified tag."""
        canonical = TAG_ALIASES.get(tag, tag)
        torrents = [
            t
            for t in self.client.torrents_info(category=self.category)
            if canonical in {TAG_ALIASES.get(value, value) for value in torrent_tags(t)}
        ]
        for torrent in torrents:
            self._load_comment(torrent)
        return torrents

    def get_torrents(self, *, migrate: bool = False, media_type: MediaType | None = None) -> list:
        """Read and optionally migrate selected media, retaining invalid identity for reporting."""
        torrents = self.client.torrents_info(category=self.category)
        selected = []
        for torrent in torrents:
            self._load_comment(torrent)
            try:
                if media_type is not None and read_request(torrent)[0] != media_type:
                    continue
                if migrate and not self.dry_run:
                    self._migrate_torrent(torrent)
            except ValueError as error:
                logger.error("Torrent %s: invalid request metadata: %s", torrent.hash, error)
            selected.append(torrent)
        if migrate and not self.dry_run:
            self._cleanup_tags()
        return selected if media_type is not None else torrents
