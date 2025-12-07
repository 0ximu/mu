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
       +---> mu_query    → MUQL execution
       +---> mu_context  → Smart context extraction
       +---> mu_deps     → Dependency traversal
       +---> mu_node     → Node lookup
       +---> mu_search   → Pattern search
       +---> mu_status   → Health check
       |
       v
DaemonClient (if daemon running)
   or
MUbase (direct access fallback)
```

## Available Tools

| Tool | Purpose | Example |
|------|---------|---------|
| `mu_query` | Execute MUQL queries | `SELECT * FROM functions WHERE complexity > 50` |
| `mu_context` | Smart context for questions | "How does authentication work?" |
| `mu_deps` | Dependency graph traversal | Show what `AuthService` depends on |
| `mu_node` | Look up specific node | Get details for `func:login` |
| `mu_search` | Pattern-based search | Find all `*Service` classes |
| `mu_status` | Health and stats | Check daemon status, node counts |

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
- `mcp__mu__mu_query("SELECT * FROM functions LIMIT 10")`
- `mcp__mu__mu_context("How does caching work?")`
- `mcp__mu__mu_deps("AuthService")`

## Data Models

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
    mu_text: str    # MU format context
    token_count: int  # Token count
    node_count: int   # Number of nodes included
```

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
