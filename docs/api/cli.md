# CLI Reference

Complete reference for the MU command-line interface.

## Global Options

| Option | Description |
|--------|-------------|
| `--help` | Show help message |
| `--version` | Show version |
| `-v, --verbose` | Increase verbosity |
| `-q, --quiet` | Suppress non-essential output |
| `-F, --format` | Output format: `table`, `json`, `csv`, `mu`, `tree` |
| `--no-color` | Disable colored output |

### Output Formatting

All MU commands that produce tabular output support consistent formatting options:

```bash
# JSON output for scripting
mu deps UserService -F json | jq '.nodes[]'

# Export to CSV
mu query "SELECT name, complexity FROM functions" -F csv > functions.csv

# Pipe-friendly (auto-disables color)
mu impact Service | grep "critical"
```

**Auto-detection**: When output is piped to a file or another command, colors are disabled automatically.

---

## Core Commands

### `mu bootstrap`

Initialize and build the graph database for a codebase.

```bash
mu bootstrap [path] [options]
```

**Arguments:**
- `path`: Directory to scan (default: current directory)

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--embed` | false | Also generate embeddings |
| `--force` | false | Rebuild even if database exists |

**Examples:**
```bash
# Initialize current directory
mu bootstrap

# Initialize with embeddings
mu bootstrap --embed

# Force rebuild
mu bootstrap --force
```

### `mu status`

Show project status and graph statistics.

```bash
mu status [path]
```

**Examples:**
```bash
mu status
# Output:
# Project: /path/to/project
# Database: .mu/mubase (2.3 MB)
# Nodes: 1,234 (512 functions, 89 classes, 633 modules)
# Edges: 4,567
# Embeddings: 1,234/1,234 (100%)
```

### `mu doctor`

Run health checks on MU installation.

```bash
mu doctor
```

---

## Query Commands

### `mu query` / `mu q`

Execute MUQL queries against the graph database.

```bash
mu query <query> [options]
mu q <query> [options]
```

**Arguments:**
- `query`: MUQL query string

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `-F, --format` | `table` | Output: `table`, `json`, `csv`, `tree` |
| `-i, --interactive` | false | Start interactive REPL |
| `--explain` | false | Show execution plan |

**Examples:**
```bash
# SQL-like query
mu query "SELECT name, complexity FROM functions WHERE complexity > 10"

# Short alias with terse syntax
mu q "fn c>50"

# Interactive REPL
mu query -i
```

### MUQL Terse Syntax

60-85% fewer tokens than full SQL:

```bash
# Node type filters
mu q "fn c>50"              # Functions with complexity > 50
mu q "cls n~'Service'"      # Classes matching 'Service'
mu q "mod"                  # All modules

# Graph operations
mu q "deps Auth d2"         # Dependencies of Auth, depth 2
mu q "rdeps Parser"         # What depends on Parser
mu q "impact UserService"   # Downstream impact

# Sorting and limits
mu q "fn c>10 sort c- 20"   # Sorted by complexity desc, limit 20
mu q "cls sort n+ 10"       # Sorted by name asc, limit 10
```

| Alias | Meaning |
|-------|---------|
| `fn`, `cls`, `mod` | Node types (functions, classes, modules) |
| `c`, `n`, `fp` | Fields (complexity, name, file_path) |
| `~` | LIKE operator |
| `deps`, `rdeps` | Dependencies / reverse dependencies |
| `d2`, `d3` | DEPTH clause |
| `sort c-`, `sort c+` | ORDER BY DESC/ASC |
| trailing number | LIMIT |

---

## Graph Analysis

### `mu deps`

Show dependencies of a node.

```bash
mu deps <node> [options]
```

**Arguments:**
- `node`: Node name or ID (supports fuzzy matching)

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `-d, --depth` | 1 | Depth of traversal |
| `-r, --reverse` | false | Show dependents instead |
| `-F, --format` | `tree` | Output format |

**Examples:**
```bash
# Show dependencies
mu deps UserService

# Show what depends on this node (reverse)
mu deps UserService -r

# Deep traversal
mu deps AuthModule -d 3
```

### `mu impact`

Find downstream impact (what breaks if this changes).

```bash
mu impact <node> [options]
```

**Examples:**
```bash
mu impact PaymentService
mu impact mod:src/auth.ts -d 3
```

### `mu ancestors`

Find upstream ancestors (what this depends on).

```bash
mu ancestors <node> [options]
```

### `mu cycles`

Detect circular dependencies.

```bash
mu cycles [options]
```

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--max` | 10 | Maximum cycles to report |
| `-F, --format` | `table` | Output format |

---

## Search & Discovery

### `mu search`

Search for code semantically or by keyword.

```bash
mu search <query> [options]
```

**Arguments:**
- `query`: Search query (natural language or keywords)

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `-l, --limit` | 10 | Maximum results |
| `-t, --type` | all | Filter by type: `function`, `class`, `module` |
| `-F, --format` | `table` | Output format |

**Examples:**
```bash
# Semantic search (requires embeddings)
mu search "authentication logic"

# Filter by type
mu search "error handling" -t function

# Keyword fallback (without embeddings)
mu search "parse"
```

> **Tip:** Run `mu embed` to enable semantic search. Without embeddings, search uses keyword matching.

### `mu grok`

Ask questions about the codebase using LLM.

```bash
mu grok <question> [options]
```

