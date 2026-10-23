"""Check access to Murid's configured external services."""

from ..clients.hardcover import Hardcover
from ..config import ConfigError, requested_media_types
from ..ui import interactive, labeled, output


def check_connections(factory) -> bool:
    """Run independent read-only checks and print one result per service."""

    labels = [
        f"Hardcover account {index}"
        for index in range(1, len(factory.config["hardcover_api_keys"]) + 1)
    ]
    width = max(map(len, [*labels, "Calibre", "MyAnonamouse", "qBittorrent"]))

    def check(label, action) -> bool:
        display = f"{label:<{width}}" if interactive() else label
        try:
            detail = action()
        # Each check must report its own failure and let the remaining checks run.
        except (Exception, SystemExit) as error:  # pylint: disable=broad-exception-caught
            reason = str(error).strip() or type(error).__name__
            if isinstance(error, SystemExit):
                reason = str(error.__cause__ or "client initialization failed; see logs")
            output(
                labeled(f"FAIL {display}: ", reason, "bold red"),
                kind="connection",
                data={"service": label, "ok": False, "detail": reason},
            )
            return False
        prefix = "OK   " if interactive() else "OK "
        output(
            labeled(f"{prefix}{display}: ", detail, "bold green"),
            kind="connection",
            data={"service": label, "ok": True, "detail": detail},
        )
        return True

    def hardcover_detail(token: str) -> str:
        user = Hardcover(token).user
        return f"authenticated as {user.name}"

    def calibre_detail() -> str:
        books = factory.calibre().get_books()
        return f"{len(books)} book{'s' if len(books) != 1 else ''} readable"

    def mam_detail() -> str:
        factory.myanonamouse().check_connection()
        return "search API responded"

    def qbittorrent_detail() -> str:
        client = factory.qbittorrent()
        count = len(client.get_torrents())
        return f"category '{client.category}' readable ({count} torrent{'s' if count != 1 else ''})"

    def audiobook_detail() -> str:
        raise ConfigError("Audiobookshelf connection checks are not supported yet")

    results = [
        check(
            f"Hardcover account {index}",
            lambda token=token: hardcover_detail(
                token["api_key"] if isinstance(token, dict) else token
            ),
        )
        for index, token in enumerate(factory.config["hardcover_api_keys"], start=1)
    ]
    media_types = requested_media_types(factory.config["hardcover_api_keys"])
    if "ebook" in media_types:
        results.append(check("Calibre", calibre_detail))
    if "audiobook" in media_types:
        results.append(check("Audiobookshelf", audiobook_detail))
    results.append(check("MyAnonamouse", mam_detail))
    results.append(check("qBittorrent", qbittorrent_detail))
    output(
        labeled(
            "Connections: ",
            f"{sum(results)} passed, {len(results) - sum(results)} failed",
            "bold green" if all(results) else "bold red",
        ),
        kind="connection_summary",
        data={"passed": sum(results), "failed": len(results) - sum(results)},
    )
    return all(results)
