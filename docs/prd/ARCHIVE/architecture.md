---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
inputDocuments: ['agent-feedback-analysis (inline)']
workflowType: 'architecture'
lastStep: 8
status: 'complete'
completedAt: '2025-12-06'
project_name: 'MU Agent-Proofing'
user_name: 'imu'
date: '2025-12-06'
---

# Architecture Decision Document

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

## Project Context Analysis

### Requirements Overview

**Functional Requirements:**

| ID | Requirement | Description |
|----|-------------|-------------|
| **FR-1** | Single Binary Distribution | Package MU as standalone executable (no pip/venv required) |
| **FR-2** | Thin Client Architecture | CLI delegates to daemon when running, prevents DuckDB lock conflicts |
| **FR-3** | Clean API Responses | Return proper JSON objects, not double-serialized strings |
| **FR-4** | Promote `mu query` | Top-level command alias for MUQL queries |
| **FR-5** | Self-Description | `mu describe` outputs MU representation of CLI interface |

**Non-Functional Requirements:**

| NFR | Description | Priority |
|-----|-------------|----------|
| Agent Usability | Zero-friction for AI agents | Critical |
| Concurrency Safety | No database corruption from concurrent access | Critical |
| API Hygiene | Machine-parseable responses without post-processing | High |
| Self-Documentation | Tool explains its own interface | Medium |

### Scale & Complexity

- **Complexity Level:** Medium (enhancement to stable system)
- **Primary Domain:** CLI + Daemon + Graph Database
- **Files Affected:** ~8-10 files across 5 fixes
- **Architectural Impact:** Moderate - no fundamental redesign needed

### Technical Constraints & Dependencies

**Existing:**
- DuckDB file-level locking (single writer)
- FastAPI daemon process model
- Click CLI framework
- Python 3.10+ runtime

**New:**
- PyInstaller/Nuitka bundling compatibility
- Daemon detection protocol (localhost ping)
- Consistent response serialization policy

### Cross-Cutting Concerns Identified

1. **Daemon Awareness** - CLI must check daemon status before database operations
2. **Serialization Consistency** - All endpoints return objects, not strings
3. **Self-Description Protocol** - CLI structure must support introspection
4. **Binary Bundling** - All imports must be statically analyzable

## Technical Foundation Assessment

### Existing Stack (Retained)

This is an enhancement to a mature, working system. The following technical decisions are already established and will be retained:

| Layer | Technology | Status |
|-------|------------|--------|
| **Language** | Python 3.10+ with type hints | Retained |
| **CLI Framework** | Click with MUContext | Retained |
| **API Server** | FastAPI + Pydantic | Retained |
| **Database** | DuckDB (graph storage) | Retained |
| **Linting** | ruff (check + format) | Retained |
| **Type Checking** | mypy | Retained |
| **Testing** | pytest | Retained |
| **Package** | pyproject.toml (setuptools) | Retained |

### New Tooling Decisions Required

The following tooling decisions must be made to support the agent-proofing requirements:

**Binary Packaging (FR-1):**
- PyInstaller - Most mature, widest compatibility
- Nuitka - Compiles to C, best performance
- Shiv - Zipapp approach, simpler but requires Python

**HTTP Client for Daemon Communication (FR-2):**
- httpx - Async-native, modern API, already in ecosystem
- requests - Simple, synchronous, well-known

**Self-Description Format (FR-5):**
- MU format - Dogfooding, optimal for LLM consumption
- JSON Schema - Standard, tooling support
- Custom introspection - Click command tree inspection

## Core Architectural Decisions

### Decision Priority Analysis

**Critical Decisions (Block Implementation):**
1. ADR-001: Binary Packaging Tool
2. ADR-002: Daemon Communication Pattern
3. ADR-003: API Response Serialization Fix

**Important Decisions (Shape Architecture):**
4. ADR-004: Command Alias Strategy
5. ADR-005: Self-Description Format

**Deferred Decisions (Post-MVP):**
- Cross-platform binary signing
- Auto-update mechanism
- Telemetry/analytics integration

---

### ADR-001: Binary Packaging Tool

**Decision:** PyInstaller

**Status:** Accepted

**Context:** MU needs to be distributed as a standalone binary that agents can execute without pip, venv, or Python environment setup.

