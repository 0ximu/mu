<p align="center">
  <img src="docs/assets/intro.gif" alt="MU Demo" width="600"/>
</p>

<h1 align="center">Machine Understanding</h1>

<p align="center">
  <strong>Semantic compression for AI-native development.</strong>
</p>

MU translates codebases into token-efficient representations optimized for LLM comprehension. Feed your entire codebase to an AI in seconds, not hours.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Tests](https://img.shields.io/badge/tests-passing-green.svg)]()

## The Problem

- LLMs choke on large codebases (500k+ lines exceed context windows)
- 90% of code is boilerplate, patterns, and syntactic noise
- Context windows are precious — wasted on syntax instead of semantics
- Current documentation is always out of date

## The Solution

MU is not a language you write — it's a language you **translate into**. Any codebase goes in, semantic signal comes out.

```
Input:  66,493 lines of Python
Output:  5,156 lines of MU (92% compression)
Result: LLM correctly answers architectural questions
```

## Validated Results

| Codebase | Original | MU Output | Compression |
|----------|----------|-----------|-------------|
| Production Backend (Python) | 66k lines | 5k lines | 92% |
| API Gateway (TypeScript) | 407k lines | 6.7k lines | 98% |

**Real test:** Fed MU output to Gemini, asked "How does ride matching work?" — it correctly explained the scoring pipeline, async event workflow, and identified Redis as a SPOF.

## Installation

```bash
# Using uv (recommended)
git clone https://github.com/0ximu/mu.git
cd mu
uv sync

# Or with pip
git clone https://github.com/0ximu/mu.git
cd mu
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

**Binary releases** are also available for standalone deployment (no Python installation required). See [Releases](https://github.com/0ximu/mu/releases) for platform-specific binaries.

## Quick Start

```bash
# 1. Compress your codebase
mu compress ./src --output system.mu

# 2. Feed to any LLM
cat system.mu | pbcopy  # Copy to clipboard (macOS)

# 3. Ask architectural questions
# "What services would break if Redis goes down?"
# "How does authentication work?"
# "Explain the data flow for user registration"
```

## CLI Commands

### Core Commands

```bash
mu init                             # Create .murc.toml config file
mu scan <path>                      # Analyze codebase structure
mu compress <path>                  # Generate MU output
mu compress <path> -o system.mu     # Save to file
mu compress <path> -f json          # JSON output format
mu compress <path> --llm            # Enable LLM summarization
mu compress <path> --local          # Local-only mode (Ollama)
mu view <file.mu>                   # Render MU with syntax highlighting
mu view <file.mu> -f html -o out.html  # Export to HTML
mu diff <base> <head>               # Semantic diff between git refs
mu man                              # Interactive manual
mu man quickstart                   # Topic: intro, quickstart, sigils, query, workflows
```

### MUbase Graph Database

```bash
mu kernel init .                    # Initialize .mubase graph database
mu kernel build .                   # Build/rebuild graph from codebase
mu kernel stats                     # Show graph statistics
mu kernel query --name "User%"      # Query nodes by pattern
mu kernel deps <node>               # Show dependencies of a node
mu kernel deps <node> -r            # Show reverse dependencies (dependents)
```

### MUQL Queries (SQL-like interface)

```bash
mu query "SELECT * FROM nodes WHERE type = 'function'"    # MUQL query
mu q "SELECT name FROM nodes WHERE complexity > 10"       # Short alias
mu kernel muql -i                   # Interactive REPL
mu kernel muql --explain "SELECT..."  # Show query execution plan
```

### Semantic Search & Context

```bash
mu kernel embed .                   # Generate embeddings for semantic search
mu kernel embed . --local           # Use local embeddings (no API)
mu kernel search "authentication"   # Natural language code search
mu kernel context "How does auth work?"  # Smart context extraction for questions
mu kernel context "..." --max-tokens 4000  # Limit output size
```

### Temporal Features (Time-Travel)

```bash
mu kernel snapshot                  # Create snapshot at current commit
mu kernel snapshots                 # List all snapshots
mu kernel history <node>            # Show change history for a node
mu kernel blame <node>              # Git-blame style attribution
mu kernel diff <commit1> <commit2>  # Semantic diff between commits
```

### Export Formats

```bash
mu kernel export --format mu        # MU format (default, LLM-optimized)
mu kernel export --format json      # JSON export
mu kernel export --format mermaid   # Mermaid diagram
mu kernel export --format d2        # D2 diagram
mu kernel export --format cytoscape # Cytoscape.js format
```

### Daemon Mode (Real-Time Updates)

```bash
mu daemon start .                   # Start daemon in background
mu daemon status                    # Check daemon status
mu daemon stop                      # Stop running daemon
mu daemon run .                     # Run in foreground (debugging)
```

### MCP Server (AI Assistant Integration)

```bash
mu mcp serve                        # Start MCP server (stdio for Claude Code)
mu mcp serve --http --port 9000     # Start with HTTP transport
mu mcp tools                        # List available MCP tools
```

### Architecture Contracts

```bash
mu contracts init                   # Create .mu-contracts.yml template
mu contracts verify                 # Verify architectural rules
mu contracts verify --format junit  # JUnit XML output for CI
```

### Agent-Proofing

```bash
mu describe                         # Self-describe CLI for AI agents
mu describe --format json           # JSON format
mu describe --format markdown       # Markdown documentation
```

### Cache Management

```bash
mu cache clear                      # Clear all cached data
mu cache stats                      # Show cache statistics
mu cache expire                     # Remove expired entries
```

## Output Format

MU uses a sigil-based syntax optimized for LLM parsing:

```mu
# MU v1.0
# source: /path/to/codebase
# modules: 257

## Module Dependencies
!auth_service -> jwt, bcrypt, sqlalchemy
!ride_service -> geoalchemy2, redis

## Modules

!module auth_service
@deps [jwt, bcrypt, sqlalchemy.ext.asyncio]

$User < BaseModel
  @attrs [id, email, hashed_password, created_at]
  #authenticate(email: str, password: str) -> Optional[User]
  #async create(data: UserCreate) -> User

#async login(credentials: LoginRequest) -> TokenResponse
#async refresh_token(token: str) -> TokenResponse
```

### Sigils

| Sigil | Meaning | Example |
|-------|---------|---------|
| `!` | Module/Service | `!module AuthService` |
| `$` | Entity/Class | `$User < BaseModel` |
| `#` | Function/Method | `#authenticate(email) -> User` |
| `@` | Metadata/Deps | `@deps [jwt, bcrypt]` |
| `::` | Annotation | `:: complexity:146` |

### Operators

| Operator | Meaning | Example |
|----------|---------|---------|
| `->` | Returns/Output | `#func(x) -> Result` |
| `=>` | State mutation | `status => PAID` |
| `<` | Inherits from | `$Admin < User` |

## Configuration

Create `.murc.toml` in your project:

```toml
[scanner]
ignore = ["node_modules/", ".git/", "__pycache__/", "*.test.ts"]
max_file_size_kb = 1000

[reducer]
complexity_threshold = 20  # Flag functions for LLM summarization

[output]
format = "mu"  # or "json"
```

## Supported Languages

| Language | Status |
|----------|--------|
| Python | ✅ Full support |
| TypeScript | ✅ Full support |
| JavaScript | ✅ Full support |
| C# | ✅ Full support |
| Go | ✅ Full support |
| Rust | ✅ Full support |
| Java | ✅ Full support |

## How It Works

```
Source Code → Scanner → Parser → Reducer → MU Output
                │          │         │
            manifest    AST     filtered &
                       data     formatted
```

1. **Scanner**: Walks filesystem, detects languages, filters noise
2. **Parser**: Tree-sitter extracts AST (classes, functions, imports)
3. **Reducer**: Applies transformation rules, strips boilerplate
4. **Generator**: Outputs MU format with sigils and dependency graph

### What Gets Stripped (Noise)

- Standard library imports
- Boilerplate (getters, setters, constructors)
- Dunder methods (`__repr__`, `__str__`, etc.)
- Trivial functions (< 3 AST nodes)
- `self`/`cls`/`this` parameters

### What Gets Kept (Signal)

- Function signatures with types
- Class inheritance
- External dependencies
- Async/static/decorator metadata
- Complex function annotations

## Example Prompts for LLMs

After generating MU output, try these prompts:

```
"What is the authentication flow in this codebase?"
"How does [feature X] work?"
"Which services would be affected if [dependency Y] goes down?"
"Explain the domain structure of this application"
"What are the main database models and their relationships?"
"Identify potential race conditions or concurrency issues"
```

## Development

```bash
# Run tests
uv run pytest

# Run specific test file
uv run pytest tests/unit/test_parser.py -v

# Type checking
uv run mypy src/mu

# Linting
uv run ruff check src/
```

## LLM Integration

MU supports multiple LLM providers for enhanced function summarization:

```bash
# With Anthropic (requires ANTHROPIC_API_KEY)
mu compress ./src --llm

# With OpenAI (requires OPENAI_API_KEY)
mu compress ./src --llm --llm-provider openai

# Local-only with Ollama (no data sent externally)
mu compress ./src --llm --local

# Disable secret redaction (use with caution)
mu compress ./src --llm --no-redact
```

### Security & Privacy

- **Secret detection**: Automatically redacts API keys, tokens, passwords, private keys
- **Local mode**: Process codebases without any external API calls
- **Privacy first**: No code leaves your machine without explicit consent

## Agent-Friendly Features

MU is designed to be easily integrated with AI coding agents:

### MCP Server for Claude Code

MU provides a Model Context Protocol (MCP) server for seamless integration with Claude Code and other AI assistants:

```bash
# Start MCP server (stdio mode for Claude Code)
mu mcp serve

# Available MCP tools:
# - mu_query: Execute MUQL queries against the code graph
# - mu_context: Extract smart context for natural language questions
# - mu_deps: Show dependencies of a code node
# - mu_node: Look up a specific code node by ID
# - mu_search: Search for code nodes by name pattern
# - mu_status: Get MU daemon status and codebase statistics
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

### Query Your Codebase

```bash
# MUQL queries (SQL-like syntax)
mu query "SELECT name, complexity FROM nodes WHERE type = 'function' AND complexity > 10"
mu q "SELECT * FROM nodes WHERE name LIKE '%User%'"

# Interactive REPL
mu kernel muql -i

# Query types: SELECT, SHOW, FIND, PATH, ANALYZE
mu q "SHOW deps OF 'UserService'"
mu q "PATH FROM 'auth_service' TO 'database'"
mu q "ANALYZE complexity"
```

### Smart Context Extraction

```bash
# Extract relevant context for natural language questions
mu kernel context "How does authentication work?"
mu kernel context "What happens when a user logs in?" --max-tokens 4000

# Semantic search with embeddings
mu kernel embed .                    # Generate embeddings first
mu kernel search "error handling"    # Natural language search
```

### Self-Description for Agents

```bash
# Generate a complete CLI reference for AI agents
mu describe                    # Default: MU format
mu describe --format json      # Structured JSON
mu describe --format markdown  # Markdown documentation

# Pipe to your agent's context
mu describe | pbcopy
```

The `mu describe` command outputs comprehensive CLI documentation optimized for AI agents, including all commands, arguments, options, and usage patterns.

## Roadmap

- [x] Core CLI (scan, compress, view, diff)
- [x] Multi-language parsing (Python, TypeScript, JavaScript, C#, Go, Rust, Java)
- [x] Transformation rules engine
- [x] MU format generator
- [x] LLM-enhanced summarization (Anthropic, OpenAI, Ollama, OpenRouter)
- [x] Caching (incremental processing)
- [x] `mu view` - render MU with syntax highlighting
- [x] Secret detection and redaction
- [x] HTML/Markdown export
- [x] `mu diff` - semantic diff between git refs
- [x] VS Code extension (syntax highlighting, commands)
- [x] GitHub Action for CI/CD integration
- [x] MUbase graph database with DuckDB
- [x] MUQL query language with interactive REPL
- [x] Vector embeddings for semantic search
- [x] Smart context extraction for questions
- [x] Temporal features (snapshots, history, blame)
- [x] Multi-format export (Mermaid, D2, Cytoscape)
- [x] Real-time daemon mode with WebSocket API
- [x] MCP server for AI assistants (Claude Code)
- [x] Architecture contracts verification
- [ ] mu-viz: Interactive graph visualization
- [ ] IDE integrations (beyond VS Code)

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for guidelines.

## License

Apache License 2.0 - see [LICENSE](./LICENSE) for details.

---

**Give AI the ability to understand any codebase in seconds, not hours.**
