"""Tests for MU Rust core extension (mu._core).

These tests verify the Rust-based parser, secret detection, complexity calculation,
and export functionality. They serve as both correctness tests and regression tests
for the native extension.
"""

import pytest

# Skip all tests if Rust core is not available
pytest.importorskip("mu._core", reason="Rust core not compiled")

from mu._core import (
    parse_file,
    parse_files,
    find_secrets,
    redact_secrets,
    calculate_complexity,
    export_mu,
    export_json,
    export_markdown,
    version,
    FileInfo,
    ParseResult,
    ModuleDef,
    FunctionDef,
    ClassDef,
    ImportDef,
    SecretMatch,
)


class TestRustCoreVersion:
    """Test version and basic functionality."""

    def test_version_string(self):
        """Version should return a valid semver string."""
        v = version()
        assert isinstance(v, str)
        parts = v.split(".")
        assert len(parts) == 3
        assert all(part.isdigit() for part in parts)


class TestParseSingleFile:
    """Test single file parsing with parse_file()."""

    def test_parse_python_function(self):
        """Parse a simple Python function."""
        source = '''
def greet(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}!"
'''
        result = parse_file(source, "test.py", "python")

        assert isinstance(result, ParseResult)
        assert result.error is None
        assert result.module is not None

        module = result.module
        assert isinstance(module, ModuleDef)
        assert len(module.functions) == 1

        func = module.functions[0]
        assert isinstance(func, FunctionDef)
        assert func.name == "greet"
        assert func.return_type == "str"
        assert len(func.parameters) == 1
        assert func.parameters[0].name == "name"
        assert func.parameters[0].type_annotation == "str"

    def test_parse_python_class(self):
        """Parse a Python class with methods."""
        source = '''
class Calculator:
    """A simple calculator."""

    def __init__(self, value: int = 0):
        self.value = value

    def add(self, x: int) -> int:
        self.value += x
        return self.value

    @staticmethod
    def multiply(a: int, b: int) -> int:
        return a * b
'''
        result = parse_file(source, "calc.py", "python")

        assert result.error is None
        assert len(result.module.classes) == 1

        cls = result.module.classes[0]
        assert isinstance(cls, ClassDef)
        assert cls.name == "Calculator"
        assert len(cls.methods) == 3

        # Find static method
        multiply = next((m for m in cls.methods if m.name == "multiply"), None)
        assert multiply is not None
        assert multiply.is_static

    def test_parse_python_imports(self):
        """Parse various import statements."""
        source = '''
import os
import sys as system
from pathlib import Path
from typing import List, Optional
'''
        result = parse_file(source, "imports.py", "python")

        assert result.error is None
        imports = result.module.imports
        assert len(imports) >= 4

        # Check import with alias
        sys_import = next((i for i in imports if i.module == "sys"), None)
        assert sys_import is not None
        assert sys_import.alias == "system"

        # Check from import
        pathlib_import = next((i for i in imports if i.module == "pathlib"), None)
        assert pathlib_import is not None
        assert pathlib_import.is_from
        assert "Path" in pathlib_import.names

    def test_parse_typescript_function(self):
        """Parse TypeScript function."""
        source = '''
function greet(name: string): string {
    return `Hello, ${name}!`;
}

export async function fetchUser(id: number): Promise<User> {
    return await api.get(`/users/${id}`);
}
'''
        result = parse_file(source, "greet.ts", "typescript")

        assert result.error is None
        assert len(result.module.functions) == 2

        greet = next(f for f in result.module.functions if f.name == "greet")
        assert greet.return_type == "string"

        fetch = next(f for f in result.module.functions if f.name == "fetchUser")
        assert fetch.is_async

    def test_parse_typescript_class(self):
        """Parse TypeScript class."""
        source = '''
class UserService {
    private apiUrl: string;

    constructor(apiUrl: string) {
        this.apiUrl = apiUrl;
    }

    async getUser(id: number): Promise<User> {
        return await fetch(`${this.apiUrl}/users/${id}`);
    }
}
'''
        result = parse_file(source, "service.ts", "typescript")

        assert result.error is None
        assert len(result.module.classes) == 1

        cls = result.module.classes[0]
        assert cls.name == "UserService"

    def test_parse_go_function(self):
        """Parse Go function."""
        source = '''
package main

func greet(name string) string {
    return "Hello, " + name + "!"
}

func (c *Calculator) Add(x int) int {
    c.value += x
    return c.value
}
'''
        result = parse_file(source, "main.go", "go")

        assert result.error is None
        assert len(result.module.functions) >= 1

        greet = next((f for f in result.module.functions if f.name == "greet"), None)
        assert greet is not None

    def test_parse_go_struct(self):
        """Parse Go struct."""
        source = '''
package main

type Calculator struct {
    value int
}

type User struct {
    ID   int
    Name string
}
'''
        result = parse_file(source, "types.go", "go")

        assert result.error is None
        assert len(result.module.classes) >= 1

        calc = next((c for c in result.module.classes if c.name == "Calculator"), None)
        assert calc is not None

    def test_parse_java_class(self):
        """Parse Java class."""
        source = '''
package com.example;

public class Calculator {
    private int value;

    public Calculator(int initial) {
        this.value = initial;
    }

    public int add(int x) {
        value += x;
        return value;
    }

    public static int multiply(int a, int b) {
        return a * b;
    }
}
'''
        result = parse_file(source, "Calculator.java", "java")

        assert result.error is None
        assert len(result.module.classes) == 1

        cls = result.module.classes[0]
        assert cls.name == "Calculator"

    def test_parse_rust_function(self):
        """Parse Rust function."""
        source = '''
fn greet(name: &str) -> String {
    format!("Hello, {}!", name)
}

async fn fetch_user(id: u64) -> Result<User, Error> {
    client.get(format!("/users/{}", id)).await
}
'''
        result = parse_file(source, "lib.rs", "rust")

        assert result.error is None
        assert len(result.module.functions) >= 1

    def test_parse_rust_struct(self):
        """Parse Rust struct and impl."""
        source = '''
pub struct Calculator {
    value: i32,
}

impl Calculator {
    pub fn new(initial: i32) -> Self {
        Calculator { value: initial }
    }

    pub fn add(&mut self, x: i32) -> i32 {
        self.value += x;
        self.value
    }
}
'''
        result = parse_file(source, "calc.rs", "rust")

        assert result.error is None
        assert len(result.module.classes) >= 1

    def test_parse_csharp_class(self):
        """Parse C# class."""
        source = '''
namespace Example;

public class Calculator
{
    private int _value;

    public Calculator(int initial)
    {
        _value = initial;
    }

    public int Add(int x)
    {
        _value += x;
        return _value;
    }

    public static int Multiply(int a, int b) => a * b;
}
'''
        result = parse_file(source, "Calculator.cs", "csharp")

        assert result.error is None
        assert len(result.module.classes) == 1
        assert result.module.classes[0].name == "Calculator"

    def test_parse_javascript(self):
        """Parse JavaScript file (uses TS parser)."""
        source = '''
function greet(name) {
    return `Hello, ${name}!`;
}

class UserService {
    constructor(apiUrl) {
        this.apiUrl = apiUrl;
    }

    async getUser(id) {
        return await fetch(`${this.apiUrl}/users/${id}`);
    }
}
'''
        result = parse_file(source, "app.js", "javascript")

        assert result.error is None
        assert len(result.module.functions) >= 1
        assert len(result.module.classes) >= 1

    def test_parse_syntax_error(self):
        """Parsing invalid syntax should return error."""
        source = '''
def broken(
    # missing closing paren and body
'''
        result = parse_file(source, "broken.py", "python")

        # Should still return a result, possibly with error or empty module
        assert isinstance(result, ParseResult)
        # The module should still be parseable (tree-sitter is error tolerant)

    def test_parse_empty_file(self):
        """Parse empty file."""
        result = parse_file("", "empty.py", "python")

        assert result.error is None
        assert result.module is not None
        assert len(result.module.functions) == 0
        assert len(result.module.classes) == 0


