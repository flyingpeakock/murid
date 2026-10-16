"""Execute commands selected by the CLI argument parser."""

import logging
import sys
from argparse import Namespace

from .clients.hardcover import HardcoverError
from .config.config import Config, ConfigError
from .notifications.apprise import send_test_notification
from .services.book_lookup import BookLookupError
from .services.book_search import BookSearchError, search_book
from .services.connection_service import check_connections
from .services.manual_import import ManualImportError, add_book
from .services.service_factory import ServiceFactory
from .services.status_service import print_status

logger = logging.getLogger("murid")


def _validate_config(config_file: str) -> int:
    """Validate a configuration file and report the result."""
    try:
        with open(config_file, "r", encoding="utf-8") as config:
            Config(config)
        print("Configuration file is valid.")
        return 0
    except ConfigError as error:
        print(f"Configuration file is invalid: {error}")
        return 1
    except FileNotFoundError:
        print(f"Configuration file not found: {config_file}")
        return 1
    except Exception as error:
        print(f"Unexpected error while validating configuration: {error}")
        raise SystemExit(1) from error


def run_command(args: Namespace) -> int:
    """Execute the requested command and return its exit status."""
    if args.command in {"run", "schedule", "retry-import", "search-book", "add-book"}:
        return _run_work_command(args)
    return _run_other_command(args)


def _run_work_command(args: Namespace) -> int:
    """Run commands that sync, import, or retry books."""
    match args.command:
        case "run":
            ServiceFactory(args).sync_service().run()
        case "schedule":
            ServiceFactory(args).sync_service().start_scheduler()
        case "retry-import":
            result = ServiceFactory(args).retry_service().retry_imports()
            print(
                f"Retry import: {result.imported} imported, "
                f"{result.already_present} already in Calibre, "
                f"{result.pending} still downloading, {result.failed} failed, "
                f"{result.skipped} skipped"
            )
            return 1 if result.pending or result.failed or result.skipped else 0
        case "search-book":
            try:
                search_book(args.name, ServiceFactory(args), add=args.add)
            except (BookLookupError, BookSearchError) as error:
                print(f"Cannot search book: {error}", file=sys.stderr)
                return 1
        case "add-book":
            try:
                book = add_book(args.name, args.path, ServiceFactory(args))
            except ManualImportError as error:
                print(f"Cannot add book: {error}", file=sys.stderr)
                return 1
            print(f"Added {book} to Calibre")
    return 0


def _run_other_command(args: Namespace) -> int:
    """Run inspection, configuration, and connection commands."""
    match args.command:
        case "test-notification":
            send_test_notification(ServiceFactory(args).notifier())
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
                print(f"Cannot inspect Hardcover books: {error}", file=sys.stderr)
                return 1
        case "status":
            print_status(ServiceFactory(args).qbittorrent())
        case "validate-config":
            return _validate_config(args.config_file)
        case "print-config":
            with open(args.config_file, "r", encoding="utf-8") as config:
                print(Config(config))
        case _:
            logger.error("Unknown command: %s", args.command)
            return 1
    return 0
