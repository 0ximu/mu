"""MU cache commands - Manage MU cache."""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from mu.cli import MUContext


@click.group()
def cache() -> None:
    """Manage MU cache."""
    pass


@cache.command("clear")
@click.option("--llm-only", is_flag=True, help="Only clear LLM response cache")
@click.option("--files-only", is_flag=True, help="Only clear file result cache")
@click.pass_obj
def cache_clear(ctx: MUContext, llm_only: bool, files_only: bool) -> None:
    """Clear all cached data."""
    from mu.cache import CacheManager
    from mu.config import MUConfig
    from mu.logging import print_info, print_success

    if ctx.config is None:
        ctx.config = MUConfig()

    cache_manager = CacheManager(ctx.config.cache)

    if not cache_manager.cache_dir.exists():
        print_info("Cache directory does not exist")
        return

    if llm_only or files_only:
        # Selective clearing using diskcache
        cache_manager._ensure_initialized()
        if llm_only and cache_manager._llm_cache:
            count = len(cache_manager._llm_cache)
            cache_manager._llm_cache.clear()
            print_success(f"Cleared {count} LLM cache entries")
        if files_only and cache_manager._file_cache:
            count = len(cache_manager._file_cache)
            cache_manager._file_cache.clear()
            print_success(f"Cleared {count} file cache entries")
        cache_manager.close()
    else:
        # Full clear
        cleared = cache_manager.clear()
        print_success(
            f"Cleared cache: {cleared['file_entries']} file entries, "
            f"{cleared['llm_entries']} LLM entries"
        )
        cache_manager.close()


@cache.command("stats")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_obj
def cache_stats(ctx: MUContext, as_json: bool) -> None:
    """Show cache statistics."""
    import json as json_module

    from rich.table import Table

    from mu.cache import CacheManager
    from mu.config import MUConfig
    from mu.logging import console, print_info

    if ctx.config is None:
        ctx.config = MUConfig()

    cache_manager = CacheManager(ctx.config.cache)
    stats = cache_manager.get_stats()
    cache_manager.close()

    if as_json:
        console.print(json_module.dumps(stats, indent=2))
        return

    if not stats.get("exists"):
        print_info("Cache is empty")
        return

    table = Table(title="Cache Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Location", stats["directory"])
    table.add_row("Enabled", "Yes" if stats["enabled"] else "No")
    table.add_row("File Entries", str(stats.get("file_entries", 0)))
    table.add_row("LLM Entries", str(stats.get("llm_entries", 0)))
    table.add_row("Disk Files", str(stats.get("file_count", 0)))
    table.add_row("Size", f"{stats.get('size_kb', 0):.1f} KB")
    table.add_row("TTL", f"{stats.get('ttl_hours', 168)} hours")
    table.add_row("", "")
    table.add_row("Cache Hits", str(stats.get("hits", 0)))
    table.add_row("Cache Misses", str(stats.get("misses", 0)))
    table.add_row("Hit Rate", f"{stats.get('hit_rate_percent', 0):.1f}%")

    console.print(table)


@cache.command("expire")
@click.pass_obj
def cache_expire(ctx: MUContext) -> None:
    """Force expiration of old cache entries."""
    from mu.cache import CacheManager
    from mu.config import MUConfig
    from mu.logging import print_info, print_success

    if ctx.config is None:
        ctx.config = MUConfig()

    cache_manager = CacheManager(ctx.config.cache)

    if not cache_manager.cache_dir.exists():
        print_info("Cache directory does not exist")
        return

    expired = cache_manager.expire_old_entries()
    cache_manager.close()

    if expired > 0:
        print_success(f"Expired {expired} cache entries")
    else:
        print_info("No entries to expire")


__all__ = ["cache", "cache_clear", "cache_stats", "cache_expire"]
