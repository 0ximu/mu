# CLI Reference

Complete reference for the MU command-line interface.

## Global Options

| Option | Description |
|--------|-------------|
| `--help` | Show help message |
| `--version` | Show version |
| `-v, --verbose` | Increase verbosity |
| `-q, --quiet` | Suppress non-essential output |

## Commands

### `mu init`

Create a `.murc.toml` configuration file in the current directory.

```bash
mu init
```

### `mu scan`

Analyze codebase structure without generating output.

```bash
mu scan <path> [options]
```

**Arguments:**
- `path`: Directory or file to scan

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--format, -f` | `text` | Output format: `text`, `json` |

**Example:**
```bash
mu scan ./src --format json
```

### `mu compress`

Generate compressed MU representation of a codebase.

```bash
mu compress <path> [options]
```

**Arguments:**
- `path`: Directory or file to compress

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--output, -o` | stdout | Output file path |
| `--format, -f` | `mu` | Output format: `mu`, `json`, `markdown` |
| `--llm` | false | Enable LLM summarization |
| `--llm-provider` | `anthropic` | LLM provider: `anthropic`, `openai`, `ollama`, `openrouter` |
| `--llm-model` | varies | Override LLM model |
| `--local` | false | Use local LLM (Ollama) |
| `--no-redact` | false | Disable secret redaction |
| `--shell-safe` | false | Escape sigils for shell piping |
| `-y, --yes` | false | Skip confirmation prompts |
| `--no-cache` | false | Disable caching (process all files fresh) |

**Examples:**
```bash
# Basic compression
mu compress ./src -o system.mu

# With LLM summarization
mu compress ./src --llm -o system.mu

# Local-only mode
mu compress ./src --llm --local -o system.mu

# JSON output
mu compress ./src -f json -o system.json

# Filter files
mu compress ./src --include "*.py" --exclude "*_test.py"
```

### `mu view`

Render MU file with syntax highlighting.

```bash
mu view <file> [options]
```

**Arguments:**
- `file`: MU file to view

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--format, -f` | `terminal` | Output: `terminal`, `html`, `markdown` |
| `--theme` | `dark` | Color theme: `dark`, `light` |
| `-n, --line-numbers` | false | Show line numbers |
| `--output, -o` | stdout | Output file (for html/markdown) |

**Examples:**
```bash
# View in terminal
mu view system.mu

# Export to HTML
mu view system.mu -f html -o docs/system.html
```

### `mu diff`

Compute semantic diff between git refs.

```bash
mu diff <base> <head> [options]
```

**Arguments:**
- `base`: Base git ref (commit, branch, tag)
- `head`: Head git ref (default: current working tree)

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--format, -f` | `text` | Output: `text`, `json`, `mu` |
| `--output, -o` | stdout | Output file |

**Examples:**
```bash
# Diff between commits
mu diff abc123 def456

# Diff against main branch
mu diff main HEAD

# Diff current changes
mu diff HEAD
```

### `mu query` / `mu q`

Execute MUQL queries (top-level alias for `mu kernel muql`).

```bash
mu query <query> [options]
mu q <query> [options]
```

**Arguments:**
- `query`: MUQL query string

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--path, -p` | `.` | Path to codebase |
| `--format, -f` | `table` | Output: `table`, `json`, `csv`, `tree` |
| `--interactive, -i` | false | Start interactive REPL |
| `--explain` | false | Show execution plan |
| `--no-color` | false | Disable colored output |
| `--full-paths` | false | Show full file paths without truncation |

**Examples:**
```bash
# Quick query
mu q "SELECT name FROM nodes WHERE type = 'function'"

# With path
mu query -p ./myproject "SELECT * FROM nodes WHERE complexity > 10"

# JSON output for scripting
mu q --format json "SELECT name, complexity FROM nodes"
```

### `mu describe`

Output MU representation of CLI interface (for AI agents).

```bash
mu describe [options]
```

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--format, -f` | `mu` | Output: `mu`, `json`, `markdown` |

**Examples:**
```bash
# MU format (default, most compact)
mu describe

# JSON for programmatic consumption
mu describe --format json

# Markdown for documentation
mu describe --format markdown

# Pipe to clipboard for LLM context
mu describe | pbcopy
```

### `mu man`

Display the MU manual.

