# Changelog

All notable changes to MU will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0-alpha.1] - 2024-12-14

### Added
- **Core Commands**
  - `mu bootstrap` - Initialize and build code graph in one step
  - `mu status` - Show project status and statistics
  - `mu doctor` - Health checks for MU installation
  - `mu compress` - Compress codebase into hierarchical MU sigil format (92-98% compression)

- **Graph Analysis**
  - `mu deps <node>` - Show dependencies of a node
  - `mu usedby <node>` - Show what depends on a node (reverse dependencies)
  - `mu impact <node>` - Find downstream impact (what breaks if this changes)
  - `mu ancestors <node>` - Find upstream ancestors
  - `mu cycles` - Detect circular dependencies
  - `mu path <from> <to>` - Find shortest path between nodes
  - Added `--depth` flag to `impact` and `ancestors` commands

- **Search & Discovery**
  - `mu search <query>` - Semantic search across the codebase
  - `mu grok <question>` - Extract relevant context for a question
  - `mu patterns` - Detect code patterns (naming conventions, architecture)
  - `mu read <file>` - Read files with MU context

- **MUQL Query Language**
  - SQL-like syntax: `SELECT * FROM functions WHERE complexity > 10`
  - Terse syntax: `fn c>50 sort c- 10` (60-85% fewer tokens)
  - Interactive REPL with `mu query -i`

- **Semantic Diff**
  - `mu diff <ref1> <ref2>` - Semantic diff between git refs
  - Breaking change detection
  - `mu history <node>` - Change history for a node

- **Export Formats**
  - MU format (LLM-optimized)
  - JSON, Mermaid, D2, Cytoscape

- **Vibes (Fun Commands)**
  - `mu yolo <node>` - Impact analysis with flair
  - `mu sus` - Find suspicious code patterns
  - `mu wtf <file>` - Git archaeology
  - `mu omg` - OMEGA compressed overview
  - `mu vibe` - Naming convention check
  - `mu zen` - Clear caches

- **Embedding Model**
  - MU-SIGMA-V2: BERT model trained on code
  - 384 dimensions, 512 max tokens
  - No API keys required - runs locally

- **Language Support**
  - Python, TypeScript, JavaScript, Go, Rust, Java, C#
  - TypeScript path alias resolution (`@/*`, `~/*`)

### Improved
- Ambiguous node resolution now shows helpful suggestions
- Better error messages throughout

### Technical
- Pure Rust implementation
- DuckDB for graph storage
- Tree-sitter for multi-language parsing
- Candle for local ML inference

---

## [Unreleased]

### Planned
- `mu-viz`: Interactive graph visualization
- IDE integrations (VS Code, JetBrains)
- MCP server for AI assistants (Claude Code)
