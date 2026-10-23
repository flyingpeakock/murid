"""Argument parsing for the murid application."""

import argparse
import os
import platform
import sys
from functools import partial
from pathlib import Path

from rich.console import Console
from rich_argparse import ArgumentDefaultsRichHelpFormatter

try:
    from ._version import __version__
except ImportError:
    __version__ = "unknown"


class MuridArgumentParser(argparse.ArgumentParser):
    """Build Murid commands with detailed help available per command."""

    def __init__(self, description: str | None = None, *, is_subparser: bool = False, **kwargs):
        self._plain_help = False
        kwargs.setdefault("formatter_class", ArgumentDefaultsRichHelpFormatter)
        if not is_subparser:
            kwargs.setdefault("epilog", "For command options, run: murid <command> --help")
        super().__init__(description=description, **kwargs)
        if is_subparser:
            return

        self.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")

        command_subparsers = self.add_subparsers(
            title="commands",
            description="Choose one command to run",
            dest="command",
            required=True,
            parser_class=partial(MuridArgumentParser, is_subparser=True),
        )

        sub_parsers = {}
        sub_parsers["run"] = command_subparsers.add_parser(
            "run",
            help="Sync the Hardcover reading list with Calibre once",
            description=(
                "Compare Hardcover books with Calibre, search MyAnonamouse for missing books, "
                "and import available downloads. Run once, then exit."
            ),
        )

        sub_parsers["schedule"] = command_subparsers.add_parser(
            "schedule",
            help="Run the sync repeatedly on the configured schedule",
            description=(
                "Keep Murid running and repeat the sync according to the cron schedule "
                "in the configuration file. Reload the configuration before each run."
            ),
        )

        sub_parsers["test-notification"] = command_subparsers.add_parser(
            "test-notification",
            help="Send a test notification through Apprise",
            description=(
                "Send a test notification using the configured Apprise destinations, then exit."
            ),
        )

        sub_parsers["test-connection"] = command_subparsers.add_parser(
            "test-connection",
            help="Check access to Hardcover, Calibre, MyAnonamouse, and qBittorrent",
            description=(
                "Test each configured service independently and report connection or "
                "authentication failures."
            ),
        )

        sub_parsers["list-missing"] = command_subparsers.add_parser(
            "list-missing",
            help="List Hardcover requests missing from their media-specific libraries",
            description=(
                "Compare configured Hardcover requests with Calibre for ebooks and "
                "Audiobookshelf for audiobooks, then list missing requests."
            ),
        )

        sub_parsers["status"] = command_subparsers.add_parser(
            "status",
            help="Show Murid downloads and any torrents needing attention",
            description=(
                "List torrents in Murid's configured qBittorrent category, including their "
                "download progress and timeout or import-failure tags."
            ),
        )

        sub_parsers["retry-import"] = command_subparsers.add_parser(
            "retry-import",
            help="Retry Calibre imports for Murid downloads needing attention",
            description=(
                "Check timed-out and failed-import torrents in Murid's qBittorrent category, "
                "and retry importing completed downloads into Calibre."
            ),
        )

        sub_parsers["search-book"] = command_subparsers.add_parser(
            "search-book",
            help="Preview torrent choices for a Hardcover book",
            description=(
                "Find a book on the Hardcover reading list, search MyAnonamouse, "
                "and explain which torrent Murid would select. Use --add to download "
                "the selected torrent and import its completed ebook into Calibre."
            ),
        )
        sub_parsers["search-book"].add_argument("name", help="Name of the book on Hardcover")
        sub_parsers["search-book"].add_argument(
            "--add",
            action="store_true",
            help="Add the selected torrent to qBittorrent and import its ebook into Calibre",
        )

        sub_parsers["add-book"] = command_subparsers.add_parser(
            "add-book",
            help="Add an ebook file using metadata from your Hardcover reading list",
            description=(
                "Match a book name against your Hardcover reading list and add the given "
                "ebook file to Calibre with the matched book's metadata."
            ),
        )
        sub_parsers["add-book"].add_argument("name", help="Name of the book on Hardcover")
        sub_parsers["add-book"].add_argument("path", help="Path to an individual ebook file")

        sub_parsers["review-matches"] = command_subparsers.add_parser(
            "review-matches",
            help="Show Hardcover library matches, scores, and evidence for each medium",
            description=(
                "Compare requests with their media-specific libraries and show scores, metadata, "
                "and ambiguous candidates. Show all books unless a filter is selected."
            ),
        )
        review_filter = sub_parsers["review-matches"].add_mutually_exclusive_group()
        review_filter.add_argument(
            "--matched",
            action="store_const",
            const=True,
            default=None,
            dest="matched",
            help="Show only Hardcover requests with an accepted library match",
        )
        review_filter.add_argument(
            "--unmatched",
            action="store_const",
            const=False,
            dest="matched",
            help="Show only Hardcover requests without an accepted library match",
        )

        sub_parsers["validate-config"] = command_subparsers.add_parser(
            "validate-config",
            help="Check the configuration file for errors",
            description="Read and validate the Murid configuration file, then report any errors.",
        )

        sub_parsers["print-config"] = command_subparsers.add_parser(
            "print-config",
            help="Print the parsed configuration",
            description="Read and print the parsed Murid configuration, then exit.",
        )

        config_path = str(self.default_config_path())
        for command, parser in sub_parsers.items():
            parser.add_argument(
                "-c",
                "--config",
                type=str,
                help="Path to the Murid YAML configuration file",
                default=config_path,
                dest="config_file",
            )
            parser.add_argument(
                "--format",
                choices=["auto", "plain", "json"],
                default="auto",
                help="Output format: terminal layout, unwrapped plain text, or JSON Lines",
                dest="output_format",
            )
            parser.add_argument(
                "--no-color",
                action="store_true",
                help="Disable color in command output, logs, and help",
                dest="no_color",
            )
            if command:
                parser.add_argument(
                    "--log-level",
                    "-l",
                    help="Minimum severity of messages written to the log",
                    default="info"
                    if command
                    in ("run", "schedule", "search-book", "retry-import", "test-connection")
                    else "warning",
                    dest="log_level",
                    type=str.upper,
                    choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                )
            if command in ("run", "schedule"):
                parser.add_argument(
                    "--dry-run",
                    "-d",
                    help="Find books and torrents without adding them to qBittorrent or Calibre",
                    action="store_true",
                    dest="dry_run",
                )

    def parse_known_args(self, args=None, namespace=None):
        # Help exits during parsing, before main can configure normal output.
        arguments = sys.argv[1:] if args is None else list(args)
        self._plain_help = "--no-color" in arguments or any(
            value in arguments for value in ("plain", "json", "--format=plain", "--format=json")
        )
        return super().parse_known_args(args, namespace)

    def _get_formatter(self):
        formatter = super()._get_formatter()
        if getattr(self, "_plain_help", False):
            formatter.console = Console(no_color=True, color_system=None)
        return formatter

    @staticmethod
    def default_config_path() -> Path:
        """Get the config file path from the environment or operating-system default."""
        config_file = os.getenv("MURID_CONFIG_FILE")
        if config_file:
            return Path(config_file)

        app_name = "murid"
        file_name = "config.yaml"

        match platform.system():
            case "Linux":
                config_home = os.getenv("XDG_CONFIG_HOME") or str(Path.home() / ".config")
                return Path(config_home) / app_name / file_name

            case "Darwin":
                return Path.home() / "Library" / "Application Support" / app_name / file_name

            case "Windows":
                appdata = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
                return Path(appdata) / app_name / file_name

            case _:
                raise RuntimeError(f"Unsupported operating system: {platform.system()}")
