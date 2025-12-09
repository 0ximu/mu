"""Lazy-loading Click group for fast CLI startup."""

from __future__ import annotations

import importlib
from typing import Any

import click


class LazyGroup(click.Group):
    """A Click group that lazily loads subcommands on first access.

    This enables fast CLI startup by deferring command module imports
    until the command is actually invoked.

    Supports hidden commands that work but don't show in help.
    """

    def __init__(
        self,
        *args: Any,
        lazy_subcommands: dict[str, tuple[str, str]] | None = None,
        hidden_subcommands: dict[str, tuple[str, str]] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize lazy group.

        Args:
            lazy_subcommands: Dict mapping command name to (module_path, attr_name)
                Example: {'compress': ('mu.commands.compress', 'compress')}
            hidden_subcommands: Same format, but these won't show in help
        """
        super().__init__(*args, **kwargs)
        self._lazy_subcommands: dict[str, tuple[str, str]] = lazy_subcommands or {}
        self._hidden_subcommands: dict[str, tuple[str, str]] = hidden_subcommands or {}
        self._loaded_commands: dict[str, click.Command] = {}

    def list_commands(self, ctx: click.Context) -> list[str]:
        """List visible commands (excludes hidden)."""
        base = super().list_commands(ctx)
        lazy = list(self._lazy_subcommands.keys())
        # Don't include hidden commands in list
        return sorted(set(base + lazy))

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        """Get command, loading lazily if needed (includes hidden)."""
        # Check if already loaded
        if cmd_name in self._loaded_commands:
            return self._loaded_commands[cmd_name]

        # Check parent (already registered commands)
        cmd = super().get_command(ctx, cmd_name)
        if cmd is not None:
            return cmd

        # Lazy load from visible commands
        if cmd_name in self._lazy_subcommands:
            module_path, attr_name = self._lazy_subcommands[cmd_name]
            return self._load_command(cmd_name, module_path, attr_name)

        # Lazy load from hidden commands
        if cmd_name in self._hidden_subcommands:
            module_path, attr_name = self._hidden_subcommands[cmd_name]
            return self._load_command(cmd_name, module_path, attr_name)

        return None

    def _load_command(self, cmd_name: str, module_path: str, attr_name: str) -> click.Command:
        """Load a command from a module."""
        try:
            module = importlib.import_module(module_path)
            loaded_cmd: click.Command = getattr(module, attr_name)
            self._loaded_commands[cmd_name] = loaded_cmd
            return loaded_cmd
        except (ImportError, AttributeError) as e:
            raise click.ClickException(f"Failed to load command '{cmd_name}': {e}") from None


__all__ = ["LazyGroup"]
