# Changelog

All notable changes to MU will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.3] - Unreleased

### Architecture

- **MCP-first design** — MU is now primarily an MCP server. Most functionality moved from CLI commands to 13 MCP tools.
- **Removed `mu-daemon` crate** — storage, search, and graph engine consolidated into `mu-cli/src/engine/`.
- **Lean CLI** — 11 commands (bootstrap, compress, status, deps, diff, impact, review, audit, mcp, doctor, completions). Query, search, path, export, and other analysis tools are now MCP-only.

### Added

- **13 MCP tools** for AI assistant integration:
  - `mu_oracle` — task-aware context retrieval (the go-to tool)
  - `mu_grok` — BM25 search + code snippets
  - `mu_find` — exact symbol lookup
  - `mu_expand` — graph traversal from seed nodes
  - `mu_read` — bulk source code retrieval
  - `mu_impact` — downstream impact analysis
  - `mu_diff` — semantic diff between git refs
  - `mu_review` — full PR review (diff + impact + audit + risk score)
  - `mu_audit` — code quality rules
  - `mu_sus` — suspicious/complex code detection
  - `mu_wtf` — git archaeology
  - `mu_enrich` — LLM summary enrichment flywheel
  - `mu_compress` — token-efficient codebase overview

- **V3 search pipeline** — three-phase cascade: exact name match, BM25 full-text search, PageRank importance tiebreak (85% BM25 + 15% PageRank)

- **Bootstrap post-processing** — PageRank importance scores, heuristic summaries (with caller/callee context from edges), BM25 full-text index on search_text

- **Enrichment flywheel** — `mu_enrich` returns candidates needing better summaries, LLM writes them, stores back. Each cycle improves future search.

### Removed

- CLI commands: `search`, `query`, `path`, `why`, `ancestors`, `cycles`, `coverage`, `export`, `patterns`, `read`, `history`, `embed`, `omg`, `yolo`, `vibe`, `zen`, `grok`, `usedby`
- Embedding-based semantic search (replaced by BM25 + importance scoring)
- Parser modules: C, C++, Kotlin, PHP, Ruby, Swift (may return later)
- `mu-daemon` crate (consolidated into `mu-cli`)

### Fixed

- MCP server now opens DuckDB in read-write mode, unblocking `mu_enrich` write-back
- Zero compiler warnings (cleaned up dead code from daemon removal)

---

## [0.0.2] - 2025-12-19

### Added

- **`mu coverage`** — Dead code detection
  - `--orphans`: Find functions with no callers (excluding entry points)
  - `--untested`: Find public functions not called by test functions

- **`mu why <from> <to>`** — Path explanation between nodes
  - Shows connection paths with edge types at each hop
  - `--all`: Show all paths, not just shortest

- **`mu review`** — PR review with risk scoring
  - Risk formula: `(caller_count * 2) + (transitive_dependents * 0.5) + (complexity_delta * 3)`
  - Risk levels: CRITICAL (>100), HIGH (>50), MEDIUM (>20), LOW
  - Test coverage gap detection, suggested reviewers

- **`uses` edges** — Composition detection (struct/class field types)

- **MCP Server** — Initial `mu_oracle` tool

### Improved

- Graph now includes 5 edge types: `contains`, `calls`, `imports`, `inherits`, `uses`

---

## [0.1.0-alpha.1] - 2024-12-14

### Added
- **Core Commands**: `bootstrap`, `status`, `doctor`, `compress`
- **Graph Analysis**: `deps`, `usedby`, `impact`, `ancestors`, `cycles`, `path`
- **Search**: `search`, `grok`, `patterns`, `read`
- **MUQL**: SQL and terse query syntax
- **Semantic Diff**: `diff`, `history`
- **Export**: JSON, Mermaid, D2, Cytoscape
- **Embeddings**: MU-SIGMA-V2 BERT model (384d, local inference via Candle)
- **Language Support**: Python, TypeScript, JavaScript, Go, Rust, Java, C#

### Technical
- Pure Rust, DuckDB storage, tree-sitter parsing, Candle ML inference
