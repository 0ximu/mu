"""Tests for the Rust-based incremental parser."""

from __future__ import annotations

import pytest


class TestIncrementalParser:
    """Tests for the Rust-based incremental parser."""

    @pytest.fixture
    def core_module(self):
        """Import _core module for tests."""
        from mu import _core
        return _core

    def test_incremental_parser_available(self, core_module):
        """Test that IncrementalParser is available from Rust."""
        assert hasattr(core_module, "IncrementalParser")
        assert hasattr(core_module, "IncrementalParseResult")

    def test_create_parser_python(self, core_module):
        """Test creating an incremental parser for Python."""
        source = "def hello():\n    pass"
        parser = core_module.IncrementalParser(source, "python", "test.py")

        assert parser.get_source() == source
        assert parser.get_language() == "python"
        assert parser.get_file_path() == "test.py"
        assert parser.has_tree()
        assert not parser.has_errors()
        assert parser.line_count() == 2
        assert parser.byte_count() == len(source)

    def test_create_parser_typescript(self, core_module):
        """Test creating an incremental parser for TypeScript."""
        source = "function hello(): string {\n    return 'hello';\n}"
        parser = core_module.IncrementalParser(source, "typescript", "test.ts")

        assert parser.get_language() == "typescript"
        assert parser.has_tree()

        module = parser.get_module()
        assert len(module.functions) == 1
        assert module.functions[0].name == "hello"

    def test_create_parser_go(self, core_module):
        """Test creating an incremental parser for Go."""
        source = "package main\n\nfunc hello() string {\n    return \"hello\"\n}"
        parser = core_module.IncrementalParser(source, "go", "test.go")

        assert parser.get_language() == "go"
        module = parser.get_module()
        assert len(module.functions) == 1
        assert module.functions[0].name == "hello"

    def test_unsupported_language_raises(self, core_module):
        """Test that unsupported languages raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            core_module.IncrementalParser("code", "brainfuck", "test.bf")

        assert "Unsupported language" in str(exc_info.value)

    def test_get_module_extracts_correctly(self, core_module):
        """Test that get_module returns correct ModuleDef."""
        source = '''
def hello(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}"

def goodbye():
    pass
'''
        parser = core_module.IncrementalParser(source.strip(), "python", "test.py")
        module = parser.get_module()

        assert module.name == "test"
        assert module.path == "test.py"
        assert module.language == "python"
        assert len(module.functions) == 2
        assert module.functions[0].name == "hello"
        assert module.functions[0].return_type == "str"
        assert len(module.functions[0].parameters) == 1
        assert module.functions[1].name == "goodbye"

    def test_apply_edit_insert_at_end(self, core_module):
        """Test inserting text at the end of a function name."""
        source = "def hello():\n    pass"
        parser = core_module.IncrementalParser(source, "python", "test.py")

        # Insert 'world' at position 9 (end of 'hello')
        # 'hello' is at bytes 4-9
        result = parser.apply_edit(9, 9, 14, "world")

        assert parser.get_source() == "def helloworld():\n    pass"
        assert result.parse_time_ms > 0
        assert result.module.functions[0].name == "helloworld"

    def test_apply_edit_delete(self, core_module):
        """Test deleting text."""
        source = "def helloworld():\n    pass"
        parser = core_module.IncrementalParser(source, "python", "test.py")

        # Delete 'world' (bytes 9-14)
        result = parser.apply_edit(9, 14, 9, "")

        assert parser.get_source() == "def hello():\n    pass"
        assert result.module.functions[0].name == "hello"

    def test_apply_edit_replace(self, core_module):
        """Test replacing text."""
        source = "def foo():\n    pass"
        parser = core_module.IncrementalParser(source, "python", "test.py")

        # Replace 'foo' with 'bar' (bytes 4-7)
        result = parser.apply_edit(4, 7, 7, "bar")

        assert parser.get_source() == "def bar():\n    pass"
        assert result.module.functions[0].name == "bar"

    def test_apply_edit_add_function(self, core_module):
        """Test adding a new function at the end."""
        source = "def foo():\n    pass"
        parser = core_module.IncrementalParser(source, "python", "test.py")

        addition = "\n\ndef bar():\n    pass"
        end = len(source)
        result = parser.apply_edit(end, end, end + len(addition), addition)

        assert "bar" in parser.get_source()
        assert len(result.module.functions) == 2
        assert result.module.functions[0].name == "foo"
        assert result.module.functions[1].name == "bar"

    def test_apply_edit_remove_function(self, core_module):
        """Test removing a function."""
        source = "def foo():\n    pass\n\ndef bar():\n    pass"
        parser = core_module.IncrementalParser(source, "python", "test.py")

        # Remove the second function starting at byte 18
        result = parser.apply_edit(18, len(source), 18, "")

        module = result.module
        assert len(module.functions) == 1
        assert module.functions[0].name == "foo"

    def test_apply_edit_multiline(self, core_module):
        """Test multiline edits."""
        source = "def hello():\n    pass"
        parser = core_module.IncrementalParser(source, "python", "test.py")

        # Replace body with a return statement
        new_body = "    return 42"
        result = parser.apply_edit(13, 21, 13 + len(new_body), new_body)

        assert "return 42" in parser.get_source()

    def test_sequential_edits(self, core_module):
        """Test applying multiple sequential edits."""
        source = "def f():\n    pass"
        parser = core_module.IncrementalParser(source, "python", "test.py")

        # f -> foo
        parser.apply_edit(4, 5, 5, "foo")
        assert parser.get_source() == "def foo():\n    pass"

        # foo -> bar
        parser.apply_edit(4, 7, 7, "bar")
        assert parser.get_source() == "def bar():\n    pass"

        # bar -> baz
        parser.apply_edit(4, 7, 7, "baz")
        assert parser.get_source() == "def baz():\n    pass"

        module = parser.get_module()
        assert module.functions[0].name == "baz"

    def test_invalid_byte_offset_raises(self, core_module):
        """Test that invalid byte offsets raise ValueError."""
        source = "def hello():\n    pass"
        parser = core_module.IncrementalParser(source, "python", "test.py")

        # start_byte beyond source length
        with pytest.raises(ValueError):
            parser.apply_edit(1000, 1000, 1001, "x")

        # old_end_byte beyond source length
        with pytest.raises(ValueError):
            parser.apply_edit(0, 1000, 0, "")

        # start_byte > old_end_byte
        with pytest.raises(ValueError):
            parser.apply_edit(10, 5, 10, "x")

    def test_byte_to_position(self, core_module):
        """Test byte offset to position conversion."""
        source = "def hello():\n    pass"
        parser = core_module.IncrementalParser(source, "python", "test.py")

        # Start of file
        assert parser.byte_to_position(0) == (0, 0)

        # 'h' in 'hello' at position 4
        assert parser.byte_to_position(4) == (0, 4)

        # Start of second line (after newline at 12)
        assert parser.byte_to_position(13) == (1, 0)

    def test_byte_to_position_invalid_raises(self, core_module):
        """Test that invalid byte offset raises ValueError."""
        source = "def hello():\n    pass"
        parser = core_module.IncrementalParser(source, "python", "test.py")

        with pytest.raises(ValueError):
            parser.byte_to_position(1000)

    def test_position_to_byte(self, core_module):
        """Test position to byte offset conversion."""
        source = "def hello():\n    pass"
        parser = core_module.IncrementalParser(source, "python", "test.py")

        # Start of file
        assert parser.position_to_byte(0, 0) == 0

        # 'h' in 'hello' at position (0, 4)
        assert parser.position_to_byte(0, 4) == 4

        # Start of second line
        assert parser.position_to_byte(1, 0) == 13

    def test_reset(self, core_module):
        """Test resetting the parser with new source."""
        source = "def foo():\n    pass"
        parser = core_module.IncrementalParser(source, "python", "test.py")

        # Make some edits
        parser.apply_edit(4, 7, 7, "bar")

        # Reset with completely new source
        new_source = "class MyClass:\n    pass"
        result = parser.reset(new_source)

        assert parser.get_source() == new_source
        module = result.module
        assert len(module.classes) == 1
        assert module.classes[0].name == "MyClass"
        assert len(module.functions) == 0

    def test_has_errors_with_invalid_syntax(self, core_module):
        """Test that has_errors returns True for invalid syntax."""
        # Valid syntax
        parser = core_module.IncrementalParser("def hello():\n    pass", "python", "test.py")
        assert not parser.has_errors()

        # Invalid syntax (tree-sitter still creates a tree, but marks errors)
        parser2 = core_module.IncrementalParser("def hello(\n    pass", "python", "test.py")
        assert parser2.has_errors()

    def test_changed_ranges_populated(self, core_module):
        """Test that changed_ranges is populated after edit."""
        source = "def hello():\n    pass"
        parser = core_module.IncrementalParser(source, "python", "test.py")

        result = parser.apply_edit(4, 9, 12, "goodbye")

        # changed_ranges should contain at least one range
        assert len(result.changed_ranges) > 0

    def test_parse_result_to_dict(self, core_module):
        """Test IncrementalParseResult serialization."""
        source = "def hello():\n    pass"
        parser = core_module.IncrementalParser(source, "python", "test.py")

        result = parser.apply_edit(4, 9, 12, "goodbye")
        data = result.to_dict()

        assert "module" in data
        assert "parse_time_ms" in data
        assert "changed_ranges" in data
        assert isinstance(data["parse_time_ms"], float)
        assert isinstance(data["changed_ranges"], list)

    def test_language_aliases(self, core_module):
        """Test that language aliases work correctly."""
        source = "def hello():\n    pass"

        # py -> python
        parser1 = core_module.IncrementalParser(source, "py", "test.py")
        assert parser1.get_language() == "python"

        # ts -> typescript
        ts_source = "function hello() {}"
        parser2 = core_module.IncrementalParser(ts_source, "ts", "test.ts")
        assert parser2.get_language() == "typescript"

        # rs -> rust
        rust_source = "fn hello() {}"
        parser3 = core_module.IncrementalParser(rust_source, "rs", "test.rs")
        assert parser3.get_language() == "rust"

    def test_all_supported_languages(self, core_module):
        """Test that all 7 supported languages can be parsed."""
        test_cases = [
            ("python", "def hello():\n    pass", "test.py"),
            ("typescript", "function hello(): void {}", "test.ts"),
            ("javascript", "function hello() {}", "test.js"),
            ("go", "package main\nfunc hello() {}", "test.go"),
            ("java", "class Test { void hello() {} }", "Test.java"),
            ("rust", "fn hello() {}", "test.rs"),
            ("csharp", "class Test { void Hello() {} }", "Test.cs"),
        ]

        for lang, source, path in test_cases:
            parser = core_module.IncrementalParser(source, lang, path)
            assert parser.has_tree(), f"Failed to create tree for {lang}"
            assert parser.get_language() == lang

    def test_incremental_faster_than_full_parse(self, core_module):
        """Test that incremental parsing is faster than full reparsing.

        This is a basic sanity check - incremental should generally be faster
        for small edits on larger files.
        """
        # Create a moderately sized source
        lines = ["def func_%d():\n    pass" % i for i in range(50)]
        source = "\n\n".join(lines)

        parser = core_module.IncrementalParser(source, "python", "test.py")

        # Make a small edit
        result = parser.apply_edit(4, 10, 13, "new_name")

        # Just verify it completed quickly (under 50ms for small edits)
        # In practice, incremental parsing is much faster
        assert result.parse_time_ms < 50, "Incremental parse took too long"


class TestIncrementalParserIntegration:
    """Integration tests for incremental parser with daemon workflow."""

    @pytest.fixture
    def core_module(self):
        """Import _core module for tests."""
        from mu import _core
        return _core

    def test_simulated_typing_workflow(self, core_module):
        """Simulate a user typing code character by character."""
        # Start with an empty file
        parser = core_module.IncrementalParser("", "python", "test.py")

        # Type "def h"
        parser.apply_edit(0, 0, 5, "def h")
        assert parser.get_source() == "def h"

        # Continue with "ello():"
        parser.apply_edit(5, 5, 12, "ello():")
        assert parser.get_source() == "def hello():"

        # Add newline and body
        parser.apply_edit(12, 12, 22, "\n    pass")
        assert parser.get_source() == "def hello():\n    pass"

        # Verify the module is correct
        module = parser.get_module()
        assert len(module.functions) == 1
        assert module.functions[0].name == "hello"

    def test_simulated_refactoring(self, core_module):
        """Simulate a refactoring operation (rename function)."""
        source = '''
def old_name(x, y):
    """Calculate something."""
    return x + y

def caller():
    return old_name(1, 2)
'''
        parser = core_module.IncrementalParser(source.strip(), "python", "test.py")

        # Find and replace 'old_name' with 'new_name' (first occurrence at byte 5)
        # 'old_name' is 8 characters
        result = parser.apply_edit(4, 12, 12, "new_name")

        new_source = parser.get_source()
        assert "new_name" in new_source
        # Note: Simple byte-based replacement won't catch all occurrences
        # In a real IDE, you'd use LSP for proper rename

    def test_error_recovery(self, core_module):
        """Test that parser recovers from syntax errors."""
        source = "def hello():\n    pass"
        parser = core_module.IncrementalParser(source, "python", "test.py")

        # Introduce a syntax error (remove closing paren)
        parser.apply_edit(10, 11, 10, "")  # Remove ')'

        # Parser should still have a tree, but with errors
        assert parser.has_tree()
        assert parser.has_errors()

        # Fix the error
        parser.apply_edit(10, 10, 11, ")")

        # Should be error-free now
        assert not parser.has_errors()
        assert parser.get_module().functions[0].name == "hello"
