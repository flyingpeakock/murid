"""Execute commands selected by the CLI argument parser."""

import logging
import sys
from argparse import Namespace

import yaml
from rich.text import Text

from .clients.hardcover import HardcoverError
from .config import Config, ConfigError
from .libraries.library import LibraryImportPending
from .notifications.apprise import send_test_notification
from .services.book_lookup import BookLookupError
from .services.book_search import BookSearchError, search_book
from .services.connection_service import check_connections
from .services.manual_import import ManualImportError, add_book
from .services.service_factory import ServiceFactory
from .services.status_service import print_status
from .ui import book_data, labeled, output

logger = logging.getLogger("murid")


def _validate_config(config_file: str) -> int:
    """Validate a configuration file and report the result."""
    try:
        with open(config_file, "r", encoding="utf-8") as config:
            Config(config)
        output(
            labeled("Configuration file is valid", ".", "bold green"),
            kind="validation",
            data={"valid": True, "path": config_file},
        )
        return 0
    except ConfigError as error:
        output(
            labeled("Configuration invalid: ", str(error), "bold red"),
            file=sys.stderr,
            kind="error",
            data={"valid": False, "path": config_file},
        )
        return 1
    except FileNotFoundError:
        output(
            labeled("Configuration file not found: ", config_file, "bold red"),
            file=sys.stderr,
            kind="error",
            data={"valid": False, "path": config_file},
        )
        return 1


def run_command(args: Namespace) -> int:
    """Execute the requested command and return its exit status."""
    if args.command in {"run", "schedule", "retry-import", "search-book", "add-book"}:
        return _run_work_command(args)
    return _run_other_command(args)


def _run_work_command(args: Namespace) -> int:
    """Run commands that sync, import, or retry books."""
    match args.command:
        case "run":
            return 1 if ServiceFactory(args).sync_service().run() is False else 0
        case "schedule":
            ServiceFactory(args).sync_service().start_scheduler()
        case "retry-import":
            service = ServiceFactory(args).retry_service()
            result = service.retry_imports()
            output(
                "[bold cyan]Retry import:[/] "
                f"{result.imported} imported, "
                f"{result.already_present} already present, "
                f"{result.pending} pending, {result.failed} failed, "
                f"{result.skipped} skipped",
                kind="retry_summary",
                data={
                    **{
                        key: getattr(result, key)
                        for key in ("imported", "already_present", "pending", "failed", "skipped")
                    },
                    "by_media": getattr(result, "by_media", {}),
                },
            )
            return 1 if result.pending or result.failed or result.skipped else 0
        case "search-book":
            try:
                search_book(
                    args.name,
                    ServiceFactory(args),
                    add=args.add,
                    torrent_id=getattr(args, "torrent_id", None),
                    media_type=getattr(args, "media_type", "ebook"),
                )
            except (BookLookupError, BookSearchError) as error:
                output(
                    labeled("Cannot search book: ", str(error), "bold red"),
                    file=sys.stderr,
                    kind="error",
                )
                return 1
        case "add-book":
            return _add_book_command(args)
    return 0


def _add_book_command(args: Namespace) -> int:
    media = getattr(args, "media_type", "ebook")
    destination = "Audiobookshelf" if media == "audiobook" else "Calibre"
    data = {"media_type": media, "destination": destination}
    try:
        book = add_book(args.name, args.path, ServiceFactory(args), media_type=media)
    except (ManualImportError, LibraryImportPending) as error:
        pending = isinstance(error, LibraryImportPending)
        output(
            labeled(
                "Import pending: " if pending else "Cannot add book: ",
                str(error),
                "bold yellow" if pending else "bold red",
            ),
            file=sys.stderr,
            kind="import_pending" if pending else "error",
            data=data,
        )
        return 1
    dry_run = bool(getattr(args, "dry_run", False))
    output(
        labeled(
            "Would add " if dry_run else "Added ",
            f"{book} to {destination}",
            "bold cyan" if dry_run else "bold green",
        ),
        kind="planned" if dry_run else "imported",
        data={**data, "book": book_data(book)} if hasattr(book, "id") else data,
    )
    return 0


def _test_notification(args: Namespace) -> int:
    """Send a test notification and report the delivery result."""
    factory = ServiceFactory(args)
    if not factory.config.get("apprise"):
        output(
            labeled("Cannot send notification: ", "no Apprise destinations configured", "bold red"),
            file=sys.stderr,
            kind="error",
        )
        return 1
    if not send_test_notification(factory.notifier()):
        output(
            labeled(
                "Notification failed: ",
                "check Apprise destinations and connection settings",
                "bold red",
            ),
            file=sys.stderr,
            kind="error",
        )
        return 1
    output(
        labeled("Test notification sent", ".", "bold green"),
        kind="notification",
        data={"sent": True},
    )
    return 0


def _run_other_command(args: Namespace) -> int:
    """Run inspection, configuration, and connection commands."""
    match args.command:
        case "test-notification":
            return _test_notification(args)
        case "test-connection":
            factory = ServiceFactory(args, initialize_notifier=False)
            return 0 if check_connections(factory) else 1
        case "list-missing" | "review-matches":
            factory = ServiceFactory(args)
            try:
                service = factory.sync_service()
                matcher = factory.matcher()
                if args.command == "list-missing":
                    service.list_missing(matcher)
                else:
                    service.review_matches(matcher, matched=args.matched)
            except HardcoverError as error:
                output(
                    labeled("Cannot inspect Hardcover books: ", str(error), "bold red"),
                    file=sys.stderr,
                    kind="error",
                )
                return 1
        case "status":
            client = ServiceFactory(args).qbittorrent()
            if getattr(args, "media_type", None):
                print_status(client, media_type=args.media_type)
            else:
                print_status(client)
        case "validate-config":
            return _validate_config(args.config_file)
        case "print-config":
            with open(args.config_file, "r", encoding="utf-8") as config:
                rendered = str(Config(config))
                output(
                    Text(rendered.rstrip()),
                    kind="config",
                    data={"config": yaml.safe_load(rendered)},
                )
        case _:
            logger.error("Unknown command: %s", args.command)
            return 1
    return 0