**Options Considered:**
| Option | Pros | Cons |
|--------|------|------|
| PyInstaller | Most mature, widest OS support, one-file mode | Larger binary (~50-100MB) |
| Nuitka | Best performance, smaller size | Complex build, longer compile |
| Shiv | Simple, fast build | Requires Python on target |

**Decision Rationale:** PyInstaller is "boring technology that works." It has the widest compatibility, most documentation, and handles edge cases well. Binary size is acceptable for a developer tool.

**Consequences:**
- Add PyInstaller to dev dependencies
- Create `.spec` file for build configuration
- CI/CD builds binaries for linux/mac/windows
- Tree-sitter native extensions must be bundled correctly

---

### ADR-002: Daemon Communication Pattern

**Decision:** HTTP Ping + httpx client

**Status:** Accepted

**Context:** CLI must detect if daemon is running and forward commands to avoid DuckDB lock conflicts.

**Options Considered:**
| Option | Description | Tradeoff |
|--------|-------------|----------|
| HTTP Ping + Forward | Ping `/status`, forward if alive | Reuses existing endpoints |
| Unix Socket | Socket file IPC | Faster but platform-specific |
| Lock File Check | PID file detection | Race conditions possible |

**Decision Rationale:** HTTP approach reuses existing FastAPI infrastructure. httpx chosen over requests for async compatibility and modern API design.

**Implementation Pattern:**
```python
def is_daemon_running() -> bool:
    try:
        response = httpx.get("http://localhost:8765/status", timeout=0.5)
        return response.status_code == 200
    except httpx.ConnectError:
        return False

def execute_query(muql: str) -> dict:
    if is_daemon_running():
        return httpx.post("http://localhost:8765/query", json={"muql": muql}).json()
    else:
        # Ephemeral local execution
        return local_query(muql)
```

**Consequences:**
- Add httpx to dependencies
- Create `src/mu/client.py` module for daemon communication
- CLI commands check daemon status before database operations
- Graceful fallback to local execution when daemon not running

---

### ADR-003: API Response Serialization Fix

**Decision:** Return native dicts from engine, let FastAPI serialize

**Status:** Accepted

**Context:** `/query` endpoint returns double-serialized JSON (`"{\"columns\":...}"` inside JSON response).

**Root Cause:** `engine.query(muql, "json")` returns JSON string, Pydantic wraps string, FastAPI re-serializes.

**Options Considered:**
| Option | Change |
|--------|--------|
| A: Return dict | Engine returns dict, FastAPI serializes once |
| B: Parse before wrap | `json.loads()` before Pydantic model |
| C: Change model type | Explicit `result: dict[str, Any]` |

**Decision Rationale:** Option A provides clean separation of concerns. Engine handles data transformation, FastAPI handles HTTP serialization. Single responsibility principle.

**Implementation:**
```python
# Before (daemon/server.py)
result = engine.query(request.muql, "json")  # Returns string
return QueryResponse(result=result)  # Double-encoded

# After
result = engine.query(request.muql, "dict")  # Returns dict
return QueryResponse(result=result)  # Single serialization
```

**Consequences:**
- Modify `MUQLEngine.query()` to support `"dict"` format
- Update `/query` endpoint to use dict format
- Review all API endpoints for similar issues
- Add response format tests

---

### ADR-004: Command Alias Strategy

**Decision:** Multi-level aliases - `mu q`, `mu query`, and `mu kernel muql` all work

**Status:** Accepted

**Context:** Agents struggle to discover that MUQL queries require `mu kernel muql`. Need simpler paths with progressive disclosure.

**Options Considered:**
| Option | Approach |
|--------|----------|
| A: Direct Alias | Both commands call same handler |
| B: Redirect | Thin wrapper invokes nested command |
| C: Deprecate | Move to top-level, deprecate nested |

**Decision Rationale:** Direct aliases preserve backward compatibility while providing ergonomic shortcuts. Following CLI conventions (`git st`, `kubectl get`), short aliases reduce friction for power users and agents alike.

**Alias Hierarchy:**
| Command | Use Case |
|---------|----------|
| `mu q "SELECT..."` | Power users, agents, scripts |
| `mu query "SELECT..."` | Discoverable, self-documenting |
| `mu kernel muql "SELECT..."` | Backward compatibility, explicit |

