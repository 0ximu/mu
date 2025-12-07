"""MU Contracts Commands - Architecture verification."""

from __future__ import annotations

import click

from mu.commands.lazy import LazyGroup

# Define lazy subcommands for contracts group
LAZY_CONTRACTS_COMMANDS: dict[str, tuple[str, str]] = {
    "init": ("mu.commands.contracts.init_cmd", "contracts_init"),
    "verify": ("mu.commands.contracts.verify", "contracts_verify"),
}


@click.group(cls=LazyGroup, lazy_subcommands=LAZY_CONTRACTS_COMMANDS)
def contracts() -> None:
    """MU Contracts - Architecture verification.

    Define and verify architectural rules against the codebase graph.
    Rules are defined in YAML files (.mu-contracts.yml).

    \b
    Examples:
        mu contracts init .           # Create template file
        mu contracts verify .         # Verify contracts
        mu contracts verify . --format json
    """
    pass


__all__ = ["contracts"]
