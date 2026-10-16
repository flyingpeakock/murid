"""Terminal output helpers that respect Murid's color preference."""

import json
import sys

from rich.console import Console
from rich.text import Text

console = Console()
OUTPUT_FORMAT = "auto"


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
    target = console if file is None else Console(file=file, no_color=console.no_color)
    if is_json():
        message = " ".join(
            item.plain if isinstance(item, Text) else Text.from_markup(str(item)).plain
            for item in renderables
        )
        if message or data:
            print(
                json.dumps({"type": kind, "message": message, **data}, ensure_ascii=False),
                file=file or sys.stdout,
            )
        return
    if OUTPUT_FORMAT == "plain" or not target.is_terminal:
        # Preserve complete lines and URLs in pipes, files, and automation.
        for item in renderables:
            print(
                item.plain if isinstance(item, Text) else Text.from_markup(str(item)).plain,
                file=file or sys.stdout,
            )
        if not renderables:
            print(file=file or sys.stdout)
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
