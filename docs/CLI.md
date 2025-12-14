# MU CLI Reference

## Quick Start

```bash
mu bootstrap          # Initialize MU for your codebase
mu status             # See what's indexed and next steps
mu q "SELECT * FROM nodes LIMIT 10"  # Query the graph
```

## Command Categories

### Core
- `mu bootstrap` - Initialize and build the MU graph
- `mu status` - Show project status and guidance
- `mu compress` - Compress code to MU format for LLMs

### Query & Navigation
- `mu query` / `mu q` - Execute MUQL queries
- `mu context` - Smart context extraction for questions
- `mu read` - Read source code for a node
- `mu search` - Search for code entities

### Graph Reasoning
- `mu deps` - Show what a node depends on
- `mu impact` - What breaks if I change this?
- `mu ancestors` - What depends on this node?
- `mu cycles` - Find circular dependencies
- `mu related` - Find related files (tests, deps)

### Intelligence
- `mu patterns` - Detect codebase patterns
- `mu warn` - Proactive warnings before changes
- `mu diff` - Semantic diff between git refs

### Vibes
Fun aliases for common operations:
- `mu omg` - OMEGA compressed context
- `mu grok` - Smart context extraction
- `mu wtf` - Git archaeology (why does this exist?)
- `mu yolo` - Impact analysis
- `mu sus` - Suspicious code warnings
- `mu vibe` - Pattern validation
- `mu zen` - Cache cleanup (`--reset` for full reset including database)

### Services
- `mu serve` - Start MU server (daemon with HTTP/WebSocket API)
  - `mu serve` - Start in background
  - `mu serve -f` - Run in foreground
  - `mu serve --stop` - Stop running daemon
  - `mu serve --status` - Check daemon status
  - `mu serve --mcp` - Start MCP server for Claude Code
- `mu mcp serve` - Start MCP server for Claude Code

### Advanced
- `mu kernel export` - Export graph in various formats
- `mu kernel history` - Show node change history
- `mu kernel snapshot` - Create temporal snapshot
- `mu kernel blame` - Show who last modified a node
- `mu kernel search` - Semantic search
- `mu kernel embed` - Generate embeddings

## Deprecated Commands

These still work but will be removed in v2.0:

| Old | New |
|-----|-----|
| `mu daemon start` | `mu serve` |
| `mu daemon stop` | `mu serve --stop` |
| `mu daemon status` | `mu serve --status` |
| `mu daemon run` | `mu serve -f` |
| `mu kernel init` | `mu bootstrap` |
| `mu kernel build` | `mu bootstrap` |
| `mu kernel context` | `mu context` |
| `mu kernel muql` | `mu query` |
| `mu kernel stats` | `mu status` |
| `mu kernel deps` | `mu deps` |

## Common Workflows

### Initial Setup
```bash
cd your-project
mu bootstrap       # One-time setup
mu serve           # Start daemon (optional, enables real-time updates)
```

### Explore Codebase
```bash
mu q "SELECT name, complexity FROM functions ORDER BY complexity DESC LIMIT 10"
mu context "How does authentication work?"
mu deps AuthService
```

### Before Making Changes
```bash
mu warn src/auth.py    # Check for risks
mu impact AuthService  # See what might break
```

### Code Review
```bash
mu diff main HEAD      # Semantic diff for PR review
mu patterns            # Check code follows patterns
```

### MCP Integration (Claude Code)
```bash
# Add to claude_desktop_config.json or use Claude Code MCP settings
mu serve --mcp
```

## MUQL Terse Syntax

MUQL supports a terse syntax optimized for minimal token usage (60-85% reduction). Both verbose SQL-like syntax and terse syntax parse to the same AST.

### Node Type Aliases

| Verbose | Terse | Alt |
|---------|-------|-----|
| `functions` | `fn` | `f` |
| `classes` | `cls` | `c` |
| `modules` | `mod` | `m` |
| `methods` | `meth` | `mt` |
| `nodes` | `n` | - |

### Field Aliases

| Verbose | Terse |
|---------|-------|
| `complexity` | `c` |
| `name` | `n` |
| `file_path` | `fp` |
| `line_start` | `ls` |
| `line_end` | `le` |
| `qualified_name` | `qn` |
| `type` | `t` |

### Operator Aliases

| Verbose | Terse |
|---------|-------|
| `LIKE` | `~` |
| `AND` | `&` |
| `OR` | `\|` |
| `NOT` | `!` |

### Command Aliases

| Verbose | Terse | Example |
|---------|-------|---------|
| `SELECT * FROM functions WHERE` | `fn` | `fn c>50` |
| `SELECT` | `s` | `s n,c fn c>50` |
| `SHOW DEPENDENCIES OF` | `deps` | `deps AuthService` |
| `SHOW DEPENDENTS OF` | `rdeps` | `rdeps AuthService` |
| `SHOW CALLERS OF` | `callers` | `callers process_payment` |
| `SHOW CALLEES OF` | `callees` | `callees main` |
| `SHOW IMPACT OF` | `impact` | `impact UserModel` |
| `DEPTH` | `d` | `deps X d3` |
| `ORDER BY` | `sort` | `fn sort c desc` |
| `LIMIT` | `lim` or trailing number | `fn c>50 10` |
| `DESC` | `desc` or `-` | `sort c-` |
| `ASC` | `asc` or `+` | `sort c+` |

### Examples

```bash
# Verbose vs Terse comparison

# Find complex functions
mu q "SELECT * FROM functions WHERE complexity > 50"
mu q "fn c>50"

# Top 10 complex functions, sorted descending
mu q "SELECT name, complexity FROM functions WHERE complexity > 30 ORDER BY complexity DESC LIMIT 10"
mu q "s n,c fn c>30 sort c- 10"

# Find by name pattern
mu q "SELECT * FROM functions WHERE name LIKE '%auth%'"
mu q "fn n~auth"

# Show dependencies
mu q "SHOW DEPENDENCIES OF AuthService DEPTH 2"
mu q "deps AuthService d2"

# Show callers
mu q "SHOW CALLERS OF process_payment DEPTH 3"
mu q "callers process_payment d3"

# Impact analysis
mu q "SHOW IMPACT OF UserModel"
mu q "impact UserModel"

# Functions in specific path
mu q "fn fp~'src/auth'"

# Combine filters
mu q "fn n~parse c>20 fp~'src/'"
```
