"""MU kernel init command - Initialize .mubase graph database."""

from __future__ import annotations

import sys
from pathlib import Path

import click


@click.command("init")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing .mubase file")
def kernel_init(path: Path, force: bool) -> None:
    """Initialize a .mubase graph database.

    Creates an empty .mubase file in the specified directory.
    Use 'mu kernel build' to populate it with your codebase.
    """
    from mu.errors import ExitCode
    from mu.kernel import MUbase
    from mu.logging import print_error, print_info, print_success, print_warning

    mubase_path = path.resolve() / ".mubase"

    if mubase_path.exists() and not force:
        print_warning(f"Database already exists: {mubase_path}")
        print_info("Use --force to overwrite")
        sys.exit(ExitCode.CONFIG_ERROR)

    if mubase_path.exists():
        mubase_path.unlink()

    try:
        db = MUbase(mubase_path)
        db.close()
        print_success(f"Created {mubase_path}")
        print_info("\nNext steps:")
        print_info("  1. Run 'mu kernel build .' to populate the graph")
        print_info("  2. Run 'mu kernel stats' to see graph statistics")
    except Exception as e:
        print_error(f"Failed to create database: {e}")
        sys.exit(ExitCode.FATAL_ERROR)


__all__ = ["kernel_init"]
