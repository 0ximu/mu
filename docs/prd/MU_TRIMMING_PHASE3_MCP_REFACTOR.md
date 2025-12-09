# MU Trimming Phase 3: MCP Server Refactor

**Status:** Draft
**Author:** Claude + imu
**Created:** 2025-12-09
**Depends on:** Phase 1 (Deletion), Phase 2 (Vibes CLI)
**Target:** Break down 3,514 LOC god component into focused modules

## Executive Summary

`src/mu/mcp/server.py` is a 3,514 LOC monolith containing 25+ MCP tools, all dataclasses, and all business logic inline. This phase breaks it into focused modules while reducing the tool count from 25 to 12.

## Goals

1. **Maintainability** - Each tool in its own module
2. **Testability** - Tools can be tested independently
3. **Readability** - ~200 LOC per file max
4. **Focus** - 12 high-value tools, not 25 mediocre ones

## Non-Goals

- Changing MCP protocol
- Adding new tools
- Changing tool signatures (yet)

---

## Current State Analysis

### File Size Breakdown

```
src/mu/mcp/server.py: 3,514 LOC

Breakdown (estimated):
- Imports & setup: ~100 LOC
- Dataclasses/Models: ~800 LOC (30+ models)
- Tool implementations: ~2,400 LOC (25 tools)
- Server setup: ~200 LOC
```

### Current Tools (25)

**Setup & Status:**
1. `mu_status` - Daemon/mubase status
2. `mu_bootstrap` - Initialize MU

**Graph Access:**
3. `mu_query` - MUQL execution
4. `mu_read` - Read node source
5. `mu_context` - Smart context
6. `mu_context_omega` - OMEGA context
7. `mu_deps` - Dependencies
8. `mu_impact` - Impact analysis
9. `mu_ancestors` - Upstream dependencies
10. `mu_cycles` - Circular dependencies

**Intelligence:**
11. `mu_patterns` - Pattern detection
12. `mu_generate` - Code generation (DELETE in Phase 1)
13. `mu_validate` - Pattern validation (DELETE in Phase 1)
14. `mu_warn` - Proactive warnings
15. `mu_related` - Related files
16. `mu_task_context` - Task-aware context (DELETE in Phase 1)

**Git/Diff:**
17. `mu_semantic_diff` - Semantic diff
18. `mu_review_diff` - PR review
19. `mu_why` - Git archaeology
20. `mu_compress` - Compress output

**Memory (DELETE in Phase 1):**
21. `mu_remember` - Store memory
22. `mu_recall` - Retrieve memory

**Advanced:**
23. `mu_ask` - NL to MUQL (DELETE in Phase 1)
24. `mu_macros` - List macros
25. `mu_export_lisp` - Lisp export

---

## Target State

### Reduced Tool Set (12 Tools)

After Phase 1 deletions and merging:

**Tier 1: Essential (6 tools)**
| Tool | Purpose | From |
|------|---------|------|
| `mu_status` | Status check | Keep |
| `mu_bootstrap` | Initialize | Keep |
| `mu_query` | MUQL queries | Keep |
| `mu_read` | Read source | Keep |
| `mu_context` | Smart context | Keep |
| `mu_context_omega` | OMEGA context | Keep |

**Tier 2: Analysis (4 tools)**
| Tool | Purpose | From |
|------|---------|------|
| `mu_deps` | Dependencies (merge ancestors) | Merge |
| `mu_impact` | Impact analysis | Keep |
| `mu_semantic_diff` | Semantic diff | Keep |
| `mu_review_diff` | PR review | Keep |

**Tier 3: Guidance (2 tools)**
| Tool | Purpose | From |
|------|---------|------|
| `mu_patterns` | Pattern detection | Keep |
| `mu_warn` | Proactive warnings | Keep |

### Tools Removed/Merged

| Tool | Action | Reason |
|------|--------|--------|
| `mu_generate` | DELETE | Phase 1 |
| `mu_validate` | DELETE | Phase 1 |
| `mu_task_context` | DELETE | Phase 1 |
| `mu_remember` | DELETE | Phase 1 |
| `mu_recall` | DELETE | Phase 1 |
| `mu_ask` | DELETE | Phase 1 |
| `mu_ancestors` | MERGE → `mu_deps` | Redundant |
| `mu_cycles` | MERGE → `mu_query` | It's a query |
| `mu_related` | KEEP (optional) | Useful but not essential |
| `mu_why` | KEEP (optional) | Useful for git archaeology |
| `mu_compress` | INTERNAL | Not MCP-worthy |
| `mu_macros` | INTERNAL | Not MCP-worthy |
| `mu_export_lisp` | INTERNAL | Not MCP-worthy |