**Implementation:**
```python
def _execute_muql(ctx, muql: str):
    """Shared MUQL execution logic"""
    # Implementation here

@cli.command("query")
@click.argument("muql")
@click.pass_context
def query_cmd(ctx, muql: str):
    """Execute MUQL query"""
    _execute_muql(ctx, muql)

@cli.command("q")
@click.argument("muql")
@click.pass_context
def q_cmd(ctx, muql: str):
    """Execute MUQL query (short alias)"""
    _execute_muql(ctx, muql)
```

**Consequences:**
- Add `query` and `q` commands to top-level CLI group
- Share implementation via helper function
- Update help text to show all paths
- Documentation shows `mu query` as primary, mentions `mu q` shortcut

---

### ADR-005: Self-Description Format

**Decision:** MU format as default, with `--format` flag for alternatives

**Status:** Accepted

**Context:** Agents need to understand MU's interface without reading source code. `mu describe` should output machine-readable interface specification.

**Options Considered:**
| Option | Best For |
|--------|----------|
| MU Format | LLM consumption (dogfooding) |
| JSON Schema | Tooling integration |
| Markdown | Human users |
| All Three | Maximum flexibility |

**Decision Rationale:** Dogfooding MU format demonstrates the tool's value. Flag provides flexibility for different consumers.

**Implementation:**
```bash
mu describe                    # Default: MU format
mu describe --format json      # JSON Schema
mu describe --format markdown  # Human-readable
```

**Output Structure (MU format):**
```
!mu-cli "MU Command Line Interface"
  @version: "0.1.0"

  #compress(path, --llm, --output) -> str
    :: "Generate MU output from source files"

  #query(muql) -> dict
    :: "Execute MUQL query"
    => Returns query results as JSON object

  #daemon.start(path, --port) -> None
    :: "Start background daemon"
```

**Consequences:**
- Create `src/mu/describe.py` module
- Introspect Click command tree
- Generate MU representation of CLI interface
- Add `describe` command to CLI

---

### Decision Impact Analysis

**Implementation Sequence:**
1. **FR-3** (API fix) - Quick win, unblocks clean agent interactions
2. **FR-2** (Thin client) - Fixes DuckDB locks, critical stability
3. **FR-4** (Query alias) - Low effort, immediate UX improvement
4. **FR-5** (Self-description) - Medium effort, high agent value
5. **FR-1** (Binary packaging) - High effort, do last when stable

**Cross-Component Dependencies:**
```
FR-3 (API fix) ──────────────────────────────┐
                                              │
FR-2 (Thin client) ──── uses httpx ──────────┼──► FR-1 (Binary)
                                              │    requires all
FR-4 (Query alias) ──────────────────────────┤    stable first
                                              │
FR-5 (Self-describe) ────────────────────────┘
```

## Implementation Patterns & Consistency Rules

These patterns ensure all AI agents write compatible, consistent code that integrates seamlessly with the existing MU codebase.

### Critical Conflict Points Identified

**8 areas** where AI agents could make different choices:
1. Naming conventions (functions, classes, files)
2. Test organization and naming
3. API response structure
4. Error handling approach
5. Data model serialization
6. Type hint syntax
7. Import organization
8. Async patterns

---

### Naming Patterns

#### Python Code Naming (THE MU WAY)

| Element | Convention | Example |
|---------|------------|---------|
| Functions/Methods | `snake_case` | `parse_file()`, `get_dependencies()` |
| Private methods | `_snake_case` | `_extract_import()`, `_reduce_class()` |
| Classes | `PascalCase` | `ModuleDef`, `LLMPool`, `SemanticDiffer` |
| Variables | `snake_case` | `module_count`, `total_lines` |
| Booleans | `is_` or `has_` prefix | `is_async`, `has_signature_change` |
| Collections | Plural nouns | `functions`, `classes`, `nodes` |
| Constants | `UPPER_SNAKE_CASE` | `PYTHON_STDLIB`, `DEFAULT_RULES` |
| Files | `snake_case.py` | `python_extractor.py`, `test_parser.py` |

#### API Field Naming

- **Always** `snake_case` in JSON responses (via Pydantic)
- Examples: `mubase_path`, `uptime_seconds`, `max_tokens`

---

### Structure Patterns

#### Test Organization

