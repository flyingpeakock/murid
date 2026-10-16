"""Display the state of torrents managed by Murid."""

from ..clients.torrent_clients.qbittorrent import Qbittorrent


def print_status(torrent_client: Qbittorrent) -> None:
    """Print downloads in Murid's category, putting torrents needing attention first."""
    torrents = torrent_client.get_torrents()
    print(f"Murid torrents in qBittorrent category '{torrent_client.category}': {len(torrents)}")
    if not torrents:
        return

    def issues(torrent) -> list[str]:
        tags = {tag.strip() for tag in (torrent.tags or "").split(",")}
        result = []
        if "murid_import_failed" in tags:
            result.append("import failed")
        if "murid_timeout" in tags:
            result.append("timed out")
        return result

    for torrent in sorted(torrents, key=lambda item: (not issues(item), item.name.casefold())):
        issue_text = f" | {', '.join(issues(torrent))}" if issues(torrent) else ""
        print(f"- {torrent.name} | {torrent.progress:.0%} | {torrent.state}{issue_text}")
