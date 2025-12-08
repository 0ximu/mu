"""Tests for the NL to MUQL translation module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mu.intelligence.nl2muql import (
    NL2MUQLTranslator,
    TranslationResult,
    _build_prompt,
    _extract_muql,
    translate,
)


class TestTranslationResult:
    """Tests for TranslationResult dataclass."""

    def test_creation(self) -> None:
        """Test TranslationResult creation."""
        result = TranslationResult(
            question="What are the complex functions?",
            muql="SELECT * FROM functions WHERE complexity > 20",
            explanation="This query finds complex functions",
            confidence=0.9,
        )
        assert result.question == "What are the complex functions?"
        assert result.muql == "SELECT * FROM functions WHERE complexity > 20"
        assert result.confidence == 0.9
        assert result.executed is False
        assert result.result is None
        assert result.error is None

    def test_to_dict(self) -> None:
        """Test TranslationResult.to_dict()."""
        result = TranslationResult(
            question="test",
            muql="SELECT * FROM functions",
            explanation="",
            confidence=0.8,
            executed=True,
            result={"columns": ["name"], "rows": [["foo"]], "row_count": 1},
        )
        d = result.to_dict()
        assert d["question"] == "test"
        assert d["muql"] == "SELECT * FROM functions"
        assert d["executed"] is True
        assert d["result"]["row_count"] == 1


class TestExtractMuql:
    """Tests for MUQL extraction from LLM responses."""

    def test_plain_query(self) -> None:
        """Test extracting a plain query."""
        response = "SELECT * FROM functions WHERE complexity > 20"
        muql, explanation = _extract_muql(response)
        assert muql == "SELECT * FROM functions WHERE complexity > 20"
        assert explanation == ""

    def test_query_in_code_block(self) -> None:
        """Test extracting query from markdown code block."""
        response = """```sql
SELECT * FROM functions WHERE complexity > 20
```"""
        muql, explanation = _extract_muql(response)
        assert muql == "SELECT * FROM functions WHERE complexity > 20"

    def test_query_with_muql_code_block(self) -> None:
        """Test extracting query from muql code block."""
        response = """```muql
SHOW dependencies OF AuthService DEPTH 2
```"""
        muql, explanation = _extract_muql(response)
        assert muql == "SHOW dependencies OF AuthService DEPTH 2"

    def test_query_with_explanation(self) -> None:
        """Test extracting query with explanation."""
        response = """SELECT name, complexity FROM functions ORDER BY complexity DESC LIMIT 10

Explanation: This query finds the most complex functions."""
        muql, explanation = _extract_muql(response)
        assert "SELECT" in muql
        assert "Explanation:" in explanation

    def test_multiline_query(self) -> None:
        """Test extracting multiline query."""
        response = """SELECT name, file_path, complexity
FROM functions
WHERE complexity > 20
ORDER BY complexity DESC"""
        muql, explanation = _extract_muql(response)
        assert "SELECT" in muql
        assert "ORDER BY complexity DESC" in muql

    def test_whitespace_normalization(self) -> None:
        """Test that whitespace is normalized."""
        response = "SELECT   *    FROM   functions"
        muql, _ = _extract_muql(response)
        assert "  " not in muql
        assert muql == "SELECT * FROM functions"


class TestBuildPrompt:
    """Tests for prompt building."""

    def test_basic_prompt(self) -> None:
        """Test basic prompt building."""
        prompt = _build_prompt("What are the complex functions?")
        assert "What are the complex functions?" in prompt
        assert "MUQL Query Types:" in prompt
        assert "SELECT" in prompt

    def test_prompt_with_schema(self) -> None:
        """Test prompt building with schema info."""
        prompt = _build_prompt(
            "What are the complex functions?",
            schema_info="Database has 100 nodes and 200 edges.",
        )
        assert "100 nodes" in prompt
        assert "200 edges" in prompt


class TestConfidenceEstimation:
    """Tests for confidence estimation."""

    def test_high_confidence_query(self) -> None:
        """Test confidence estimation for valid-looking queries."""
        translator = NL2MUQLTranslator(db=None)

        # Valid query with balanced quotes and parentheses
        confidence = translator._estimate_confidence(
            "complex functions",
            "SELECT * FROM functions WHERE complexity > 20",
        )
        assert confidence > 0.7

    def test_low_confidence_empty_query(self) -> None:
        """Test confidence estimation for empty query."""
        translator = NL2MUQLTranslator(db=None)
        confidence = translator._estimate_confidence("test", "")
        assert confidence == 0.0

    def test_confidence_boost_for_matching_terms(self) -> None:
        """Test confidence boost when question terms match query."""
        translator = NL2MUQLTranslator(db=None)

        confidence = translator._estimate_confidence(
            "what are the most complex functions",
            "SELECT name, complexity FROM functions ORDER BY complexity DESC",
        )
        # Should get boost for "complex" matching "complexity"
        assert confidence > 0.8


class TestNL2MUQLTranslator:
    """Tests for NL2MUQLTranslator class."""

    def test_init_defaults(self) -> None:
        """Test translator initialization with defaults."""
        translator = NL2MUQLTranslator()
        assert translator.db is None
        assert "claude" in translator.model or "haiku" in translator.model

    def test_init_with_model(self) -> None:
        """Test translator initialization with custom model."""
        translator = NL2MUQLTranslator(model="gpt-4")
        assert translator.model == "gpt-4"

    @patch("mu.intelligence.nl2muql.completion")
    def test_translate_success(self, mock_completion: MagicMock) -> None:
        """Test successful translation."""
        # Mock LLM response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "SELECT * FROM functions LIMIT 10"
        mock_completion.return_value = mock_response

        translator = NL2MUQLTranslator(db=None)
        result = translator.translate("show me some functions", execute=False)

        assert result.muql == "SELECT * FROM functions LIMIT 10"
        assert result.confidence > 0.5
        assert result.error is None

    @patch("mu.intelligence.nl2muql.completion")
    def test_translate_handles_error(self, mock_completion: MagicMock) -> None:
        """Test translation error handling."""
        mock_completion.side_effect = Exception("API error")

        translator = NL2MUQLTranslator(db=None)
        result = translator.translate("test", execute=False)

        assert result.muql == ""
        assert result.error is not None
        assert "API error" in result.error


class TestTranslateFunction:
    """Tests for the translate convenience function."""

    @patch("mu.intelligence.nl2muql.completion")
    def test_translate_function(self, mock_completion: MagicMock) -> None:
        """Test the translate convenience function."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "SELECT COUNT(*) FROM modules"
        mock_completion.return_value = mock_response

        result = translate("how many modules are there?", execute=False)

        assert result.muql == "SELECT COUNT(*) FROM modules"
        assert isinstance(result, TranslationResult)


class TestMCPIntegration:
    """Tests for MCP server integration."""

    def test_ask_result_dataclass(self) -> None:
        """Test AskResult dataclass exists and works."""
        from mu.mcp.server import AskResult

        result = AskResult(
            question="test",
            muql="SELECT * FROM functions",
            explanation="",
            confidence=0.9,
            executed=True,
            columns=["name"],
            rows=[["foo"]],
            row_count=1,
        )
        assert result.question == "test"
        assert result.row_count == 1

    @patch("mu.mcp.server._find_mubase")
    def test_mu_ask_no_mubase(self, mock_find_mubase: MagicMock) -> None:
        """Test mu_ask when no .mubase exists."""
        from mu.client import DaemonError
        from mu.mcp.server import mu_ask

        mock_find_mubase.return_value = None

        with pytest.raises(DaemonError, match="No .mubase found"):
            mu_ask("test question")