```bash
mu man [topic] [options]
```

**Arguments:**
- `topic`: Manual topic (optional)

**Topics:**
| Topic | Description |
|-------|-------------|
| `intro` | What is MU? |
| `quickstart` | 5-minute getting started guide |
| `sigils` | Sigil reference with examples |
| `operators` | Data flow operators |
| `query` | MUbase queries and graph database |
| `workflows` | Common usage patterns |
| `philosophy` | Design principles behind MU |

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--toc` | false | Print table of contents |
| `--no-color` | false | Disable colored output |
| `--width` | auto | Override terminal width |

**Examples:**
```bash
# Interactive manual navigation
mu man

# Specific topic
mu man quickstart
mu man sigils

# Table of contents
mu man --toc
```

### `mu llm`

Output MU format spec for LLM consumption.

```bash
mu llm [options]
```

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--full` | false | Complete spec with all examples (~2K tokens) |
| `--examples` | false | Just example transformations |
| `--copy` | false | Copy to clipboard |
| `--raw` | false | Output without version header |

**Examples:**
```bash
# Quick reference
mu llm

# Full specification
mu llm --full

# Copy to clipboard
mu llm --copy
```

---

## Kernel Commands

The `mu kernel` command group provides graph database operations.

### `mu kernel init`

Initialize a .mubase graph database.

```bash
mu kernel init [path] [options]
```

**Arguments:**
- `path`: Directory to initialize (default: current directory)

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--force, -f` | false | Overwrite existing .mubase file |

### `mu kernel build`

Build graph database from codebase.

```bash
mu kernel build [path] [options]
```

**Arguments:**
- `path`: Directory to scan (default: current directory)

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--output, -o` | `{path}/.mubase` | Output .mubase file |

### `mu kernel stats`

Show graph database statistics.

```bash
mu kernel stats [path] [options]
```

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--json` | false | Output as JSON |

### `mu kernel query`

Query the graph database (simple interface).

```bash
mu kernel query [path] [options]
```

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--type, -t` | all | Filter: `module`, `class`, `function`, `external` |
| `--complexity, -c` | 0 | Minimum complexity threshold |
| `--name, -n` | - | Filter by name (supports % wildcard) |
| `--limit, -l` | 20 | Maximum results |
| `--json` | false | Output as JSON |

**Examples:**
```bash
# Find complex functions
mu kernel query --complexity 20

# Search by name pattern
mu kernel query --name "parse%"

# Filter by type
mu kernel query --type class --limit 50
```

### `mu kernel deps`

Show dependencies or dependents of a node.

```bash
mu kernel deps <node_name> [path] [options]
```

**Arguments:**
- `node_name`: Function, class, or module name

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--depth, -d` | 1 | Depth of traversal |
| `--reverse, -r` | false | Show dependents instead |
| `--json` | false | Output as JSON |

**Examples:**
```bash
# Show dependencies
mu kernel deps UserService

# Show what depends on this node
mu kernel deps UserService --reverse

# Deep traversal
mu kernel deps AuthModule --depth 3
```

### `mu kernel embed`

Generate vector embeddings for semantic code search.

```bash
mu kernel embed [path] [options]
```

**Arguments:**
- `path`: Directory to embed (default: current directory)

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--provider, -p` | `openai` | Embedding provider: `openai`, `local` |
| `--model` | varies | Embedding model to use |
| `--batch-size` | `100` | Number of nodes to embed per batch |
| `--local` | false | Force local embeddings (sentence-transformers) |

**Examples:**
```bash
# Generate embeddings with OpenAI
mu kernel embed ./src

# Use local embeddings (no API key required)
mu kernel embed ./src --local

# Custom batch size for large codebases
mu kernel embed ./src --batch-size 50
```

**Environment Variables:**
- `OPENAI_API_KEY`: Required for OpenAI embeddings

### `mu kernel context`

Extract optimal context for answering a question about the code.

```bash
mu kernel context <question> [path] [options]
```

**Arguments:**
- `question`: Natural language question about the code
- `path`: Directory containing .mubase file (default: current directory)

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--max-tokens, -t` | `8000` | Maximum tokens in output |
| `--format, -f` | `mu` | Output format: `mu`, `json` |
| `--verbose, -v` | false | Show extraction statistics |
| `--exclude-tests` | false | Filter out test files |
| `--scores` | false | Include relevance annotations |
| `--depth` | `1` | Graph expansion depth |
| `--copy` | false | Copy output to clipboard |

**Examples:**
```bash
# Basic context extraction
mu kernel context "How does authentication work?"

