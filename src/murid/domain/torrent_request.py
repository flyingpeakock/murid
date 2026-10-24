"""Persistent request identity in torrent comments, with legacy tag recovery."""

import json

from .book_request import BookRequest, MediaType

TAG_ALIASES = {
    "murid_pending": "murid",
    "murid_timeout": "murid-timeout",
    "murid_import_failed": "murid-import-failed",
}
IMPORT_TAGS = ("murid", "murid-timeout", "murid-import-failed")
_COMMENT_PREFIX = "[murid:"
_COMMENT_V1 = "[murid:1]"


def torrent_tags(torrent) -> set[str]:
    """Read tags without relying on qBittorrent's comma spacing."""
    return {tag.strip() for tag in (getattr(torrent, "tags", "") or "").split(",") if tag.strip()}


def request_identity(request: BookRequest) -> tuple[MediaType, int | None]:
    """Validate the identity before publishing a request to qBittorrent."""
    return read_request_tags(request_tags(request))


def read_request_comment(comment: str) -> tuple[MediaType, int | None] | None:
    """Reject malformed, duplicate and future metadata rather than guessing a medium."""
    lines = [line for line in comment.splitlines() if line.startswith(_COMMENT_PREFIX)]
    if not lines:
        return None
    if len(lines) != 1 or not lines[0].startswith(_COMMENT_V1):
        raise ValueError("Torrent has duplicate or unsupported Murid comment metadata")
    try:
        data = json.loads(lines[0][len(_COMMENT_V1) :])
    except (ValueError, TypeError) as error:
        raise ValueError("Torrent has invalid Murid comment metadata") from error
    if not isinstance(data, dict) or set(data) != {"media_type", "hardcover_id"}:
        raise ValueError("Torrent has invalid Murid comment metadata")
    media, work_id = data["media_type"], data["hardcover_id"]
    if media not in ("ebook", "audiobook") or (media == "audiobook" and work_id is None):
        raise ValueError("Torrent has invalid Murid comment identity")
    if work_id is not None and (
        not isinstance(work_id, int) or isinstance(work_id, bool) or work_id <= 0
    ):
        raise ValueError("Torrent has invalid Murid comment identity")
    return media, work_id


def write_request_comment(comment: str, identity: tuple[MediaType, int | None]) -> str:
    """Append identity while preserving the original tracker comment verbatim."""
    existing = read_request_comment(comment)
    if existing is not None:
        if existing != identity:
            raise ValueError("Torrent has conflicting Murid request identity")
        return comment
    media, work_id = identity
    metadata = json.dumps({"media_type": media, "hardcover_id": work_id}, separators=(",", ":"))
    result = comment + ("\n" if comment and not comment.endswith("\n") else "")
    result += _COMMENT_V1 + metadata
    read_request_comment(result)
    return result


def read_request(torrent) -> tuple[MediaType, int | None]:
    """Prefer comment identity, checking any remaining legacy tags for conflicts."""
    comment = getattr(torrent, "comment", "")
    identity = read_request_comment(comment if isinstance(comment, str) else "")
    tags = torrent_tags(torrent)
    if identity is None:
        return read_request_tags(tags)
    media, work_id = identity
    # A crash may leave only some legacy tags after the comment was verified.
    # Fill missing fields from the comment, retaining every conflicting old value.
    if not any(tag.startswith("murid_media_") for tag in tags):
        tags.add(f"murid_media_{media}")
    if work_id is not None and not any(tag.startswith("murid_hardcover_") for tag in tags):
        tags.add(f"murid_hardcover_{work_id}")
    if read_request_tags(tags) != identity:
        raise ValueError("Torrent has conflicting Murid comment and tag identity")
    return identity


def request_tags(request: BookRequest) -> set[str]:
    """Encode the legacy representation for validation and compatibility readers."""
    tags = {f"murid_media_{request.media_type}"}
    book = request.book
    if isinstance(book.source, str) and book.source.lower() == "hardcover":
        if isinstance(book.id, bool) or not str(book.id).isascii() or not str(book.id).isdigit():
            raise ValueError("Torrent request requires a positive Hardcover ID")
        if int(book.id) <= 0:
            raise ValueError("Torrent request requires a positive Hardcover ID")
        tags.add(f"murid_hardcover_{int(book.id)}")
    elif request.media_type == "audiobook":
        raise ValueError("Audiobook torrents require Hardcover work identity")
    return tags


def read_request_tags(tags: set[str]) -> tuple[MediaType, int | None]:
    """Untagged legacy torrents are ebooks; inconsistent identities require intervention."""
    media = {tag.removeprefix("murid_media_") for tag in tags if tag.startswith("murid_media_")}
    if media and (len(media) != 1 or not media <= {"ebook", "audiobook"}):
        raise ValueError("Torrent has conflicting or unknown Murid media tags")
    medium: MediaType = "audiobook" if media == {"audiobook"} else "ebook"
    ids = {
        tag.removeprefix("murid_hardcover_") for tag in tags if tag.startswith("murid_hardcover_")
    }
    if len(ids) > 1:
        raise ValueError("Torrent has conflicting Hardcover work tags")
    work_id = next(iter(ids), None)
    if work_id is not None and (
        not work_id.isascii() or not work_id.isdigit() or int(work_id) <= 0
    ):
        raise ValueError("Torrent has an invalid Hardcover work tag")
    if medium == "audiobook" and work_id is None:
        raise ValueError("Audiobook torrent has no Hardcover work identity")
    return medium, int(work_id) if work_id is not None else None
