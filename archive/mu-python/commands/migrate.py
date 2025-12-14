"""MU migrate command - Migrate from legacy file layout to .mu/ directory."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from mu.paths import has_legacy_files, migrate_legacy_files


@click.command("migrate")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--dry-run", is_flag=True, help="Show what would be migrated without doing it")
@click.option("--force", "-f", is_flag=True, help="Migrate even if .mu/ already exists")
def migrate(path: Path, dry_run: bool, force: bool) -> None:
    """Migrate legacy MU files to the new .mu/ directory structure.

    This command moves:
    - .mubase -> .mu/mubase
    - .mu-cache/ -> .mu/cache/
    - .mu-contracts.yml -> .mu/contracts.yml
    - .mu.pid -> .mu/daemon.pid

    \b
    Examples:
        mu migrate             # Migrate current directory
        mu migrate . --dry-run # Show what would be migrated
        mu migrate /path/to/project
    """
    from mu.logging import print_info, print_success, print_warning
    from mu.paths import get_mu_dir

    root = path.resolve()
    mu_dir = get_mu_dir(root)

    # Check if .mu/ already exists with content
    if mu_dir.exists() and any(mu_dir.iterdir()) and not force:
        print_warning(f".mu/ directory already exists at {mu_dir}")
        print_info("Use --force to migrate anyway (existing files in .mu/ will not be overwritten)")
        sys.exit(1)

    # Check for legacy files
    legacy = has_legacy_files(root)
    if not legacy:
        print_info("No legacy MU files found. Nothing to migrate.")
        return

    print_info(f"Found {len(legacy)} legacy MU file(s) to migrate:")
    for _name, legacy_path in legacy.items():
        print_info(f"  - {legacy_path.name}")

    if dry_run:
        print_info("\nDry run - no changes made. Run without --dry-run to migrate.")
        migrations = migrate_legacy_files(root, dry_run=True)
        print_info("\nWould perform these migrations:")
        for src, dst in migrations:
            print_info(f"  {src} -> {dst}")
        return

    # Perform migration
    migrations = migrate_legacy_files(root, dry_run=False)

    if migrations:
        print_success(f"\nMigrated {len(migrations)} file(s) to .mu/ directory:")
        for src, dst in migrations:
            print_success(f"  {src.name} -> {dst.relative_to(root)}")

        print_info("\nNote: Your .murc.toml config file remains in the project root.")
        print_info("You may want to update any CI/CD scripts that reference the old paths.")
    else:
        print_warning("No files were migrated.")


__all__ = ["migrate"]
