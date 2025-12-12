"""MU zen command - Cache cleanup to achieve zen.

This command clears caches and temporary files, providing a clean slate
for the codebase analysis tools.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from mu.cli import MUContext


@click.command(name="zen", short_help="Clean up - clear caches")
@click.option(
    "--yes", "-y", "--force", "-f", is_flag=True, help="Skip confirmation prompt"
)
@click.option("--dry-run", "-n", is_flag=True, help="Show what would be cleaned without doing it")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_obj
def zen(ctx: MUContext, yes: bool, dry_run: bool, as_json: bool) -> None:
    """Clean up - clear caches and achieve zen.

    Shows what would be cleaned and prompts for confirmation (interactive).
    Use --yes to skip the prompt, or --dry-run to just preview.

    \b
    Examples:
        mu zen           # Interactive - shows preview and asks to confirm
        mu zen --yes     # Clean without asking
        mu zen --dry-run # Just show what would be cleaned
        mu zen --json    # Output stats as JSON
    """
    import json
    import shutil

    from mu.cache import CacheManager
    from mu.config import MUConfig

    cwd = Path.cwd()
    mu_dir = cwd / ".mu"

    # Load config
    try:
        config = MUConfig.load()
    except Exception:
        config = MUConfig()

    stats = {
        "cache_entries_removed": 0,
        "bytes_freed": 0,
        "temp_files_removed": 0,
    }

    # Calculate what would be cleaned
    cache_dir = mu_dir / "cache"
    cache_size = 0
    cache_files = 0
    if cache_dir.exists():
        cache_size = sum(f.stat().st_size for f in cache_dir.rglob("*") if f.is_file())
        cache_files = len(list(cache_dir.rglob("*")))

    temp_files_to_clean: list[Path] = []
    temp_patterns = ["*.tmp", "*.temp", ".mu-*.tmp"]
    for pattern in temp_patterns:
        temp_files_to_clean.extend(cwd.glob(pattern))

    temp_size = sum(f.stat().st_size for f in temp_files_to_clean if f.exists())

    total_items = cache_files + len(temp_files_to_clean)

    # Show preview
    def show_preview() -> None:
        click.echo()
        click.echo(click.style("Would clean:", bold=True))
        click.echo()
        if cache_files > 0:
            mb = cache_size / 1_000_000
            click.echo(f"  * {cache_files:,} cached entries ({mb:.1f}MB)")
        else:
            click.echo(click.style("  * No cached entries", dim=True))
        if temp_files_to_clean:
            mb = temp_size / 1_000_000
            click.echo(f"  * {len(temp_files_to_clean):,} temp files ({mb:.1f}MB)")
        else:
            click.echo(click.style("  * No temp files", dim=True))
        click.echo()

    # Dry-run mode: just show what would be cleaned
    if dry_run:
        show_preview()
        if total_items == 0:
            click.echo(click.style("Nothing to clean. Zen achieved.", dim=True))
        return

    # JSON mode with --yes: perform cleanup and output JSON
    if as_json and not yes:
        # JSON mode without --yes: just output stats as JSON
        pass  # Fall through to cleanup logic
    elif not yes:
        # Interactive mode: show preview and prompt for confirmation
        show_preview()
        if total_items == 0:
            click.echo(click.style("Nothing to clean. Zen achieved.", dim=True))
            return

        # Prompt for confirmation if running interactively
        if sys.stdin.isatty():
            if not click.confirm("Proceed with cleanup?"):
                click.echo(click.style("Cancelled.", dim=True))
                return
        else:
            # Non-interactive mode without --yes: just show preview
            click.echo(click.style("Run with --yes to clean (non-interactive mode)", dim=True))
            return

    # Actually perform cleanup
    if cache_dir.exists() and cache_files > 0:
        try:
            shutil.rmtree(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
            stats["cache_entries_removed"] = cache_files
            stats["bytes_freed"] += cache_size
        except Exception:
            pass

    for temp_file in temp_files_to_clean:
        try:
            size = temp_file.stat().st_size
            temp_file.unlink()
            stats["temp_files_removed"] += 1
            stats["bytes_freed"] += size
        except Exception:
            pass

    # Also use CacheManager
    try:
        cache_manager = CacheManager(config.cache, cwd)
        cache_manager.clear()
        cache_manager.close()
    except Exception:
        pass

    if as_json:
        click.echo(json.dumps(stats, indent=2))
        return

    # Output with personality
    click.echo()
    click.echo(click.style("Cleaning...", bold=True))
    click.echo()

    if stats["cache_entries_removed"] > 0:
        click.echo(
            click.style("[OK] ", fg="green")
            + f"Removed {stats['cache_entries_removed']:,} cached entries"
        )

    if stats["temp_files_removed"] > 0:
        click.echo(
            click.style("[OK] ", fg="green") + f"Removed {stats['temp_files_removed']:,} temp files"
        )

    mb_freed = stats["bytes_freed"] / 1_000_000
    if mb_freed > 0.01:
        click.echo(click.style("[OK] ", fg="green") + f"Freed {mb_freed:.1f}MB")

    if stats["cache_entries_removed"] == 0 and stats["temp_files_removed"] == 0:
        click.echo(click.style("[OK] ", fg="green") + "Already clean")

    click.echo()
    click.echo(click.style("Zen achieved.", dim=True))


__all__ = ["zen"]