# With token limit
mu kernel context "database queries" --max-tokens 4000

# JSON output with scores
mu kernel context "user validation" --format json --scores

# Verbose mode shows extraction stats
mu kernel context "error handling" --verbose

# Exclude test files
mu kernel context "API endpoints" --exclude-tests

# Copy to clipboard for LLM prompt
mu kernel context "parser logic" --copy
```

**Output Example:**
```
! auth.service
  Authentication service module
  $ AuthService < BaseService
    # login(email: str, password: str) -> Result[User]
      Authenticate user with credentials
      @validate, @log_call
    # logout(user_id: UUID) -> None
    # refresh_token(token: str) -> Token
  @ UserRepository, TokenService, CacheService
```

### `mu kernel search`

Semantic search for code using vector embeddings.

```bash
mu kernel search <query> [path] [options]
```

**Arguments:**
- `query`: Natural language search query
- `path`: Directory containing .mubase file (default: current directory)

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--limit, -l` | `10` | Maximum results to return |
| `--type, -t` | all | Filter by node type: `function`, `class`, `module` |
| `--json` | false | Output results as JSON |
| `--provider, -p` | `openai` | Embedding provider for query |
| `--local` | false | Use local embeddings for query |

**Examples:**
```bash
# Search for authentication logic
mu kernel search "user authentication and login"

# Find only functions, limit to 5 results
mu kernel search "error handling" --type function --limit 5

# JSON output for scripting
mu kernel search "database connection" --json

# Use local embeddings
mu kernel search "api endpoint" --local
```

### `mu kernel snapshot`

Create a temporal snapshot of the current graph state (links to git commits).

```bash
mu kernel snapshot [path] [options]
```

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--commit, -c` | HEAD | Git commit to snapshot |
| `--force, -f` | false | Overwrite existing snapshot |
| `--json` | false | Output as JSON |

### `mu kernel snapshots`

List all temporal snapshots.

```bash
mu kernel snapshots [path] [options]
```

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--limit, -l` | 20 | Maximum snapshots to show |
| `--json` | false | Output as JSON |

### `mu kernel history`

Show change history for a code node.

```bash
mu kernel history <node_name> [path] [options]
```

**Arguments:**
- `node_name`: Name of node to track

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--limit, -l` | 20 | Maximum changes to show |
| `--json` | false | Output as JSON |

### `mu kernel blame`

Show who last modified each aspect of a node (like git blame).

```bash
mu kernel blame <node_name> [path] [options]
```

**Arguments:**
- `node_name`: Name of node

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--json` | false | Output as JSON |

### `mu kernel diff`

Show semantic diff between two snapshots.

```bash
mu kernel diff <from_commit> <to_commit> [path] [options]
```

**Arguments:**
- `from_commit`: Starting commit hash/ref
- `to_commit`: Ending commit hash/ref

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--json` | false | Output as JSON |

### `mu kernel export`

Export graph in multiple formats.

```bash
mu kernel export [path] [options]
```

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--format, -f` | `mu` | Export: `mu`, `json`, `mermaid`, `d2`, `cytoscape` |
| `--output, -o` | stdout | Output file |
| `--nodes, -n` | all | Comma-separated node IDs to export |
| `--types, -t` | all | Node types: `module`, `class`, `function`, `external` |
| `--max-nodes, -m` | unlimited | Maximum nodes to export |
| `--direction` | TB | Diagram direction (TB/LR for mermaid, right/down for d2) |
| `--diagram-type` | `flowchart` | Mermaid: `flowchart` or `classDiagram` |
| `--no-edges` | false | Exclude edges from export |
| `--pretty/--compact` | pretty | JSON formatting |
| `--list-formats` | false | List available formats |

**Examples:**
```bash
# MU format (LLM-optimized)
mu kernel export --format mu

# JSON export
mu kernel export --format json --output graph.json

# Mermaid diagram
mu kernel export --format mermaid --direction LR

# D2 diagram
mu kernel export --format d2 --output arch.d2

# Cytoscape.js format for visualization
mu kernel export --format cytoscape --output graph.cyto.json

# Export specific types
mu kernel export --format mermaid --types class,function

# Limit for large codebases
mu kernel export --format json --max-nodes 100
```

