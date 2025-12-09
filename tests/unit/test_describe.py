"""Tests for the CLI describe module."""

from __future__ import annotations

import json

from mu.describe import (
    ArgumentInfo,
    CommandInfo,
    DescribeResult,
    OptionInfo,
    describe_cli,
    format_json,
    format_markdown,
    format_mu,
)


class TestArgumentInfo:
    """Tests for ArgumentInfo dataclass."""

    def test_to_dict(self) -> None:
        """Test ArgumentInfo serialization."""
        arg = ArgumentInfo(name="path", required=True, type="path")
        result = arg.to_dict()

        assert result["name"] == "path"
        assert result["required"] is True
        assert result["type"] == "path"


class TestOptionInfo:
    """Tests for OptionInfo dataclass."""

    def test_to_dict_minimal(self) -> None:
        """Test OptionInfo serialization with minimal fields."""
        opt = OptionInfo(
            name="verbose",
            short=None,
            type="bool",
            required=False,
            default=None,
            help="Enable verbose output",
        )
        result = opt.to_dict()

        assert result["name"] == "verbose"
        assert result["type"] == "bool"
        assert result["required"] is False
        assert result["help"] == "Enable verbose output"
        assert "short" not in result
        assert "default" not in result

    def test_to_dict_full(self) -> None:
        """Test OptionInfo serialization with all fields."""
        opt = OptionInfo(
            name="format",
            short="f",
            type="choice[json,yaml]",
            required=False,
            default="json",
            help="Output format",
        )
        result = opt.to_dict()

        assert result["name"] == "format"
        assert result["short"] == "f"
        assert result["default"] == "json"

    def test_to_dict_excludes_non_serializable_defaults(self) -> None:
        """Test OptionInfo excludes non-JSON-serializable defaults like Sentinel."""
        from enum import Enum

        class MockSentinel(Enum):
            UNSET = "unset"

        opt = OptionInfo(
            name="option",
            short=None,
            type="string",
            required=False,
            default=MockSentinel.UNSET,  # Click uses Sentinel enum for unset
            help="Test option",
        )
        result = opt.to_dict()

        # Should NOT include the Sentinel default since it's not JSON-serializable
        assert "default" not in result

    def test_to_dict_includes_serializable_defaults(self) -> None:
        """Test OptionInfo includes JSON-serializable defaults."""
        # Test various serializable types
        test_cases = [
            ("string", "default_value"),
            ("int", 42),
            ("float", 3.14),
            ("bool", True),
            ("list", ["a", "b"]),
            ("dict", {"key": "value"}),
        ]

        for type_name, default_val in test_cases:
            opt = OptionInfo(
                name="option",
                short=None,
                type=type_name,
                required=False,
                default=default_val,
                help="Test option",
            )
            result = opt.to_dict()
            assert "default" in result, f"default should be present for {type_name}"
            assert result["default"] == default_val


class TestCommandInfo:
    """Tests for CommandInfo dataclass."""

    def test_to_dict_simple(self) -> None:
        """Test CommandInfo serialization for simple command."""
        cmd = CommandInfo(
            name="scan",
            description="Scan codebase",
        )
        result = cmd.to_dict()

        assert result["name"] == "scan"
        assert result["description"] == "Scan codebase"
        assert "arguments" not in result
        assert "options" not in result
        assert "subcommands" not in result

    def test_to_dict_with_args_and_options(self) -> None:
        """Test CommandInfo serialization with arguments and options."""
        cmd = CommandInfo(
            name="compress",
            description="Compress codebase",
            arguments=[ArgumentInfo("path", True, "path")],
            options=[
                OptionInfo("output", "o", "path", False, None, "Output file"),
            ],
        )
        result = cmd.to_dict()

        assert len(result["arguments"]) == 1
        assert len(result["options"]) == 1

    def test_to_dict_with_subcommands(self) -> None:
        """Test CommandInfo serialization with subcommands."""
        cmd = CommandInfo(
            name="kernel",
            description="Kernel commands",
            subcommands=[
                CommandInfo("init", "Initialize database"),
                CommandInfo("build", "Build graph"),
            ],
        )
        result = cmd.to_dict()

        assert len(result["subcommands"]) == 2
        assert result["subcommands"][0]["name"] == "init"