**Examples:**
```bash
mu grok "How does user authentication work?"
mu grok "What would break if I changed the PaymentService?"
```

### `mu patterns`

Detect code patterns in the codebase.

```bash
mu patterns [options]
```

### `mu read`

Read and display a file with MU context.

```bash
mu read <file> [options]
```

---

## Embeddings

### `mu embed`

Generate vector embeddings for semantic search.

```bash
mu embed [options]
```

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--force` | false | Regenerate all embeddings |
| `--status` | false | Show embedding coverage |

**Examples:**
```bash
# Generate embeddings (incremental)
mu embed

# Force regenerate all
mu embed --force

# Check status
mu embed --status
```

---

## Semantic Diff

### `mu diff`

Compute semantic diff between git refs.

```bash
mu diff <base> [head] [options]
```

**Arguments:**
- `base`: Base git ref (commit, branch, tag)
- `head`: Head git ref (default: HEAD)

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `-F, --format` | `text` | Output: `text`, `json`, `mu` |

**Examples:**
```bash
# Diff between commits
mu diff abc123 def456

# Diff against main branch
mu diff main HEAD

# Diff last 5 commits
mu diff HEAD~5 HEAD
```

### `mu history`

Show change history for a node.

```bash
mu history <node> [options]
```

---

## Export

### `mu export`

Export the graph in multiple formats.

```bash
mu export [options]
```

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `-F, --format` | `mu` | Export: `mu`, `json`, `mermaid`, `d2` |
| `-o, --output` | stdout | Output file |
| `-l, --limit` | unlimited | Maximum nodes to export |
| `-t, --types` | all | Node types: `module`, `class`, `function` |

**Examples:**
```bash
# MU format (LLM-optimized)
mu export

# JSON export
mu export -F json -o graph.json

# Mermaid diagram
mu export -F mermaid -o arch.md

# D2 diagram
mu export -F d2 -o arch.d2

# Limit for large codebases
mu export -F json -l 100
```

---

## Server / Daemon

### `mu serve`

Start the MU daemon (HTTP API or MCP server).

```bash
mu serve [options]
```

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--foreground` | false | Run in foreground |
| `--stop` | false | Stop running daemon |
| `--port` | 9120 | HTTP port |
| `--mcp` | false | Start MCP server (stdio) |
| `--list-tools` | false | List available MCP tools |

**Examples:**
```bash
# Start HTTP daemon
mu serve

# Run in foreground (debug mode)
mu serve --foreground

# Stop daemon
mu serve --stop

# Start MCP server for Claude Code
mu serve --mcp
```

**HTTP API Endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/status` | GET | Daemon and graph statistics |
| `/query` | POST | Execute MUQL query |
| `/context` | POST | Smart context extraction |
| `/nodes/{id}` | GET | Node details |

---

## MCP Server (Claude Code Integration)

### `mu serve --mcp`

Start Model Context Protocol server for AI assistants.

```bash
mu serve --mcp
```

**Available MCP Tools:**

| Tool | Description |
|------|-------------|
| `mu_query` | Execute MUQL queries |
| `mu_context` | Extract smart context for questions |
| `mu_deps` | Show dependencies of a node |
| `mu_search` | Search for code nodes |
| `mu_status` | Get daemon status and statistics |

**Configure in Claude Code** (`~/.claude/mcp_servers.json`):
```json
{
  "mu": {
    "command": "mu",
    "args": ["serve", "--mcp"]
  }
}
```

---

## Vibes

Commands that do real work with real personality.

| Command | Vibe | What it actually does |
|---------|------|----------------------|
| `mu yolo <node>` | "Mass deploy on Friday" | Impact analysis — what breaks if you touch this? |
| `mu sus` | "Emergency code review" | Find suspicious patterns: complexity bombs, security smells |
| `mu wtf <file>` | "Archaeology expedition" | Git blame on steroids. Who did this? When? WHY? |
| `mu omg` | "Monday morning standup" | Dramatic summary of what changed. The tea. The drama. |
| `mu vibe` | "Project health check" | Overall codebase vibe. Cozy? Chaotic? A beautiful mess? |
| `mu zen` | "Digital declutter" | Clear caches, reset state, achieve inner peace |

> **Philosophy**: Most CLI tools are either boring or try-hard. MU aims for the sweet spot — useful AND fun.

---

## Configuration

MU looks for configuration in this order:
1. CLI flags
2. `.murc.toml` in current directory
3. Environment variables

### `.murc.toml` Example

```toml
[mu]
version = "1.0"

[scanner]
ignore = ["vendor/", "node_modules/", "dist/"]
include_hidden = false
max_file_size_kb = 1024

[parser]
languages = ["python", "typescript", "rust", "go"]

[output]
format = "table"
color = true

[cache]
enabled = true
directory = ".mu/cache"
```

---

## Node Identifiers

MU uses prefixed identifiers:

| Prefix | Type | Example |
|--------|------|---------|
| `mod:` | Module/File | `mod:src/lib/utils.ts` |
| `cls:` | Class | `cls:src/models/User.ts:User` |
| `fn:` | Function | `fn:src/api/auth.ts:login` |
| `ext:` | External | `ext:react` |

**Usage:**
- **Short name**: `mu deps UserService` (fuzzy match)
- **Full ID**: `mu deps mod:src/services/UserService.ts` (exact match)

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Configuration error |
| 3 | Parse error |
| 4 | IO error |
