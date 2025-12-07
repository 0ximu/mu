"""MU init command - Initialize .murc.toml configuration."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from mu.cli import MUContext


@click.command()
@click.option("--force", "-f", is_flag=True, help="Overwrite existing .murc.toml")
@click.pass_obj
def init(ctx: MUContext, force: bool) -> None:
    """Initialize a new .murc.toml configuration file.

    Creates a configuration file with sensible defaults in the current directory.
    """
    from mu.config import get_default_config_toml
    from mu.errors import ExitCode
    from mu.logging import print_error, print_info, print_success, print_warning

    config_path = Path.cwd() / ".murc.toml"

    if config_path.exists() and not force:
        print_warning(f"Configuration file already exists: {config_path}")
        print_info("Use --force to overwrite")
        sys.exit(ExitCode.CONFIG_ERROR)

    try:
        config_path.write_text(get_default_config_toml())
        print_success(f"Created {config_path}")
        print_info("\nNext steps:")
        print_info("  1. Edit .murc.toml to customize settings")
        print_info("  2. Run 'mu scan .' to analyze your codebase")
        print_info("  3. Run 'mu compress .' to generate MU output")
    except PermissionError:
        print_error(f"Permission denied: {config_path}")
        sys.exit(ExitCode.CONFIG_ERROR)
    except Exception as e:
        print_error(f"Failed to create config file: {e}")
        sys.exit(ExitCode.FATAL_ERROR)


__all__ = ["init"]