```
tests/
└── unit/
    ├── test_parser.py      # mirrors src/mu/parser.py
    ├── test_reducer.py     # mirrors src/mu/reducer.py
    └── test_assembler.py   # mirrors src/mu/assembler.py
```

#### Test Naming Convention

- **File:** `test_{module}.py`
- **Class:** `class Test{Feature}:`
- **Method:** `test_{behavior}_{scenario}()`

#### Module Exports

```python
# Always use __all__ to control public API
__all__ = ["ModuleDef", "FunctionDef", "ClassDef"]
```

---

### Format Patterns

#### Data Model Pattern (MANDATORY)

```python
@dataclass
class MyModel:
    name: str
    items: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "items": self.items,
        }
```

#### Type Hint Syntax (Python 3.10+)

```python
# CORRECT - The MU Way
def process(data: str | None) -> dict[str, Any]:
    items: list[str] = []

# WRONG - Do not use
def process(data: Optional[str]) -> Dict[str, Any]:
    items: List[str] = []
```

#### API Response Pattern

```python
class QueryResponse(BaseModel):
    result: dict[str, Any] = Field(description="Query results")
    success: bool = Field(description="Whether query succeeded")
    error: str | None = Field(default=None, description="Error message if failed")
```

---

### Error Handling Patterns

#### Error Class Hierarchy

```python
class MUError(Exception):
    exit_code: ExitCode
    context: dict[str, Any]

    def to_dict(self) -> dict[str, Any]: ...
```

#### Expected vs Unexpected Failures

```python
# CORRECT - Expected failures set error field
def parse_file(path: Path) -> ParsedFile:
    result = ParsedFile(path=str(path))
    if error_occurred:
        result.error = str(error)  # Don't raise
    return result

# WRONG - Don't raise for expected failures
def parse_file(path: Path) -> ParsedFile:
    if error_occurred:
        raise ParseError("...")  # Only for unexpected
```

---

### Process Patterns

#### Async Code

- Use `asyncio` with semaphore-based concurrency
- **Never** make synchronous LLM calls
- Mark async tests with `@pytest.mark.asyncio`

#### Logging

```python
logger = logging.getLogger(__name__)

# Use mu.logging helpers for CLI output
print_error(), print_success(), print_warning(), print_info()
```

#### CLI Exit Codes

```python
class ExitCode(IntEnum):
    SUCCESS = 0
    CONFIG_ERROR = 1
    PARTIAL_SUCCESS = 2
    FATAL_ERROR = 3
    GIT_ERROR = 4
    CONTRACT_VIOLATION = 5
```

---

### Enforcement Guidelines

#### All AI Agents MUST

1. ✅ Use `snake_case` for all functions, methods, and variables
2. ✅ Implement `to_dict() -> dict[str, Any]` on all data models
3. ✅ Use `X | None` syntax, never `Optional[X]`
4. ✅ Return error info in result objects, don't raise for expected failures
5. ✅ Use absolute imports from `mu.` prefix
6. ✅ Place tests in `tests/unit/test_{module}.py`
7. ✅ Add `Field(description="...")` to all Pydantic model fields

#### Anti-Patterns (FORBIDDEN)

1. ❌ Exposing Tree-sitter types outside parser module
2. ❌ Synchronous LLM calls
3. ❌ Hardcoding stdlib lists (use assembler constants)
4. ❌ Manual secret parsing (use `SecretScanner`)
5. ❌ Relative imports between modules
6. ❌ Assuming file encoding (use `errors="replace"`)
7. ❌ Using `Optional[X]` or `Union[X, Y]` syntax

---

### Pattern Examples

#### Good Example - New Command Module

```python
"""New CLI command following MU patterns."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import click

from mu.cli import MUContext, pass_context
from mu.logging import print_error, print_success


@dataclass
class DescribeResult:
    """Result of describe operation."""

    commands: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {"commands": self.commands}
        if self.error:
            result["error"] = self.error
        return result


@click.command("describe")
@click.option("--format", type=click.Choice(["mu", "json", "markdown"]), default="mu")
@pass_context
def describe_cmd(ctx: MUContext, format: str) -> None:
    """Output MU representation of CLI interface."""
    result = _generate_description(ctx, format)
    if result.error:
        print_error(result.error)
        raise SystemExit(1)
    print_success(result.to_dict())
```

