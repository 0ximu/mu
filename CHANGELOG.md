# Changelog

All notable changes to MU will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.4] - 2026-07-09

Correctness and trust release, driven by a blind eval on a 920k-line C#
microservices codebase (agents answering real questions with MU tools vs
plain grep). Every fix below traces to a measured failure.

### Added

- **Message-bus impact edges** - MassTransit `Publish<T>` and `IConsumer<T>`
  are now connected through shared message nodes, so `mu_impact` traverses
  the bus: impact of a message type returns its publishers and consumers
  across services (152 dependents for a core message on the eval codebase,
  previously invisible)
- **Index staleness detection** - bootstrap stamps `indexed_at`; the MCP
  server warns in search/impact output when source files changed since the
  last bootstrap, and `mu doctor` reports index freshness
- **`mu compress --budget <tokens>`** (CLI) and `budget` param (MCP, default
  8000) - importance-ranked degradation across four detail levels with an
  always-present honest footer; the budget is a hard ceiling
- **Importance percentiles** - search/impact/compress render `imp=p87`
  instead of raw scores that round to 0.00 on large graphs
- Nested C# type declarations (`Outer.Inner`) are extracted with bases, so
  nested-class interface implementations appear in the graph
- Search matches camelCase/snake_case name words ("auth middleware" finds
  `DominaiteAuthMiddleware`) and expands common abbreviations
  (auth/config/db/repo/...) at query time
- `mu_find` accepts qualified names (`Class.Method`) and prints node ids

### Fixed

- **Parse cache ignored `--force` and binary upgrades**, silently rebuilding
  the database from stale parse results - parser fixes never reached
  unchanged files (+8.7% edges on the eval codebase once invalidated)
- C# constructor parameter types with user-defined types were dropped,
  emptying the DI receiver map (zero DI call edges on C# codebases)
- `this._field.Method()` calls did not resolve through the DI receiver map
- `mu_impact` resolved C# class names to constructors (which share the class
  name), producing near-empty blast radii; class targets also seed the BFS
  with their methods so callers are reachable (CLI and MCP)
- Zero graph dependents now carries an explicit "this does not prove
  absence" warning pointing at text references
- `calls_http` edges required a client-like receiver; any `.SendAsync(` no
  longer creates false HTTP edges
- Message nodes were keyed by the referencing module's namespace, splitting
  publisher and consumer onto disconnected nodes
- MCP `mu_compress` no longer truncates to 500 alphabetically-first nodes
- `mu_read` states exactly what was truncated and where to read the rest

## [0.0.3] - 2026-07-08

### Architecture

- **MCP-first design** - MU is now primarily an MCP server. Most functionality moved from CLI commands to 13 MCP tools.
- **Removed `mu-daemon` crate** - storage, search, and graph engine consolidated into `mu-cli/src/engine/`.
- **Removed `mu-embeddings` crate** - nothing in the product called it; search is BM25 + importance. The training pipeline and models moved to a separate research repo. The unused `embeddings` table is dropped by a schema migration (v2.2.0).
- **Lean CLI** - 11 commands (bootstrap, compress, status, deps, diff, impact, review, audit, mcp, doctor, completions). Query, search, path, export, and other analysis tools are now MCP-only.

### Added

- **13 MCP tools** for AI assistant integration:
  - `mu_grok` - BM25 search + code snippets
  - `mu_find` - exact symbol lookup by name or node ID
  - `mu_expand` - graph traversal from seed nodes
  - `mu_read` - bulk source code retrieval
  - `mu_impact` - transitive downstream impact analysis
  - `mu_diff` - semantic diff between git refs
  - `mu_review` - full PR review (diff + impact + audit + risk score)
  - `mu_audit` - code quality rules
  - `mu_sus` - suspicious/complex code detection
  - `mu_enrich` - LLM summary enrichment flywheel
  - `mu_compress` - token-efficient codebase overview
  - `mu_bootstrap` - build or rebuild the index in-session
  - `mu_configure` - project auto-configuration and enrichment workflow

- **V3 search pipeline** - three-phase cascade: exact name match, BM25 full-text search, PageRank importance tiebreak (85% BM25 + 15% PageRank), with composite importance scoring (PageRank + complexity + LOC + visibility) and trivial-utility dampening
- **Bootstrap post-processing** - importance scores, heuristic summaries (with caller/callee context from edges), BM25 full-text index on search_text
- **Enrichment flywheel** - `mu_enrich` returns candidates needing better summaries, LLM writes them, stores back. Enriched summaries survive re-bootstrap via node-level code hashing.
- **DI- and inheritance-aware call resolution** - calls through constructor-injected interfaces and inherited methods now resolve to real graph edges
- **Audit improvements** - R9 secrets rule gates matches on Shannon entropy, R5 docs rule is opt-in, `--top` bounds output (default 20)

### Removed

- CLI commands: `search`, `query`, `path`, `why`, `ancestors`, `cycles`, `coverage`, `export`, `patterns`, `read`, `history`, `embed`, `omg`, `yolo`, `vibe`, `zen`, `grok`, `usedby`
- MCP tools `mu_oracle` and `mu_wtf` (overlapped mu_grok/mu_read and plain git)
- Embedding-based semantic search (replaced by BM25 + importance scoring)
- Parser modules: C, C++, Kotlin, PHP, Ruby, Swift (may return later)
- `mu-daemon` and `mu-embeddings` crates

### Fixed

- Parser: C# methods and properties with user-defined return types lost their names
- Parser: Rust trait impl methods were attributed to the trait instead of the implementing type
- Parser: `.tsx` files were parsed with the TypeScript grammar, losing code inside JSX
- Parser: syntax errors are now flagged on `ModuleDef.has_parse_errors` instead of being silently ignored
- Complexity: Python `elif` was not counted, `with`/`assert` were; match/switch arms double-counted in Rust, Python, and C#; Java arrow switches counted nothing
- Impact analysis is truly transitive (incoming-edge BFS) in both CLI and MCP, ranked by importance
- Git-backed MCP tools (`mu_diff`, `mu_review`, `mu_audit`) run git in the project root instead of the server's launch directory
- UTF-8-safe truncation shared across all output paths (multibyte summaries no longer panic the MCP server)
- `mu doctor` compares schema versions numerically instead of lexicographically
- `mu review` sorts top affected files by impact instead of alphabetically
- Orphan-rule suppression list no longer hardcodes MU's own symbol names
- MCP server now opens DuckDB in read-write mode, unblocking `mu_enrich` write-back
- Zero compiler warnings, enforced in CI with `-D warnings`

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