---

## Daemon Commands

### `mu daemon`

Manage the MU daemon for real-time file watching and HTTP/WebSocket API.

```bash
mu daemon <subcommand>
```

**Subcommands:**

| Command | Description |
|---------|-------------|
| `start` | Start daemon in background |
| `stop` | Stop running daemon |
| `status` | Check daemon status |
| `run` | Run daemon in foreground (debugging) |

**Options for `start` and `run`:**
| Option | Default | Description |
|--------|---------|-------------|
| `--port, -p` | `8765` | Server port |
| `--host` | `127.0.0.1` | Server host |
| `--watch, -w` | project root | Additional paths to watch (multiple allowed) |

**Examples:**
```bash
# Start daemon in background
mu daemon start .

# Start with custom port
mu daemon start . --port 9000

# Watch multiple directories
mu daemon start . --watch ./src --watch ./lib

# Check status
mu daemon status

# Check status as JSON
mu daemon status --json

# Stop daemon
mu daemon stop

# Run in foreground (for debugging)
mu daemon run .
```

**HTTP API Endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/status` | GET | Daemon and graph statistics |
| `/nodes/{id}` | GET | Node details by ID |
| `/nodes/{id}/neighbors` | GET | Node neighbors |
| `/query` | POST | Execute MUQL query |
| `/context` | POST | Smart context extraction |
| `/export` | GET | Export graph in various formats |
| `/live` | WebSocket | Real-time graph change notifications |

**Example API Usage:**
```bash
# Check daemon status
curl http://localhost:8765/status

# Get node by ID
curl http://localhost:8765/nodes/fn:auth.login

# Execute MUQL query
curl -X POST http://localhost:8765/query \
  -H "Content-Type: application/json" \
  -d '{"muql": "SELECT * FROM functions WHERE complexity > 20"}'

# Get context for a question
curl -X POST http://localhost:8765/context \
  -H "Content-Type: application/json" \
  -d '{"question": "How does authentication work?", "max_tokens": 4000}'

# Export as JSON
curl "http://localhost:8765/export?format=json"

# WebSocket for live updates
websocat ws://localhost:8765/live
```

### `mu cache`

Manage the MU cache.

```bash
mu cache <subcommand>
```

**Subcommands:**

| Command | Description |
|---------|-------------|
| `stats` | Show cache statistics |
| `clear` | Clear all cached data |
| `expire` | Remove expired entries |

**Examples:**
```bash
mu cache stats
mu cache clear
mu cache expire
```

---

## MCP Commands

### `mu mcp serve`

Start MCP (Model Context Protocol) server for AI assistants like Claude Code.

```bash
mu mcp serve [options]
```

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--http` | false | Use HTTP transport instead of stdio |
| `--port, -p` | 8000 | Port for HTTP transport |

**Examples:**
```bash
# Start stdio server (for Claude Code)
mu mcp serve

# Start HTTP server
mu mcp serve --http --port 9000
```

**Configure in Claude Code** (`~/.claude/mcp_servers.json`):
```json
{
  "mu": {
    "command": "mu",
    "args": ["mcp", "serve"]
  }
}
```

### `mu mcp tools`

List available MCP tools.

```bash
mu mcp tools
```

**Available Tools:**
| Tool | Description |
|------|-------------|
| `mu_query` | Execute MUQL queries against the code graph |
| `mu_context` | Extract smart context for natural language questions |
| `mu_deps` | Show dependencies of a code node |
| `mu_node` | Look up a specific code node by ID |
| `mu_search` | Search for code nodes by name pattern |
| `mu_status` | Get MU daemon status and codebase statistics |

### `mu mcp test`

Test MCP tools without starting server.

```bash
mu mcp test
```

Runs each MCP tool with a simple test case and reports PASS/FAIL status. Useful for verifying setup.

---

## Contracts Commands

### `mu contracts init`

Create a template `.mu-contracts.yml` file for architecture verification.

