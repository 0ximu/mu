"""MU view command - Render MU file in human-readable format."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from mu.cli import MUContext


@click.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--format",
    "-f",
    type=click.Choice(["terminal", "html", "markdown"]),
    default="terminal",
    help="Output format",
)
@click.option(
    "--theme",
    type=click.Choice(["dark", "light"]),
    default="dark",
    help="Color theme for terminal/HTML output",
)
@click.option(
    "--line-numbers",
    "-n",
    is_flag=True,
    help="Show line numbers",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output file (for html/markdown formats)",
)
@click.pass_obj
def view(
    ctx: MUContext,
    file: Path,
    format: str,
    theme: str,
    line_numbers: bool,
    output: Path | None,
) -> None:
    """Render MU file in human-readable format.

    Supports terminal output with syntax highlighting, HTML export,
    and markdown code fencing.
    """
    from mu.logging import console, print_success
    from mu.viewer import view_file

    result = view_file(
        file_path=file,
        output_format=format,
        theme=theme,
        line_numbers=line_numbers,
    )

    if output:
        output.write_text(result)
        print_success(f"Output written to {output}")
    else:
        # For terminal, use rich console; for others, print directly
        if format == "terminal":
            # Print raw ANSI - rich console will handle it
            console.print(result, highlight=False)
        else:
            console.print(result)


__all__ = ["view"]
