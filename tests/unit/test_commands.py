"""Tests for MU documentation commands (man, llm)."""

import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock

from mu.cli import cli
from mu.commands.man import (
    TOPICS,
    TOPIC_ALIASES,
    _resolve_topic,
    _load_content,
    _load_all_content,
)
from mu.commands.llm_spec import _load_content as load_llm_content


class TestManCommand:
    """Tests for the mu man command."""

    @pytest.fixture
    def runner(self):
        """Create a CLI runner."""
        return CliRunner()

    def test_man_help(self, runner):
        """Test mu man --help shows usage."""
        result = runner.invoke(cli, ["man", "--help"])
        assert result.exit_code == 0
        assert "Display the MU manual" in result.output
        assert "--toc" in result.output

    def test_man_toc(self, runner):
        """Test mu man --toc shows table of contents."""
        result = runner.invoke(cli, ["man", "--toc"])
        assert result.exit_code == 0
        assert "Table of Contents" in result.output
        # Should list all topics
        for topic in TOPICS:
            assert topic in result.output

    def test_man_specific_topic(self, runner):
        """Test mu man <topic> shows specific section."""
        result = runner.invoke(cli, ["man", "sigils", "--no-color"])
        assert result.exit_code == 0
        assert "Sigils" in result.output or "sigils" in result.output.lower()

    def test_man_invalid_topic(self, runner):
        """Test mu man <invalid> suggests alternatives."""
        result = runner.invoke(cli, ["man", "xyzzy123"])
        assert result.exit_code == 1
        assert "Unknown topic" in result.output
        # Should list available topics
        assert "Available topics" in result.output

    def test_man_topic_alias(self, runner):
        """Test mu man with alias works."""
        result = runner.invoke(cli, ["man", "start", "--no-color"])
        assert result.exit_code == 0
        # 'start' is alias for 'quickstart'
        assert "Quick Start" in result.output or "quickstart" in result.output.lower()

    def test_man_no_color(self, runner):
        """Test mu man --no-color disables ANSI codes."""
        result = runner.invoke(cli, ["man", "intro", "--no-color"])
        assert result.exit_code == 0
        # Should not contain ANSI escape codes
        assert "\033[" not in result.output or result.output.count("\033[") == 0

    def test_man_full_manual(self, runner):
        """Test mu man without args shows full manual."""
        result = runner.invoke(cli, ["man", "--no-color"], input="q")
        # May exit early due to pager, but should not error
        assert result.exit_code == 0


class TestManTopicResolution:
    """Tests for topic name resolution."""

    def test_resolve_direct_topic(self):
        """Test resolving a direct topic name."""
        assert _resolve_topic("intro") == "intro"
        assert _resolve_topic("sigils") == "sigils"
        assert _resolve_topic("philosophy") == "philosophy"

    def test_resolve_topic_alias(self):
        """Test resolving topic aliases."""
        assert _resolve_topic("start") == "quickstart"
        assert _resolve_topic("quick") == "quickstart"
        assert _resolve_topic("ops") == "operators"
        assert _resolve_topic("mubase") == "query"
        assert _resolve_topic("why") == "philosophy"

    def test_resolve_case_insensitive(self):
        """Test topic resolution is case-insensitive."""
        assert _resolve_topic("INTRO") == "intro"
        assert _resolve_topic("Sigils") == "sigils"
        assert _resolve_topic("QUICKSTART") == "quickstart"

    def test_resolve_fuzzy_match(self):
        """Test fuzzy matching for misspellings."""
        assert _resolve_topic("siglz") == "sigils"
        assert _resolve_topic("qickstart") == "quickstart"
        assert _resolve_topic("operatrs") == "operators"

    def test_resolve_unknown_topic(self):
        """Test None returned for completely unknown topic."""
        assert _resolve_topic("xyzzy") is None
        assert _resolve_topic("foobar") is None


class TestManContentLoading:
    """Tests for content loading functions."""

    def test_load_content_exists(self):
        """Test loading existing content file."""
        content = _load_content("01-intro.md")
        assert "MU" in content
        assert "What is MU" in content or "Machine Understanding" in content

    def test_load_content_all_topics(self):
        """Test all topic files can be loaded."""
        for topic, filename in TOPICS.items():
            content = _load_content(filename)
            assert content, f"Failed to load {filename}"
            assert "Error:" not in content, f"Error loading {filename}"

    def test_load_all_content(self):
        """Test loading all sections together."""
        content = _load_all_content()
        # Should contain content from all sections
        assert "MU" in content
        assert "Sigil" in content or "sigil" in content
        assert "---" in content  # Separator between sections


