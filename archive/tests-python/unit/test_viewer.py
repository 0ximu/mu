"""Tests for MU viewer module - terminal and HTML rendering."""

import pytest
from pathlib import Path
import tempfile

# Skip this entire module if mu.viewer is not available (moved to mu-viz package)
pytest.importorskip("mu.viewer", reason="mu.viewer moved to mu-viz package")

from mu.viewer import (
    TokenType,
    Token,
    MUDocument,
    tokenize_line,
    TerminalRenderer,
    HTMLRenderer,
    render_terminal,
    render_html,
    view_file,
)


class TestTokenizer:
    """Test the MU format tokenizer."""

    def test_tokenize_empty_line(self):
        """Test tokenizing an empty line."""
        tokens = list(tokenize_line(""))
        assert tokens == []

    def test_tokenize_header_line(self):
        """Test tokenizing a header comment line."""
        tokens = list(tokenize_line("# MU v1.0"))
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.HEADER
        assert tokens[0].value == "# MU v1.0"

    def test_tokenize_module_sigil(self):
        """Test tokenizing module sigil (!)."""
        tokens = list(tokenize_line("!module test"))
        sigils = [t for t in tokens if t.type == TokenType.SIGIL_MODULE]
        assert len(sigils) == 1
        assert sigils[0].value == "!"

    def test_tokenize_entity_sigil(self):
        """Test tokenizing entity sigil ($)."""
        tokens = list(tokenize_line("$User"))
        sigils = [t for t in tokens if t.type == TokenType.SIGIL_ENTITY]
        assert len(sigils) == 1
        assert sigils[0].value == "$"

    def test_tokenize_function_sigil(self):
        """Test tokenizing function sigil (#)."""
        tokens = list(tokenize_line("#create_user(name) -> User"))
        sigils = [t for t in tokens if t.type == TokenType.SIGIL_FUNCTION]
        assert len(sigils) == 1
        assert sigils[0].value == "#"

    def test_tokenize_metadata_sigil(self):
        """Test tokenizing metadata sigil (@)."""
        tokens = list(tokenize_line("@deps [click, pydantic]"))
        sigils = [t for t in tokens if t.type == TokenType.SIGIL_METADATA]
        assert len(sigils) == 1
        assert sigils[0].value == "@"

    def test_tokenize_conditional_sigil(self):
        """Test tokenizing conditional sigil (?)."""
        tokens = list(tokenize_line("? not_found -> err(404)"))
        sigils = [t for t in tokens if t.type == TokenType.SIGIL_CONDITIONAL]
        assert len(sigils) == 1
        assert sigils[0].value == "?"

    def test_tokenize_annotation(self):
        """Test tokenizing annotation (::)."""
        tokens = list(tokenize_line(":: guard: status != PAID"))
        annotations = [t for t in tokens if t.type == TokenType.ANNOTATION]
        assert len(annotations) == 1
        assert annotations[0].value == "::"

    def test_tokenize_flow_operator(self):
        """Test tokenizing flow operator (->)."""
        tokens = list(tokenize_line("#func(x) -> Result"))
        operators = [t for t in tokens if t.type == TokenType.OPERATOR]
        assert any(op.value == "->" for op in operators)

    def test_tokenize_mutation_operator(self):
        """Test tokenizing mutation operator (=>)."""
        tokens = list(tokenize_line("status => PAID"))
        operators = [t for t in tokens if t.type == TokenType.OPERATOR]
        assert any(op.value == "=>" for op in operators)

    def test_tokenize_keyword(self):
        """Test tokenizing keywords."""
        tokens = list(tokenize_line("#async process()"))
        keywords = [t for t in tokens if t.type == TokenType.KEYWORD]
        assert any(kw.value == "async" for kw in keywords)

    def test_tokenize_string(self):
        """Test tokenizing string literals."""
        tokens = list(tokenize_line('name = "hello"'))
        strings = [t for t in tokens if t.type == TokenType.STRING]
        assert len(strings) == 1
        assert strings[0].value == '"hello"'

    def test_tokenize_number(self):
        """Test tokenizing numbers."""
        tokens = list(tokenize_line("count: 42"))
        numbers = [t for t in tokens if t.type == TokenType.NUMBER]
        assert len(numbers) == 1
        assert numbers[0].value == "42"

    def test_tokenize_punctuation(self):
        """Test tokenizing punctuation."""
        tokens = list(tokenize_line("func(a, b)"))
        puncts = [t for t in tokens if t.type == TokenType.PUNCTUATION]
        values = {p.value for p in puncts}
        assert "(" in values
        assert ")" in values
        assert "," in values

    def test_tokenize_preserves_whitespace(self):
        """Test that whitespace is preserved."""
        tokens = list(tokenize_line("  #indented"))
        assert tokens[0].type == TokenType.WHITESPACE
        assert tokens[0].value == "  "

    def test_tokenize_complex_line(self):
        """Test tokenizing a complex MU line."""
        line = "#async create_user(name: str, email: str) -> Result<User>"
        tokens = list(tokenize_line(line))

        # Should have function sigil, async keyword, name, params, operator, return type
        types = [t.type for t in tokens]
        assert TokenType.SIGIL_FUNCTION in types
        assert TokenType.KEYWORD in types  # async
        assert TokenType.OPERATOR in types  # ->


