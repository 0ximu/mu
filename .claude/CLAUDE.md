# MU - Claude Code Project Instructions

MU is a pure Rust project. This file provides project-wide guidance.

## Pre-PR Checklist

Before creating a pull request, verify:

### Code Quality
- [ ] `cargo check` passes with no errors
- [ ] `cargo fmt` applied (code is formatted)
- [ ] `cargo clippy` passes with no warnings
- [ ] No `#[allow(...)]` without justification

### Testing
- [ ] `cargo test` passes all tests
- [ ] New code has corresponding tests

### Architecture
- [ ] New parsers added to `mu-core/src/parser/`
- [ ] Types implement `Serialize`/`Deserialize` where needed
- [ ] No circular dependencies between crates

### Security
- [ ] No hardcoded secrets or API keys
- [ ] Secret patterns in `mu-core/src/security/`

## Project Structure

```
mu-cli/          # CLI application (clap-based)
mu-core/         # Parser, scanner, graph algorithms, diff
mu-daemon/       # Storage layer (DuckDB), embedding trait
mu-embeddings/   # MU-SIGMA-V2 embedding model (Candle)
mu-sigma/        # Training pipeline (Python, model training only)
models/          # Trained model weights
```

## Essential Commands

```bash
# Build
cargo build --release

# Test
cargo test
cargo test -p mu-core           # Test specific crate
cargo test -- --nocapture       # Show println output

# Lint & Format
cargo fmt
cargo clippy

# Run CLI
./target/release/mu bootstrap
./target/release/mu status
./target/release/mu q "fn c>50"
```

## Crate Reference

| Crate | Purpose |
|-------|---------|
| `mu-cli` | CLI commands, output formatting |
| `mu-core` | Tree-sitter parsing (7 langs), graph algorithms, semantic diff |
| `mu-daemon` | DuckDB storage layer, embedding trait |
| `mu-embeddings` | BERT inference via Candle, MU-SIGMA-V2 model |

## Key Types

- **`ModuleDef`** (`mu-core/src/types.rs`): Parsed file with imports, classes, functions
- **`Node`** (`mu-daemon/src/storage/`): Graph node (function, class, module)
- **`Edge`** (`mu-daemon/src/storage/`): Graph edge (calls, imports, inherits)

## Critical Patterns

### Error Handling
Use `anyhow::Result` for application code, `thiserror` for library errors:
```rust
// In mu-core (library)
#[derive(thiserror::Error, Debug)]
pub enum ParseError {
    #[error("unsupported language: {0}")]
    UnsupportedLanguage(String),
}

// In mu-cli (application)
fn main() -> anyhow::Result<()> {
    // ...
}
```

### Parallel Processing
Use Rayon for CPU-bound parallel work:
```rust
use rayon::prelude::*;
modules.par_iter().map(|m| parse(m)).collect()
```

### Async
Use Tokio for I/O-bound async work:
```rust
#[tokio::main]
async fn main() {
    // ...
}
```

## MUQL

Query language for the code graph:

```sql
-- Full syntax
SELECT name, complexity FROM functions WHERE complexity > 10

-- Terse syntax
fn c>50 sort c- 10    -- Functions with complexity > 50
deps Auth d2          -- Dependencies of Auth, depth 2
```

## Configuration

`.murc.toml` at project root. All sections are optional.

```toml
[mu]
version = "1.0"  # Config version (informational)

[scanner]
ignore = ["vendor/", "dist/"]  # Additional patterns to ignore
include_hidden = false          # Include hidden files (default: false)
max_file_size_kb = 1024         # Skip files larger than this (KB)

[parser]
languages = ["python", "typescript", "rust"]  # Only parse these languages

[output]
format = "table"  # Default output: table, json, csv, mu, tree
color = true      # Enable colored output

[cache]
enabled = true           # Enable caching (default: true)
directory = ".mu/cache"  # Custom cache directory
```

### Scanner Section
- `ignore` - Glob patterns to exclude (combined with `.gitignore`, `.muignore`)
- `include_hidden` - Process files starting with `.`
- `max_file_size_kb` - Skip large files (useful for generated code)

### Parser Section
- `languages` - Restrict parsing to specific languages. Supported: `python`, `typescript`, `javascript`, `tsx`, `jsx`, `rust`, `go`, `java`, `csharp`

### Output Section
- `format` - Default output format for CLI commands
- `color` - Override auto-detection for colored output

## Local Overrides

Create `.claude/CLAUDE.local.md` for personal customizations (gitignored).

## Troubleshooting

```bash
# Fresh start (clears database and rebuilds)
rm -rf .mu && mu bootstrap

# Database errors about schema/columns
# The database may be from an old version. Delete and rebuild:
rm -rf .mu && mu bootstrap

# Check database contents
duckdb .mu/mubase "SELECT type, COUNT(*) FROM nodes GROUP BY type"
duckdb .mu/mubase "SELECT type, COUNT(*) FROM edges GROUP BY type"
```