class TestParseMultipleFiles:
    """Test parallel file parsing with parse_files()."""

    def test_parse_files_parallel(self):
        """Parse multiple files in parallel."""
        files = [
            FileInfo(path="a.py", source="def foo(): pass", language="python"),
            FileInfo(path="b.py", source="def bar(): pass", language="python"),
            FileInfo(path="c.py", source="class Baz: pass", language="python"),
        ]

        results = parse_files(files)

        assert len(results) == 3
        assert all(r.error is None for r in results)

        # Check we got the right functions/classes
        all_functions = [f.name for r in results for f in r.module.functions]
        all_classes = [c.name for r in results for c in r.module.classes]

        assert "foo" in all_functions
        assert "bar" in all_functions
        assert "Baz" in all_classes

    def test_parse_files_mixed_languages(self):
        """Parse files in different languages."""
        files = [
            FileInfo(path="a.py", source="def foo(): pass", language="python"),
            FileInfo(path="b.ts", source="function bar(): void {}", language="typescript"),
            FileInfo(path="c.go", source="package main\nfunc baz() {}", language="go"),
        ]

        results = parse_files(files)

        assert len(results) == 3
        assert all(r.error is None for r in results)

    def test_parse_files_with_thread_count(self):
        """Specify thread count for parallel parsing."""
        files = [
            FileInfo(path=f"file{i}.py", source=f"def func{i}(): pass", language="python")
            for i in range(10)
        ]

        # Use 2 threads
        results = parse_files(files, num_threads=2)

        assert len(results) == 10
        assert all(r.error is None for r in results)

    def test_parse_files_empty_list(self):
        """Parse empty file list."""
        results = parse_files([])
        assert results == []


