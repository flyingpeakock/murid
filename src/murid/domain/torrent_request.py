"""Persistent request identity stored alongside torrent lifecycle tags."""

from .book_request import BookRequest, MediaType

IMPORT_TAGS = ("murid_pending", "murid_timeout", "murid_import_failed")


def request_tags(request: BookRequest) -> set[str]:
    """Write routing on the initial add, before the process can be interrupted."""
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
