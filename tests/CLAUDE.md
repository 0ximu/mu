# Tests - Testing Standards & Patterns

This directory contains all tests for the MU project, organized by test type.

## Directory Structure

```
tests/
├── unit/                    # Unit tests for individual modules
│   ├── test_cli_commands.py # CLI command registration and help tests
│   ├── test_parser.py      # Multi-language parser tests
│   ├── test_assembler.py   # Import resolution tests
│   ├── test_reducer.py     # Transformation rule tests
│   ├── test_diff.py        # Semantic diff tests
│   ├── test_llm.py         # LLM integration tests
│   ├── test_security.py    # Secret detection tests
│   ├── test_viewer.py      # Rendering tests
│   ├── test_cache.py       # Cache behavior tests
│   ├── test_scanner.py     # File discovery tests
│   ├── test_client.py      # Daemon client tests
│   ├── test_describe.py    # CLI introspection tests
│   ├── test_muql_parser.py # MUQL query parser tests
│   └── test_config.py      # Configuration tests
├── daemon/                  # Daemon integration tests
│   └── test_contracts_endpoint.py  # Contracts API tests
└── conftest.py             # Shared fixtures
```

## Naming Conventions

### Test Files
- `test_{module}.py` - Tests for `src/mu/{module}/`

### Test Classes
- `Test{Component}` - Group related tests
- Example: `TestPythonParser`, `TestGoParser`, `TestLLMPool`

### Test Methods
- `test_{method}_{scenario}_{expected}` or `test_{behavior}`
- Examples:
  - `test_parse_function_with_decorators`
  - `test_resolve_relative_import`
  - `test_redact_github_token`

## Test Organization

Use class-based organization for related tests:

```python
class TestPythonParser:
    """Tests for Python language extraction."""

    def test_parse_simple_function(self):
        ...

    def test_parse_async_function(self):
        ...

    def test_parse_class_with_inheritance(self):
        ...


class TestGoParser:
    """Tests for Go language extraction."""

    def test_parse_struct(self):
        ...
```

## Fixtures (conftest.py)

Common fixtures available:

```python
@pytest.fixture
def sample_python_source():
    """Simple Python source for parsing tests."""
    return '''
def hello(name: str) -> str:
    return f"Hello, {name}"
'''

@pytest.fixture
def temp_codebase(tmp_path):
    """Creates a temporary codebase structure."""
    ...

@pytest.fixture
def mock_llm_response():
    """Mock LLM API response."""
    ...
```

## Test Patterns

### Parser Tests

```python
def test_parse_function_with_parameters(self):
    source = '''
def greet(name: str, greeting: str = "Hello") -> str:
    return f"{greeting}, {name}"
'''
    result = parse_file(Path("test.py"), "python")

    assert result.success
    assert len(result.module.functions) == 1

    func = result.module.functions[0]
    assert func.name == "greet"
    assert len(func.parameters) == 2
    assert func.parameters[0].name == "name"
    assert func.parameters[0].type_annotation == "str"
    assert func.return_type == "str"
```

### Assembler Tests

```python
def test_resolve_relative_import(self, temp_codebase):
    # Setup modules
    modules = [
        ModuleDef(name="pkg.utils", path="pkg/utils.py", ...),
        ModuleDef(name="pkg.main", path="pkg/main.py", ...),
    ]

    resolver = ImportResolver(modules, temp_codebase)
    imp = ImportDef(module=".utils", is_from=True)

    resolved = resolver.resolve(imp, modules[1])

    assert resolved.dep_type == DependencyType.INTERNAL
    assert resolved.resolved_path == "pkg/utils.py"
```

### Security Tests

```python
def test_redact_github_pat(self):
    source = 'token = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"'

    result = SecretScanner().scan(source)

    assert result.has_secrets
    assert result.secrets[0].pattern_name == "github_pat"
    assert "REDACTED" in result.redacted_source
    assert "ghp_" not in result.redacted_source
```

### LLM Tests (with mocking)

```python
@pytest.mark.asyncio
async def test_summarize_caches_result(self, mock_llm_response):
    with patch("mu.llm.pool.acompletion", return_value=mock_llm_response):
        pool = LLMPool(config)

        # First call hits API
        result1 = await pool.summarize(request)
        assert not result1.cached

        # Second call hits cache
        result2 = await pool.summarize(request)
        assert result2.cached
```

## Running Tests

```bash
# All tests
pytest

# Verbose output
pytest -v

# Specific test file
pytest tests/unit/test_parser.py

# Specific test class
pytest tests/unit/test_parser.py::TestPythonParser

# Specific test method
pytest tests/unit/test_parser.py::TestPythonParser::test_parse_function

# With coverage
pytest --cov=src/mu

# Coverage report
pytest --cov=src/mu --cov-report=html

# Run tests matching pattern
pytest -k "python and parser"

# Show print statements
pytest -s
```

## Async Tests

Use `@pytest.mark.asyncio` for async tests:

```python
import pytest

@pytest.mark.asyncio
async def test_async_summarize():
    result = await pool.summarize(request)
    assert result.summary
```

## Parameterized Tests

Use `@pytest.mark.parametrize` for multiple inputs:

```python
@pytest.mark.parametrize("language,source,expected_count", [
    ("python", "def foo(): pass", 1),
    ("python", "def foo(): pass\ndef bar(): pass", 2),
    ("go", "func foo() {}", 1),
])
def test_function_count(language, source, expected_count):
    result = parse_source(source, language)
    assert len(result.module.functions) == expected_count
```

## Test Data

For larger test fixtures, use files in `tests/fixtures/`:

```python
@pytest.fixture
def sample_project(tmp_path):
    fixtures_dir = Path(__file__).parent / "fixtures" / "sample_project"
    shutil.copytree(fixtures_dir, tmp_path / "project")
    return tmp_path / "project"
```

## Anti-Patterns

1. **Never** test implementation details - test behavior
2. **Never** use real API keys - mock LLM calls
3. **Never** depend on test order - each test should be independent
4. **Never** hardcode absolute paths - use `tmp_path` fixture
5. **Never** skip cleanup - use fixtures with proper teardown
6. **Never** test private methods directly - test through public API

## Coverage Requirements

Aim for meaningful coverage:
- New features: Tests covering happy path + edge cases
- Bug fixes: Regression test reproducing the bug
- Parser changes: Tests for each language affected

Check coverage:
```bash
pytest --cov=src/mu --cov-report=term-missing
```

## Writing Good Tests

### Do
- Test one thing per test
- Use descriptive test names
- Include edge cases (empty input, None, unicode)
- Use fixtures for setup/teardown
- Test error conditions

### Don't
- Test obvious things (Python works)
- Duplicate production logic in tests
- Make tests depend on each other
- Use sleep() for async - use proper async tools
- Ignore flaky tests - fix them