class TestSecretDetection:
    """Test secret detection and redaction."""

    def test_find_aws_key(self):
        """Detect AWS access key."""
        source = 'aws_key = "AKIAIOSFODNN7EXAMPLE"'
        secrets = find_secrets(source)

        assert len(secrets) >= 1
        assert any(s.pattern_name == "aws_access_key_id" for s in secrets)

    def test_find_github_pat(self):
        """Detect GitHub personal access token."""
        source = 'token = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"'
        secrets = find_secrets(source)

        assert len(secrets) >= 1
        assert any(s.pattern_name == "github_token" for s in secrets)

    def test_find_openai_key(self):
        """Detect OpenAI API key."""
        source = 'OPENAI_API_KEY = "sk-proj-abcdefghijklmnopqrstuvwxyz12345"'
        secrets = find_secrets(source)

        assert len(secrets) >= 1
        assert any("openai" in s.pattern_name for s in secrets)

    def test_find_private_key(self):
        """Detect private key block."""
        source = '''
-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA...
-----END RSA PRIVATE KEY-----
'''
        secrets = find_secrets(source)

        assert len(secrets) >= 1
        assert any("private_key" in s.pattern_name for s in secrets)

    def test_find_database_uri(self):
        """Detect database connection string with password."""
        source = 'db_url = "postgresql://user:secretpass123@localhost:5432/mydb"'
        secrets = find_secrets(source)

        assert len(secrets) >= 1

    def test_secret_match_properties(self):
        """SecretMatch should have line/column info."""
        source = 'line1\ntoken = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"'
        secrets = find_secrets(source)

        assert len(secrets) >= 1
        match = secrets[0]
        assert isinstance(match, SecretMatch)
        assert match.line >= 1
        assert match.column >= 0
        assert match.start >= 0
        assert match.end > match.start

    def test_redact_secrets(self):
        """Redact secrets from source."""
        source = 'token = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"'
        redacted = redact_secrets(source)

        assert "ghp_" not in redacted
        assert "REDACTED" in redacted  # Format: ":: REDACTED:pattern_name"

    def test_redact_multiple_secrets(self):
        """Redact multiple secrets."""
        source = '''
aws_key = "AKIAIOSFODNN7EXAMPLE"
token = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"
'''
        redacted = redact_secrets(source)

        assert "AKIAIOSFODNN7EXAMPLE" not in redacted
        assert "ghp_" not in redacted
        assert redacted.count("REDACTED") >= 2

    def test_no_secrets_found(self):
        """No secrets in clean code."""
        source = '''
def greet(name: str) -> str:
    return f"Hello, {name}!"
'''
        secrets = find_secrets(source)
        assert len(secrets) == 0

        redacted = redact_secrets(source)
        assert source == redacted