```bash
mu contracts init [path] [options]
```

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--force, -f` | false | Overwrite existing file |

### `mu contracts verify`

Verify architectural contracts against codebase.

```bash
mu contracts verify [path] [options]
```

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--contract-file, -c` | `.mu-contracts.yml` | Contract file path |
| `--format, -f` | `text` | Output: `text`, `json`, `junit` |
| `--no-color` | false | Disable colored output |
| `--fail-fast` | false | Stop on first error |
| `--only` | all | Only run contracts matching pattern |
| `--output, -o` | stdout | Output file |

**Examples:**
```bash
# Basic verification
mu contracts verify

# JUnit output for CI
mu contracts verify --format junit --output test-results.xml

# Run specific contracts
mu contracts verify --only "no-circular-*"

# Fail fast mode
mu contracts verify --fail-fast
```

**Contract File Example (`.mu-contracts.yml`):**
```yaml
contracts:
  - name: no-circular-imports
    description: Prevent circular import dependencies
    rule:
      type: analyze
      query: circular_imports
    expect:
      type: empty
    severity: error

  - name: max-function-complexity
    description: Functions should have complexity < 50
    rule:
      type: query
      muql: "SELECT * FROM nodes WHERE type = 'function' AND complexity > 50"
    expect:
      type: empty
    severity: warning

  - name: parser-no-external-deps
    description: Parser module should not import external packages
    rule:
      type: dependency
      source: "parser/*"
      forbid: ["requests", "httpx", "aiohttp"]
    expect:
      type: empty
    severity: error
```

---

## Configuration

MU looks for configuration in this order:
1. CLI flags
2. `.murc.toml` in current directory
3. `.murc.toml` in home directory
4. Environment variables (`MU_*` prefix)
5. Built-in defaults

### `.murc.toml` Example

```toml
[scanner]
ignore = ["node_modules/", ".git/", "__pycache__/", "*.test.ts"]
max_file_size_kb = 1000

[reducer]
complexity_threshold = 20

[output]
format = "mu"

[llm]
provider = "anthropic"
model = "claude-3-haiku-20240307"

[embeddings]
provider = "openai"              # or "local"
model = "text-embedding-3-small" # or "all-MiniLM-L6-v2" for local
batch_size = 100
cache_embeddings = true

[embeddings.openai]
api_key_env = "OPENAI_API_KEY"
dimensions = 1536

[embeddings.local]
model = "sentence-transformers/all-MiniLM-L6-v2"
device = "auto"  # auto, cpu, cuda, mps
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `MU_CONFIG` | Path to config file |
| `MU_CACHE_DIR` | Cache directory |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `OPENROUTER_API_KEY` | OpenRouter API key |

### `mu kernel muql`

Execute MUQL queries against a MUbase database.

```bash
mu kernel muql <path> [query] [options]
```

**Arguments:**
- `path`: Path to directory containing `.mubase` file
- `query`: MUQL query to execute (optional if using `-i`)

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `-f, --format` | `table` | Output format: `table`, `json`, `csv` |
| `-i, --interactive` | false | Launch interactive REPL |
| `--explain` | false | Show execution plan |
| `--db` | `.mubase` | Path to database file |

**Examples:**
```bash
# Execute a single query
mu kernel muql . "SELECT * FROM functions WHERE complexity > 20"

# JSON output
mu kernel muql . -f json "SELECT name, complexity FROM classes"

# Interactive REPL mode
mu kernel muql . -i

# Show execution plan
mu kernel muql . --explain "SHOW dependencies OF MUbase DEPTH 2"
```

**MUQL Query Types:**

| Type | Description | Example |
|------|-------------|---------|
| SELECT | Query nodes with filters | `SELECT * FROM functions WHERE complexity > 20` |
| SHOW | Explore relationships | `SHOW dependencies OF MUbase DEPTH 2` |
| FIND | Pattern-based search | `FIND functions MATCHING "test_%"` |
| PATH | Find paths between nodes | `PATH FROM cli TO parser MAX DEPTH 5` |
| ANALYZE | Built-in analysis | `ANALYZE complexity` |

**REPL Commands:**

| Command | Description |
|---------|-------------|
| `.help` | Show help |
| `.exit` | Exit REPL |
| `.format <fmt>` | Set output format |
| `.explain` | Toggle explain mode |
| `.history` | Show query history |
| `.clear` | Clear screen |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Configuration error |
| 3 | Parse error |
| 4 | IO error |
