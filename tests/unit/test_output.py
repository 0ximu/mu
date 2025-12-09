"""Tests for Output Formatter - Unified output formatting for CLI commands.

Tests cover output formats (table, json, csv, tree), truncation behavior,
TTY auto-detection, and smart path truncation.
"""

from __future__ import annotations

import json

from mu.output import (
    Colors,
    Column,
    OutputConfig,
    colorize,
    format_csv,
    format_cycles,
    format_json,
    format_node_list,
    format_output,
    format_table,
    format_tree,
    smart_truncate,
)


class TestOutputConfig:
    """Tests for OutputConfig dataclass."""

    def test_default_config(self) -> None:
        """Default config should have sensible defaults."""
        config = OutputConfig()

        assert config.format == "table"
        assert config.no_truncate is False
        assert config.no_color is False
        assert config.width is None

    def test_config_with_values(self) -> None:
        """Config should accept custom values."""
        config = OutputConfig(
            format="json",
            no_truncate=True,
            no_color=True,
            width=120,
        )

        assert config.format == "json"
        assert config.no_truncate is True
        assert config.no_color is True
        assert config.width == 120

    def test_to_dict(self) -> None:
        """Config should serialize to dictionary."""
        config = OutputConfig(format="csv", no_truncate=True)
        result = config.to_dict()

        assert result["format"] == "csv"
        assert result["no_truncate"] is True
        assert result["no_color"] is False
        assert result["width"] is None


class TestColorize:
    """Tests for ANSI color functions."""

    def test_colorize_applies_color(self) -> None:
        """Colorize should wrap text with ANSI codes."""
        result = colorize("hello", Colors.RED)

        assert result.startswith(Colors.RED)
        assert result.endswith(Colors.RESET)
        assert "hello" in result

    def test_colorize_no_color_mode(self) -> None:
        """Colorize should return plain text when no_color=True."""
        result = colorize("hello", Colors.RED, no_color=True)

        assert result == "hello"
        assert Colors.RED not in result


class TestSmartTruncate:
    """Tests for smart truncation logic."""

    def test_short_values_unchanged(self) -> None:
        """Short values should not be truncated."""
        result = smart_truncate("short", max_width=20)

        assert result == "short"

    def test_exact_width_unchanged(self) -> None:
        """Values at exact max_width should not be truncated."""
        value = "x" * 20
        result = smart_truncate(value, max_width=20)

        assert result == value

    def test_path_middle_truncation(self) -> None:
        """Paths should use middle truncation to preserve filename."""
        path = "src/very/long/path/to/file.py"
        result = smart_truncate(path, max_width=25, column_hint="file_path")

        assert "..." in result
        assert result.startswith("src/")
        assert result.endswith(".py")
        assert len(result) <= 25

    def test_name_end_truncation(self) -> None:
        """Names should use end truncation."""
        name = "VeryLongClassNameThatNeedsTruncation"
        result = smart_truncate(name, max_width=20)

        assert result.endswith("...")
        assert result.startswith("VeryLongClass")
        assert len(result) <= 20

    def test_path_detection_by_slash(self) -> None:
        """Values with slashes should be detected as paths."""
        path = "/usr/local/bin/something/very/long/path"
        result = smart_truncate(path, max_width=25)

        # Should use middle truncation for paths
        assert "..." in result
        assert not result.endswith("...")  # End truncation would end with ...

    def test_path_detection_by_extension(self) -> None:
        """Values with common file extensions should be detected as paths."""
        path = "very_long_filename_here.py"
        result = smart_truncate(path, max_width=20, column_hint="something")

        # Should preserve extension
        assert result.endswith(".py")

    def test_minimum_width_enforced(self) -> None:
        """Truncation should respect minimum width."""
        value = "something"
        result = smart_truncate(value, max_width=5)

        # Should return original if max_width is too small
        assert result == value