class TestDescribeResult:
    """Tests for DescribeResult dataclass."""

    def test_to_dict_success(self) -> None:
        """Test DescribeResult serialization for success case."""
        result = DescribeResult(
            version="0.1.0",
            commands=[CommandInfo("scan", "Scan codebase")],
        )
        data = result.to_dict()

        assert data["version"] == "0.1.0"
        assert len(data["commands"]) == 1
        assert "error" not in data

    def test_to_dict_with_error(self) -> None:
        """Test DescribeResult serialization with error."""
        result = DescribeResult(
            version="0.1.0",
            error="Something went wrong",
        )
        data = result.to_dict()

        assert data["error"] == "Something went wrong"


class TestDescribeCli:
    """Tests for describe_cli function."""

    def test_describe_cli_returns_result(self) -> None:
        """Test describe_cli returns DescribeResult."""
        result = describe_cli()

        assert isinstance(result, DescribeResult)
        assert result.version is not None
        assert len(result.commands) > 0
        assert result.error is None

    def test_describe_cli_includes_main_commands(self) -> None:
        """Test describe_cli includes expected commands."""
        result = describe_cli()

        # Should have the main 'mu' command
        assert len(result.commands) == 1
        main = result.commands[0]
        assert main.name == "mu"

        # Should have subcommands
        subcommand_names = [c.name for c in main.subcommands]
        assert "compress" in subcommand_names
        assert "query" in subcommand_names
        assert "describe" in subcommand_names


class TestFormatMu:
    """Tests for format_mu function."""

    def test_format_mu_basic(self) -> None:
        """Test basic MU formatting."""
        result = DescribeResult(
            version="0.1.0",
            commands=[
                CommandInfo(
                    name="mu",
                    description="Main CLI",
                    subcommands=[
                        CommandInfo("scan", "Scan codebase"),
                    ],
                ),
            ],
        )
        output = format_mu(result)

        assert "!mu-cli" in output
        assert "@version: 0.1.0" in output
        assert "#scan" in output

    def test_format_mu_with_error(self) -> None:
        """Test MU formatting with error."""
        result = DescribeResult(version="0.1.0", error="Test error")
        output = format_mu(result)

        assert "Error: Test error" in output


class TestFormatJson:
    """Tests for format_json function."""

    def test_format_json_valid(self) -> None:
        """Test JSON formatting produces valid JSON."""
        result = DescribeResult(
            version="0.1.0",
            commands=[CommandInfo("scan", "Scan codebase")],
        )
        output = format_json(result)

        # Should be valid JSON
        data = json.loads(output)
        assert data["version"] == "0.1.0"
        assert len(data["commands"]) == 1

    def test_format_json_from_real_cli(self) -> None:
        """Test that describe_cli() output is valid JSON (regression test)."""
        # This catches non-serializable types like Click's Sentinel
        result = describe_cli()
        output = format_json(result)

        # Should produce valid JSON without TypeError
        data = json.loads(output)
        assert data["version"] is not None
        assert len(data["commands"]) > 0

        # Should have subcommands (not empty due to extraction issues)
        main_cmd = data["commands"][0]
        assert len(main_cmd.get("subcommands", [])) > 0


class TestFormatMarkdown:
    """Tests for format_markdown function."""

    def test_format_markdown_basic(self) -> None:
        """Test basic Markdown formatting."""
        result = DescribeResult(
            version="0.1.0",
            commands=[
                CommandInfo(
                    name="mu",
                    description="Main CLI",
                    subcommands=[
                        CommandInfo("scan", "Scan codebase"),
                    ],
                ),
            ],
        )
        output = format_markdown(result)

        assert "# MU CLI Reference" in output
        assert "**Version:** 0.1.0" in output
        assert "## scan" in output

    def test_format_markdown_with_error(self) -> None:
        """Test Markdown formatting with error."""
        result = DescribeResult(version="0.1.0", error="Test error")
        output = format_markdown(result)

        assert "**Error:** Test error" in output
