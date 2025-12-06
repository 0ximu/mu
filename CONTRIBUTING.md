# Contributing to MU

Thanks for your interest in contributing to MU! This document provides guidelines for contributing.

## Development Setup

### Prerequisites
- Python 3.11+
- Git

### Setup

```bash
# Clone the repository
git clone https://github.com/dominaite/mu.git
cd mu

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install with dev dependencies
pip install -e ".[dev]"

# Verify setup
pytest
mu --version
```

## Project Structure

```
mu/
├── src/mu/
│   ├── cli.py              # CLI entry point (Click) - 823 lines
│   ├── config.py           # Configuration models (Pydantic)
│   ├── errors.py           # Error handling framework
│   ├── logging.py          # Rich-based logging
│   ├── scanner/            # Filesystem scanning & language detection
│   ├── parser/             # Tree-sitter AST extraction
│   │   ├── base.py         # Parser infrastructure & language routing
│   │   ├── models.py       # AST data models (ModuleDef, ClassDef, etc.)
│   │   ├── python_extractor.py
│   │   ├── typescript_extractor.py
│   │   ├── csharp_extractor.py
│   │   ├── go_extractor.py
│   │   ├── rust_extractor.py
│   │   └── java_extractor.py
│   ├── reducer/            # Transformation rules
│   │   ├── rules.py        # What to strip/keep
│   │   └── generator.py    # MU format output
│   ├── assembler/          # Cross-file import resolution
│   │   ├── __init__.py     # ImportResolver, ModuleGraph, Assembler
│   │   └── exporters.py    # JSON, Markdown, MU format export
│   ├── llm/                # LLM integration
│   │   ├── pool.py         # Async multi-provider LLM pool
│   │   ├── types.py        # Request/response types
│   │   ├── prompts.py      # Prompt templates
│   │   ├── cost.py         # Token/cost estimation
│   │   └── providers.py    # Provider configuration
│   ├── cache/              # Persistent caching
│   │   └── __init__.py     # CacheManager with diskcache
│   ├── security/           # Secret detection & redaction
│   │   └── __init__.py     # SecretScanner, patterns
│   ├── diff/               # Semantic diff
│   │   ├── models.py       # FunctionDiff, ClassDiff, ModuleDiff
│   │   ├── differ.py       # SemanticDiffer
│   │   ├── git_utils.py    # GitWorktreeManager
│   │   └── formatters.py   # Terminal, JSON, Markdown output
│   └── viewer/             # MU format rendering
│       └── __init__.py     # Tokenizer, TerminalRenderer, HTMLRenderer
├── tests/
│   ├── unit/               # 4,700+ lines of tests
│   │   ├── test_parser.py  # Multi-language parser tests
│   │   ├── test_assembler.py
│   │   ├── test_security.py
│   │   ├── test_diff.py
│   │   ├── test_llm.py
│   │   └── ...
│   └── integration/
├── tools/
│   ├── vscode-mu/          # VS Code extension
│   └── action-mu/          # GitHub Action
├── docs/
│   ├── MU-TECH-SPEC.md     # Technical specification
│   └── MU-Claude-Code-Kickoff.md
├── examples/
│   └── sample-output.mu
├── pyproject.toml
└── README.md
```

## Making Changes

### 1. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/bug-description
```

### 2. Make Your Changes

Follow existing code patterns:
- Use type hints
- Follow the existing module structure
- Keep functions focused and small

### 3. Write Tests

All new features should have tests:

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/unit/test_parser.py -v

# Run with coverage
pytest --cov=src/mu
```

### 4. Check Code Quality

```bash
# Type checking
mypy src/mu

# Linting
ruff check src/

# Format (if needed)
ruff format src/
```

### 5. Commit

Write clear commit messages:
```
Add Go language support to parser

- Implement GoExtractor using tree-sitter-go
- Add tests for Go parsing
- Update supported languages in README
```

### 6. Open a Pull Request

- Describe what your PR does
- Link any related issues
- Include test results

## Adding a New Language

To add support for a new programming language:

### 1. Install the Tree-sitter Grammar

Add to `pyproject.toml`:
```toml
dependencies = [
    # ... existing deps
    "tree-sitter-go>=0.21.0",
]
```

### 2. Create the Extractor

Create `src/mu/parser/{language}_extractor.py`:

```python
"""Go-specific AST extractor using Tree-sitter."""

from pathlib import Path
from tree_sitter import Node

from mu.parser.models import (
    ClassDef,  # Use for structs/interfaces
    FunctionDef,
    ImportDef,
    ModuleDef,
)
from mu.parser.base import (
    count_nodes,
    get_node_text,
    find_child_by_type,
)


class GoExtractor:
    """Extract AST information from Go source files."""

    def extract(self, root: Node, source: bytes, file_path: str) -> ModuleDef:
        """Extract module definition from Go AST."""
        # Implement extraction logic
        pass
```

### 3. Register in Base Parser

Update `src/mu/parser/base.py`:

```python
def _get_language(lang: str) -> Language:
    # ... existing languages
    elif lang == "go":
        import tree_sitter_go as tsgo
        _languages[lang] = Language(tsgo.language())

def _get_extractor(lang: str) -> LanguageExtractor:
    # ... existing extractors
    elif lang == "go":
        from mu.parser.go_extractor import GoExtractor
        _extractors[lang] = GoExtractor()
```

### 4. Add Language Detection

Update `src/mu/scanner/__init__.py`:

```python
LANGUAGE_EXTENSIONS: dict[str, str] = {
    # ... existing
    ".go": "go",
}

SUPPORTED_LANGUAGES = {"python", "typescript", "javascript", "csharp", "go", "rust", "java"}
```

### 5. Add Tests

Create `tests/unit/test_parser_go.py` with tests for:
- Function parsing
- Struct/interface parsing
- Import parsing
- Method parsing

## Code Style

### Python Style

- Use type hints everywhere
- Prefer dataclasses for data structures
- Use `pathlib.Path` instead of string paths
- Follow PEP 8 (enforced by ruff)

### Documentation

- Add docstrings to public functions
- Update README if adding features
- Keep MU-TECH-SPEC.md in sync with implementation

### Testing

- Unit tests for individual functions
- Integration tests for full pipelines
- Use pytest fixtures for common setup
- Property-based tests for parsers (hypothesis)

## Architecture Decisions

### Why Tree-sitter?

- Language-agnostic parsing
- Excellent error recovery
- Active community with many grammars
- Incremental parsing support (future use)

### Why Sigil-based Output?

- Minimal syntax overhead
- Easy for LLMs to parse
- Scannable by humans
- Language-agnostic representation

### Why Pydantic for Config?

- Type validation out of the box
- Environment variable support
- Clear error messages
- Easy TOML integration

## Getting Help

- **Questions:** Open a GitHub Discussion
- **Bugs:** Open a GitHub Issue
- **Features:** Open an Issue to discuss first

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
