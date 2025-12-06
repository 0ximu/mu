"""MU LLM Spec - Machine-readable format specification."""

from __future__ import annotations

from importlib.resources import files

import click

from mu import __version__
from mu.logging import console, print_info, print_success, print_warning


def _load_content(filename: str) -> str:
    """Load markdown content from package data."""
    try:
        return files("mu.data.man.llm").joinpath(filename).read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"Error: Could not find spec file: {filename}"


def _copy_to_clipboard(content: str) -> bool:
    """Attempt to copy content to clipboard. Returns True on success."""
    try:
        import pyperclip

        pyperclip.copy(content)
        return True
    except ImportError:
        return False
    except Exception:
        # pyperclip can raise various errors on different platforms
        return False


@click.command("llm")
@click.option(
    "--full",
    is_flag=True,
    help="Output complete spec with all examples (~2K tokens)",
)
@click.option(
    "--examples",
    is_flag=True,
    help="Output just example transformations",
)
@click.option(
    "--copy",
    is_flag=True,
    help="Copy output to clipboard",
)
@click.option(
    "--raw",
    is_flag=True,
    help="Output without version header",
)
def llm_command(
    full: bool,
    examples: bool,
    copy: bool,
    raw: bool,
) -> None:
    """Output MU format spec for LLM consumption.

    Generates a token-efficient specification that can be pasted into
    an AI assistant's context to teach it the MU format.

    \b
    Modes:
      (default)    Minimal spec (~800 tokens) - sufficient to parse MU
      --full       Complete spec with examples (~2K tokens)
      --examples   Just input→output transformation examples

    \b
    Examples:
      mu llm                 # Minimal spec to stdout
      mu llm --copy          # Copy minimal spec to clipboard
      mu llm --full --copy   # Copy full spec to clipboard
      mu llm --examples      # Just the transformation examples
      mu llm --raw           # Without version header
    """
    # Determine which content to load
    if examples:
        content = _load_content("examples.md")
    elif full:
        content = _load_content("full.md")
    else:
        content = _load_content("minimal.md")

    # Add header unless raw mode
    if not raw:
        header = f"# MU Format Spec v{__version__}\n"
        header += "# Paste this to teach an LLM about MU\n\n"
        content = header + content

    # Handle clipboard copy
    if copy:
        success = _copy_to_clipboard(content)
        if success:
            token_estimate = len(content.split())  # Rough estimate
            print_success(f"Copied to clipboard ({len(content)} chars, ~{token_estimate} tokens)")
            return
        else:
            print_warning("Clipboard unavailable. Install 'pyperclip' or use system clipboard.")
            print_info("Output printed below:\n")

    # Output to stdout
    console.print(content, highlight=False)
