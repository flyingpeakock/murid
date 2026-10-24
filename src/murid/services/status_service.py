"""Display the state of torrents managed by Murid."""

from rich.table import Table
from rich.text import Text

from ..clients.torrent_clients.qbittorrent import Qbittorrent
from ..domain.book_request import MediaType
from ..domain.torrent_request import TAG_ALIASES, read_request
from ..ui import interactive, labeled, output, terminal_width

_STATES = {
    "stalledUP": "seeding (idle)",
    "stalledDL": "download stalled",
    "uploading": "seeding",
    "downloading": "downloading",
    "error": "error",
    "missingFiles": "files missing",
    "pausedDL": "download paused",
    "pausedUP": "seeding paused",
    "stoppedDL": "download stopped",
    "stoppedUP": "seeding stopped",
    "queuedDL": "download queued",
    "queuedUP": "seeding queued",
    "checkingDL": "checking download",
    "checkingUP": "checking seed",
    "checkingResumeData": "checking resume data",
    "allocating": "allocating space",
    "moving": "moving files",
    "metaDL": "fetching metadata",
    "forcedMetaDL": "fetching metadata (forced)",
    "forcedDL": "downloading (forced)",
    "forcedUP": "seeding (forced)",
    "unknown": "unknown",
}


def _request_info(torrent) -> dict:
    try:
        media, work_id = read_request(torrent)
    except ValueError as error:
        return {
            "media_type": None,
            "destination": None,
            "hardcover_id": None,
            "identity_error": str(error),
        }
    return {
        "media_type": media,
        "destination": "Audiobookshelf" if media == "audiobook" else "Calibre",
        "hardcover_id": work_id,
        "identity_error": None,
    }


def print_status(torrent_client: Qbittorrent, media_type: MediaType | None = None) -> None:
    """Print downloads in Murid's category, putting torrents needing attention first."""
    torrents = [
        torrent
        for torrent in torrent_client.get_torrents()
        if not media_type or _request_info(torrent)["media_type"] in {media_type, None}
    ]
    output(
        labeled(
            "Murid torrents: ",
            f"{len(torrents)} (category '{torrent_client.category}')",
            "bold cyan",
        ),
        kind="status",
        data={"category": torrent_client.category, "count": len(torrents)},
    )
    if not torrents:
        return

    def issues(torrent) -> list[str]:
        tags = {
            TAG_ALIASES.get(tag.strip(), tag.strip()) for tag in (torrent.tags or "").split(",")
        }
        result = ["invalid request identity"] if _request_info(torrent)["identity_error"] else []
        if "murid-import-failed" in tags:
            result.append("import failed")
        if "murid-timeout" in tags:
            result.append("timed out")
        elif "murid" in tags:
            result.append("import pending")
        if torrent.state in {"error", "missingFiles"}:
            result.append(_STATES[torrent.state])
        return result

    table = Table(box=None, padding=(0, 1), expand=True)
    table.add_column("Book / torrent", ratio=3)
    table.add_column("Media / library", ratio=2)
    table.add_column("Done", justify="right", no_wrap=True)
    table.add_column("State", width=17)
    table.add_column("Attention", width=14)
    attention = 0
    for torrent in sorted(torrents, key=lambda item: (not issues(item), item.name.casefold())):
        problems = issues(torrent)
        request = _request_info(torrent)
        routing = (
            f"{request['media_type']} → {request['destination']}"
            if request["media_type"]
            else "unknown request"
        )
        attention += bool(problems)
        issue_text = ", ".join(problems)
        issue_style = (
            "bold red"
            if any(
                problem in {"import failed", "error", "files missing", "invalid request identity"}
                for problem in problems
            )
            else "bold yellow"
        )
        state = _STATES.get(torrent.state, torrent.state)
        if interactive() and terminal_width() < 64:
            title = Table.grid(expand=True)
            title.add_column(width=2, no_wrap=True)
            title.add_column(ratio=1)
            title.add_row("- ", Text(f"{torrent.name} [{routing}]"))
            output(title)
            output(
                Text.assemble(
                    (f"  {torrent.progress:4.0%} · {state}", "cyan"),
                    (f" · {issue_text}" if problems else "", issue_style),
                )
            )
        elif interactive():
            table.add_row(
                Text(torrent.name),
                Text(routing),
                f"{torrent.progress:.0%}",
                Text(state),
                Text(issue_text or "—", style=issue_style if problems else "dim"),
            )
        else:
            output(
                Text(
                    f"- {torrent.name} [{routing}] | {torrent.progress:4.0%} | {state}"
                    + (f" | {issue_text}" if problems else "")
                ),
                kind="torrent",
                data={
                    **request,
                    "name": torrent.name,
                    "progress": torrent.progress,
                    "state": torrent.state,
                    "state_label": state,
                    "issues": problems,
                    "hash": getattr(torrent, "hash", None),
                },
            )
    if interactive() and terminal_width() >= 64:
        output(table)
    if attention:
        output(
            labeled(
                "Needs attention: ",
                f"{attention}. Inspect qBittorrent, then run murid retry-import.",
                "bold yellow",
            ),
            kind="status_summary",
            data={"attention": attention},
        )
