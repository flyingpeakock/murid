"""Preview the MyAnonamouse search and selection for a Hardcover book."""

from rich.text import Text

from ..domain.book_request import BookRequest, MediaType
from ..ui import book_data, colored, is_json, labeled, output
from .book_lookup import find_hardcover_book


class BookSearchError(Exception):
    """The requested torrent could not be added and imported."""


def _print_candidates(request, torrents, matcher, discovery, *, torrent_id=None):
    """Print candidates in selection and score order; return the selected torrent."""
    failed_ids = discovery.mam_ids_with_tag("murid-import-failed", request.media_type)
    selector = discovery.torrent_selectors[request.media_type]
    available = {torrent for torrent in torrents if str(torrent.book.id) not in failed_ids}
    if torrent_id is not None:
        available = {torrent for torrent in available if torrent.book.id == torrent_id}
    selected = selector.select(request.book, available, matcher) if available else None

    def describe(torrent):
        score = matcher.similarity(request.book, torrent.book)
        reasons = []
        if str(torrent.book.id) in failed_ids:
            reasons.append("previously failed import")
        reasons.extend(selector.rejection_reasons(torrent))
        if not reasons and score < matcher.threshold:
            reasons.append(f"match score below threshold {matcher.threshold:.3f}")
        if not reasons:
            rejection = matcher.rejection_reason(request.book, torrent.book)
            if rejection:
                reasons.append(rejection)

        return score, reasons

    candidates = [(torrent, *describe(torrent)) for torrent in torrents]
    candidates.sort(
        key=lambda item: (
            item[0] is not selected,
            selector.preference(item[0], item[1]),
            item[0].book.title.casefold(),
            item[0].book.id,
        )
    )
    for torrent, score, reasons in candidates:
        output(
            labeled(
                (
                    "- SELECTED: "
                    if torrent is selected
                    else "- REJECTED: "
                    if reasons
                    else "- ELIGIBLE: "
                ),
                str(torrent.book),
                "bold green" if torrent is selected else "bold yellow" if reasons else "cyan",
            ),
            kind="candidate",
            data={
                "book": book_data(torrent.book),
                "media_type": request.media_type,
                "destination": "Audiobookshelf" if request.media_type == "audiobook" else "Calibre",
                "score": score,
                "threshold": matcher.threshold,
                "selected": torrent is selected,
                "reasons": reasons,
                "language": torrent.language,
                "file_types": torrent.file_types or [],
                "seeders": torrent.metadata.seeders,
                "url": str(torrent),
            },
        )
        # Candidate records carry all metadata in JSON; extra lines are for people.
        if not is_json():
            output(
                Text(
                    f"  ID {torrent.book.id} · score {score:.3f} / {matcher.threshold:.3f}"
                    f" · {torrent.language or 'unknown'}"
                    f" · {', '.join(torrent.file_types or []) or 'unknown'}"
                    f" · {torrent.metadata.seeders} seeders"
                )
            )
            if reasons:
                output(labeled("  Reason: ", "; ".join(reasons), "yellow"))
            elif torrent is not selected:
                output("  Eligible; another torrent was selected.")
            output(Text(f"  {torrent}"))
    if torrent_id is not None and selected is None:
        requested = [item for item in candidates if item[0].book.id == torrent_id]
        if not requested:
            raise BookSearchError(f"Torrent {torrent_id} was not found in search results")
        raise BookSearchError(
            f"Torrent {torrent_id} cannot be selected: {'; '.join(requested[0][2])}"
        )
    return selected


def search_book(
    name: str,
    factory,
    *,
    add: bool = False,
    media_type: MediaType = "ebook",
    torrent_id: int | None = None,
) -> None:
    """Show search candidates and optionally import the selected torrent."""
    if torrent_id is not None and torrent_id <= 0:
        raise BookSearchError("Torrent ID must be a positive integer")
    destination = "Audiobookshelf" if media_type == "audiobook" else "Calibre"
    book = find_hardcover_book(name, factory)
    matcher = factory.matcher()
    discovery = factory.torrent_discovery(media_type)
    _, torrents = discovery.find_torrents(BookRequest(book, media_type))
    output(
        labeled(
            "Hardcover: ",
            f"{book} [{media_type} → {destination}]",
            "bold cyan",
        ),
        kind="search",
        data={
            "book": book_data(book),
            "count": len(torrents),
            "threshold": matcher.threshold,
            "media_type": media_type,
            "destination": "Audiobookshelf" if media_type == "audiobook" else "Calibre",
        },
    )
    output(
        labeled(
            "MyAnonamouse candidates: ",
            f"{len(torrents)} (match threshold {matcher.threshold:.3f})",
            "bold cyan",
        )
    )
    if not torrents:
        output("[bold yellow]No torrents found.[/]")
        if torrent_id is not None:
            raise BookSearchError(f"Torrent {torrent_id} was not found in search results")
        if add:
            raise BookSearchError("No torrent was selected")
        return

    selected = _print_candidates(
        BookRequest(book, media_type), torrents, matcher, discovery, torrent_id=torrent_id
    )

    if selected is None:
        output("[bold yellow]No torrent would be selected.[/]")
        if add:
            raise BookSearchError("No torrent was selected")
        return

    if not add:
        return

    library = factory.library(media_type)
    if library.contains_book(book, matcher):
        raise BookSearchError(f"{book} is already in {library.name}")

    torrent_file = discovery.mam.download_torrent(selected)
    if not torrent_file:
        raise BookSearchError(f"Could not download torrent for {book}")

    output(labeled("Adding selected torrent: ", str(book), "bold cyan"))
    result = factory.torrent_import(media_type).import_torrents([(torrent_file, book)])
    if getattr(getattr(factory, "args", None), "dry_run", False):
        output(
            f"Would import {book} [{media_type} → {library.name}]",
            kind="planned",
            data={"book": book_data(book), "media_type": media_type, "destination": library.name},
        )
        return
    if result.imported != 1:
        raise BookSearchError(
            f"Book is not yet in {library.name}; run murid status, inspect qBittorrent, "
            "then run murid retry-import"
        )
    output(
        colored(f"Imported {book} into {library.name} [{media_type}]", "bold green"),
        kind="imported",
        data={"book": book_data(book), "media_type": media_type, "destination": library.name},
    )