**Final count: 12-14 tools** (down from 25)

---

## New Directory Structure

```
src/mu/mcp/
├── __init__.py           # Package exports
├── server.py             # FastMCP setup (~150 LOC)
├── models/               # Dataclass definitions
│   ├── __init__.py       # Re-exports all models
│   ├── common.py         # Shared models (NodeInfo, etc.)
│   ├── query.py          # Query-related models
│   ├── context.py        # Context-related models
│   ├── analysis.py       # Diff/impact models
│   └── guidance.py       # Pattern/warning models
└── tools/                # Tool implementations
    ├── __init__.py       # Tool registration
    ├── setup.py          # mu_status, mu_bootstrap
    ├── graph.py          # mu_query, mu_read
    ├── context.py        # mu_context, mu_context_omega
    ├── analysis.py       # mu_deps, mu_impact, mu_semantic_diff, mu_review_diff
    └── guidance.py       # mu_patterns, mu_warn
```

---

## Module Specifications

### `server.py` (~150 LOC)

```python
"""MCP Server - FastMCP setup and tool registration."""

from mcp.server.fastmcp import FastMCP

from mu.mcp.tools import register_all_tools

def create_server() -> FastMCP:
    """Create and configure the MCP server."""
    mcp = FastMCP(
        name="mu",
        version="0.2.0",
        description="MU - Machine Understanding for codebases",
    )
    register_all_tools(mcp)
    return mcp

def run_server(transport: str = "stdio") -> None:
    """Run the MCP server."""
    server = create_server()
    if transport == "stdio":
        server.run()
    elif transport == "http":
        server.run_http(port=8765)
```

### `models/common.py` (~100 LOC)

```python
"""Common models used across MCP tools."""

from dataclasses import dataclass

@dataclass
class NodeInfo:
    """Basic node information."""
    id: str
    type: str
    name: str
    qualified_name: str | None
    file_path: str | None
    line_start: int | None
    line_end: int | None
    complexity: int

@dataclass
class FileLocation:
    """File location reference."""
    path: str
    line_start: int | None = None
    line_end: int | None = None
```

### `models/query.py` (~80 LOC)

```python
"""Query-related models."""

from dataclasses import dataclass
from typing import Any

@dataclass
class QueryResult:
    """MUQL query result."""
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    execution_time_ms: float

@dataclass
class ReadResult:
    """Source code read result."""
    node_id: str
    file_path: str
    line_start: int
    line_end: int
    source: str
    context_before: str
    context_after: str
    language: str
```

### `models/context.py` (~100 LOC)

```python
"""Context extraction models."""

from dataclasses import dataclass

@dataclass
class ContextResult:
    """Smart context result."""
    mu_text: str
    token_count: int
    node_count: int

@dataclass
class OmegaContextResult:
    """OMEGA compressed context result."""
    seed: str
    body: str
    full_output: str
    seed_tokens: int
    body_tokens: int
    total_tokens: int
    original_tokens: int
    compression_ratio: float
    nodes_included: int
```

### `models/analysis.py` (~150 LOC)

```python
"""Analysis models (diff, impact, deps)."""

from dataclasses import dataclass

@dataclass
class DepsResult:
    """Dependency analysis result."""
    node_id: str
    direction: str  # "outgoing", "incoming", "both"
    dependencies: list[str]
    depth: int

@dataclass
class ImpactResult:
    """Impact analysis result."""
    node_id: str
    impacted_nodes: list[str]
    count: int

@dataclass
class SemanticChange:
    """A single semantic change."""
    entity_type: str
    entity_name: str
    change_type: str  # added, removed, modified
    details: str
    module_path: str
    is_breaking: bool

@dataclass
class SemanticDiffResult:
    """Semantic diff result."""
    base_ref: str
    head_ref: str
    changes: list[SemanticChange]
    breaking_changes: list[SemanticChange]
    summary_text: str
    has_breaking_changes: bool
    total_changes: int
```

### `tools/setup.py` (~150 LOC)

