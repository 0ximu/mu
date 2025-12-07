"""CLI self-description module for agent consumption.

This module provides introspection of the MU CLI interface,
generating machine-readable descriptions in MU, JSON, or Markdown formats.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import click

from mu import __version__

__all__ = [
    "CommandInfo",
    "DescribeResult",
    "describe_cli",
    "format_mu",
    "format_json",
    "format_markdown",
]


@dataclass
class OptionInfo:
    """Information about a CLI option."""

    name: str
    short: str | None
    type: str
    required: bool
    default: Any
    help: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "required": self.required,
            "help": self.help,
        }
        if self.short:
            result["short"] = self.short
        if self.default is not None:
            result["default"] = self.default
        return result


@dataclass
class ArgumentInfo:
    """Information about a CLI argument."""

    name: str
    required: bool
    type: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "required": self.required,
            "type": self.type,
        }


@dataclass
class CommandInfo:
    """Information about a CLI command."""

    name: str
    description: str
    arguments: list[ArgumentInfo] = field(default_factory=list)
    options: list[OptionInfo] = field(default_factory=list)
    subcommands: list[CommandInfo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
        }
        if self.arguments:
            result["arguments"] = [a.to_dict() for a in self.arguments]
        if self.options:
            result["options"] = [o.to_dict() for o in self.options]
        if self.subcommands:
            result["subcommands"] = [s.to_dict() for s in self.subcommands]
        return result


@dataclass
class DescribeResult:
    """Result of CLI description."""

    version: str
    commands: list[CommandInfo] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result: dict[str, Any] = {
            "version": self.version,
            "commands": [c.to_dict() for c in self.commands],
        }
        if self.error:
            result["error"] = self.error
        return result


def _extract_command_info(cmd: click.Command, name: str | None = None) -> CommandInfo:
    """Extract information from a Click command.

    Args:
        cmd: The Click command to extract info from.
        name: Override for command name.

    Returns:
        CommandInfo with command details.
    """
    cmd_name = name or cmd.name or "unknown"
    description = cmd.help or cmd.short_help or ""

    # Clean up description - take first line/paragraph
    if description:
        description = description.split("\n\n")[0].strip()
        description = description.replace("\n", " ").strip()

    # Extract arguments
    arguments: list[ArgumentInfo] = []
    for param in cmd.params:
        if isinstance(param, click.Argument):
            arguments.append(
                ArgumentInfo(
                    name=param.name or "",
                    required=param.required,
                    type=_get_param_type(param),
                )
            )

    # Extract options
    options: list[OptionInfo] = []
    for param in cmd.params:
        if isinstance(param, click.Option):
            # Get short name if available
            short = None
            long_name = param.name or ""
            for opt in param.opts:
                if opt.startswith("--"):
                    long_name = opt[2:]
                elif opt.startswith("-") and len(opt) == 2:
                    short = opt[1:]

            # Skip hidden options like --help
            if param.is_eager and param.name == "help":
                continue

            options.append(
                OptionInfo(
                    name=long_name,
                    short=short,
                    type=_get_param_type(param),
                    required=param.required,
                    default=param.default if param.default is not None else None,
                    help=param.help or "",
                )
            )

    # Extract subcommands for groups
    subcommands: list[CommandInfo] = []
    if isinstance(cmd, click.Group):
        for sub_name, sub_cmd in sorted(cmd.commands.items()):
            subcommands.append(_extract_command_info(sub_cmd, sub_name))

    return CommandInfo(
        name=cmd_name,
        description=description,
        arguments=arguments,
        options=options,
        subcommands=subcommands,
    )


def _get_param_type(param: click.Parameter) -> str:
    """Get string representation of parameter type."""
    if param.type is None:
        return "string"

    type_name = param.type.name
    if type_name == "STRING":
        return "string"
    elif type_name == "INT":
        return "int"
    elif type_name == "FLOAT":
        return "float"
    elif type_name == "BOOL":
        return "bool"
    elif type_name == "PATH":
        return "path"
    elif type_name == "Choice":
        if hasattr(param.type, "choices"):
            return f"choice[{','.join(param.type.choices)}]"
        return "choice"
    else:
        return type_name.lower()


def describe_cli() -> DescribeResult:
    """Generate CLI description by introspecting Click commands.

    Returns:
        DescribeResult with command tree.
    """
    from mu.cli import cli as main_cli

    try:
        # Extract main CLI group info
        main_info = _extract_command_info(main_cli, "mu")

        # Return just the top-level commands as a flat list
        return DescribeResult(
            version=__version__,
            commands=[main_info],
        )
    except Exception as e:
        return DescribeResult(
            version=__version__,
            error=str(e),
        )


def format_mu(result: DescribeResult) -> str:
    """Format description as MU text.

    Args:
        result: The description result.

    Returns:
        MU-formatted string.
    """
    if result.error:
        return f":: Error: {result.error}"

    lines: list[str] = []
    lines.append('!mu-cli "MU Command Line Interface"')
    lines.append(f"  @version: {result.version}")
    lines.append("")

    def format_command(cmd: CommandInfo, indent: int = 2) -> None:
        prefix = " " * indent
        sig_parts = [cmd.name]

        # Add arguments
        for arg in cmd.arguments:
            if arg.required:
                sig_parts.append(f"<{arg.name}>")
            else:
                sig_parts.append(f"[{arg.name}]")

        # Add key options
        for opt in cmd.options:
            if opt.short:
                sig_parts.append(f"-{opt.short}")
            else:
                sig_parts.append(f"--{opt.name}")

        signature = ", ".join(sig_parts) if len(sig_parts) > 1 else sig_parts[0]

        # Format command line
        if cmd.subcommands:
            lines.append(f"{prefix}#{signature}")
        else:
            lines.append(f"{prefix}#{signature} -> result")

        if cmd.description:
            lines.append(f'{prefix}  :: "{cmd.description}"')

        # Recurse into subcommands
        for sub in cmd.subcommands:
            format_command(sub, indent + 2)

    # Format each top-level command's subcommands
    for cmd in result.commands:
        for sub in cmd.subcommands:
            format_command(sub)

    return "\n".join(lines)


def format_json(result: DescribeResult) -> str:
    """Format description as JSON.

    Args:
        result: The description result.

    Returns:
        JSON string.
    """
    return json.dumps(result.to_dict(), indent=2)


def format_markdown(result: DescribeResult) -> str:
    """Format description as Markdown.

    Args:
        result: The description result.

    Returns:
        Markdown string.
    """
    if result.error:
        return f"**Error:** {result.error}"

    lines: list[str] = []
    lines.append("# MU CLI Reference")
    lines.append("")
    lines.append(f"**Version:** {result.version}")
    lines.append("")

    def format_command(cmd: CommandInfo, level: int = 2) -> None:
        heading = "#" * level
        lines.append(f"{heading} {cmd.name}")
        lines.append("")

        if cmd.description:
            lines.append(cmd.description)
            lines.append("")

        if cmd.arguments:
            lines.append("**Arguments:**")
            for arg in cmd.arguments:
                req = "(required)" if arg.required else "(optional)"
                lines.append(f"- `{arg.name}` - {arg.type} {req}")
            lines.append("")

        if cmd.options:
            lines.append("**Options:**")
            for opt in cmd.options:
                short = f"`-{opt.short}`, " if opt.short else ""
                lines.append(f"- {short}`--{opt.name}` - {opt.help}")
            lines.append("")

        for sub in cmd.subcommands:
            format_command(sub, min(level + 1, 6))

    for cmd in result.commands:
        format_command(cmd)

    return "\n".join(lines)
