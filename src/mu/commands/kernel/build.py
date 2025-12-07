"""MU kernel build command - Build graph database from codebase."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from mu.cli import MUContext


@click.command("build")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output .mubase file (default: {path}/.mubase)",
)
@click.pass_obj
def kernel_build(ctx: MUContext, path: Path, output: Path | None) -> None:
    """Build graph database from codebase.

    Scans the directory, parses all supported files, and builds a
    queryable graph of modules, classes, functions, and their relationships.
    """
    from mu.config import MUConfig
    from mu.kernel import MUbase
    from mu.logging import print_info, print_success, print_warning
    from mu.parser.base import parse_file
    from mu.scanner import SUPPORTED_LANGUAGES, scan_codebase_auto

    if ctx.config is None:
        ctx.config = MUConfig()

    root_path = path.resolve()
    mubase_path = output or (root_path / ".mubase")

    # Scan codebase
    print_info(f"Scanning {root_path}...")
    scan_result = scan_codebase_auto(root_path, ctx.config)

    if not scan_result.files:
        print_warning("No supported files found")
        return

    print_info(f"Found {len(scan_result.files)} files")

    # Parse all files (only supported languages)
    print_info("Parsing files...")
    modules = []
    errors = 0
    skipped = 0

    for file_info in scan_result.files:
        # Skip non-parseable languages (markdown, json, yaml, toml, etc.)
        if file_info.language not in SUPPORTED_LANGUAGES:
            skipped += 1
            continue

        parsed = parse_file(Path(root_path / file_info.path), file_info.language)
        if parsed.success and parsed.module:
            modules.append(parsed.module)
        elif parsed.error:
            errors += 1
            if ctx.verbosity == "verbose":
                print_warning(f"  Parse error in {file_info.path}: {parsed.error}")

    if errors > 0:
        print_warning(f"  {errors} files had parse errors")

    if not modules:
        print_warning("No modules parsed successfully")
        return

    print_info(f"Parsed {len(modules)} modules")

    # Build graph
    print_info("Building graph...")
    db = MUbase(mubase_path)
    db.build(modules, root_path)
    stats = db.stats()
    db.close()

    print_success(f"Built graph: {stats['nodes']} nodes, {stats['edges']} edges")
    print_info(f"Database: {mubase_path}")

    # Show breakdown
    if ctx.verbosity != "quiet":
        for node_type, count in stats.get("nodes_by_type", {}).items():
            print_info(f"  {node_type}: {count}")


__all__ = ["kernel_build"]