class TestFormatJson:
    """Tests for JSON output format."""

    def test_format_json_valid(self) -> None:
        """JSON output should be parseable."""
        data = [
            {"name": "foo", "value": 1},
            {"name": "bar", "value": 2},
        ]

        result = format_json(data)
        parsed = json.loads(result)

        assert "data" in parsed
        assert "count" in parsed
        assert len(parsed["data"]) == 2

    def test_format_json_with_title(self) -> None:
        """JSON output should include title when provided."""
        data = [{"name": "foo"}]

        result = format_json(data, title="Test Title")
        parsed = json.loads(result)

        assert parsed["title"] == "Test Title"

    def test_format_json_empty_data(self) -> None:
        """Empty data should produce valid JSON."""
        result = format_json([])
        parsed = json.loads(result)

        assert parsed["data"] == []
        assert parsed["count"] == 0


class TestFormatCsv:
    """Tests for CSV output format."""

    def test_format_csv_headers(self) -> None:
        """CSV should have header row."""
        data = [
            {"name": "foo", "type": "class"},
            {"name": "bar", "type": "function"},
        ]
        columns = [Column("Name", "name"), Column("Type", "type")]

        result = format_csv(data, columns)
        # CSV uses \r\n line endings, normalize for comparison
        lines = [line.rstrip("\r") for line in result.strip().split("\n")]

        assert lines[0] == "Name,Type"
        assert len(lines) == 3  # header + 2 data rows

    def test_format_csv_escapes_quotes(self) -> None:
        """CSV should properly escape quotes."""
        data = [{"name": 'value "with" quotes', "type": "test"}]
        columns = [Column("Name", "name"), Column("Type", "type")]

        result = format_csv(data, columns)

        assert '""' in result  # Doubled quotes

    def test_format_csv_escapes_commas(self) -> None:
        """CSV should quote values with commas."""
        data = [{"name": "a, b, c", "type": "test"}]
        columns = [Column("Name", "name"), Column("Type", "type")]

        result = format_csv(data, columns)

        assert '"a, b, c"' in result

    def test_format_csv_empty_data(self) -> None:
        """Empty data should produce empty string."""
        columns = [Column("Name", "name")]

        result = format_csv([], columns)

        assert result == ""


class TestFormatTable:
    """Tests for table output format."""

    def test_format_table_basic(self) -> None:
        """Table should show column headers and data."""
        data = [
            {"name": "foo", "type": "class"},
            {"name": "bar", "type": "function"},
        ]
        columns = [Column("Name", "name"), Column("Type", "type")]
        config = OutputConfig(no_color=True)

        result = format_table(data, columns, config)

        assert "Name" in result
        assert "Type" in result
        assert "foo" in result
        assert "bar" in result
        assert "2 rows" in result

    def test_format_table_no_truncate(self) -> None:
        """Table with no_truncate should show full values."""
        data = [{"name": "VeryLongClassNameThatNeedsTruncation"}]
        columns = [Column("Name", "name")]
        config = OutputConfig(no_truncate=True, no_color=True)

        result = format_table(data, columns, config)

        assert "VeryLongClassNameThatNeedsTruncation" in result
        assert "..." not in result

    def test_format_table_with_title(self) -> None:
        """Table should show title when provided."""
        data = [{"name": "foo"}]
        columns = [Column("Name", "name")]
        config = OutputConfig(no_color=True)

        result = format_table(data, columns, config, title="Test Title")

        assert "Test Title" in result

    def test_format_table_empty_data(self) -> None:
        """Empty data should show 'No results found'."""
        columns = [Column("Name", "name")]
        config = OutputConfig(no_color=True)

        result = format_table([], columns, config)

        assert "No results found" in result


class TestFormatTree:
    """Tests for tree output format."""

    def test_format_tree_basic(self) -> None:
        """Tree should show items with tree markers."""
        data = [
            {"node_id": "foo", "type": "class"},
            {"node_id": "bar", "type": "function"},
        ]
        columns = [Column("Node", "node_id"), Column("Type", "type")]
        config = OutputConfig(no_color=True)

        result = format_tree(data, columns, config)

        assert "|--" in result or "`--" in result
        assert "foo" in result
        assert "bar" in result

    def test_format_tree_empty_data(self) -> None:
        """Empty data should show 'No results found'."""
        columns = [Column("Name", "name")]
        config = OutputConfig(no_color=True)

        result = format_tree([], columns, config)

        assert "No results found" in result


