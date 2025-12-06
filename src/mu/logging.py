"""Logging configuration for MU CLI."""

from __future__ import annotations

import logging
import sys
from typing import Literal

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

# Console instances for stdout/stderr
console = Console()
err_console = Console(stderr=True)


def setup_logging(
    verbosity: Literal["quiet", "normal", "verbose"] = "normal",
) -> logging.Logger:
    """Configure logging based on verbosity level."""
    logger = logging.getLogger("mu")

    # Clear existing handlers
    logger.handlers.clear()

    # Set level based on verbosity
    level_map = {
        "quiet": logging.ERROR,
        "normal": logging.INFO,
        "verbose": logging.DEBUG,
    }
    logger.setLevel(level_map[verbosity])

    # Use Rich handler for pretty output
    handler = RichHandler(
        console=err_console,
        show_time=verbosity == "verbose",
        show_path=verbosity == "verbose",
        rich_tracebacks=True,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)

    return logger


def get_logger() -> logging.Logger:
    """Get the MU logger instance."""
    return logging.getLogger("mu")


def create_progress() -> Progress:
    """Create a Rich progress bar for file processing."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=err_console,
    )


def print_error(message: str) -> None:
    """Print an error message to stderr."""
    err_console.print(f"[red]Error:[/red] {message}")


def print_warning(message: str) -> None:
    """Print a warning message to stderr."""
    err_console.print(f"[yellow]Warning:[/yellow] {message}")


def print_success(message: str) -> None:
    """Print a success message to stdout."""
    console.print(f"[green]{message}[/green]")


def print_info(message: str) -> None:
    """Print an info message to stdout."""
    console.print(message)
