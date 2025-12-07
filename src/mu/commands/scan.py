"""MU scan command - Analyze codebase structure."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from mu.cli import MUContext
    from mu.scanner import ScanResult


@click.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output file for manifest (default: stdout)",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(["json", "text"]),
    default="text",
    help="Output format",
)
@click.pass_obj
def scan(ctx: MUContext, path: Path, output: Path | None, format: str) -> None:
    """Analyze codebase structure and output manifest.

    Walks the filesystem, identifies modules, languages, and structure.
    Filters noise directories (node_modules, .git, etc.).
    """
    from mu.config import MUConfig
    from mu.logging import console, print_success
    from mu.scanner import scan_codebase

    if ctx.config is None:
        ctx.config = MUConfig()

    result = scan_codebase(path, ctx.config)

    if format == "json":
        import json

        output_str = json.dumps(result.to_dict(), indent=2)
    else:
        # Text format summary
        output_str = _format_scan_result(result)

    if output:
        output.write_text(output_str)
        print_success(f"Manifest written to {output}")
    else:
        console.print(output_str)


def _format_scan_result(result: ScanResult) -> str:
    """Format scan result as human-readable text."""
    lines = [
        f"Scanned: {result.root}",
        f"Files found: {result.stats.total_files}",
        f"Total lines: {result.stats.total_lines}",
        "",
        "Languages:",
    ]
    for lang, count in sorted(result.stats.languages.items(), key=lambda x: -x[1]):
        lines.append(f"  {lang}: {count} files")

    if result.skipped:
        lines.append("")
        lines.append(f"Skipped: {len(result.skipped)} items")

    return "\n".join(lines)


__all__ = ["scan"]
