# MU - Claude Code Project Instructions

This file provides project-wide guidance to Claude Code. Nested CLAUDE.md files in subsystem directories provide specialized context.

## Pre-PR Checklist

Before creating a pull request, verify:

### Code Quality
- [ ] `ruff check src/` passes with no errors
- [ ] `ruff format src/` applied (code is formatted)
- [ ] `mypy src/mu` passes with no type errors
- [ ] No new `# type: ignore` without justification

### Testing
- [ ] `pytest` passes all tests
- [ ] New code has corresponding tests
- [ ] `pytest --cov=src/mu` shows coverage for changed code

### Architecture
- [ ] New parsers implement `LanguageExtractor` protocol
- [ ] New LLM providers added via LiteLLM, not custom code
- [ ] Data models use dataclasses with `to_dict()` methods
- [ ] No circular imports between modules

### Security
- [ ] No hardcoded secrets or API keys
- [ ] New secret patterns added to `security/__init__.py` if needed
- [ ] Secret redaction tested for new file formats

## Project Overview

MU (Machine Understanding) is a semantic compression tool that translates codebases into token-efficient representations optimized for LLM comprehension. Achieves 92-98% compression while preserving semantic signal.

### Pipeline Flow

```
Source Files -> Scanner -> Parser -> Reducer -> Assembler -> Exporter
                  |           |          |          |
              manifest    ModuleDef  Reduced   ModuleGraph -> MU/JSON/MD
```

## Essential Commands

```bash
# Development
pip install -e ".[dev]"    # Install with dev dependencies
pytest                      # Run all tests
pytest -v -k "test_name"   # Run specific test
mypy src/mu                # Type checking
ruff check src/            # Linting
ruff format src/           # Format code

# CLI usage
mu scan <path>              # Analyze codebase structure
mu compress <path>          # Generate MU output
mu compress <path> --llm    # With LLM summarization
mu view <file.mu>           # Render with syntax highlighting
mu diff <base> <head>       # Semantic diff between git refs
mu cache stats              # Cache statistics
mu query <muql>             # Execute MUQL query (alias: mu q)
mu describe                 # CLI self-description for AI agents
```

## Core Modules Reference

| Module | Purpose | CLAUDE.md |
|--------|---------|-----------|
| `parser/` | Tree-sitter AST extraction (7 languages) | Yes |
| `llm/` | Multi-provider async pool | Yes |
| `assembler/` | Import resolution, dependency graph | Yes |
| `reducer/` | Transformation rules, boilerplate stripping | Yes |
| `diff/` | Semantic diff between git refs | Yes |
| `security/` | Secret detection and redaction | Yes |
| `scanner/` | Filesystem walking, language detection | No |
| `cache/` | Persistent file/LLM caching | No |
| `viewer/` | MU format rendering | No |
| `client.py` | Daemon client module (httpx-based) | No |
| `describe.py` | CLI introspection for AI agents | No |
| `cli.py` | Click-based CLI orchestration | No |

## Key Data Models

- **`ModuleDef`** (`parser/models.py`): File-level AST with imports, classes, functions
- **`ReducedModule`** (`reducer/generator.py`): Post-transformation with `needs_llm` markers
- **`ModuleGraph`** (`assembler/__init__.py`): Dependency graph with resolved imports
- **`DiffResult`** (`diff/models.py`): Semantic changes between versions

## Critical Patterns

### Return Types
All functions that can fail should return explicit types, not raise exceptions for expected failures:
```python
# Good
def parse_file(path: Path) -> ParsedFile:
    result = ParsedFile(path=str(path), language=lang)
    if error:
        result.error = str(error)
    return result

# Avoid
def parse_file(path: Path) -> ModuleDef:
    raise ParseError("...")  # Only for unexpected failures
```

### Data Model Serialization
All data models must implement `to_dict()` for JSON serialization:
```python
@dataclass
class MyModel:
    name: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name}
```

### Language-Agnostic Design
Parser extractors convert language-specific AST to common `ModuleDef` structure. Never expose Tree-sitter node types outside extractors.

## Anti-Patterns

1. **Never** import Tree-sitter types outside `parser/` module
2. **Never** make synchronous LLM calls - always use `LLMPool.summarize_batch()`
3. **Never** hardcode stdlib lists - use `assembler/` constants
4. **Never** parse secrets manually - use `SecretScanner`
5. **Never** assume file encoding - always handle decode errors

## Configuration Resolution Order

1. CLI flags (highest priority)
2. `.murc.toml` in current directory
3. `.murc.toml` in home directory
4. Environment variables (`MU_*` prefix)
5. Built-in defaults (lowest priority)

## MU Output Format

Sigil-based syntax for LLM consumption:
- `!` Module/Service
- `$` Entity/Class (with `<` for inheritance)
- `#` Function/Method
- `@` Metadata/Dependencies
- `::` Annotations
- `->` Return type, `=>` State mutation

## Local Overrides

Create `.claude/CLAUDE.local.md` for personal customizations (gitignored).
