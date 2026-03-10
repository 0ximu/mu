# Contributing to MU

## Development Setup

### Prerequisites
- Rust 1.70+ (install via [rustup](https://rustup.rs/))
- Git

### Setup

```bash
git clone https://github.com/0ximu/mu.git
cd mu
cargo build
cargo test
```

## Project Structure

```
mu/
├── mu-cli/                # CLI + MCP server
│   ├── src/
│   │   ├── main.rs        # Entry point, clap commands
│   │   ├── commands/      # CLI command implementations
│   │   │   ├── mcp/       # MCP server + tool implementations
│   │   │   │   ├── server.rs    # rmcp server, tool dispatch
│   │   │   │   └── tools_v3.rs  # Tool logic (search, expand, read, enrich, etc.)
│   │   │   ├── bootstrap.rs     # Graph building pipeline
│   │   │   ├── compress/        # Codebase compression
│   │   │   ├── review.rs        # PR review with risk scoring
│   │   │   └── audit.rs         # Code quality rules
│   │   └── engine/        # Storage + search engine
│   │       ├── storage/   # DuckDB storage (MUbase)
│   │       ├── search.rs  # BM25 + importance search
│   │       ├── pagerank.rs # Node importance scoring
│   │       └── summary.rs # Heuristic summary generation
│   └── Cargo.toml
├── mu-core/               # Parser + scanner (no storage dependency)
│   ├── src/
│   │   ├── parser/        # Tree-sitter language extractors
│   │   ├── scanner.rs     # Filesystem scanning
│   │   ├── reducer/       # Complexity analysis
│   │   └── types.rs       # Core types (ModuleDef, etc.)
│   └── Cargo.toml
└── mu-embeddings/         # MU-SIGMA-V2 model (Candle, optional)
```

## Making Changes

### 1. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/bug-description
```

### 2. Follow Existing Patterns

- Parsers: `parse(source, path) -> Result<ModuleDef, String>`, register in `mod.rs` dispatcher
- CLI commands: create `commands/foo.rs`, add to `Commands` enum in `main.rs`
- MCP tools: add `#[tool(...)]` method in `server.rs`, implement logic in `tools_v3.rs`
- Storage: methods on `MUbase` in `engine/storage/mubase.rs`

### 3. Write Tests

```bash
cargo test                    # All tests
cargo test -p mu-core         # Core only
cargo test -p mu-cli          # CLI only
cargo test test_name          # Specific test
cargo test -- --nocapture     # With stdout
```

### 4. Check Code Quality

```bash
cargo fmt && cargo clippy && cargo test
```

Zero warnings policy — `cargo clippy` must be clean.

### 5. Commit

Write clear commit messages:
```
Add Go language support to parser

- Implement Go extractor using tree-sitter-go
- Add tests for Go parsing
- Register in parser dispatcher
```

## Adding a New Language

### 1. Add Grammar Dependency

In `mu-core/Cargo.toml`:
```toml
tree-sitter-newlang = "0.23"
```

### 2. Create Extractor

Create `mu-core/src/parser/newlang.rs`:

```rust
use std::path::Path;
use tree_sitter::Parser;
use crate::types::ModuleDef;
use super::helpers::{get_node_text, find_child_by_type, get_start_line, get_end_line, count_lines};

pub fn parse(source: &str, file_path: &str) -> Result<ModuleDef, String> {
    let mut parser = Parser::new();
    parser.set_language(&tree_sitter_newlang::LANGUAGE.into())
        .map_err(|e| format!("Failed to set language: {}", e))?;

    let tree = parser.parse(source, None)
        .ok_or("Failed to parse source")?;

    let name = Path::new(file_path)
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("unknown")
        .to_string();

    let mut module = ModuleDef {
        name,
        path: file_path.to_string(),
        language: "newlang".to_string(),
        total_lines: count_lines(source),
        ..Default::default()
    };

    // Extract imports, classes, functions from AST
    // See existing extractors for patterns

    Ok(module)
}
```

### 3. Register

In `mu-core/src/parser/mod.rs`:
```rust
pub mod newlang;

// In parse_source():
"newlang" | "nl" => newlang::parse(source, path),

// In supported_languages():
"newlang", "nl",
```

### 4. Add Complexity Decision Points

In `mu-core/src/reducer/complexity.rs`, add to `DECISION_POINTS`:
```rust
("newlang", hashset![
    "if_statement",
    "for_statement",
    "while_statement",
    // ... language-specific branching constructs
])
```

### 5. Add Scanner Detection

In `mu-core/src/scanner.rs`, add the file extension mapping.

### 6. Add Tests

Test at minimum: function extraction, class extraction, import extraction, and edge cases (empty files, syntax errors).

## Architecture Notes

### Why Tree-sitter?
Language-agnostic parsing with error recovery. Active community with grammar support for most languages.

### Why DuckDB?
Embedded database, fast analytical queries, SQL interface, FTS extension for BM25 search.

### Why MCP-first?
Most MU functionality is consumed by AI assistants, not humans typing CLI commands. MCP tools are the primary interface; CLI commands are for bootstrapping and direct analysis.

## Pre-PR Checklist

- [ ] `cargo fmt` applied
- [ ] `cargo clippy` passes with zero warnings
- [ ] `cargo test` passes all tests
- [ ] New code has tests
- [ ] README updated if adding user-facing features

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