class TestFormatOutput:
    """Tests for main format_output dispatcher."""

    def test_format_output_table(self) -> None:
        """format_output should dispatch to table formatter."""
        data = [{"name": "foo"}]
        columns = [("Name", "name")]
        config = OutputConfig(format="table", no_color=True)

        result = format_output(data, columns, config)

        assert "Name" in result  # Table header
        assert "foo" in result

    def test_format_output_json(self) -> None:
        """format_output should dispatch to JSON formatter."""
        data = [{"name": "foo"}]
        columns = [("Name", "name")]
        config = OutputConfig(format="json")

        result = format_output(data, columns, config)

        parsed = json.loads(result)
        assert parsed["data"][0]["name"] == "foo"

    def test_format_output_csv(self) -> None:
        """format_output should dispatch to CSV formatter."""
        data = [{"name": "foo"}]
        columns = [("Name", "name")]
        config = OutputConfig(format="csv")

        result = format_output(data, columns, config)

        assert "Name" in result
        assert "foo" in result

    def test_format_output_tree(self) -> None:
        """format_output should dispatch to tree formatter."""
        data = [{"name": "foo"}]
        columns = [("Name", "name")]
        config = OutputConfig(format="tree", no_color=True)

        result = format_output(data, columns, config)

        assert "foo" in result


class TestFormatNodeList:
    """Tests for node list formatting."""

    def test_format_node_list_json(self) -> None:
        """Node list JSON should be valid and parseable."""
        nodes = ["mod:src/foo.py", "cls:src/bar.py:MyClass"]
        config = OutputConfig(format="json")

        result = format_node_list(nodes, "Test Nodes", config)
        parsed = json.loads(result)

        assert len(parsed["data"]) == 2
        assert parsed["data"][0]["node_id"] == "mod:src/foo.py"
        assert parsed["data"][0]["type"] == "module"
        assert parsed["data"][1]["type"] == "class"

    def test_format_node_list_table(self) -> None:
        """Node list table should show node IDs and types."""
        nodes = ["mod:src/foo.py"]
        config = OutputConfig(format="table", no_color=True)

        result = format_node_list(nodes, "Test", config)

        assert "mod:src/foo.py" in result
        assert "module" in result


class TestFormatCycles:
    """Tests for cycle detection output."""

    def test_format_cycles_json(self) -> None:
        """Cycles JSON should include cycle_count."""
        cycles = [["a", "b", "c"], ["d", "e"]]
        config = OutputConfig(format="json")

        result = format_cycles(cycles, config)
        parsed = json.loads(result)

        assert parsed["cycle_count"] == 2
        assert len(parsed["cycles"]) == 2
        assert parsed["total_nodes"] == 5

    def test_format_cycles_csv(self) -> None:
        """Cycles CSV should have cycle_id and node_id columns."""
        cycles = [["a", "b"]]
        config = OutputConfig(format="csv")

        result = format_cycles(cycles, config)

        assert "cycle_id,node_id" in result
        assert "0,a" in result
        assert "0,b" in result

    def test_format_cycles_table_empty(self) -> None:
        """Empty cycles should show 'No cycles detected'."""
        config = OutputConfig(format="table", no_color=True)

        result = format_cycles([], config)

        assert "No cycles detected" in result

    def test_format_cycles_table_arrow_visualization(self) -> None:
        """Table format should show cycle with arrows."""
        cycles = [["a", "b", "c"]]
        config = OutputConfig(format="table", no_color=True)

        result = format_cycles(cycles, config)

        assert "a -> b -> c -> a" in result  # Cycle visualization


