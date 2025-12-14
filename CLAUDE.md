# CLAUDE.md

This file provides quick-reference guidance for Claude Code. MU is now a pure Rust project.

## Project Structure

```
mu-cli/          # CLI application
mu-core/         # Parser, scanner, graph algorithms
mu-daemon/       # Storage layer (DuckDB), embedding trait
mu-embeddings/   # MU-SIGMA-V2 embedding model
mu-sigma/        # Training data pipeline (Python, for model training only)
models/          # Trained model weights
```

## Project Overview

MU (Machine Understanding) is a semantic code intelligence tool. It parses codebases into a graph database and provides fast queries, semantic search, and diff analysis.

## Quick Commands

```bash
# Build
cargo build --release

# Run (after build, binary is in target/release/mu)
mu bootstrap              # Initialize + build graph + embeddings
mu status                 # Show project status

# Query
mu query "SELECT * FROM functions WHERE complexity > 10"
mu q "fn c>50"            # Terse: functions with complexity > 50
mu q "deps Auth d2"       # Terse: dependencies of Auth, depth 2

# Graph Reasoning
mu deps NODE              # Show dependencies
mu deps NODE -r           # Show what depends on NODE
mu impact NODE            # What breaks if I change NODE?
mu ancestors NODE         # What does NODE depend on?
mu cycles                 # Detect circular dependencies

# Analysis
mu diff main HEAD         # Semantic diff between git refs
mu patterns               # Detect code patterns
mu search "query"         # Semantic search (requires embeddings)
mu grok "question"        # LLM-powered Q&A

# Export
mu export -F mermaid      # Export as Mermaid diagram
mu export -F json         # Export as JSON
mu export -F d2           # Export as D2 diagram
mu export -F json -l 100  # Export max 100 nodes

# Vibes (fun aliases)
mu yolo NODE              # Impact analysis
mu sus                    # Find suspicious patterns
mu wtf FILE               # Git archaeology
mu omg                    # Summarize recent changes
```

## MUQL Query Language

```sql
-- Full SQL syntax
SELECT name, complexity FROM functions WHERE complexity > 10 ORDER BY complexity DESC LIMIT 20

-- Terse syntax (60-85% fewer tokens)
fn c>50 sort c- 10        -- Functions with complexity > 50, sorted desc, limit 10
cls n~'Service'           -- Classes matching 'Service'
deps Auth d2              -- Dependencies of Auth, depth 2
rdeps Parser              -- What depends on Parser
```

## Key Types

- **Node**: Code entity (function, class, module) with id, name, type, complexity
- **Edge**: Relationship (calls, imports, inherits, contains)
- **ModuleDef**: Parsed file with imports, classes, functions

## Supported Languages

Python, TypeScript, JavaScript, Go, Java, Rust, C#

## Rust Crates

| Crate | Purpose |
|-------|---------|
| `mu-cli` | CLI commands, output formatting |
| `mu-core` | Tree-sitter parsing, graph algorithms, diff |
| `mu-daemon` | DuckDB storage layer, embedding trait |
| `mu-embeddings` | MU-SIGMA-V2 model inference via Candle |

## Embedding Model

MU uses **MU-SIGMA-V2**, a BERT model trained on code for semantic search. The model weights are compiled into the binary via `include_bytes!`.

```rust
// mu-embeddings/src/lib.rs
pub const MODEL_BYTES: &[u8] = include_bytes!("../models/mu-sigma-v2/model.safetensors");
```

- Dimension: 384
- Max sequence: 512 tokens
- Pooling: Mean

## Development

```bash
# Check compilation
cargo check

# Run tests
cargo test

# Format
cargo fmt

# Lint
cargo clippy
```

## Troubleshooting

```bash
# Fresh start (clears database and rebuilds)
rm -rf .mu && mu bootstrap

# Database errors about schema/columns
# The database may be from an old version. Delete and rebuild:
rm -rf .mu && mu bootstrap

# Check what's in the database
duckdb .mu/mubase "SELECT type, COUNT(*) FROM nodes GROUP BY type"
duckdb .mu/mubase "SELECT type, COUNT(*) FROM edges GROUP BY type"
```