class TestComplexity:
    """Test cyclomatic complexity calculation."""

    def test_simple_function_complexity(self):
        """Simple function has complexity 1."""
        source = '''
def greet(name):
    return f"Hello, {name}!"
'''
        complexity = calculate_complexity(source, "python")
        assert complexity == 1

    def test_if_statement_complexity(self):
        """If statement adds 1 to complexity."""
        source = '''
def greet(name):
    if name:
        return f"Hello, {name}!"
    return "Hello!"
'''
        complexity = calculate_complexity(source, "python")
        assert complexity >= 2

    def test_multiple_branches_complexity(self):
        """Multiple branches increase complexity."""
        source = '''
def classify(value):
    if value < 0:
        return "negative"
    elif value == 0:
        return "zero"
    elif value < 10:
        return "small"
    else:
        return "large"
'''
        complexity = calculate_complexity(source, "python")
        assert complexity >= 4

    def test_loop_complexity(self):
        """Loops add to complexity."""
        source = '''
def sum_list(items):
    total = 0
    for item in items:
        total += item
    return total
'''
        complexity = calculate_complexity(source, "python")
        assert complexity >= 2

    def test_nested_complexity(self):
        """Nested control flow increases complexity."""
        source = '''
def process(items):
    for item in items:
        if item > 0:
            for i in range(item):
                if i % 2 == 0:
                    print(i)
'''
        complexity = calculate_complexity(source, "python")
        assert complexity >= 4


class TestExport:
    """Test export functionality."""

    def test_export_mu_format(self):
        """Export to MU sigil format."""
        source = '''
def greet(name: str) -> str:
    return f"Hello, {name}!"

class Calculator:
    def add(self, x: int) -> int:
        return x
'''
        result = parse_file(source, "test.py", "python")
        mu_output = export_mu(result.module)

        assert isinstance(mu_output, str)
        assert "!" in mu_output  # Module sigil
        assert "#" in mu_output  # Function sigil
        assert "$" in mu_output  # Class sigil

    def test_export_json(self):
        """Export to JSON format."""
        source = 'def foo(): pass'
        result = parse_file(source, "test.py", "python")
        json_output = export_json(result.module)

        import json
        parsed = json.loads(json_output)
        assert "functions" in parsed
        assert len(parsed["functions"]) == 1
        assert parsed["functions"][0]["name"] == "foo"

    def test_export_json_pretty(self):
        """Export to pretty-printed JSON."""
        source = 'def foo(): pass'
        result = parse_file(source, "test.py", "python")
        json_pretty = export_json(result.module, pretty=True)

        assert "\n" in json_pretty
        assert "  " in json_pretty  # Indentation

    def test_export_markdown(self):
        """Export to Markdown format."""
        source = '''
def greet(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}!"
'''
        result = parse_file(source, "test.py", "python")
        md_output = export_markdown(result.module)

        assert isinstance(md_output, str)
        assert "#" in md_output  # Markdown headers
        assert "greet" in md_output


class TestModuleDef:
    """Test ModuleDef type and methods."""

    def test_module_to_dict(self):
        """ModuleDef.to_dict() returns dictionary."""
        source = '''
def foo(): pass
class Bar: pass
'''
        result = parse_file(source, "test.py", "python")
        module_dict = result.module.to_dict()

        assert isinstance(module_dict, dict)
        assert "functions" in module_dict
        assert "classes" in module_dict
        assert len(module_dict["functions"]) == 1
        assert len(module_dict["classes"]) == 1

    def test_module_properties(self):
        """ModuleDef has expected properties."""
        source = 'def foo(): pass'
        result = parse_file(source, "test.py", "python")
        module = result.module

        assert module.name == "test"
        assert module.path == "test.py"
        assert module.language == "python"
        assert isinstance(module.total_lines, int)


class TestFileInfo:
    """Test FileInfo type."""

    def test_create_file_info(self):
        """Create FileInfo instance."""
        fi = FileInfo(path="test.py", source="def foo(): pass", language="python")

        assert fi.path == "test.py"
        assert fi.source == "def foo(): pass"
        assert fi.language == "python"


@pytest.mark.parametrize("language,source,expected_funcs", [
    ("python", "def foo(): pass", 1),
    ("python", "def foo(): pass\ndef bar(): pass", 2),
    ("typescript", "function foo() {}", 1),
    ("go", "package main\nfunc foo() {}", 1),
    ("java", "public class A { void foo() {} }", 0),  # Methods are inside class
    ("rust", "fn foo() {}", 1),
    ("csharp", "class A { void Foo() {} }", 0),  # Methods are inside class
])
def test_function_count_by_language(language, source, expected_funcs):
    """Verify function parsing across languages."""
    result = parse_file(source, f"test.{language[:2]}", language)
    assert len(result.module.functions) == expected_funcs


