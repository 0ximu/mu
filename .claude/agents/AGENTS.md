# MU Agent Coordination Hub

This document provides comprehensive guidance for AI agents working on MU (Machine Understanding).

## Communication Rules

- No unnecessary summaries unless requested
- Direct, actionable feedback
- Reference specific file paths and line numbers

## Core Commands

```bash
# Build & Test
pip install -e ".[dev]"           # Install with dev dependencies
pytest                             # Run all tests
pytest -v -k "test_name"          # Run specific test
mypy src/mu                       # Type checking
ruff check src/                   # Linting
ruff format src/                  # Format code

# CLI Usage
mu scan <path>                    # Analyze structure
mu compress <path>                # Generate MU output
mu compress <path> --llm          # With LLM summarization
mu diff <base> <head>             # Semantic diff
```

## Architecture Overview

### Technology Stack
- Python 3.11+
- Tree-sitter (AST parsing)
- LiteLLM (multi-provider LLM)
- Click (CLI)
- pytest + pytest-cov (testing)

### Pipeline Architecture
```
Source Files -> Scanner -> Parser -> Reducer -> Assembler -> Exporter
                  |           |          |          |
              manifest    ModuleDef  Reduced   ModuleGraph -> MU/JSON/MD
```

### Core Modules
| Module | Purpose |
|--------|---------|
| `parser/` | Tree-sitter AST extraction (7 languages) |
| `llm/` | Multi-provider async pool via LiteLLM |
| `assembler/` | Import resolution, dependency graph |
| `reducer/` | Transformation rules, boilerplate stripping |
| `diff/` | Semantic diff between git refs |
| `security/` | Secret detection and redaction |
| `scanner/` | Filesystem walking, language detection |
| `cache/` | Persistent file/LLM caching |

## Development Patterns

### Data Models
All data models use dataclasses with `to_dict()` serialization:
```python
@dataclass
class MyModel:
    name: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name}
```

### Return Types
Return explicit types, not exceptions for expected failures:
```python
# Good
def parse_file(path: Path) -> ParsedFile:
    result = ParsedFile(path=str(path), language=lang)
    if error:
        result.error = str(error)
    return result
```

### Language Extractors
Implement `LanguageExtractor` protocol for new parsers:
```python
class MyExtractor:
    def extract(self, tree: Tree, source: bytes) -> ModuleDef:
        ...
```

### LLM Integration
Always use async batch operations:
```python
# Good
results = await llm_pool.summarize_batch(items)

# Never
result = llm.summarize(item)  # synchronous
```

## Security Rules

1. **Secret Detection**: Use `SecretScanner` for all secret patterns
2. **No Hardcoded Secrets**: Never hardcode API keys or credentials
3. **Encoding Safety**: Always handle decode errors gracefully
4. **Tree-sitter Isolation**: Never expose Tree-sitter types outside `parser/`

## Quality Requirements

### Testing
- pytest for all tests
- pytest-cov for coverage
- New code requires corresponding tests

### Pre-PR Checklist
- `ruff check src/` passes
- `ruff format src/` applied
- `mypy src/mu` passes
- `pytest` passes all tests
- No circular imports
- Documentation updated (if applicable)
- ADR created (for architectural decisions)

## Agent Workflow

```
/plan -> /code -> /test -> /review -> /docs -> /ship
   |        |        |         |         |        |
Planner  Coder   Tester   Reviewer    Docs    Ship
   |                                              |
   └── Creates feature branch from dev            └── Draft PR → dev
```

## Branch Strategy

| Branch | Purpose |
|--------|---------|
| `dev` | Default branch, all PRs target here |
| `feature/*` | Feature development (created by planner) |
| `fix/*` | Bug fixes |
| `main` | Production releases only (protected) |

## Agent Responsibilities

| Agent | Role | Focus |
|-------|------|-------|
| Planner | Business Discovery | Pattern analysis, task breakdown, branch creation |
| Coder | Implementation | Following patterns, quality code, doc updates |
| Tester | QA Engineer | Test coverage, edge cases |
| Reviewer | Code Review | Security, performance, architecture, draft PR |
| Docs | Documentation | ADRs, API docs, guides |
| Ship | Deployment | Commit, push, PR comment |

## Documentation Requirements

Documentation MUST be updated when:
- Adding new CLI commands → `docs/api/cli.md`
- Adding new Python APIs → `docs/api/python.md`
- Making architectural decisions → Create ADR in `docs/adr/`
- Security-related changes → Update `docs/security/`
- Configuration changes → `docs/guides/configuration.md`
- Breaking changes → CHANGELOG + migration guide

### Documentation Structure

```
docs/
├── adr/              # Architecture Decision Records
├── security/         # Security policy, threat model
├── api/              # CLI and Python API reference
├── guides/           # User and developer guides
└── assets/           # Images, diagrams
```

## Anti-Patterns

1. **Never** import Tree-sitter types outside `parser/` module
2. **Never** make synchronous LLM calls
3. **Never** hardcode stdlib lists - use `assembler/` constants
4. **Never** parse secrets manually - use `SecretScanner`
5. **Never** assume file encoding - always handle decode errors

## Documentation References

### Internal (CLAUDE.md files)
- `CLAUDE.md` - Root project instructions
- `src/mu/parser/CLAUDE.md` - Parser subsystem
- `src/mu/llm/CLAUDE.md` - LLM integration
- `src/mu/assembler/CLAUDE.md` - Import resolution
- `src/mu/reducer/CLAUDE.md` - Transformation rules
- `src/mu/diff/CLAUDE.md` - Semantic diff
- `src/mu/security/CLAUDE.md` - Secret detection
- `tests/CLAUDE.md` - Testing standards

### Official Documentation (docs/)
- `docs/README.md` - Documentation overview
- `docs/adr/` - Architecture Decision Records
- `docs/security/` - Security policy and threat model
- `docs/api/cli.md` - CLI reference
- `docs/api/python.md` - Python API reference
- `docs/guides/` - User and developer guides
