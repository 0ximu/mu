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
tests/CLAUDE.md                       # Testing standards and patterns
```

## Project Overview

MU (Machine Understanding) is a semantic compression tool that translates codebases into token-efficient representations optimized for LLM comprehension. Achieves 92-98% compression while preserving semantic signal.

## Quick Commands

```bash
# Development
pip install -e ".[dev]"        # Install
pytest                          # Test
mypy src/mu                    # Type check
ruff check src/ && ruff format src/  # Lint + format

# CLI
mu scan <path>                 # Analyze structure
mu compress <path>             # Generate MU output
mu compress <path> --llm       # With LLM summarization
mu diff <base> <head>          # Semantic diff

# Kernel/Temporal
mu kernel snapshot <path>      # Create snapshot at HEAD
mu kernel history <node>       # Show node history
mu kernel blame <node>         # Show blame info

# Kernel/Export
mu kernel export <path> --format mu       # Export as MU text
mu kernel export <path> --format json     # Export as JSON
mu kernel export <path> --format mermaid  # Export as Mermaid diagram
mu kernel export <path> --format d2       # Export as D2 diagram
mu kernel export <path> --format cytoscape # Export for Cytoscape.js

# Daemon (real-time updates)
mu daemon start .                    # Start daemon in background
mu daemon status                     # Check daemon status
mu daemon stop                       # Stop running daemon
mu daemon run .                      # Run in foreground (debugging)

# MUQL Queries (agent-proofing)
mu query "SELECT..."                 # Execute MUQL query (alias for mu kernel muql)
mu q "SELECT..."                     # Short alias

# CLI Introspection (agent-proofing)
mu describe                          # Output CLI interface description
mu describe --format json            # JSON format for tooling
mu describe --format markdown        # Markdown format for documentation
```

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

## Supported Languages

Python, TypeScript, JavaScript, Go, Java, Rust, C#

## MU Sigils

- `!` Module/Service
- `$` Entity/Class (`<` inheritance)
- `#` Function/Method
- `@` Dependencies
- `::` Annotations
- `->` Return, `=>` Mutation

## Keeping Documentation Current

When making significant changes to a module (new features, architectural changes, new patterns), update the corresponding CLAUDE.md file. This ensures Claude Code has accurate context for future work.