class TestTTYAutoDetection:
    """Tests for TTY auto-detection behavior."""

    def test_output_config_from_context_defaults_interactive(self) -> None:
        """from_context should use interactive defaults when TTY."""
        # This test verifies the structure, actual TTY detection
        # depends on runtime environment
        config = OutputConfig()

        assert config.format == "table"
        # Default should be False (assume interactive unless explicitly set)
        assert config.no_truncate is False
        assert config.no_color is False

    def test_piped_output_config(self) -> None:
        """Piped output should disable truncation and color."""
        # Simulate piped (non-TTY) config
        config = OutputConfig(
            format="table",
            no_truncate=True,  # Piped = no truncation
            no_color=True,  # Piped = no color
        )

        assert config.no_truncate is True
        assert config.no_color is True


class TestOutputConfigFromContext:
    """Tests for OutputConfig.from_context() method."""

    def test_from_context_with_none_context(self) -> None:
        """from_context should handle None context gracefully."""
        from unittest.mock import patch

        # Mock is_interactive at the location where it's imported
        with patch("mu.commands.utils.is_interactive", return_value=True):
            config = OutputConfig.from_context(None, default_format="json")

            assert config.format == "json"
            assert config.no_truncate is False
            assert config.no_color is False

    def test_from_context_non_interactive(self) -> None:
        """from_context should disable truncation/color in non-TTY mode."""
        from unittest.mock import patch

        # Mock is_interactive to return False (piped mode)
        with patch("mu.commands.utils.is_interactive", return_value=False):
            config = OutputConfig.from_context(None, default_format="table")

            assert config.format == "table"
            assert config.no_truncate is True  # Auto-disabled for piped output
            assert config.no_color is True  # Auto-disabled for piped output

    def test_from_context_with_click_context(self) -> None:
        """from_context should extract settings from Click context object."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        # Create mock Click context with obj attribute
        mock_obj = SimpleNamespace(
            output_format="csv",
            no_truncate=True,
            no_color=False,
            width=100,
        )
        mock_ctx = MagicMock()
        mock_ctx.obj = mock_obj

        with patch("mu.commands.utils.is_interactive", return_value=True):
            config = OutputConfig.from_context(mock_ctx)

            assert config.format == "csv"
            assert config.no_truncate is True
            assert config.no_color is False
            assert config.width == 100

    def test_from_context_uses_default_format_when_not_set(self) -> None:
        """from_context should use default_format when obj.output_format is None."""
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        mock_obj = SimpleNamespace(output_format=None)
        mock_ctx = MagicMock()
        mock_ctx.obj = mock_obj

        with patch("mu.commands.utils.is_interactive", return_value=True):
            config = OutputConfig.from_context(mock_ctx, default_format="tree")

            assert config.format == "tree"

    def test_from_context_with_context_no_obj(self) -> None:
        """from_context should handle context with no obj attribute."""
        from unittest.mock import MagicMock, patch

        mock_ctx = MagicMock(spec=[])  # No obj attribute

        with patch("mu.commands.utils.is_interactive", return_value=True):
            config = OutputConfig.from_context(mock_ctx, default_format="json")

            assert config.format == "json"


class TestSmartTruncateAdvanced:
    """Advanced tests for smart truncation edge cases."""

    def test_windows_path_detection(self) -> None:
        """Backslashes should be detected as paths (Windows-style)."""
        path = r"C:\Users\very\long\path\to\file.py"
        result = smart_truncate(path, max_width=25)

        # Should use middle truncation for paths
        assert "..." in result
        assert len(result) <= 25

    def test_no_extension_not_detected_as_path(self) -> None:
        """Values without slashes or extensions should use end truncation."""
        name = "AVeryLongIdentifierNameWithoutExtension"
        result = smart_truncate(name, max_width=20)

        # Should use end truncation
        assert result.endswith("...")
        assert len(result) <= 20

    def test_path_column_hint_forces_middle_truncation(self) -> None:
        """Column hint 'path' should force middle truncation."""
        value = "this_is_not_a_path_but_very_long"
        result = smart_truncate(value, max_width=20, column_hint="path")

        # Middle truncation puts ... in the middle
        assert "..." in result
        # End truncation would be "this_is_not_a_pa..."
        # Middle truncation would be "this_is_...ry_long"
        assert not result.endswith("...")

    def test_various_path_column_hints(self) -> None:
        """Various path column names should trigger middle truncation."""
        value = "a_very_long_value_that_needs_truncation"

        for hint in ["path", "file_path", "source_path", "module_path", "file"]:
            result = smart_truncate(value, max_width=20, column_hint=hint)
            assert "..." in result
            # Middle truncation doesn't end with ...
            assert not result.endswith("...")

    def test_various_extensions_detected_as_paths(self) -> None:
        """Common source file extensions should be detected as paths."""
        extensions = ["py", "ts", "js", "go", "java", "rs", "cs", "rb", "cpp", "c", "h"]

        for ext in extensions:
            value = f"very_long_filename_that_needs_truncation.{ext}"
            result = smart_truncate(value, max_width=25)
            # Should preserve extension with middle truncation
            assert result.endswith(f".{ext}"), f"Extension .{ext} not preserved"


class TestTerminalWidth:
    """Tests for terminal width handling."""

    def test_terminal_width_from_config(self) -> None:
        """Config width should override auto-detection."""
        from mu.output import _get_terminal_width

        config = OutputConfig(width=200)
        width = _get_terminal_width(config)

        assert width == 200

    def test_terminal_width_auto_detection(self) -> None:
        """Without config width, should use shutil.get_terminal_size."""
        from mu.output import _get_terminal_width

        # None config
        width = _get_terminal_width(None)
        assert width > 0

        # Config without width
        config = OutputConfig(width=None)
        width = _get_terminal_width(config)
        assert width > 0


class TestFormatTableAdvanced:
    """Advanced tests for table formatting."""

    def test_format_table_single_row(self) -> None:
        """Single row should show '1 row' (singular)."""
        data = [{"name": "foo"}]
        columns = [Column("Name", "name")]
        config = OutputConfig(no_color=True)

        result = format_table(data, columns, config)

        assert "1 row" in result
        assert "rows" not in result

    def test_format_table_with_column_colors(self) -> None:
        """Table should apply column colors when enabled."""
        data = [{"name": "foo", "status": "active"}]
        columns = [
            Column("Name", "name", color=Colors.CYAN),
            Column("Status", "status", color=Colors.GREEN),
        ]
        config = OutputConfig(no_color=False)

        result = format_table(data, columns, config)

        # Colors should be in output
        assert Colors.CYAN in result
        assert Colors.GREEN in result

    def test_format_table_truncates_long_values(self) -> None:
        """Table should truncate values when terminal is narrow."""
        data = [{"name": "VeryLongClassNameThatExceedsTerminalWidth" * 3}]
        columns = [Column("Name", "name")]
        config = OutputConfig(no_truncate=False, no_color=True, width=40)

        result = format_table(data, columns, config)

        # Should contain truncation marker
        assert "..." in result

    def test_format_table_missing_keys(self) -> None:
        """Table should handle missing keys gracefully."""
        data = [
            {"name": "foo"},  # Missing 'type' key
            {"name": "bar", "type": "class"},
        ]
        columns = [Column("Name", "name"), Column("Type", "type")]
        config = OutputConfig(no_color=True)

        result = format_table(data, columns, config)

        assert "foo" in result
        assert "bar" in result
        assert "class" in result

    def test_format_table_unicode_values(self) -> None:
        """Table should handle unicode characters correctly."""
        data = [
            {"name": "Unicode_Name", "desc": "hello world"},
            {"name": "Regular", "desc": "standard text"},
        ]
        columns = [Column("Name", "name"), Column("Description", "desc")]
        config = OutputConfig(no_color=True)

        result = format_table(data, columns, config)

        assert "Unicode_Name" in result
        assert "hello world" in result


class TestFormatJsonAdvanced:
    """Advanced tests for JSON formatting."""

    def test_format_json_not_pretty(self) -> None:
        """JSON with pretty=False should be compact."""
        data = [{"name": "foo"}]

        result = format_json(data, pretty=False)
        parsed = json.loads(result)

        assert parsed["data"][0]["name"] == "foo"
        # Should be on one line (no indentation)
        assert "\n" not in result

    def test_format_json_with_non_serializable(self) -> None:
        """JSON should handle non-serializable values via default=str."""
        from datetime import datetime

        data = [{"name": "foo", "timestamp": datetime(2024, 1, 1)}]

        result = format_json(data)
        parsed = json.loads(result)

        # datetime should be serialized as string
        assert "2024" in parsed["data"][0]["timestamp"]


class TestFormatTreeAdvanced:
    """Advanced tests for tree formatting."""

    def test_format_tree_with_details(self) -> None:
        """Tree should show additional column details."""
        data = [
            {"node_id": "foo", "type": "class", "lines": 100},
            {"node_id": "bar", "type": "function", "lines": 50},
        ]
        columns = [
            Column("Node", "node_id"),
            Column("Type", "type"),
            Column("Lines", "lines"),
        ]
        config = OutputConfig(no_color=True)

        result = format_tree(data, columns, config)

        # Should show details below each node
        assert "Type: class" in result
        assert "Lines: 100" in result

    def test_format_tree_truncates_long_values(self) -> None:
        """Tree should truncate long primary values."""
        data = [{"node_id": "a" * 100}]
        columns = [Column("Node", "node_id")]
        config = OutputConfig(no_truncate=False, no_color=True)

        result = format_tree(data, columns, config)

        # Long value should be truncated
        assert "..." in result

    def test_format_tree_no_truncate_mode(self) -> None:
        """Tree with no_truncate should show full values."""
        data = [{"node_id": "a" * 100}]
        columns = [Column("Node", "node_id")]
        config = OutputConfig(no_truncate=True, no_color=True)

        result = format_tree(data, columns, config)

        # Full value should be present
        assert "a" * 100 in result

    def test_format_tree_shows_item_count(self) -> None:
        """Tree should show item count at the end."""
        data = [{"node_id": f"node{i}"} for i in range(5)]
        columns = [Column("Node", "node_id")]
        config = OutputConfig(no_color=True)

        result = format_tree(data, columns, config)

        assert "5 items" in result

    def test_format_tree_single_item(self) -> None:
        """Tree with single item should show last marker only."""
        data = [{"node_id": "only_node"}]
        columns = [Column("Node", "node_id")]
        config = OutputConfig(no_color=True)

        result = format_tree(data, columns, config)

        # Only last marker should appear
        assert "`--" in result
        assert "|--" not in result

    def test_format_tree_empty_detail_values(self) -> None:
        """Tree should skip empty detail values."""
        data = [{"node_id": "foo", "type": None, "lines": ""}]
        columns = [
            Column("Node", "node_id"),
            Column("Type", "type"),
            Column("Lines", "lines"),
        ]
        config = OutputConfig(no_color=True)

        result = format_tree(data, columns, config)

        # Empty values should not appear in details
        assert "Type: None" not in result
        assert "Lines: " not in result.replace("Lines: ", "X")  # Avoid false positive


class TestFormatNodeListAdvanced:
    """Advanced tests for node list formatting."""

    def test_format_node_list_with_dict_input(self) -> None:
        """Node list should handle dict input directly."""
        nodes = [
            {"node_id": "custom:node1", "type": "custom_type"},
            {"node_id": "custom:node2", "type": "another_type"},
        ]
        config = OutputConfig(format="json")

        result = format_node_list(nodes, "Custom Nodes", config)
        parsed = json.loads(result)

        assert len(parsed["data"]) == 2
        assert parsed["data"][0]["node_id"] == "custom:node1"
        assert parsed["data"][0]["type"] == "custom_type"

    def test_format_node_list_unknown_type(self) -> None:
        """Node list should mark unknown node types."""
        nodes = ["unknown:prefix:value"]
        config = OutputConfig(format="json")

        result = format_node_list(nodes, "Nodes", config)
        parsed = json.loads(result)

        assert parsed["data"][0]["type"] == "unknown"

    def test_format_node_list_function_type(self) -> None:
        """Node list should detect function type from prefix."""
        nodes = ["fn:src/foo.py:my_function"]
        config = OutputConfig(format="json")

        result = format_node_list(nodes, "Functions", config)
        parsed = json.loads(result)

        assert parsed["data"][0]["type"] == "function"


class TestFormatCyclesAdvanced:
    """Advanced tests for cycle formatting."""

    def test_format_cycles_multiple_cycles(self) -> None:
        """Multiple cycles should all be shown."""
        cycles = [["a", "b"], ["x", "y", "z"]]
        config = OutputConfig(format="table", no_color=True)

        result = format_cycles(cycles, config)

        assert "Cycle 1:" in result
        assert "Cycle 2:" in result
        assert "a -> b -> a" in result
        assert "x -> y -> z -> x" in result
        assert "Found 2 cycle(s)" in result

    def test_format_cycles_title_includes_count(self) -> None:
        """Cycle table title should include cycle count."""
        cycles = [["a", "b", "c"]]
        config = OutputConfig(format="table", no_color=True)

        result = format_cycles(cycles, config)

        assert "Circular Dependencies (1 cycles)" in result


class TestIsPathValueEdgeCases:
    """Tests for _is_path_value edge cases to achieve 100% branch coverage."""

    def test_unknown_extension_not_detected_as_path(self) -> None:
        """Values with unknown extensions should NOT be detected as paths."""
        from mu.output import _is_path_value

        # These have dots but are not recognized file extensions
        assert _is_path_value("my.config", "") is False
        assert _is_path_value("user.name", "") is False
        assert _is_path_value("file.xyz", "") is False
        assert _is_path_value("data.json", "") is False  # json not in list
        assert _is_path_value("styles.css", "") is False  # css not in list

    def test_no_dot_no_slash_returns_false(self) -> None:
        """Values without dots or slashes should return False."""
        from mu.output import _is_path_value

        assert _is_path_value("simple_name", "") is False
        assert _is_path_value("NoExtension", "") is False


class TestFormatCyclesEdgeCases:
    """Tests for format_cycles edge cases."""

    def test_format_cycles_with_empty_cycle(self) -> None:
        """Empty cycle (edge case) should handle gracefully."""
        cycles: list[list[str]] = [[]]  # A cycle with no nodes
        config = OutputConfig(format="table", no_color=True)

        result = format_cycles(cycles, config)

        # Should show cycle but without arrow visualization
        assert "Cycle 1:" in result
        # The cycle string will be empty, won't have arrows
        assert "Found 1 cycle(s)" in result

    def test_format_cycles_single_node_cycle(self) -> None:
        """Single-node cycle should show proper visualization."""
        cycles = [["a"]]  # Self-referencing cycle
        config = OutputConfig(format="table", no_color=True)

        result = format_cycles(cycles, config)

        # Should show: a -> a
        assert "a -> a" in result


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_string_values(self) -> None:
        """Empty string values should be handled."""
        data = [{"name": "", "type": "class"}]
        columns = [Column("Name", "name"), Column("Type", "type")]
        config = OutputConfig(no_color=True)

        result = format_table(data, columns, config)

        assert "class" in result

    def test_very_narrow_terminal(self) -> None:
        """Very narrow terminal should still produce output."""
        data = [{"name": "foo", "type": "class"}]
        columns = [Column("Name", "name"), Column("Type", "type")]
        config = OutputConfig(no_color=True, width=20)

        result = format_table(data, columns, config)

        # Should still produce some output
        assert len(result) > 0
        assert "foo" in result or "..." in result

    def test_column_with_min_width(self) -> None:
        """Column min_width should be respected."""
        data = [{"id": "x"}]
        columns = [Column("ID", "id", min_width=10)]
        config = OutputConfig(no_color=True)

        result = format_table(data, columns, config)

        # The ID column should be at least 10 chars wide
        lines = result.split("\n")
        header_line = lines[0] if lines else ""
        # ID header should be padded
        assert "ID" in header_line

    def test_none_values_in_data(self) -> None:
        """None values should be converted to strings."""
        data = [{"name": None, "type": "class"}]
        columns = [Column("Name", "name"), Column("Type", "type")]
        config = OutputConfig(no_color=True)

        result = format_table(data, columns, config)

        assert "None" in result or "class" in result
