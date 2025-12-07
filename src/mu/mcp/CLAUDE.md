# MCP Module - Model Context Protocol Server

This module provides an MCP (Model Context Protocol) server that exposes MU's code analysis capabilities to AI assistants like Claude Code.

## Overview

The MCP server translates natural language queries into MUQL and returns structured code context. This is Phase 1 of the MU Conductor architecture (see `docs/future-improvements/mu-conductor-architecture.md`).

## Architecture

```
AI Assistant (Claude Code)
       |
       | natural language / tool calls
       v
MCP Server (FastMCP)
       |
       +---> Bootstrap Tools (P0)
       |     +---> mu_init          → Initialize config
       |     +---> mu_build         → Build .mubase graph
       |     +---> mu_semantic_diff → Semantic diff between refs
       |
       +---> Discovery Tools (P1)
       |     +---> mu_scan          → Fast file scanning
       |     +---> mu_compress      → Generate MU output
       |
       +---> Query Tools
       |     +---> mu_query         → MUQL execution
       |     +---> mu_context       → Smart context extraction
       |     +---> mu_deps          → Dependency traversal
       |     +---> mu_node          → Node lookup
       |     +---> mu_search        → Pattern search
       |     +---> mu_status        → Health check + next_action
       |
       +---> Graph Reasoning (petgraph)
             +---> mu_impact        → Downstream impact analysis
             +---> mu_ancestors     → Upstream dependencies
             +---> mu_cycles        → Circular dependency detection
       |
       v
DaemonClient (if daemon running)
   or
MUbase (direct access fallback)
```

## Agent Bootstrap Flow

When an agent first encounters a codebase, use this flow:

```
mu_status() → "next_action": "mu_init"
     ↓
mu_init(".") → creates .murc.toml
     ↓
mu_status() → "next_action": "mu_build"
     ↓
mu_build(".") → builds .mubase graph
     ↓
mu_status() → "next_action": "mu_embed" (optional)
     ↓
mu_context("How does auth work?") → works!
     ↓
mu_semantic_diff("main", "HEAD") → PR review
```

## Available Tools

### Bootstrap Tools (P0)

| Tool | Purpose | Returns |
|------|---------|---------|
| `mu_init` | Initialize .murc.toml config | `InitResult` |
| `mu_build` | Build .mubase code graph | `BuildResult` with stats |
| `mu_semantic_diff` | Semantic diff between git refs | `SemanticDiffOutput` with changes |

### Discovery Tools (P1)

| Tool | Purpose | Returns |
|------|---------|---------|
| `mu_scan` | Fast codebase scanning | `ScanOutput` with file list |
| `mu_compress` | Generate MU representation | `CompressOutput` with output |

### Query Tools

| Tool | Purpose | Example |
|------|---------|---------|
| `mu_query` | Execute MUQL queries | `SELECT * FROM functions WHERE complexity > 50` |
| `mu_context` | Smart context for questions | "How does authentication work?" |
| `mu_deps` | Dependency graph traversal | Show what `AuthService` depends on |
| `mu_node` | Look up specific node | Get details for `func:login` |
| `mu_search` | Pattern-based search | Find all `*Service` classes |
| `mu_status` | Health, stats, and `next_action` | Check status, get guidance |

### Graph Reasoning Tools

| Tool | Purpose | Algorithm |
|------|---------|-----------|
| `mu_impact` | "If I change X, what breaks?" | BFS via petgraph |
| `mu_ancestors` | "What does X depend on?" | BFS via petgraph |
| `mu_cycles` | Detect circular dependencies | Kosaraju's SCC |

## CLI Commands

```bash
# Start MCP server (stdio transport for Claude Code)
mu mcp serve

# Start with HTTP transport
mu mcp serve --http
mu mcp serve --http --port 9000

# List available tools
mu mcp tools
```

## Claude Code Integration

Add to `~/.claude/mcp_servers.json`:

```json
{
  "mu": {
    "command": "mu",
    "args": ["mcp", "serve"]
  }
}
```

Then Claude Code can use:
- `mcp__mu__mu_status()` - Check status and get next action
- `mcp__mu__mu_build(".")` - Build the code graph
- `mcp__mu__mu_query("SELECT * FROM functions LIMIT 10")`
- `mcp__mu__mu_context("How does caching work?")`
- `mcp__mu__mu_semantic_diff("main", "HEAD")` - PR review

## Data Models

### InitResult

```python
@dataclass
class InitResult:
    success: bool
    config_path: str
    message: str
```

### BuildResult

```python
@dataclass
class BuildResult:
    success: bool
    mubase_path: str
    stats: dict[str, Any]  # nodes, edges, nodes_by_type
    duration_ms: float
```

### SemanticDiffOutput

```python
@dataclass
class SemanticDiffOutput:
    base_ref: str
    head_ref: str
    changes: list[dict[str, Any]]  # All changes
    breaking_changes: list[dict[str, Any]]  # Breaking only
    summary_text: str  # Human-readable summary
    has_breaking_changes: bool
    total_changes: int
```

### ScanOutput

```python
@dataclass
class ScanOutput:
    files: list[dict[str, Any]]  # path, language, lines, size_bytes
    total_files: int
    total_lines: int
    by_language: dict[str, int]
    duration_ms: float
```

### CompressOutput

```python
@dataclass
class CompressOutput:
    output: str  # MU/JSON/Markdown output
    token_count: int  # Estimated tokens
    compression_ratio: float  # 0.0-1.0
    file_count: int
```

### NodeInfo

```python
@dataclass
class NodeInfo:
    id: str                     # Node ID (e.g., "func:login")
    type: str                   # Node type (function, class, module)
    name: str                   # Simple name
    qualified_name: str | None  # Full qualified name
    file_path: str | None       # Source file path
    line_start: int | None      # Start line
    line_end: int | None        # End line
    complexity: int             # Cyclomatic complexity
```

### QueryResult

```python
@dataclass
class QueryResult:
    columns: list[str]          # Column names
    rows: list[list[Any]]       # Row data
    row_count: int              # Total rows
    execution_time_ms: float | None
```

### ContextResult

```python
@dataclass
class ContextResult:
    mu_text: str      # MU format context
    token_count: int  # Token count
    node_count: int   # Number of nodes included
```

## Enhanced mu_status

The `mu_status` tool now returns a `next_action` field for agent guidance:

```python
{
    "daemon_running": False,
    "config_exists": True,
    "mubase_exists": False,
    "embeddings_exist": False,
    "stats": {},
    "next_action": "mu_build",  # What agent should do next
    "message": "No .mubase found. Run mu_build() to build the code graph."
}
```

Possible `next_action` values:
- `"mu_init"` - No config, create .murc.toml
- `"mu_build"` - No .mubase, build code graph
- `"mu_embed"` - No embeddings, enable semantic search
- `None` - System is ready

## Fallback Behavior

Each tool tries:
1. Connect to running daemon via `DaemonClient`
2. If daemon unavailable, fall back to direct `MUbase` access
3. If no `.mubase` found, raise error with instructions

## Transport Types

| Transport | Use Case |
|-----------|----------|
| `stdio` | Claude Code integration (default) |
| `sse` | Server-Sent Events |
| `streamable-http` | HTTP with streaming |

## Testing

```bash
# Run MCP tests
pytest tests/unit/test_mcp.py -v

# Test CLI commands
mu mcp tools
mu mcp serve --help
```

## Files

| File | Purpose |
|------|---------|
| `__init__.py` | Public API exports |
| `server.py` | FastMCP server and tool implementations |
| `CLAUDE.md` | This documentation |
