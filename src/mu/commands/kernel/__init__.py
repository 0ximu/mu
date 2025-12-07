"""MU Kernel Commands - Graph database operations."""

from __future__ import annotations

import click

from mu.commands.lazy import LazyGroup

# Define lazy subcommands for kernel group
LAZY_KERNEL_COMMANDS: dict[str, tuple[str, str]] = {
    "init": ("mu.commands.kernel.init_cmd", "kernel_init"),
    "build": ("mu.commands.kernel.build", "kernel_build"),
    "stats": ("mu.commands.kernel.stats", "kernel_stats"),
    "muql": ("mu.commands.kernel.muql", "kernel_muql"),
    "deps": ("mu.commands.kernel.deps", "kernel_deps"),
    "embed": ("mu.commands.kernel.embed", "kernel_embed"),
    "search": ("mu.commands.kernel.search", "kernel_search"),
    "context": ("mu.commands.kernel.context", "kernel_context"),
    "snapshot": ("mu.commands.kernel.snapshot", "kernel_snapshot"),
    "snapshots": ("mu.commands.kernel.snapshot", "kernel_snapshots"),
    "history": ("mu.commands.kernel.history", "kernel_history"),
    "blame": ("mu.commands.kernel.blame", "kernel_blame"),
    "diff": ("mu.commands.kernel.diff", "kernel_diff"),
    "export": ("mu.commands.kernel.export", "kernel_export"),
}


@click.group(cls=LazyGroup, lazy_subcommands=LAZY_KERNEL_COMMANDS)
def kernel() -> None:
    """MU Kernel commands (graph database).

    Build and query a graph representation of your codebase stored in .mubase.
    """
    pass


__all__ = ["kernel"]
