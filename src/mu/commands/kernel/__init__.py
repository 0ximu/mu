"""MU Kernel Commands - Advanced graph database operations."""

from __future__ import annotations

import click

from mu.commands.lazy import LazyGroup

# Active kernel commands (visible in help)
LAZY_KERNEL_COMMANDS: dict[str, tuple[str, str]] = {
    # Kept (visible) - power-user commands not available at top level
    "export": ("mu.commands.kernel.export", "kernel_export"),
    "history": ("mu.commands.kernel.history", "kernel_history"),
    "snapshot": ("mu.commands.kernel.snapshot", "kernel_snapshot"),
    "snapshots": ("mu.commands.kernel.snapshot", "kernel_snapshots"),
    "blame": ("mu.commands.kernel.blame", "kernel_blame"),
    "search": ("mu.commands.kernel.search", "kernel_search"),
    "embed": ("mu.commands.kernel.embed", "kernel_embed"),
    "diff": ("mu.commands.kernel.diff", "kernel_diff"),
}

# Deprecated kernel commands (hidden but still work)
HIDDEN_KERNEL_COMMANDS: dict[str, tuple[str, str]] = {
    "init": ("mu.commands.kernel.init_cmd", "kernel_init"),
    "build": ("mu.commands.kernel.build", "kernel_build"),
    "stats": ("mu.commands.kernel.stats", "kernel_stats"),
    "muql": ("mu.commands.kernel.muql", "kernel_muql"),
    "deps": ("mu.commands.kernel.deps", "kernel_deps"),
    "context": ("mu.commands.kernel.context", "kernel_context"),
}


@click.group(
    cls=LazyGroup,
    lazy_subcommands=LAZY_KERNEL_COMMANDS,
    hidden_subcommands=HIDDEN_KERNEL_COMMANDS,
)
def kernel() -> None:
    """Advanced graph operations (power users).

    Most common operations are now available at the top level.
    Use 'mu kernel' for export, history, snapshots, blame.

    \b
    Migrated commands (use top-level instead):
        mu kernel init/build  ->  mu bootstrap
        mu kernel stats       ->  mu status
        mu kernel context     ->  mu context
        mu kernel muql        ->  mu query
        mu kernel deps        ->  mu deps
    """
    pass


__all__ = ["kernel"]