#### Anti-Pattern Example (DO NOT DO)

```python
# WRONG: Multiple violations
from typing import Optional, Dict, List  # Wrong type syntax
from .utils import helper  # Relative import

def GetUserData(userId: str) -> Optional[Dict]:  # Wrong naming
    try:
        return fetch_user(userId)
    except Exception as e:
        raise UserError(str(e))  # Raising for expected failure
```

## Project Structure & Boundaries

This section defines the complete project structure for the agent-proofing enhancements, including new files to create and existing files to modify.

### Requirements to Structure Mapping

| Requirement | Action | Files |
|-------------|--------|-------|
| **FR-1** Binary Packaging | NEW | `mu.spec`, `.github/workflows/build-binary.yml` |
| **FR-2** Thin Client | NEW | `src/mu/client.py`, `tests/unit/test_client.py` |
| **FR-3** API Fix | MODIFY | `src/mu/daemon/server.py`, `src/mu/kernel/muql/engine.py` |
| **FR-4** Query Aliases | MODIFY | `src/mu/cli.py` |
| **FR-5** Self-Description | NEW | `src/mu/describe.py`, `tests/unit/test_describe.py` |

---

### New Files to Create

#### `src/mu/client.py` - Daemon Communication Client (FR-2)

```python
"""Daemon communication client for CLI-to-daemon forwarding."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

__all__ = ["DaemonClient", "is_daemon_running", "forward_query"]

DEFAULT_DAEMON_URL = "http://localhost:8765"
DEFAULT_TIMEOUT = 0.5


@dataclass
class DaemonClient:
    """Client for communicating with MU daemon."""

    base_url: str = DEFAULT_DAEMON_URL
    timeout: float = DEFAULT_TIMEOUT

    def is_running(self) -> bool: ...
    def query(self, muql: str) -> dict[str, Any]: ...
    def status(self) -> dict[str, Any]: ...


def is_daemon_running(url: str = DEFAULT_DAEMON_URL) -> bool: ...
def forward_query(muql: str, url: str = DEFAULT_DAEMON_URL) -> dict[str, Any]: ...
```

#### `src/mu/describe.py` - CLI Self-Description (FR-5)

```python
"""CLI self-description module for agent consumption."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["DescribeResult", "describe_cli", "format_mu", "format_json", "format_markdown"]


@dataclass
class CommandInfo:
    """Information about a CLI command."""

    name: str
    description: str
    arguments: list[str] = field(default_factory=list)
    options: list[dict[str, Any]] = field(default_factory=list)
    subcommands: list[CommandInfo] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]: ...


@dataclass
class DescribeResult:
    """Result of CLI description."""

    version: str
    commands: list[CommandInfo] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]: ...


def describe_cli() -> DescribeResult: ...
def format_mu(result: DescribeResult) -> str: ...
def format_json(result: DescribeResult) -> str: ...
def format_markdown(result: DescribeResult) -> str: ...
```

#### `mu.spec` - PyInstaller Configuration (FR-1)

```python
# PyInstaller spec file for MU binary distribution
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['src/mu/cli.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Include tree-sitter language files
        ('src/mu/parser/languages', 'mu/parser/languages'),
    ],
    hiddenimports=[
        'mu.parser.extractors',
        'tree_sitter',
        'tree_sitter_python',
        'tree_sitter_javascript',
        'tree_sitter_typescript',
        'tree_sitter_go',
        'tree_sitter_java',
        'tree_sitter_rust',
        'tree_sitter_c_sharp',
    ],
    # ... rest of spec
)
```

#### `.github/workflows/build-binary.yml` - Binary Build Workflow (FR-1)

```yaml
name: Build Binaries

on:
  release:
    types: [created]
  workflow_dispatch:

jobs:
  build:
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install pyinstaller
      - run: pip install -e ".[dev]"
      - run: pyinstaller mu.spec
      - uses: actions/upload-artifact@v4
        with:
          name: mu-${{ matrix.os }}
          path: dist/mu*
```

---

### Existing Files to Modify

#### `src/mu/daemon/server.py` - Fix Double-JSON (FR-3)

**Location:** Lines ~395-407 (execute_query endpoint)

