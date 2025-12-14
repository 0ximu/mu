"""MU kernel init command - Initialize .mu/mubase graph database.

DEPRECATED: Use 'mu bootstrap' instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from mu.paths import get_mubase_path


def _show_deprecation_warning() -> None:
    """Show deprecation warning for kernel init."""
    click.secho(
        "⚠️  'mu kernel init' is deprecated. Use 'mu bootstrap' instead.",
        fg="yellow",
        err=True,
    )


@click.command("init")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing .mu/mubase file")
def kernel_init(path: Path, force: bool) -> None:
    """[DEPRECATED] Initialize a .mu/mubase graph database.

    Use 'mu bootstrap' instead - it handles both init and build in one step.
    """
    _show_deprecation_warning()
    from mu.errors import ExitCode
    from mu.kernel import MUbase
    from mu.logging import print_error, print_info, print_success, print_warning

    mubase_path = get_mubase_path(path)

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
