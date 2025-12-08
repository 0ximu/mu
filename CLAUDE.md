# CLAUDE.md

This file provides quick-reference guidance for Claude Code. For detailed documentation, see the nested CLAUDE.md files.

## Documentation Structure

```
.claude/CLAUDE.md                     # Project-wide standards, pre-PR checklist
src/mu/parser/CLAUDE.md               # Multi-language AST extraction
src/mu/llm/CLAUDE.md                  # LLM provider integration
src/mu/assembler/CLAUDE.md            # Import resolution, dependency graph
src/mu/reducer/CLAUDE.md              # Transformation rules, compression
src/mu/diff/CLAUDE.md                 # Semantic diff computation
src/mu/security/CLAUDE.md             # Secret detection and redaction
src/mu/kernel/CLAUDE.md               # Graph database for code analysis
src/mu/kernel/temporal/CLAUDE.md      # Git-linked snapshots and time-travel
src/mu/kernel/embeddings/CLAUDE.md    # Vector embeddings for semantic search
src/mu/kernel/context/CLAUDE.md       # Smart context extraction for questions
src/mu/kernel/export/CLAUDE.md        # Multi-format graph export
src/mu/daemon/CLAUDE.md               # Real-time daemon mode and API
src/mu/mcp/CLAUDE.md                  # MCP server for AI assistants
src/mu/agent/CLAUDE.md                # MU Agent - code structure specialist
tests/CLAUDE.md                       # Testing standards and patterns
```

## Project Overview

MU (Machine Understanding) is a semantic compression tool that translates codebases into token-efficient representations optimized for LLM comprehension. Achieves 92-98% compression while preserving semantic signal.

## Quick Commands

```bash
# Development (uv handles virtualenv automatically)
uv sync                                    # Install dependencies
uv run pytest                              # Run tests
uv run mypy src/mu                         # Type check
uv run ruff check src/ && uv run ruff format src/  # Lint + format

# Alternative: pip (requires manual venv activation)
# pip install -e ".[dev]"

# CLI (use uv run for all mu commands)
uv run mu init                 # Create .murc.toml config
uv run mu scan <path>          # Analyze structure
uv run mu compress <path>      # Generate MU output
uv run mu compress <path> --llm # With LLM summarization
uv run mu view <file.mu>       # Render with syntax highlighting
uv run mu diff <base> <head>   # Semantic diff

# MUQL Queries
uv run mu query "SELECT..."    # Execute MUQL query
uv run mu q "SELECT..."        # Short alias
uv run mu kernel muql -i       # Interactive REPL

# Kernel/Temporal
uv run mu kernel init .        # Initialize .mu/mubase
uv run mu kernel build .       # Build graph from codebase
uv run mu kernel stats         # Show graph statistics
uv run mu kernel snapshot      # Create snapshot at HEAD
uv run mu kernel history <node> # Show node history
uv run mu kernel blame <node>  # Show blame info

# Kernel/Export
uv run mu kernel export --format mu       # Export as MU text
uv run mu kernel export --format json     # Export as JSON
uv run mu kernel export --format mermaid  # Export as Mermaid diagram
uv run mu kernel export --format d2       # Export as D2 diagram
uv run mu kernel export --format cytoscape # Export for Cytoscape.js

# Semantic Search & Context
uv run mu kernel embed .       # Generate embeddings
uv run mu kernel search "query" # Natural language search
uv run mu kernel context "question" # Smart context extraction

# Daemon (real-time updates)
uv run mu daemon start .       # Start daemon in background
uv run mu daemon status        # Check daemon status
uv run mu daemon stop          # Stop running daemon
uv run mu daemon run .         # Run in foreground (debugging)

# Cache Management
uv run mu cache stats          # Show cache statistics
uv run mu cache clear          # Clear all cached data
uv run mu cache expire         # Remove expired entries

# CLI Introspection (agent-proofing)
uv run mu describe             # Output CLI interface description
uv run mu describe --format json # JSON format for tooling
uv run mu describe --format markdown # Markdown format for documentation

# MCP Server (AI assistant integration)
uv run mu mcp serve            # Start MCP server (stdio for Claude Code)
uv run mu mcp serve --http     # Start with HTTP transport
uv run mu mcp tools            # List available MCP tools
uv run mu mcp test             # Test MCP tools

# MCP Bootstrap Flow (for agents)
# 1. mu_status() → get next_action
# 2. mu_init(".") → create .murc.toml (if needed)
# 3. mu_build(".") → build .mu/mubase graph
# 4. mu_context("question") → query works!
# 5. mu_semantic_diff("main", "HEAD") → PR review

# Migration (legacy files to .mu/ directory)
uv run mu migrate              # Migrate .mubase, .mu-cache/, etc. to .mu/
uv run mu migrate --dry-run    # Show what would be migrated

# Architecture Contracts
uv run mu contracts init       # Create .mu/contracts.yml template
uv run mu contracts verify     # Verify architectural rules

# MU Agent (code structure specialist)
uv run mu agent ask "question" # Ask about codebase structure
uv run mu agent interactive    # Start interactive session
uv run mu agent query "MUQL"   # Direct MUQL query (bypass LLM)
uv run mu agent deps NODE      # Show dependencies
uv run mu agent impact NODE    # Show impact analysis
uv run mu agent cycles         # Detect circular dependencies
```

