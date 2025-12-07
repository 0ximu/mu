# MU Project Context

> Critical rules and patterns for AI agents implementing MU code. Read this before writing any code.

## Language & Runtime

- **Python 3.10+** with full type hints
- Use `X | None` syntax, NEVER `Optional[X]` or `Union[X, Y]`
- Use `list[str]`, `dict[str, Any]`, NEVER `List`, `Dict` from typing

## Naming Conventions (THE MU WAY)

| Element | Convention | Example |
|---------|------------|---------|
| Functions/Methods | `snake_case` | `parse_file()`, `get_dependencies()` |
| Private methods | `_snake_case` | `_extract_import()` |
| Classes | `PascalCase` | `ModuleDef`, `LLMPool` |
| Variables | `snake_case` | `module_count` |
| Booleans | `is_`/`has_` prefix | `is_async`, `has_error` |
| Constants | `UPPER_SNAKE_CASE` | `DEFAULT_TIMEOUT` |
| Files | `snake_case.py` | `python_extractor.py` |
| JSON fields | `snake_case` | `mubase_path` |

## Data Model Pattern (MANDATORY)

Every data model MUST implement `to_dict()`:

```python
@dataclass
class MyModel:
    name: str
    items: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {"name": self.name, "items": self.items}
        if self.error:
            result["error"] = self.error
        return result
```

## Error Handling Pattern

**Expected failures:** Set error field, don't raise
```python
def parse_file(path: Path) -> ParsedFile:
    result = ParsedFile(path=str(path))
    if error_occurred:
        result.error = str(error)  # Don't raise
    return result
```

**Unexpected failures:** Raise `MUError` subclass with `exit_code`

## Import Rules

- ALWAYS use absolute imports: `from mu.parser import ModuleDef`
- NEVER use relative imports: `from .utils import helper`
- Control public API with `__all__`

## Test Organization

```
tests/unit/test_{module}.py  # mirrors src/mu/{module}.py
```

- File: `test_{module}.py`
- Class: `class Test{Feature}:`
- Method: `test_{behavior}_{scenario}()`

## API Response Pattern (Pydantic)

```python
class QueryResponse(BaseModel):
    result: dict[str, Any] = Field(description="Query results")
    success: bool = Field(description="Whether query succeeded")
    error: str | None = Field(default=None, description="Error message")
```

ALL Pydantic fields MUST have `Field(description="...")`.

## CLI Exit Codes

```python
class ExitCode(IntEnum):
    SUCCESS = 0
    CONFIG_ERROR = 1
    PARTIAL_SUCCESS = 2
    FATAL_ERROR = 3
    GIT_ERROR = 4
    CONTRACT_VIOLATION = 5
```

## Logging

```python
logger = logging.getLogger(__name__)

# For CLI output, use mu.logging helpers:
print_error(), print_success(), print_warning(), print_info()
```

## Anti-Patterns (FORBIDDEN)

1. Exposing Tree-sitter types outside `parser/` module
2. Synchronous LLM calls (always use `LLMPool.summarize_batch()`)
3. Hardcoding stdlib lists (use `assembler/` constants)
4. Manual secret parsing (use `SecretScanner`)
5. Relative imports between modules
6. Assuming file encoding (use `errors="replace"`)
7. Using `Optional[X]` or `Union[X, Y]` syntax
8. Raising exceptions for expected failures

## Async Code

- Use `asyncio` with semaphore-based concurrency
- Mark async tests with `@pytest.mark.asyncio`
- NEVER make synchronous LLM calls

## Quality Checks Before PR

```bash
ruff check src/           # Linting
ruff format src/          # Formatting
mypy src/mu               # Type checking
pytest                    # Tests
```

---

**Architecture Reference:** See `docs/architecture.md` for full ADRs and implementation details.