**Change:**
```python
# Before
result = engine.query(request.muql, "json")
return QueryResponse(result=result)

# After
result = engine.query(request.muql, "dict")
return QueryResponse(result=result)
```

#### `src/mu/kernel/muql/engine.py` - Add Dict Format (FR-3)

**Change:** Add `"dict"` as valid format option in `query()` method

#### `src/mu/cli.py` - Add Command Aliases (FR-4, FR-5)

**Add:**
```python
@cli.command("query")
@click.argument("muql")
@pass_context
def query_cmd(ctx: MUContext, muql: str) -> None:
    """Execute MUQL query."""
    _execute_muql(ctx, muql)


@cli.command("q")
@click.argument("muql")
@pass_context
def q_cmd(ctx: MUContext, muql: str) -> None:
    """Execute MUQL query (short alias)."""
    _execute_muql(ctx, muql)


@cli.command("describe")
@click.option("--format", type=click.Choice(["mu", "json", "markdown"]), default="mu")
@pass_context
def describe_cmd(ctx: MUContext, format: str) -> None:
    """Output MU representation of CLI interface."""
    from mu.describe import describe_cli, format_mu, format_json, format_markdown
    # Implementation
```

#### `pyproject.toml` - Add Dependencies

**Add to dependencies:**
```toml
dependencies = [
    # ... existing
    "httpx>=0.25.0",
]

[project.optional-dependencies]
dev = [
    # ... existing
    "pyinstaller>=6.0.0",
]
```

---

### Complete Project Tree (Changes Only)

```
mu/
├── mu.spec                          # NEW - PyInstaller config
├── pyproject.toml                   # MODIFY - add httpx, pyinstaller
│
├── .github/
│   └── workflows/
│       └── build-binary.yml         # NEW - binary release workflow
│
├── src/mu/
│   ├── cli.py                       # MODIFY - add query/q/describe commands
│   ├── client.py                    # NEW - daemon client module
│   ├── describe.py                  # NEW - self-description module
│   │
│   ├── daemon/
│   │   └── server.py                # MODIFY - fix double-JSON
│   │
│   └── kernel/
│       └── muql/
│           └── engine.py            # MODIFY - add dict format
│
└── tests/unit/
    ├── test_client.py               # NEW - client tests
    └── test_describe.py             # NEW - describe tests
```

---

### Architectural Boundaries

#### Client-Daemon Communication Boundary

```
┌──────────────────────────────────────────────────────────────┐
│                         CLI Layer                             │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌──────────┐  │
│  │ mu q    │    │ mu query│    │ describe│    │ compress │  │
│  └────┬────┘    └────┬────┘    └────┬────┘    └────┬─────┘  │
│       │              │              │              │         │
│       └──────────────┴──────────────┴──────────────┘         │
│                              │                                │
│                              ▼                                │
│                      ┌─────────────┐                         │
│                      │  client.py  │  ◀── Daemon-aware       │
│                      └──────┬──────┘                         │
└─────────────────────────────┼────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              │                               │
              ▼                               ▼
     ┌─────────────────┐            ┌─────────────────┐
     │  Daemon Running │            │  No Daemon      │
     │  (HTTP forward) │            │  (Local exec)   │
     └────────┬────────┘            └────────┬────────┘
              │                               │
              ▼                               ▼
     ┌─────────────────┐            ┌─────────────────┐
     │  FastAPI Server │            │  Direct MUbase  │
     │  /query endpoint│            │  connection     │
     └─────────────────┘            └─────────────────┘
```

#### API Response Flow (Fixed)

```
Request: POST /query {"muql": "SELECT..."}
              │
              ▼
     ┌─────────────────┐
     │  MUQLEngine     │
     │  .query(muql,   │
     │   format="dict")│  ◀── Returns dict, not string
     └────────┬────────┘
              │
              ▼
     ┌─────────────────┐
     │  QueryResponse  │
     │  (Pydantic)     │  ◀── Wraps dict directly
     └────────┬────────┘
              │
              ▼
     ┌─────────────────┐
     │  FastAPI        │
     │  JSON serialize │  ◀── Single serialization
     └────────┬────────┘
              │
              ▼
Response: {"result": {"columns": [...], "rows": [...]}, "success": true}
```

---

### Integration Points