class TestMUDocument:
    """Test MUDocument parsing."""

    def test_parse_simple_document(self):
        """Test parsing a simple MU document."""
        source = """# MU v1.0
# source: /path/to/code

!module auth
#login(user, password) -> bool
"""
        doc = MUDocument.parse(source)

        assert doc.source == source
        assert len(doc.lines) == 5
        assert len(doc.tokens) == 5
        assert "MU v1.0" in doc.header.get("", "") or doc.lines[0] == "# MU v1.0"

    def test_parse_extracts_modules(self):
        """Test that module names are extracted."""
        source = """# Header
!module auth
!module api
!module models
"""
        doc = MUDocument.parse(source)
        assert "auth" in doc.modules
        assert "api" in doc.modules
        assert "models" in doc.modules


class TestTerminalRenderer:
    """Test terminal rendering with ANSI colors."""

    @pytest.fixture
    def sample_doc(self):
        """Create a sample MU document for testing."""
        return MUDocument.parse("""# MU v1.0
!module auth
$User { id, email }
#login(user, password) -> bool
:: guard: user is not None
""")

    def test_render_produces_output(self, sample_doc):
        """Test that render produces output."""
        renderer = TerminalRenderer(theme="dark")
        result = renderer.render(sample_doc)

        assert result
        assert "MU v1.0" in result
        assert "auth" in result

    def test_render_includes_ansi_codes(self, sample_doc):
        """Test that render includes ANSI escape codes."""
        renderer = TerminalRenderer(theme="dark")
        result = renderer.render(sample_doc)

        # Should contain ANSI escape codes
        assert "\033[" in result

    def test_render_with_line_numbers(self, sample_doc):
        """Test rendering with line numbers."""
        renderer = TerminalRenderer(theme="dark")
        result = renderer.render_with_line_numbers(sample_doc)

        # Should contain line number indicators
        assert "│" in result
        assert "1" in result

    def test_light_theme(self, sample_doc):
        """Test light theme rendering."""
        renderer = TerminalRenderer(theme="light")
        result = renderer.render(sample_doc)

        assert result
        assert "\033[" in result


class TestHTMLRenderer:
    """Test HTML rendering."""

    @pytest.fixture
    def sample_doc(self):
        """Create a sample MU document for testing."""
        return MUDocument.parse("""# MU v1.0
!module auth
$User { id, email }
#login(user, password) -> bool
""")

    def test_render_produces_html(self, sample_doc):
        """Test that render produces HTML."""
        renderer = HTMLRenderer(theme="dark")
        result = renderer.render(sample_doc)

        assert "<div" in result
        assert "mu-container" in result

    def test_render_escapes_html(self):
        """Test that HTML special characters are escaped."""
        doc = MUDocument.parse("#func(a, b) -> Result<T>")
        renderer = HTMLRenderer()
        result = renderer.render(doc)

        # < and > should be escaped
        assert "&lt;" in result
        assert "&gt;" in result

    def test_render_includes_line_numbers(self, sample_doc):
        """Test that line numbers are included."""
        renderer = HTMLRenderer(show_line_numbers=True)
        result = renderer.render(sample_doc)

        assert "mu-line-num" in result

    def test_render_without_line_numbers(self, sample_doc):
        """Test rendering without line numbers."""
        renderer = HTMLRenderer(show_line_numbers=False)
        result = renderer.render(sample_doc)

        assert "mu-line-num" not in result

    def test_render_full_page(self, sample_doc):
        """Test full HTML page rendering."""
        renderer = HTMLRenderer(theme="dark")
        result = renderer.render_full_page(sample_doc, title="Test Output")

        assert "<!DOCTYPE html>" in result
        assert "<html" in result
        assert "Test Output" in result
        assert "<style>" in result

    def test_light_theme_class(self, sample_doc):
        """Test light theme applies correct class."""
        renderer = HTMLRenderer(theme="light")
        result = renderer.render(sample_doc)

        assert "light" in result

    def test_token_classes(self, sample_doc):
        """Test that token classes are applied."""
        renderer = HTMLRenderer()
        result = renderer.render(sample_doc)

        assert "mu-header" in result
        assert "mu-sigil-module" in result


