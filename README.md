<p align="center">
  <img src="docs/assets/intro.gif" alt="MU Demo" width="600"/>
</p>

<h1 align="center">MU</h1>

<p align="center">
  <strong>Your codebase, understood.</strong>
</p>

<p align="center">
  <em>MCP server that gives AI assistants deep codebase understanding.<br/>
  Semantic graph, BM25 search, impact analysis, code review — all via tool calls.</em>
</p>

MU parses your codebase into a semantic graph stored in DuckDB, then exposes it through 13 MCP tools. Your AI assistant can search, navigate, review, and understand your code without stuffing the entire repo into a context window.

[![Rust 1.70+](https://img.shields.io/badge/rust-1.70+-orange.svg)](https://www.rust-lang.org/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

## Why

LLMs choke on large codebases. Context windows are precious. 90% of code is boilerplate. You're feeding syntax when you need semantics.

MU solves this by building a semantic graph — nodes (files, classes, functions), edges (imports, calls, inheritance), importance scores, summaries — and letting your AI pull exactly what it needs.

```
Input:  66,493 lines of Python
Output: 2,173 tokens (mu compress)
Result: LLM correctly answers architectural questions
```

## Quick Start

```bash
# Build from source
git clone https://github.com/0ximu/mu.git
cd mu && cargo build --release

# Bootstrap your project
cd /path/to/your/project
mu bootstrap

# Start the MCP server
mu mcp
```

Add to your Claude Code config (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "mu": {
      "command": "mu",
      "args": ["mcp"]
    }
  }
}
```

That's it. Your AI assistant now has full codebase understanding.

## MCP Tools

These are the tools your AI assistant can call:

| Tool | What it does |
|------|-------------|
| `mu_oracle` | The go-to tool — given a task description, returns exactly the code and context needed |
| `mu_grok` | Search + code snippets. BM25 full-text search ranked by importance |
| `mu_find` | Exact symbol lookup by name |
| `mu_expand` | Graph traversal — explore dependencies outward from seed nodes |
| `mu_read` | Bulk source code retrieval for specific nodes |
| `mu_impact` | Downstream impact — what breaks if this symbol changes |
| `mu_diff` | Semantic diff between git refs (branches, commits) |
| `mu_review` | Full PR review: diff + impact + audit + risk score |
| `mu_audit` | Code quality rules — complexity, missing docs, code smells |
| `mu_sus` | Find suspicious code — high complexity, security-sensitive, untested |
| `mu_wtf` | Git archaeology — who wrote this, how it evolved, co-changed files |
| `mu_enrich` | Enrichment flywheel — LLM generates better summaries, improving future search |
| `mu_compress` | Token-efficient codebase overview with sigil notation |

### The Enrichment Flywheel

`mu_enrich` is unique: it returns nodes that need better summaries, the LLM writes them, and stores them back. Each enrichment cycle improves future search results. The graph gets smarter the more you use it.

## CLI Commands

The CLI is lean — bootstrap, compress, and analyze:

```bash
mu bootstrap              # Build the semantic graph (run this first)
mu compress               # Compress codebase for LLM consumption
mu compress -o context.mu # Write to file
mu status                 # Project status and stats
mu deps <node>            # Show dependencies
mu impact <node>          # Downstream impact analysis
mu diff main HEAD         # Semantic diff between git refs
mu review                 # Review uncommitted changes
mu review main..feature   # Review branch diff
mu audit                  # Code quality audit
mu doctor                 # Health checks
```

### Compress (The Killer Feature)

Feed your entire codebase to an LLM in seconds. MU compresses your code into a hierarchical, star-ranked format that preserves semantic structure.

```
# 42 modules, 15 classes, 128 functions, 245 edges

## Domain Overview
### Core Entities
$ AuthService  [★★★]
  @attrs [user_repo, token_manager]
  → Database (uses), UserRepo (calls)
  ← LoginHandler, ApiMiddleware

## Hot Paths (complexity > 20 or calls > 5)
  # process_request  c=35  calls=12 ★★
    | src/handlers/api.rs
```

Sigil notation: `!` modules, `$` classes, `#` functions. Complexity scores, call counts, importance stars — all in minimal tokens.

## What Bootstrap Builds

`mu bootstrap` parses your codebase and produces:

1. **Semantic graph** — nodes (files, classes, functions) and edges (imports, calls, inheritance, uses)
2. **PageRank importance scores** — which symbols are most connected/important
3. **Heuristic summaries** — auto-generated descriptions for each node (generated after the graph is complete — summaries include caller/callee information from edges)
4. **BM25 full-text index** — fast search over summaries, names, and code
5. **DuckDB database** — everything stored in `.mu/mubase`

Bootstrap is fast: a 400k-line TypeScript project takes about 60 seconds.

## Supported Languages

| Language | Extensions |
|----------|-----------|
| Python | `.py` |
| TypeScript | `.ts`, `.tsx` |
| JavaScript | `.js`, `.jsx` |
| Go | `.go` |
| Rust | `.rs` |
| Java | `.java` |
| C# | `.cs` |

## How It Works

```
Source Code → Scanner → Parser → Graph Builder → DuckDB
                │          │          │              │
            manifest    AST       nodes &      PageRank,
                       data       edges       summaries,
                                              FTS index
                                                  │
                                            MCP Server
                                                  │
                                          AI Assistant
```

1. **Scanner** walks the filesystem, detects languages, filters noise
2. **Parser** uses tree-sitter to extract AST (classes, functions, imports)
3. **Graph Builder** creates nodes and edges for code relationships
4. **Post-processing** computes PageRank, generates summaries, builds BM25 index
5. **MCP Server** exposes 13 tools for AI assistants to query the graph

## Configuration

Create `.murc.toml` in your project:

```toml
[mu]
exclude = ["vendor/", "node_modules/", ".git/", "__pycache__/"]
```

## Node Identifiers

| Prefix | Type | Example |
|--------|------|---------|
| `mod:` | Module/File | `mod:src/lib/utils.ts` |
| `cls:` | Class | `cls:src/models/User.ts:User` |
| `fn:` | Function | `fn:src/api/auth.ts:login` |
| `ext:` | External dependency | `ext:react` |

## Known Limitations

- **Single-writer DuckDB**: Can't bootstrap while the MCP server is running. Stop the server, bootstrap, restart.
- **Test coverage detection**: `mu_sus` finds tests by looking for test files in the scanned tree. If tests live in a sibling directory, they won't be found.
- **.NET projects**: For solutions with code in `src/`, run `mu bootstrap` from the `src/` directory.

## Development

```bash
cargo build --release
cargo test
cargo fmt && cargo clippy    # Zero warnings policy
```

## Contributing

Contributions welcome.

```bash
cargo fmt && cargo clippy && cargo test
```

See [CONTRIBUTING.md](./CONTRIBUTING.md) for details.

## License

Apache License 2.0 — see [LICENSE](./LICENSE).

---

<p align="center">
  <strong>MU: Because life's too short to grep through 500k lines of code.</strong>
</p>