| From | To | Method | Purpose |
|------|-----|--------|---------|
| `cli.py` | `client.py` | Import | Daemon detection |
| `client.py` | `daemon/server.py` | HTTP (httpx) | Query forwarding |
| `cli.py` | `describe.py` | Import | CLI introspection |
| `describe.py` | Click | Introspection | Command tree extraction |
| CI workflow | PyInstaller | Build | Binary generation |

---

### Development Workflow

**Local Development:**
```bash
pip install -e ".[dev]"     # Install with dev deps
pytest                       # Run tests
mypy src/mu                 # Type check
ruff check src/             # Lint
```

**Binary Build (Local):**
```bash
pip install pyinstaller
pyinstaller mu.spec
./dist/mu --help            # Test binary
```

**CI/CD Binary Release:**
- Triggered on GitHub release creation
- Builds for Linux, macOS, Windows
- Uploads artifacts to release

## Architecture Validation Results

### Coherence Validation ✅

**Decision Compatibility:**

| Decision | Compatible With | Status |
|----------|----------------|--------|
| PyInstaller (ADR-001) | Python 3.10+, Click, FastAPI | ✅ Compatible |
| httpx (ADR-002) | FastAPI ecosystem, async patterns | ✅ Compatible |
| Dict returns (ADR-003) | Pydantic, FastAPI serialization | ✅ Compatible |
| Click aliases (ADR-004) | Existing CLI structure | ✅ Compatible |
| MU format describe (ADR-005) | Click introspection | ✅ Compatible |

**Pattern Consistency:**
- ✅ All naming conventions follow existing `snake_case` patterns
- ✅ New modules follow `to_dict()` serialization pattern
- ✅ Error handling follows "expected failures set error field" pattern
- ✅ Type hints use `X | None` syntax consistently

**Structure Alignment:**
- ✅ New files placed in correct locations (`src/mu/`)
- ✅ Tests mirror source structure (`tests/unit/test_*.py`)
- ✅ Integration points clearly defined

---

### Requirements Coverage Validation ✅

| Requirement | Architectural Support | Coverage |
|-------------|----------------------|----------|
| **FR-1** Single Binary | PyInstaller + mu.spec + CI workflow | ✅ Full |
| **FR-2** Thin Client | client.py + httpx + daemon detection | ✅ Full |
| **FR-3** Clean API | Dict returns from engine | ✅ Full |
| **FR-4** Query Aliases | `mu q` + `mu query` commands | ✅ Full |
| **FR-5** Self-Description | describe.py + MU format output | ✅ Full |

**Non-Functional Requirements:**

| NFR | How Addressed | Status |
|-----|--------------|--------|
| Agent Usability | All fixes target agent pain points | ✅ |
| Concurrency Safety | Daemon detection prevents lock conflicts | ✅ |
| API Hygiene | Single serialization, clean JSON | ✅ |
| Self-Documentation | `mu describe` command | ✅ |

---

### Implementation Readiness Validation ✅

**Decision Completeness:**
- ✅ All 5 ADRs documented with rationale
- ✅ Implementation patterns specified with code examples
- ✅ Technology versions specified (httpx ≥0.25.0, PyInstaller ≥6.0.0)

**Structure Completeness:**
- ✅ All new files defined with module structure
- ✅ All modifications specified with before/after
- ✅ Integration boundaries diagrammed

**Pattern Completeness:**
- ✅ 8 conflict points identified and addressed
- ✅ Good/bad examples provided
- ✅ Enforcement guidelines clear

---

### Gap Analysis Results

**Critical Gaps:** None found ✅

**Important Gaps (Addressed):**

| Gap | Resolution |
|-----|------------|
| PyInstaller hidden imports | Listed in mu.spec template |
| httpx timeout handling | Specified in ADR-002 pattern |
| Describe output formats | All three formats specified |

**Deferred (Post-MVP):**
- Cross-platform binary signing
- Auto-update mechanism
- Performance benchmarking

---

### Architecture Completeness Checklist

**✅ Requirements Analysis**
- [x] Project context thoroughly analyzed
- [x] Scale and complexity assessed (Medium)
- [x] Technical constraints identified (DuckDB locking, FastAPI)
- [x] Cross-cutting concerns mapped (4 identified)

**✅ Architectural Decisions**
- [x] 5 ADRs documented with versions
- [x] Technology stack fully specified
- [x] Integration patterns defined
- [x] Implementation sequence ordered

