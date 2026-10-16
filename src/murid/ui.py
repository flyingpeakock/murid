"""Terminal output helpers that respect Murid's color preference."""

import json
import logging
import sys

from rich.console import Console
from rich.text import Text

from .logging_config import is_journal_stream, journal_message

console = Console()
OUTPUT_FORMAT = "auto"


def _output_level(kind: str, data: dict) -> int:
    """Give diagnostics and unresolved summaries an appropriate journal priority."""
    if kind == "error" or data.get("aborted") or (kind == "connection" and data.get("ok") is False):
        return logging.ERROR
    if data.get("ok") is True:
        return logging.INFO
    if data.get("ok") is False or any(
        data.get(key, 0) for key in ("failed", "pending", "skipped", "attention")
    ):
        return logging.WARNING
    return logging.INFO


def _write(message: str, stream, level: int) -> None:
    """Flush complete lines promptly, adding priority prefixes only on journal streams."""
    if is_journal_stream(stream):
        message = journal_message(message, level)
    print(message, file=stream, flush=True)


def setup_output(*, color: bool, output_format: str = "auto") -> None:
    """Configure human-facing terminal output."""
    global console, OUTPUT_FORMAT  # pylint: disable=global-statement
    OUTPUT_FORMAT = output_format
    console = Console(no_color=True if not color or output_format != "auto" else None)


def output(*renderables, **kwargs) -> None:
    """Print a renderable to the configured terminal."""
    file = kwargs.pop("file", None)
    kind = kwargs.pop("kind", "message")
    data = kwargs.pop("data", {})
    level = kwargs.pop("level", _output_level(kind, data))
    stream = sys.stdout if file is None else file
    target = console if file is None else Console(file=file, no_color=console.no_color)
    if is_json():
        message = " ".join(
            item.plain if isinstance(item, Text) else Text.from_markup(str(item)).plain
            for item in renderables
        )
        if message or data:
            _write(
                json.dumps({"type": kind, "message": message, **data}, ensure_ascii=False),
                stream,
                level,
            )
        return
    if OUTPUT_FORMAT == "plain" or not target.is_terminal:
        # Preserve complete lines and URLs in pipes, files, and automation.
        for item in renderables:
            _write(
                item.plain if isinstance(item, Text) else Text.from_markup(str(item)).plain,
                stream,
                level,
            )
        if not renderables:
            _write("", stream, level)
        return
    target.print(*renderables, **kwargs)


def match_review(text: str) -> Text:
    """Apply scan-friendly styling to a formatted match review."""
    rendered = Text(text)
    rendered.highlight_regex(r"(?m)^Hardcover:", style="bold cyan")
    rendered.highlight_regex(r"(?m)^  MATCH", style="bold green")
    rendered.highlight_regex(r"(?m)^  candidate", style="bold yellow")
    rendered.highlight_regex(r"(?m)^  No Calibre", style="bold yellow")
    rendered.highlight_regex(r"(?m)^    Evidence:", style="dim")
    return rendered


def interactive() -> bool:
    """Whether output should use layouts sized for an interactive terminal."""
    return OUTPUT_FORMAT == "auto" and console.is_terminal


def is_json() -> bool:
    """Whether output is a stream of JSON records."""
    return OUTPUT_FORMAT == "json"


def terminal_width() -> int:
    """Width available to interactive layouts."""
    return console.width


def book_data(book) -> dict:
    """Stable fields shared by machine-readable book results."""
    return {
        "id": book.id,
        "title": book.title,
        "authors": list(book.authors),
        "source": book.source,
    }


def labeled(label: str, value: str, style: str) -> Text:
    """Return a styled label followed by unstyled, copyable text."""
    return Text.assemble((label, style), (value,))


def colored(value: str, style: str) -> Text:
    """Return styled text without interpreting its contents as markup."""
    return Text(value, style=style)
