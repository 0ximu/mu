"""Lazy-loading Click group for fast CLI startup."""

from __future__ import annotations

import importlib
from typing import Any

import click


class LazyGroup(click.Group):
    """A Click group that lazily loads subcommands on first access.

    This enables fast CLI startup by deferring command module imports
    until the command is actually invoked.
    """

    def __init__(
        self,
        *args: Any,
        lazy_subcommands: dict[str, tuple[str, str]] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize lazy group.

        Args:
            lazy_subcommands: Dict mapping command name to (module_path, attr_name)
                Example: {'compress': ('mu.commands.compress', 'compress')}
        """
        super().__init__(*args, **kwargs)
        self._lazy_subcommands: dict[str, tuple[str, str]] = lazy_subcommands or {}
        self._loaded_commands: dict[str, click.Command] = {}

    def list_commands(self, ctx: click.Context) -> list[str]:
        """List all available commands (lazy + already registered)."""
        base = super().list_commands(ctx)
        lazy = list(self._lazy_subcommands.keys())
        return sorted(set(base + lazy))

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        """Get command, loading lazily if needed."""
        # Check if already loaded
        if cmd_name in self._loaded_commands:
            return self._loaded_commands[cmd_name]

        # Check parent (already registered commands)
        cmd = super().get_command(ctx, cmd_name)
        if cmd is not None:
            return cmd

        # Lazy load
        if cmd_name in self._lazy_subcommands:
            module_path, attr_name = self._lazy_subcommands[cmd_name]
            try:
                module = importlib.import_module(module_path)
                loaded_cmd: click.Command = getattr(module, attr_name)
                self._loaded_commands[cmd_name] = loaded_cmd
                return loaded_cmd
            except (ImportError, AttributeError) as e:
                raise click.ClickException(f"Failed to load command '{cmd_name}': {e}") from None

        return None


__all__ = ["LazyGroup"]