```python
"""Setup tools: status and bootstrap."""

from mcp.server.fastmcp import FastMCP

from mu.mcp.models import BootstrapResult, StatusResult

def register_setup_tools(mcp: FastMCP) -> None:
    """Register setup tools."""

    @mcp.tool()
    def mu_status() -> dict:
        """Get MU daemon and mubase status.

        Returns information about:
        - Whether daemon is running
        - Mubase location and stats
        - Language statistics
        - Next recommended action
        """
        # Implementation...

    @mcp.tool()
    def mu_bootstrap(path: str = ".", force: bool = False) -> BootstrapResult:
        """Bootstrap MU for a codebase in one step.

        Creates config, builds graph, returns ready status.
        Safe to run multiple times.
        """
        # Implementation...
```

### `tools/graph.py` (~200 LOC)

```python
"""Graph access tools: query and read."""

from mcp.server.fastmcp import FastMCP

from mu.mcp.models import QueryResult, ReadResult

def register_graph_tools(mcp: FastMCP) -> None:
    """Register graph access tools."""

    @mcp.tool()
    def mu_query(query: str) -> QueryResult:
        """Execute a MUQL query against the code graph.

        MUQL is SQL-like for querying code structure.

        Examples:
        - SELECT * FROM functions WHERE complexity > 50
        - SELECT name, file_path FROM classes WHERE name LIKE '%Service%'
        """
        # Implementation...

    @mcp.tool()
    def mu_read(node_id: str, context_lines: int = 3) -> ReadResult:
        """Read source code for a specific node.

        Use after finding nodes with mu_query or mu_context.
        """
        # Implementation...
```

### `tools/context.py` (~250 LOC)

```python
"""Context extraction tools."""

from mcp.server.fastmcp import FastMCP

from mu.mcp.models import ContextResult, OmegaContextResult

def register_context_tools(mcp: FastMCP) -> None:
    """Register context extraction tools."""

    @mcp.tool()
    def mu_context(question: str, max_tokens: int = 8000) -> ContextResult:
        """Extract smart context for a natural language question.

        Analyzes the question, finds relevant code, returns MU format.

        Examples:
        - "How does authentication work?"
        - "What calls the payment processing?"
        """
        # Implementation...

    @mcp.tool()
    def mu_context_omega(
        question: str,
        max_tokens: int = 8000,
        include_synthesized: bool = True,
    ) -> OmegaContextResult:
        """Extract OMEGA-compressed context.

        Like mu_context but uses S-expression format with macro
        compression for 3-5x token reduction.
        """
        # Implementation...
```

### `tools/analysis.py` (~400 LOC)

```python
"""Analysis tools: deps, impact, diff."""

from mcp.server.fastmcp import FastMCP

from mu.mcp.models import DepsResult, ImpactResult, SemanticDiffResult

def register_analysis_tools(mcp: FastMCP) -> None:
    """Register analysis tools."""

    @mcp.tool()
    def mu_deps(
        node_name: str,
        depth: int = 2,
        direction: str = "both",  # outgoing, incoming, both
    ) -> DepsResult:
        """Show dependencies of a code node.

        Finds what a node depends on (outgoing) or what depends on it (incoming).
        Merges previous mu_ancestors functionality.
        """
        # Implementation...

    @mcp.tool()
    def mu_impact(
        node_id: str,
        edge_types: list[str] | None = None,
    ) -> ImpactResult:
        """Find downstream impact of changing a node.

        "If I change X, what might break?"
        """
        # Implementation...

    @mcp.tool()
    def mu_semantic_diff(
        base_ref: str,
        head_ref: str,
        path: str = ".",
    ) -> SemanticDiffResult:
        """Compare two git refs and return semantic changes.

        Returns added/removed/modified functions, classes, methods
        with breaking change detection.
        """
        # Implementation...

    @mcp.tool()
    def mu_review_diff(
        base_ref: str,
        head_ref: str,
        path: str = ".",
        validate_patterns: bool = True,
    ) -> ReviewDiffResult:
        """Comprehensive code review of changes between git refs.

        Combines semantic diff with pattern validation.
        Recommended for PR reviews.
        """
        # Implementation...
```

### `tools/guidance.py` (~250 LOC)

```python
"""Guidance tools: patterns and warnings."""

from mcp.server.fastmcp import FastMCP

from mu.mcp.models import PatternsResult, WarningsResult

def register_guidance_tools(mcp: FastMCP) -> None:
    """Register guidance tools."""

    @mcp.tool()
    def mu_patterns(
        category: str | None = None,
        refresh: bool = False,
    ) -> PatternsResult:
        """Get detected codebase patterns.

        Analyzes naming conventions, error handling, imports,
        architecture, testing patterns, etc.
        """
        # Implementation...

    @mcp.tool()
    def mu_warn(target: str) -> WarningsResult:
        """Get proactive warnings about a target before modification.

        Returns warnings about high impact, stale code, security
        sensitivity, missing tests, high complexity, deprecation.
        """
        # Implementation...
```

