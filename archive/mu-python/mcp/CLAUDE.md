# MCP Module - Model Context Protocol Server

This module provides an MCP (Model Context Protocol) server that exposes MU's code analysis capabilities to AI assistants like Claude Code.

## Overview

The MCP server translates natural language queries into MUQL and returns structured code context. It provides 12 tools organized into 5 categories.

## Architecture

```
AI Assistant (Claude Code)
       |
       | natural language / tool calls
       v
MCP Server (FastMCP)
       |
       +---> Setup Tools
       |     +---> mu_status          → Health check + next_action
       |     +---> mu_bootstrap       → Initialize + build in one step
       |
       +---> Graph Tools
       |     +---> mu_query           → MUQL execution
       |     +---> mu_read            → Read source code for nodes
       |
       +---> Context Tools
       |     +---> mu_context         → Smart context extraction
       |     +---> mu_context_omega   → OMEGA S-expression context
       |
       +---> Analysis Tools
       |     +---> mu_deps            → Dependency traversal (in/out/both)
       |     +---> mu_impact          → Downstream impact analysis
       |     +---> mu_semantic_diff   → Semantic diff between refs
       |     +---> mu_review_diff     → Comprehensive PR review
       |
       +---> Guidance Tools
             +---> mu_patterns        → Detected codebase patterns
             +---> mu_warn            → Proactive warnings
       |
       v
DaemonClient (if daemon running)
   or
MUbase (direct access fallback)
```

## Module Structure

```
src/mu/mcp/
├── __init__.py           # Package exports
├── server.py             # FastMCP setup (~200 LOC)
├── CLAUDE.md             # This documentation
├── models/               # Dataclass definitions
│   ├── __init__.py       # Re-exports all models
│   ├── common.py         # NodeInfo, QueryResult, ReadResult
│   ├── context.py        # ContextResult, OmegaContextOutput
│   ├── analysis.py       # DepsResult, ImpactResult, SemanticDiffOutput, ReviewDiffOutput
│   ├── guidance.py       # PatternsOutput, WarningsOutput
│   └── setup.py          # BootstrapResult
└── tools/                # Tool implementations
    ├── __init__.py       # Tool registration
    ├── _utils.py         # Shared utilities (get_client, find_mubase)
    ├── setup.py          # mu_status, mu_bootstrap
    ├── graph.py          # mu_query, mu_read
    ├── context.py        # mu_context, mu_context_omega
    ├── analysis.py       # mu_deps, mu_impact, mu_semantic_diff, mu_review_diff
    └── guidance.py       # mu_patterns, mu_warn
```

## Agent Bootstrap Flow

When an agent first encounters a codebase, use this flow:

```
mu_status() → "next_action": "mu_bootstrap"
     ↓
mu_bootstrap(".") → creates config + builds .mubase
     ↓
mu_status() → "next_action": "mu_embed" (optional)
     ↓
mu_context("How does auth work?") → works!
     ↓
mu_semantic_diff("main", "HEAD") → PR review
```

## Available Tools (12 total)

### Setup Tools

| Tool | Purpose | Returns |
|------|---------|---------|
| `mu_status` | Health check + next_action guidance | `dict` with status info |
| `mu_bootstrap` | Initialize config + build graph | `BootstrapResult` |

### Graph Tools

| Tool | Purpose | Returns |
|------|---------|---------|
| `mu_query` | Execute MUQL queries | `QueryResult` with rows |
| `mu_read` | Read source code for a node | `ReadResult` with source |

### Context Tools

| Tool | Purpose | Returns |
|------|---------|---------|
| `mu_context` | Smart context extraction | `ContextResult` with MU text |
| `mu_context_omega` | OMEGA S-expression context (LLM-parseable) | `OmegaContextOutput` |

### Analysis Tools

| Tool | Purpose | Returns |
|------|---------|---------|
| `mu_deps` | Dependency traversal (outgoing/incoming/both) | `DepsResult` |
| `mu_impact` | "If I change X, what breaks?" | `ImpactResult` |
| `mu_semantic_diff` | Semantic diff between git refs | `SemanticDiffOutput` |
| `mu_review_diff` | Comprehensive PR review | `ReviewDiffOutput` |

### Guidance Tools

| Tool | Purpose | Returns |
|------|---------|---------|
| `mu_patterns` | Detected codebase patterns | `PatternsOutput` |
| `mu_warn` | Proactive warnings before changes | `WarningsOutput` |

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
- `mcp__mu__mu_bootstrap(".")` - Initialize and build in one step
- `mcp__mu__mu_query("SELECT * FROM functions LIMIT 10")`
- `mcp__mu__mu_context("How does caching work?")`
- `mcp__mu__mu_context_omega("How does auth work?")` - OMEGA S-expression format
- `mcp__mu__mu_deps("AuthService", direction="both")` - All dependencies
- `mcp__mu__mu_semantic_diff("main", "HEAD")` - PR review

## Enhanced mu_status

The `mu_status` tool returns a `next_action` field for agent guidance:

```python
{
    "daemon_running": False,
    "config_exists": True,
    "mubase_exists": False,
    "embeddings_exist": False,
    "stats": {},
    "next_action": "mu_bootstrap",  # What agent should do next
    "message": "No .mu/mubase found. Run mu_bootstrap() to initialize MU."
}
```

Possible `next_action` values:
- `"mu_bootstrap"` - No .mubase, initialize and build
- `"mu_embed"` - No embeddings, enable semantic search
- `None` - System is ready

## Fallback Behavior

Each tool tries:
1. Connect to running daemon via `DaemonClient`
2. If daemon unavailable, fall back to direct `MUbase` access
3. If no `.mubase` found, raise error with instructions

## OMEGA vs Sigils

OMEGA (`mu_context_omega`) provides an alternative output format to sigil-based MU (`mu_context`):

| Aspect | Sigils (mu_context) | OMEGA (mu_context_omega) |
|--------|---------------------|--------------------------|
| Format | Custom sigil syntax (`!`, `$`, `#`) | S-expressions (Lisp-like) |
| Purpose | Human readability | LLM parseability |
| Token usage | More compact | More verbose (~1.0-1.2x) |
| Structure | Visual hierarchy | Explicit parentheses |
| Caching | N/A | Stable seed enables prompt cache |

**Important:** OMEGA Schema v2.0 prioritizes **LLM parseability** over token savings. S-expressions are more verbose than sigils, so `compression_ratio` may be < 1.0 (expansion). The value is in structured format and prompt cache optimization, not raw token reduction.

## Testing

```bash
# Run MCP tests
pytest tests/unit/test_mcp.py -v

# Test CLI commands
mu mcp tools
mu mcp serve --help
```