class TestLLMCommand:
    """Tests for the mu llm command."""

    @pytest.fixture
    def runner(self):
        """Create a CLI runner."""
        return CliRunner()

    def test_llm_help(self, runner):
        """Test mu llm --help shows usage."""
        result = runner.invoke(cli, ["llm", "--help"])
        assert result.exit_code == 0
        assert "Output MU format spec" in result.output
        assert "--full" in result.output
        assert "--examples" in result.output
        assert "--copy" in result.output

    def test_llm_minimal_default(self, runner):
        """Test mu llm outputs minimal spec by default."""
        result = runner.invoke(cli, ["llm"])
        assert result.exit_code == 0
        # Should have version header
        assert "MU Format Spec" in result.output
        # Should have sigils
        assert "!" in result.output
        assert "$" in result.output
        assert "#" in result.output

    def test_llm_full(self, runner):
        """Test mu llm --full outputs complete spec."""
        result = runner.invoke(cli, ["llm", "--full"])
        assert result.exit_code == 0
        assert "MU Format Spec" in result.output
        # Full spec has more content
        assert "Anti-Pattern" in result.output or "Example" in result.output

    def test_llm_examples(self, runner):
        """Test mu llm --examples outputs just examples."""
        result = runner.invoke(cli, ["llm", "--examples"])
        assert result.exit_code == 0
        # Should have transformation examples
        assert "Input:" in result.output or "Output:" in result.output
        assert "```" in result.output  # Code blocks

    def test_llm_raw(self, runner):
        """Test mu llm --raw outputs without header."""
        result = runner.invoke(cli, ["llm", "--raw"])
        assert result.exit_code == 0
        # Should NOT have version header
        assert "MU Format Spec v" not in result.output
        # But should still have content
        assert "!" in result.output

    def test_llm_copy_with_pyperclip(self, runner):
        """Test mu llm --copy copies to clipboard when pyperclip available."""
        mock_pyperclip = MagicMock()
        with patch.dict("sys.modules", {"pyperclip": mock_pyperclip}):
            result = runner.invoke(cli, ["llm", "--copy"])
            # Should succeed and indicate copy happened
            assert "Copied to clipboard" in result.output or result.exit_code == 0

    def test_llm_copy_without_pyperclip(self, runner):
        """Test mu llm --copy gracefully handles missing pyperclip."""
        # Make pyperclip import fail
        with patch.dict("sys.modules", {"pyperclip": None}):
            with patch("mu.commands.llm_spec._copy_to_clipboard", return_value=False):
                result = runner.invoke(cli, ["llm", "--copy"])
                # Should still output content
                assert result.exit_code == 0
                assert "!" in result.output  # Has sigil content


class TestLLMContentLoading:
    """Tests for LLM spec content loading."""

    def test_load_minimal_spec(self):
        """Test loading minimal LLM spec."""
        content = load_llm_content("minimal.md")
        assert "Sigil" in content or "sigil" in content.lower()
        assert "!" in content
        assert "$" in content

    def test_load_full_spec(self):
        """Test loading full LLM spec."""
        content = load_llm_content("full.md")
        assert "Sigil" in content or "sigil" in content.lower()
        # Full has more content than minimal
        assert len(content) > len(load_llm_content("minimal.md"))

    def test_load_examples(self):
        """Test loading examples."""
        content = load_llm_content("examples.md")
        assert "Example" in content or "example" in content.lower()
        # Should have code blocks
        assert "```" in content


class TestTokenCounts:
    """Tests for token count requirements from PRD."""

    def test_minimal_under_1k_tokens(self):
        """Test minimal spec is under 1K tokens."""
        content = load_llm_content("minimal.md")
        # Rough token estimate: words ~= tokens for technical content
        word_count = len(content.split())
        assert word_count < 1000, f"Minimal spec has {word_count} words, expected < 1000"

    def test_full_under_2k_tokens(self):
        """Test full spec is under 2K tokens."""
        content = load_llm_content("full.md")
        word_count = len(content.split())
        assert word_count < 2000, f"Full spec has {word_count} words, expected < 2000"


class TestTopicCompleteness:
    """Tests to ensure all topics and aliases are valid."""

    def test_all_topics_have_files(self):
        """Test every topic maps to an existing file."""
        for topic, filename in TOPICS.items():
            content = _load_content(filename)
            assert "Error:" not in content, f"Topic '{topic}' file '{filename}' not found"

    def test_all_aliases_resolve_to_valid_topics(self):
        """Test every alias maps to a valid topic."""
        for alias, topic in TOPIC_ALIASES.items():
            assert topic in TOPICS, f"Alias '{alias}' maps to invalid topic '{topic}'"

    def test_topics_have_headers(self):
        """Test each topic file has a proper markdown header."""
        for topic, filename in TOPICS.items():
            content = _load_content(filename)
            lines = content.strip().split("\n")
            assert lines[0].startswith("#"), f"Topic '{topic}' missing header"