### `tools/__init__.py` (~50 LOC)

```python
"""Tool registration."""

from mcp.server.fastmcp import FastMCP

from mu.mcp.tools.setup import register_setup_tools
from mu.mcp.tools.graph import register_graph_tools
from mu.mcp.tools.context import register_context_tools
from mu.mcp.tools.analysis import register_analysis_tools
from mu.mcp.tools.guidance import register_guidance_tools

def register_all_tools(mcp: FastMCP) -> None:
    """Register all MCP tools."""
    register_setup_tools(mcp)
    register_graph_tools(mcp)
    register_context_tools(mcp)
    register_analysis_tools(mcp)
    register_guidance_tools(mcp)

__all__ = ["register_all_tools"]
```

---

## Implementation Plan

### Step 1: Create Directory Structure (Day 1)

```bash
mkdir -p src/mu/mcp/models
mkdir -p src/mu/mcp/tools
touch src/mu/mcp/models/__init__.py
touch src/mu/mcp/tools/__init__.py
```

### Step 2: Extract Models (Day 1)

1. Create `models/common.py` with shared models
2. Create `models/query.py` with query models
3. Create `models/context.py` with context models
4. Create `models/analysis.py` with analysis models
5. Create `models/guidance.py` with guidance models
6. Update `models/__init__.py` to re-export all

### Step 3: Extract Tools (Day 2)

1. Create `tools/setup.py` - Extract mu_status, mu_bootstrap
2. Create `tools/graph.py` - Extract mu_query, mu_read
3. Create `tools/context.py` - Extract mu_context, mu_context_omega
4. Create `tools/analysis.py` - Extract analysis tools, merge mu_ancestors into mu_deps
5. Create `tools/guidance.py` - Extract mu_patterns, mu_warn
6. Update `tools/__init__.py` with registration

### Step 4: Slim Down server.py (Day 2)

1. Remove all inline tool implementations
2. Remove all model definitions
3. Keep only create_server() and run_server()
4. Import from new modules

### Step 5: Update Imports (Day 3)

1. Find all imports of `mu.mcp.server`
2. Update to import from specific modules
3. Run tests to verify

### Step 6: Test & Verify (Day 3)

1. MCP server starts correctly
2. All 12 tools work
3. Tool descriptions show correctly
4. No import errors

---

## Migration: mu_ancestors → mu_deps

Before:
```python
mu_deps(node_name, depth=2, direction="outgoing")
mu_ancestors(node_name, depth=2)  # direction always "incoming"
```

After:
```python
mu_deps(node_name, depth=2, direction="both")  # default changed
mu_deps(node_name, direction="outgoing")  # what it depends on
mu_deps(node_name, direction="incoming")  # what depends on it (was ancestors)
```

---

## Success Criteria

- [ ] `server.py` reduced to ~150 LOC
- [ ] 12 tools registered and working
- [ ] All models in dedicated files
- [ ] No tool >200 LOC
- [ ] MCP server starts in <1s
- [ ] All existing tests pass
- [ ] Documentation updated

---

## File Size Targets

| File | Target LOC |
|------|------------|
| `server.py` | ~150 |
| `models/common.py` | ~100 |
| `models/query.py` | ~80 |
| `models/context.py` | ~100 |
| `models/analysis.py` | ~150 |
| `models/guidance.py` | ~80 |
| `tools/setup.py` | ~150 |
| `tools/graph.py` | ~200 |
| `tools/context.py` | ~250 |
| `tools/analysis.py` | ~400 |
| `tools/guidance.py` | ~250 |
| **Total** | **~1,900** |

**Reduction: 3,514 → 1,900 LOC (46% reduction)**

---

## Appendix: Tool Docstring Template

Each tool should follow this pattern:

```python
@mcp.tool()
def mu_example(
    required_arg: str,
    optional_arg: int = 10,
) -> ExampleResult:
    """One-line summary of what this tool does.

    Longer description if needed, explaining:
    - When to use this tool
    - What it returns
    - Any important caveats

    Args:
        required_arg: Description of the argument
        optional_arg: Description with default noted

    Returns:
        ExampleResult with fields explained

    Examples:
        - mu_example("foo") - Basic usage
        - mu_example("bar", optional_arg=5) - With options
    """
    # Implementation
```