## Data Directory Structure

All MU data files are stored in the `.mu/` directory:

```
.mu/
├── mubase          # Graph database (DuckDB)
├── mubase.wal      # DuckDB write-ahead log
├── cache/          # File and LLM response cache
├── contracts.yml   # Architecture contracts
└── daemon.pid      # Daemon process ID file

.murc.toml          # Configuration (stays at project root)
```

Use `mu migrate` to move legacy files (`.mubase`, `.mu-cache/`, etc.) to the new structure.

## Pipeline

```
Source Files -> Scanner -> Parser -> Reducer -> Assembler -> Exporter
                  |           |          |          |
              manifest    ModuleDef  Reduced   ModuleGraph -> MU/JSON/MD
```

## Key Models

- **`ModuleDef`**: File-level AST (imports, classes, functions)
- **`ReducedModule`**: Post-compression with `needs_llm` markers
- **`ModuleGraph`**: Dependency graph with resolved imports
- **`DiffResult`**: Semantic changes between versions
- **`ContextResult`**: Smart context extraction result with MU output
- **`Snapshot`**: Point-in-time graph state linked to git commit
- **`ExportResult`**: Multi-format export output with error handling
- **`DaemonConfig`**: Daemon server configuration
- **`GraphEvent`**: Real-time graph change notifications

## Agent-Proofing Modules

- **`client.py`**: Daemon communication client for programmatic MU integration
- **`describe.py`**: CLI introspection and self-description (mu/json/markdown formats)
- **`mcp/`**: MCP server exposing MU tools for Claude Code and other AI assistants
- **`agent/`**: MU Agent - code structure specialist running on Haiku (60x cheaper)

## Supported Languages

Python, TypeScript, JavaScript, Go, Java, Rust, C#

## Rust Core Performance (mu-core)

- **Scanner**: 6.9x faster than Python, respects .gitignore/.muignore
- **Semantic Diff**: Entity-level changes with breaking change detection
- **Incremental Parser**: <5ms updates for daemon mode
- **Graph Reasoning**: petgraph-backed O(V+E) algorithms (impact, ancestors, cycles)

## MU Sigils

- `!` Module/Service
- `$` Entity/Class (`<` inheritance)
- `#` Function/Method
- `@` Dependencies
- `::` Annotations
- `->` Return, `=>` Mutation

## Keeping Documentation Current

When making significant changes to a module (new features, architectural changes, new patterns), update the corresponding CLAUDE.md file. This ensures Claude Code has accurate context for future work.
