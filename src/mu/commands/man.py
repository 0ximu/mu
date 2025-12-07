"""MU Manual - Human-readable documentation command."""

from __future__ import annotations

from difflib import get_close_matches
from importlib.resources import files

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

# Topic registry - maps topic names to markdown files
TOPICS: dict[str, str] = {
    "intro": "01-intro.md",
    "quickstart": "02-quickstart.md",
    "sigils": "03-sigils.md",
    "operators": "04-operators.md",
    "query": "05-query.md",
    "workflows": "06-workflows.md",
    "philosophy": "07-philosophy.md",
}

# Aliases for common lookups
TOPIC_ALIASES: dict[str, str] = {
    "start": "quickstart",
    "quick": "quickstart",
    "getting-started": "quickstart",
    "sigil": "sigils",
    "operator": "operators",
    "ops": "operators",
    "mubase": "query",
    "queries": "query",
    "kernel": "query",
    "workflow": "workflows",
    "usage": "workflows",
    "why": "philosophy",
    "about": "philosophy",
    "what": "intro",
}


def _load_content(filename: str) -> str:
    """Load markdown content from package data."""
    try:
        return files("mu.data.man.human").joinpath(filename).read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"Error: Could not find documentation file: {filename}"


def _load_all_content() -> str:
    """Load all documentation sections in order."""
    sections = []
    for filename in TOPICS.values():
        content = _load_content(filename)
        sections.append(content)
    return "\n\n---\n\n".join(sections)


def _resolve_topic(topic: str) -> str | None:
    """Resolve a topic name, handling aliases and fuzzy matching."""
    topic_lower = topic.lower()

    # Direct match
    if topic_lower in TOPICS:
        return topic_lower

    # Alias match
    if topic_lower in TOPIC_ALIASES:
        return TOPIC_ALIASES[topic_lower]

    # Fuzzy match against topics and aliases
    all_names = list(TOPICS.keys()) + list(TOPIC_ALIASES.keys())
    matches = get_close_matches(topic_lower, all_names, n=1, cutoff=0.6)
    if matches:
        match = matches[0]
        # Resolve alias if needed
        return TOPIC_ALIASES.get(match, match)

    return None


def _suggest_topic(console: Console, invalid_topic: str) -> None:
    """Suggest a valid topic when an invalid one is provided."""
    resolved = _resolve_topic(invalid_topic)

    if resolved:
        console.print(f"\n[yellow]Unknown topic:[/yellow] '{invalid_topic}'")
        console.print(f"[green]Did you mean:[/green] {resolved}?\n")
    else:
        console.print(f"\n[yellow]Unknown topic:[/yellow] '{invalid_topic}'\n")

    console.print("[cyan]Available topics:[/cyan]")
    for name in TOPICS:
        console.print(f"  - {name}")
    console.print()


def _print_toc(console: Console) -> None:
    """Print table of contents."""
    console.print()
    console.print(
        Panel(
            Text("MU Manual - Table of Contents", style="bold cyan"),
            border_style="cyan",
        )
    )
    console.print()

    for i, (name, filename) in enumerate(TOPICS.items(), 1):
        # Load first line as title
        content = _load_content(filename)
        title = content.split("\n")[0].lstrip("# ")
        console.print(f"  [cyan]{i}.[/cyan] [bold]{name}[/bold] - {title}")

    console.print()
    console.print("[dim]Use 'mu man <topic>' to view a specific section[/dim]")
    console.print()


@click.command("man")
@click.argument("topic", required=False)
@click.option("--toc", is_flag=True, help="Print table of contents")
@click.option("--no-color", is_flag=True, help="Disable colored output")
@click.option(
    "--width",
    type=int,
    default=None,
    help="Override terminal width",
)
def man_command(
    topic: str | None,
    toc: bool,
    no_color: bool,
    width: int | None,
) -> None:
    """Display the MU manual.

    View the full manual or jump to a specific topic.

    \b
    Topics:
      intro       What is MU?
      quickstart  5-minute getting started guide
      sigils      Sigil reference with examples
      operators   Data flow operators
      query       MUbase queries and graph database
      workflows   Common usage patterns
      philosophy  Design principles behind MU

    \b
    Examples:
      mu man              # Full manual, paginated
      mu man sigils       # Jump to sigils section
      mu man --toc        # Show table of contents
    """
    console = Console(
        width=width,
        no_color=no_color,
    )

    # Table of contents mode
    if toc:
        _print_toc(console)
        return

    # Specific topic mode
    if topic:
        resolved = _resolve_topic(topic)
        if resolved is None:
            _suggest_topic(console, topic)
            raise SystemExit(1)

        content = _load_content(TOPICS[resolved])
    else:
        # Full manual
        content = _load_all_content()

    # Render with pager
    # Set LESS env var to handle ANSI codes properly (fixes PyInstaller binary)
    import os
    os.environ.setdefault("LESS", "-R")
    with console.pager(styles=True):
        console.print(Markdown(content))
