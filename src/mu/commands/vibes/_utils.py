"""Shared utilities for MU vibes commands.

This module contains common helper functions used across multiple vibes commands,
including interactive prompting and date/time formatting utilities.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

import click


def prompt_for_input(prompt_text: str, command_name: str = "this command") -> str:
    """Prompt user for input interactively.

    Args:
        prompt_text: The prompt message to display.
        command_name: The command name for error messages.

    Returns:
        User input string.

    Raises:
        SystemExit: If running in non-interactive mode or user cancels.
    """
    # Check if stdin is a TTY (interactive terminal)
    if not sys.stdin.isatty():
        click.echo(
            click.style("Error: ", fg="red")
            + f"{command_name} requires a target argument in non-interactive mode."
        )
        click.echo(click.style(f"Usage: mu {command_name} <target>", dim=True))
        sys.exit(1)

    try:
        result: str = click.prompt(click.style(prompt_text, fg="cyan"))
        return result
    except (click.Abort, EOFError):
        click.echo(click.style("\nCancelled.", dim=True))
        sys.exit(0)


def format_age(days: int) -> str:
    """Format age in days to human-readable string.

    Args:
        days: Number of days.

    Returns:
        Human-readable age string (e.g., "today", "3 days ago", "2 months ago").
    """
    if days == 0:
        return "today"
    elif days == 1:
        return "yesterday"
    elif days < 7:
        return f"{days} days ago"
    elif days < 30:
        weeks = days // 7
        return f"{weeks} week{'s' if weeks > 1 else ''} ago"
    elif days < 365:
        months = days // 30
        return f"{months} month{'s' if months > 1 else ''} ago"
    else:
        years = days // 365
        return f"{years} year{'s' if years > 1 else ''} ago"


def days_since(dt: datetime | None) -> int:
    """Calculate days since a datetime.

    Args:
        dt: The datetime to calculate from, or None.

    Returns:
        Number of days since the given datetime, or 0 if dt is None.
    """
    if dt is None:
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    return (now - dt).days


__all__ = ["prompt_for_input", "format_age", "days_since"]