**✅ Implementation Patterns**
- [x] Naming conventions established (THE MU WAY)
- [x] Structure patterns defined
- [x] Error handling patterns documented
- [x] 7 enforcement rules + 7 anti-patterns

**✅ Project Structure**
- [x] Complete directory structure defined
- [x] Component boundaries established
- [x] Integration points mapped
- [x] Requirements to structure mapping complete

---

### Architecture Readiness Assessment

**Overall Status:** ✅ READY FOR IMPLEMENTATION

**Confidence Level:** HIGH

**Key Strengths:**
1. Pragmatic, incremental approach - no over-engineering
2. Reuses existing patterns and infrastructure
3. Clear implementation sequence with dependencies
4. Comprehensive patterns prevent agent conflicts
5. Quick wins (FR-3, FR-4) can ship immediately

**Areas for Future Enhancement:**
1. Binary signing for release downloads
2. Auto-update mechanism for deployed binaries
3. Telemetry for usage analytics (opt-in)

---

### Implementation Handoff

**AI Agent Guidelines:**
1. Follow all architectural decisions exactly as documented
2. Use implementation patterns consistently
3. Respect project structure and boundaries
4. Reference this document for all architectural questions

**Implementation Sequence:**

| Order | Requirement | Priority | Effort |
|-------|-------------|----------|--------|
| 1 | FR-3 (API fix) | Quick win | Low |
| 2 | FR-4 (Query aliases) | UX improvement | Low |
| 3 | FR-2 (Thin client) | Critical stability | Medium |
| 4 | FR-5 (Self-description) | Agent value | Medium |
| 5 | FR-1 (Binary packaging) | Final step | High |

**First Implementation Command:**
```bash
# Start with FR-3 - the quick win
# Files to modify:
#   - src/mu/daemon/server.py (line ~405)
#   - src/mu/kernel/muql/engine.py (add dict format)
# Tests to add:
#   - tests/unit/test_daemon_api.py
```

## Architecture Completion Summary

### Workflow Completion

**Architecture Decision Workflow:** COMPLETED ✅
**Total Steps Completed:** 8
**Date Completed:** 2025-12-06
**Document Location:** `docs/architecture.md`

---

### Final Architecture Deliverables

**Complete Architecture Document**
- 5 architectural decisions (ADRs) documented with specific versions
- Implementation patterns ensuring AI agent consistency ("THE MU WAY")
- Complete project structure with all new/modified files
- Requirements to architecture mapping
- Validation confirming coherence and completeness

**Implementation Ready Foundation**
- 5 architectural decisions made
- 8 conflict points addressed with patterns
- 7 enforcement rules + 7 anti-patterns defined
- 5 functional requirements fully supported

**AI Agent Implementation Guide**
- Technology stack with verified versions
- Consistency rules that prevent implementation conflicts
- Project structure with clear boundaries
- Integration patterns and communication standards

---

### Quality Assurance Checklist

**✅ Architecture Coherence**
- [x] All decisions work together without conflicts
- [x] Technology choices are compatible
- [x] Patterns support the architectural decisions
- [x] Structure aligns with all choices

**✅ Requirements Coverage**
- [x] All functional requirements are supported
- [x] All non-functional requirements are addressed
- [x] Cross-cutting concerns are handled
- [x] Integration points are defined

**✅ Implementation Readiness**
- [x] Decisions are specific and actionable
- [x] Patterns prevent agent conflicts
- [x] Structure is complete and unambiguous
- [x] Examples are provided for clarity

---

### Project Success Factors

**Clear Decision Framework**
Every technology choice was made collaboratively with clear rationale, ensuring all stakeholders understand the architectural direction.

**Consistency Guarantee**
Implementation patterns and rules ensure that multiple AI agents will produce compatible, consistent code that works together seamlessly.

**Complete Coverage**
All project requirements are architecturally supported, with clear mapping from business needs to technical implementation.

**Solid Foundation**
The existing MU codebase patterns were documented as "THE MU WAY" to ensure consistent enhancement.

---

**Architecture Status:** ✅ READY FOR IMPLEMENTATION

**Next Phase:** Begin implementation using the architectural decisions and patterns documented herein.

**Document Maintenance:** Update this architecture when major technical decisions are made during implementation.

