"""Check access to Murid's configured external services."""

from ..clients.hardcover import Hardcover


def check_connections(factory) -> bool:
    """Run independent read-only checks and print one result per service."""

    def check(label, action) -> bool:
        try:
            detail = action()
        # Each check must report its own failure and let the remaining checks run.
        except (Exception, SystemExit) as error:  # pylint: disable=broad-exception-caught
            reason = str(error).strip() or type(error).__name__
            if isinstance(error, SystemExit):
                reason = "client initialization failed; see logs"
            print(f"FAIL {label}: {reason}")
            return False
        print(f"OK {label}: {detail}")
        return True

    def hardcover_detail(token: str) -> str:
        user = Hardcover(token).user
        return f"authenticated as {user.name}"

    def calibre_detail() -> str:
        books = factory.calibre().get_books()
        return f"{len(books)} books readable"

    def mam_detail() -> str:
        factory.myanonamouse().check_connection()
        return "search API responded"

    def qbittorrent_detail() -> str:
        client = factory.qbittorrent()
        return f"category '{client.category}' readable ({len(client.get_torrents())} torrents)"

    results = [
        check(
            f"Hardcover account {index}",
            lambda token=token: hardcover_detail(token),
        )
        for index, token in enumerate(factory.config["hardcover_api_keys"], start=1)
    ]
    results.append(check("Calibre", calibre_detail))
    results.append(check("MyAnonamouse", mam_detail))
    results.append(check("qBittorrent", qbittorrent_detail))
    return all(results)