class TestConvenienceFunctions:
    """Test convenience functions."""

    @pytest.fixture
    def sample_mu(self):
        """Sample MU source."""
        return """# MU v1.0
# generated: 2024-12-06
!module test
#hello() -> str
"""

    def test_render_terminal(self, sample_mu):
        """Test render_terminal function."""
        result = render_terminal(sample_mu)

        assert result
        assert "test" in result
        assert "\033[" in result

    def test_render_terminal_with_line_numbers(self, sample_mu):
        """Test render_terminal with line numbers."""
        result = render_terminal(sample_mu, line_numbers=True)

        assert "│" in result

    def test_render_html(self, sample_mu):
        """Test render_html function."""
        result = render_html(sample_mu)

        assert "<div" in result
        assert "mu-container" in result

    def test_render_html_full_page(self, sample_mu):
        """Test render_html with full_page."""
        result = render_html(sample_mu, full_page=True, title="My Title")

        assert "<!DOCTYPE html>" in result
        assert "My Title" in result

    def test_view_file_terminal(self, sample_mu):
        """Test view_file with terminal format."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".mu", delete=False) as f:
            f.write(sample_mu)
            f.flush()

            result = view_file(Path(f.name), output_format="terminal")
            assert result
            assert "\033[" in result

    def test_view_file_html(self, sample_mu):
        """Test view_file with HTML format."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".mu", delete=False) as f:
            f.write(sample_mu)
            f.flush()

            result = view_file(Path(f.name), output_format="html")
            assert "<!DOCTYPE html>" in result

    def test_view_file_markdown(self, sample_mu):
        """Test view_file with markdown format."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".mu", delete=False) as f:
            f.write(sample_mu)
            f.flush()

            result = view_file(Path(f.name), output_format="markdown")
            assert result.startswith("```mu\n")
            assert result.endswith("\n```")


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_input(self):
        """Test handling of empty input."""
        doc = MUDocument.parse("")
        renderer = TerminalRenderer()
        result = renderer.render(doc)

        assert result == ""

    def test_unicode_content(self):
        """Test handling of unicode characters."""
        source = "# 日本語コメント\n!module テスト\n#関数() -> str"
        doc = MUDocument.parse(source)
        renderer = TerminalRenderer()
        result = renderer.render(doc)

        assert "日本語" in result
        assert "テスト" in result

    def test_special_characters_in_html(self):
        """Test HTML escaping of special characters."""
        source = "#compare(a, b) -> bool  :: a < b && b > c"
        doc = MUDocument.parse(source)
        renderer = HTMLRenderer()
        result = renderer.render(doc)

        # Should escape < and > in content
        assert "&lt;" in result
        assert "&gt;" in result
        assert "&amp;" in result

    def test_very_long_line(self):
        """Test handling of very long lines."""
        long_name = "a" * 1000
        source = f"#function_{long_name}() -> void"
        doc = MUDocument.parse(source)

        term_result = TerminalRenderer().render(doc)
        html_result = HTMLRenderer().render(doc)

        assert long_name in term_result
        assert long_name in html_result

    def test_nested_brackets(self):
        """Test handling of nested brackets."""
        source = "#func(a: list[dict[str, Any]]) -> Optional[Result[T]]"
        doc = MUDocument.parse(source)
        renderer = TerminalRenderer()
        result = renderer.render(doc)

        # Check that all parts are present (ANSI codes split up the text)
        assert "list" in result
        assert "dict" in result
        assert "str" in result
        assert "Any" in result
        assert "Optional" in result
        assert "Result" in result

    def test_escaped_quotes_in_strings(self):
        """Test handling of escaped quotes in strings."""
        source = r'message = "hello \"world\""'
        doc = MUDocument.parse(source)
        tokens = doc.tokens[0]

        # Should handle escaped quotes and produce string token
        strings = [t for t in tokens if t.type == TokenType.STRING]
        assert len(strings) == 1
        assert "hello" in strings[0].value


class TestTokenPositions:
    """Test that tokens have correct positions."""

    def test_token_line_numbers(self):
        """Test that tokens have correct line numbers."""
        source = "line1\nline2\nline3"
        doc = MUDocument.parse(source)

        for line_num, line_tokens in enumerate(doc.tokens):
            for token in line_tokens:
                assert token.line == line_num

    def test_token_column_positions(self):
        """Test that tokens have correct column positions."""
        line = "  #func()"
        tokens = list(tokenize_line(line))

        # First token is whitespace at column 0
        assert tokens[0].column == 0
        assert tokens[0].type == TokenType.WHITESPACE

        # Sigil at column 2
        assert tokens[1].column == 2
        assert tokens[1].type == TokenType.SIGIL_FUNCTION
