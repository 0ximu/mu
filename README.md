<p align="center">
  <img src="docs/assets/intro.gif" alt="MU Demo" width="600"/>
</p>

<h1 align="center">MU</h1>

<p align="center">
  <strong>Your codebase, understood.</strong>
</p>

<p align="center">
  <em>"Where's the auth code?" "What breaks if I change this?" "Why does this file exist?"</em><br/>
  <strong>MU answers in seconds.</strong>
</p>

MU builds a semantic graph of your codebase and provides fast queries, semantic search, and diff analysis. Feed your entire codebase to an AI in seconds, not hours.

[![Rust 1.70+](https://img.shields.io/badge/rust-1.70+-orange.svg)](https://www.rust-lang.org/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Tests](https://img.shields.io/badge/tests-passing-green.svg)]()

## The Problem

You know the drill:

- "Paste the codebase into Claude" → **token limit exceeded**
- "Where's the authentication code?" → **grep, grep, grep...**
- "What depends on this?" → **¯\\\_(ツ)\_/¯**
- "Read the documentation" → **what documentation?**

LLMs choke on large codebases. Context windows are precious. 90% of code is boilerplate. You're feeding syntax when you need semantics.

## The Solution

MU parses your codebase into a semantic graph database. Fast queries. Semantic search. Intelligent context extraction.

```
Input:  66,493 lines of Python
Output: 2,173 tokens
Vibe:   omg, semantic compression
Result: LLM correctly answers architectural questions
```

## Validated Results

| Codebase | Files | Lines | MU Nodes | Export LOC | Bootstrap |
|----------|-------|-------|----------|------------|-----------|
| Next.js 14 App (TypeScript) | 1,112 | 406k | 4,471 | 16k | 63s |
| .NET 8 Microservices (C#) | 796 | 147k | 6,843 | 22k | 117s |

**Real test:** Fed MU output to Claude, asked architectural questions — correctly explained service patterns, identified dependencies, found complexity hotspots.

## Installation

```bash
# Build from source (requires Rust 1.70+)
git clone https://github.com/0ximu/mu.git
cd mu
cargo build --release

# Binary is at: ./target/release/mu
# Optionally, copy to PATH:
sudo cp target/release/mu /usr/local/bin/
```

**Binary releases** are also available for standalone deployment. See [Releases](https://github.com/0ximu/mu/releases) for platform-specific binaries.

## Quick Start

```bash
# 1. Bootstrap with embeddings (recommended)
mu bootstrap --embed              # Builds graph + generates embeddings

# 2. Query (terse syntax = fewer tokens)
mu q "fn c>50"                    # Functions with complexity > 50
mu q "deps Auth d2"               # Dependencies of Auth, depth 2

# 3. Semantic search (powered by local MU-SIGMA model)
mu search "error handling"        # No API keys needed

# 4. Compress for LLMs (the killer feature)
mu compress > codebase.txt        # Feed entire codebase to Claude/GPT

# 5. Get the vibes
mu omg                            # Dramatic summary. The tea. The drama.
```

That's it. Your codebase is now understood.

## CLI Commands

### Core Commands

```bash
mu bootstrap                      # Initialize and build graph database
mu bootstrap --embed              # Build graph + generate embeddings (recommended)
mu status                         # Show project status
mu doctor                         # Run health checks on MU installation
```

### Graph Analysis

```bash
mu deps <node>                    # Show dependencies of a node
mu deps <node> -r                 # Show reverse dependencies (dependents)
mu impact <node>                  # Find downstream impact (what breaks if this changes)
mu ancestors <node>               # Find upstream ancestors (what this depends on)
mu cycles                         # Detect circular dependencies
```

### Search & Discovery

```bash
mu search "query"                 # Semantic search (requires embeddings)
mu search "query"                 # Falls back to keyword search if no embeddings
mu grok "question"                # Ask a question about the codebase
mu patterns                       # Detect code patterns
mu read <file>                    # Read and display a file with MU context
```

> **Tip:** Run `mu bootstrap --embed` or `mu embed` to enable semantic search. Without embeddings, search uses keyword matching.

### Embeddings

```bash
mu embed                          # Generate embeddings (incremental)
mu embed --force                  # Regenerate all embeddings
mu embed --status                 # Show embedding coverage status
```

### MUQL Queries

```bash
# Full SQL-like syntax
mu query "SELECT * FROM functions WHERE complexity > 10"
mu query "SELECT name, complexity FROM functions ORDER BY complexity DESC LIMIT 20"

# Terse syntax (60-85% fewer tokens)
mu q "fn c>50"                    # Functions with complexity > 50
mu q "fn c>50 sort c- 10"         # Sorted descending, limit 10
mu q "cls n~'Service'"            # Classes matching 'Service'
mu q "deps Auth d2"               # Dependencies of Auth, depth 2
mu q "rdeps Parser"               # What depends on Parser

# Interactive REPL
mu query -i
```

### Semantic Diff & History

```bash
mu diff main HEAD                 # Semantic diff between git refs
mu diff HEAD~5 HEAD               # Last 5 commits
mu history <node>                 # Show change history for a node
```

### Compress (The Killer Feature)

Feed your entire codebase to an LLM in seconds. MU compresses your code into a hierarchical, star-ranked format that preserves semantic structure while minimizing tokens.

```bash
mu compress                       # Compress codebase to stdout
mu compress > codebase.txt        # Save for LLM consumption
mu c                              # Alias

# Detail levels
mu compress --detail low          # Minimal: just structure
mu compress --detail medium       # Default: structure + hot paths + core entities
mu compress --detail high         # Full: everything including relationship clusters

# Output to file
mu compress -o context.mu         # Write directly to file
```

**Output includes:**
- **Core Entities** with star rankings (`★`, `★★`, `★★★`) based on importance (connectivity + usage)
- **Hot Paths** — functions with high complexity (>20) or call counts (>5)
- **Hierarchical Tree** — folder structure with modules, classes, functions
- **Relationship Clusters** — who uses what (at `high` detail level)

**Example output:**
```
# MU v2.0 - Compressed Codebase
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

### Export Formats

For diagram generation and data interchange:

```bash
mu export -F json                 # JSON graph export
mu export -F mermaid              # Mermaid diagram
mu export -F json -l 100          # Limit to 100 nodes
```

### Vibes

MU doesn't take itself too seriously. These commands do real work with real personality.

```bash
mu yolo <node>     # "Mass deploy on Friday"
                   # → Impact analysis. What breaks if you touch this?

mu sus             # "Emergency code review"
                   # → Find suspicious patterns: complexity bombs,
                   #   security smells, code that makes you go "hmm"

mu wtf <file>      # "Archaeology expedition"
                   # → Git blame on steroids. Who did this? When? WHY?

mu omg             # "OMEGA context extraction"
                   # → Compressed codebase overview for LLMs. Ranks nodes
                   #   by importance (complexity + connectivity). ~4k tokens.

mu vibe            # "Naming convention check"
                   # → Are you snake_case or camelCase? PascalCase purist?
                   #   MU checks if your code follows consistent conventions.

mu zen             # "Digital declutter"
                   # → Clear caches, reset state, achieve inner peace.
                   #   Sometimes you just need a fresh start.
```

> **Philosophy**: Most CLI tools are either boring or try-hard. MU aims for the sweet spot — useful AND fun. The vibes are real.

## Configuration

Create `.murc.toml` in your project:

```toml
[mu]
exclude = ["vendor/", "node_modules/", ".git/", "__pycache__/"]
```

## Supported Languages

| Language | Status |
|----------|--------|
| Python | Full support |
| TypeScript | Full support |
| JavaScript | Full support |
| Go | Full support |
| Rust | Full support |
| Java | Full support |
| C# | Full support |

## Node Identifiers

MU uses prefixed identifiers to distinguish node types:

| Prefix | Type | Example |
|--------|------|---------|
| `mod:` | Module/File | `mod:src/lib/utils.ts` |
| `cls:` | Class | `cls:src/models/User.ts:User` |
| `fn:` | Function | `fn:src/api/auth.ts:login` |
| `ext:` | External dependency | `ext:react` |

When using commands like `mu deps`, you can use:
- **Short name**: `mu deps UserService` (fuzzy match)
- **Full ID**: `mu deps mod:src/services/UserService.ts` (exact match)

### Language Notes

| Language | Import Resolution |
|----------|------------------|
| TypeScript/JS | File-based with path alias support (`@/*`, `~/*`) |
| Python | Module-based with relative imports |
| C# | Namespace-based (e.g., `using System.Net`) |
| Go | Package-based |
| Java | Package-based |
| Rust | Module-based with `use` statements |

**TypeScript Path Aliases**: MU automatically reads `tsconfig.json` or `jsconfig.json` to resolve path aliases like `@/lib/utils`.

## How It Works

```
Source Code → Scanner → Parser → Graph Builder → DuckDB
                │          │          │
            manifest    AST       nodes &
                       data       edges
```

1. **Scanner**: Walks filesystem, detects languages, filters noise
2. **Parser**: Tree-sitter extracts AST (classes, functions, imports)
3. **Graph Builder**: Creates nodes and edges for code relationships
4. **DuckDB**: Stores the semantic graph for fast SQL queries

### Embeddings (MU-SIGMA-V2)

MU includes a bundled BERT model trained on code for semantic search:

- **Dimension**: 384
- **Max sequence**: 512 tokens
- **Pooling**: Mean
- **No API keys required**: Runs locally

## Development

```bash
# Build
cargo build --release

# Run tests
cargo test

# Format
cargo fmt

# Lint
cargo clippy
```

## Known Limitations

### Test Coverage Detection

The `mu sus` command detects test coverage by looking for test files in the scanned directory tree. If your tests live in a sibling directory (e.g., `src/` and `tests/` at the same level), MU won't find them.

**Workaround**: Run `mu bootstrap` from the parent directory, or configure test paths in `.murc.toml`:

```toml
[scanner]
# Include sibling test directory
include_paths = ["../tests"]
```

### .NET Solutions

For .NET projects with a solution file at root and code in `src/`, run MU from the `src/` directory:

```bash
cd src && mu bootstrap --embed
```

### Monorepo Support

MU works best when run from the directory containing your source code. For monorepos, bootstrap each project separately or run from the root with appropriate excludes.

## Troubleshooting

### "No supported files found"

MU didn't find parseable files in the current directory. Check:
- You're in the right directory (source code, not project root)
- Files aren't excluded by `.murc.toml` or `.gitignore`
- Language is supported (run `mu doctor`)

### Database errors

```bash
rm -rf .mu && mu bootstrap
```

### Embeddings not working

```bash
mu embed --status  # Check coverage
mu embed --force   # Regenerate all
```

### Check what's in the database

```bash
duckdb .mu/mubase "SELECT type, COUNT(*) FROM nodes GROUP BY type"
duckdb .mu/mubase "SELECT type, COUNT(*) FROM edges GROUP BY type"
```

## Roadmap

- [x] Multi-language parsing (Python, TypeScript, JavaScript, C#, Go, Rust, Java)
- [x] DuckDB graph storage with fast SQL queries
- [x] MUQL query language with terse syntax
- [x] Vector embeddings for semantic search (MU-SIGMA-V2)
- [x] Smart context extraction for questions
- [x] Semantic diff between git refs
- [x] Multi-format export (Mermaid, D2, JSON)
- [ ] Real-time daemon mode with HTTP API
- [ ] MCP server for AI assistants (Claude Code)
- [ ] mu-viz: Interactive graph visualization
- [ ] IDE integrations (VS Code, JetBrains)

## Contributing

Contributions welcome! We're building something genuinely useful here.

```bash
cargo fmt && cargo clippy && cargo test  # The holy trinity
```

See [CONTRIBUTING.md](./CONTRIBUTING.md) for details.

## License

Apache License 2.0 - see [LICENSE](./LICENSE) for details.

---

<p align="center">
  <strong>MU: Because life's too short to grep through 500k lines of code.</strong>
</p>