# =============================================================================
# GraphEngine Tests (petgraph integration)
# =============================================================================

from mu._core import GraphEngine


class TestGraphEngine:
    """Test the petgraph-based GraphEngine for graph reasoning."""

    def test_create_graph_engine(self):
        """Create a GraphEngine from nodes and edges."""
        nodes = ["a", "b", "c"]
        edges = [("a", "b", "imports"), ("b", "c", "imports")]

        engine = GraphEngine(nodes, edges)

        assert engine.node_count() == 3
        assert engine.edge_count() == 2

    def test_find_cycles_with_cycle(self):
        """Detect cycles in the graph."""
        nodes = ["a", "b", "c"]
        edges = [
            ("a", "b", "imports"),
            ("b", "c", "imports"),
            ("c", "a", "imports"),  # Creates cycle a -> b -> c -> a
        ]

        engine = GraphEngine(nodes, edges)
        cycles = engine.find_cycles()

        assert len(cycles) == 1
        cycle = cycles[0]
        assert len(cycle) == 3
        assert set(cycle) == {"a", "b", "c"}

    def test_find_cycles_no_cycle(self):
        """No cycles in acyclic graph."""
        nodes = ["a", "b", "c"]
        edges = [("a", "b", "imports"), ("b", "c", "imports")]

        engine = GraphEngine(nodes, edges)
        cycles = engine.find_cycles()

        assert len(cycles) == 0

    def test_find_cycles_filtered_by_edge_type(self):
        """Filter cycles by edge type."""
        nodes = ["a", "b", "c"]
        edges = [
            ("a", "b", "imports"),
            ("b", "c", "imports"),
            ("c", "a", "calls"),  # Different edge type
        ]

        engine = GraphEngine(nodes, edges)

        # With all edges, there's a cycle
        all_cycles = engine.find_cycles()
        assert len(all_cycles) == 1

        # With only imports, no cycle (missing c -> a)
        import_cycles = engine.find_cycles(["imports"])
        assert len(import_cycles) == 0

    def test_impact_analysis(self):
        """Find downstream impact of a node."""
        nodes = ["a", "b", "c", "d"]
        edges = [
            ("a", "b", "imports"),
            ("b", "c", "imports"),
            ("b", "d", "calls"),
        ]

        engine = GraphEngine(nodes, edges)
        impact = engine.impact("a")

        # a -> b -> c, d
        assert "b" in impact
        assert "c" in impact
        assert "d" in impact
        assert "a" not in impact  # Start node not included

    def test_impact_filtered_by_edge_type(self):
        """Filter impact analysis by edge type."""
        nodes = ["a", "b", "c", "d"]
        edges = [
            ("a", "b", "imports"),
            ("b", "c", "imports"),
            ("b", "d", "calls"),
        ]

        engine = GraphEngine(nodes, edges)

        # Only imports
        import_impact = engine.impact("a", ["imports"])
        assert "b" in import_impact
        assert "c" in import_impact
        assert "d" not in import_impact  # calls edge ignored

        # Only calls
        calls_impact = engine.impact("a", ["calls"])
        assert "d" not in calls_impact  # Can't reach d from a with just calls

    def test_ancestors(self):
        """Find upstream ancestors of a node."""
        nodes = ["a", "b", "c", "d"]
        edges = [
            ("a", "b", "imports"),
            ("b", "c", "imports"),
            ("d", "c", "imports"),
        ]

        engine = GraphEngine(nodes, edges)
        ancestors = engine.ancestors("c")

        # c <- b <- a, c <- d
        assert "b" in ancestors
        assert "a" in ancestors
        assert "d" in ancestors
        assert "c" not in ancestors

    def test_shortest_path_exists(self):
        """Find shortest path between two nodes."""
        nodes = ["a", "b", "c", "d"]
        edges = [
            ("a", "b", "imports"),
            ("b", "c", "imports"),
            ("c", "d", "imports"),
            ("a", "d", "calls"),  # Shortcut
        ]

        engine = GraphEngine(nodes, edges)

        # Direct path via calls
        path = engine.shortest_path("a", "d")
        assert path is not None
        assert path[0] == "a"
        assert path[-1] == "d"
        assert len(path) == 2  # Direct shortcut

        # Force imports-only path
        import_path = engine.shortest_path("a", "d", ["imports"])
        assert import_path is not None
        assert len(import_path) == 4  # a -> b -> c -> d

    def test_shortest_path_not_exists(self):
        """No path between disconnected nodes."""
        nodes = ["a", "b", "c", "d"]
        edges = [
            ("a", "b", "imports"),
            ("c", "d", "imports"),
        ]

        engine = GraphEngine(nodes, edges)
        path = engine.shortest_path("a", "d")

        assert path is None

    def test_neighbors_outgoing(self):
        """Find outgoing neighbors."""
        nodes = ["a", "b", "c", "d"]
        edges = [
            ("a", "b", "imports"),
            ("a", "c", "calls"),
            ("d", "a", "imports"),
        ]

        engine = GraphEngine(nodes, edges)
        neighbors = engine.neighbors("a", "outgoing", 1)

        assert "b" in neighbors
        assert "c" in neighbors
        assert "d" not in neighbors  # d -> a, not a -> d

    def test_neighbors_incoming(self):
        """Find incoming neighbors."""
        nodes = ["a", "b", "c", "d"]
        edges = [
            ("a", "b", "imports"),
            ("a", "c", "calls"),
            ("d", "a", "imports"),
        ]

        engine = GraphEngine(nodes, edges)
        neighbors = engine.neighbors("a", "incoming", 1)

        assert "d" in neighbors  # d -> a
        assert "b" not in neighbors
        assert "c" not in neighbors

    def test_neighbors_both_directions(self):
        """Find neighbors in both directions."""
        nodes = ["a", "b", "c", "d"]
        edges = [
            ("a", "b", "imports"),
            ("d", "a", "imports"),
        ]

        engine = GraphEngine(nodes, edges)
        neighbors = engine.neighbors("a", "both", 1)

        assert "b" in neighbors
        assert "d" in neighbors

    def test_neighbors_depth(self):
        """Find neighbors at multiple depths."""
        nodes = ["a", "b", "c", "d"]
        edges = [
            ("a", "b", "imports"),
            ("b", "c", "imports"),
            ("c", "d", "imports"),
        ]

        engine = GraphEngine(nodes, edges)

        # Depth 1
        depth1 = engine.neighbors("a", "outgoing", 1)
        assert depth1 == ["b"]

        # Depth 2
        depth2 = engine.neighbors("a", "outgoing", 2)
        assert "b" in depth2
        assert "c" in depth2
        assert "d" not in depth2

        # Depth 3
        depth3 = engine.neighbors("a", "outgoing", 3)
        assert "b" in depth3
        assert "c" in depth3
        assert "d" in depth3

    def test_has_node(self):
        """Check if node exists."""
        nodes = ["a", "b", "c"]
        edges = [("a", "b", "imports")]

        engine = GraphEngine(nodes, edges)

        assert engine.has_node("a")
        assert engine.has_node("b")
        assert engine.has_node("c")
        assert not engine.has_node("nonexistent")

    def test_edge_types(self):
        """Get unique edge types in graph."""
        nodes = ["a", "b", "c"]
        edges = [
            ("a", "b", "imports"),
            ("b", "c", "calls"),
            ("a", "c", "imports"),
        ]

        engine = GraphEngine(nodes, edges)
        types = engine.edge_types()

        assert "imports" in types
        assert "calls" in types
        assert len(types) == 2

    def test_empty_graph(self):
        """Handle empty graph."""
        engine = GraphEngine([], [])

        assert engine.node_count() == 0
        assert engine.edge_count() == 0
        assert engine.find_cycles() == []
        assert engine.impact("nonexistent") == []

    def test_edge_to_unknown_node_ignored(self):
        """Edges referencing unknown nodes are ignored."""
        nodes = ["a", "b"]
        edges = [
            ("a", "b", "imports"),
            ("a", "unknown", "imports"),  # Target doesn't exist
            ("unknown", "b", "imports"),  # Source doesn't exist
        ]

        engine = GraphEngine(nodes, edges)

        assert engine.node_count() == 2
        assert engine.edge_count() == 1  # Only a -> b
