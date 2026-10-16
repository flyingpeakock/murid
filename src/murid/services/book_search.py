"""Preview the MyAnonamouse search and selection for a Hardcover book."""

from .book_lookup import find_hardcover_book


class BookSearchError(Exception):
    """The requested torrent could not be added and imported."""


def _print_candidates(book, torrents, matcher, discovery):
    """Print candidates in selection and score order; return the selected torrent."""
    failed_ids = discovery.mam_ids_with_tag("murid_import_failed")
    selector = discovery.torrent_selector
    available = {torrent for torrent in torrents if str(torrent.book.id) not in failed_ids}
    selected = selector.select(book, available, matcher) if available else None

    def describe(torrent):
        score = matcher.similarity(book, torrent.book)
        reasons = []
        if str(torrent.book.id) in failed_ids:
            reasons.append("previously failed import")
        reasons.extend(selector.rejection_reasons(torrent))
        if not reasons and score < matcher.threshold:
            reasons.append("match score below threshold")
        if not reasons and not matcher.is_match(book, torrent.book):
            reasons.append("book matching rules")

        if torrent is selected:
            status = "SELECTED"
        elif reasons:
            status = "REJECTED: " + ", ".join(reasons)
        else:
            status = "eligible, not selected"
        return score, status

    candidates = [(torrent, *describe(torrent)) for torrent in torrents]
    candidates.sort(
        key=lambda item: (
            item[0] is not selected,
            -item[1],
            item[0].book.title.casefold(),
            item[0].book.id,
        )
    )
    for torrent, score, status in candidates:
        file_types = ", ".join(torrent.file_types or []) or "unknown"
        print(
            f"- {status}: {torrent.book} [ID {torrent.book.id}, score {score:.3f}, "
            f"language {torrent.language or 'unknown'}, files {file_types}, "
            f"seeders {torrent.metadata.seeders}]"
        )
        print(f"  {torrent}")
    return selected


def search_book(name: str, factory, *, add: bool = False) -> None:
    """Show search candidates and optionally import the selected torrent."""
    book = find_hardcover_book(name, factory)
    matcher = factory.matcher()
    discovery = factory.torrent_discovery()
    _, torrents = discovery.find_torrents(book)
    print(f"Hardcover: {book}")
    print(f"MyAnonamouse candidates: {len(torrents)}")
    if not torrents:
        print("No torrents found.")
        if add:
            raise BookSearchError("No torrent was selected")
        return

    selected = _print_candidates(book, torrents, matcher, discovery)

    if selected is None:
        print("No torrent would be selected.")
        if add:
            raise BookSearchError("No torrent was selected")
        return

    if not add:
        return

    calibre = factory.calibre()
    if calibre.contains_book(book, matcher):
        raise BookSearchError(f"{book} is already in Calibre")

    torrent_file = discovery.mam.download_torrent(selected)
    if not torrent_file:
        raise BookSearchError(f"Could not download torrent for {book}")

    print(f"Adding selected torrent for {book} and waiting for Calibre import...")
    factory.torrent_import().import_torrents([(torrent_file, selected.book)])
    if not calibre.contains_book(book, matcher):
        raise BookSearchError(
            "Book is not yet in Calibre after the import attempt; check status and the logs"
        )
    print(f"Imported {book} into Calibre")
