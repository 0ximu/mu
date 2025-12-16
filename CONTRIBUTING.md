# Contributing to MU

Thanks for your interest in contributing to MU! This document provides guidelines for contributing.

## Development Setup

### Prerequisites
- Rust 1.70+ (install via [rustup](https://rustup.rs/))
- Git

### Setup

```bash
# Clone the repository
git clone https://github.com/0ximu/mu.git
cd mu

# Build
cargo build

# Run tests
cargo test

# Verify setup
./target/debug/mu --version
```

## Project Structure

```
mu/
├── mu-cli/              # CLI application (clap-based)
│   ├── src/
│   │   ├── main.rs      # Entry point
│   │   └── commands/    # CLI command implementations
│   └── Cargo.toml
├── mu-core/             # Parser, scanner, graph algorithms
│   ├── src/
│   │   ├── parser/      # Tree-sitter language extractors
│   │   ├── scanner/     # Filesystem scanning
│   │   ├── graph/       # Graph algorithms
│   │   ├── diff/        # Semantic diff
│   │   └── types.rs     # Core types (ModuleDef, etc.)
│   └── Cargo.toml
├── mu-daemon/           # Storage layer (DuckDB)
│   ├── src/
│   │   ├── storage/     # DuckDB storage
│   │   └── embedding.rs # Embedding trait
│   └── Cargo.toml
├── mu-embeddings/       # MU-SIGMA-V2 model (Candle)
│   ├── src/
│   │   └── lib.rs       # BERT inference
│   └── models/          # Model weights
└── models/              # Trained model weights
```

## Making Changes

### 1. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/bug-description
```

### 2. Make Your Changes

Follow existing code patterns:
- Use Rust idioms (Result, Option, iterators)
- Follow the existing module structure
- Keep functions focused and small

### 3. Write Tests

All new features should have tests:

```bash
# Run all tests
cargo test

# Run specific crate tests
cargo test -p mu-core

# Run with output
cargo test -- --nocapture

# Run a specific test
cargo test test_name
```

### 4. Check Code Quality

```bash
# Check compilation
cargo check

# Lint (fix all warnings)
cargo clippy

# Format
cargo fmt

# All three (recommended before commit)
cargo fmt && cargo clippy && cargo test
```

### 5. Commit

Write clear commit messages:
```
Add Go language support to parser

- Implement Go extractor using tree-sitter-go
- Add tests for Go parsing
- Update supported languages in README
```

### 6. Open a Pull Request

- Describe what your PR does
- Link any related issues
- Include test results

## Adding a New Language

To add support for a new programming language:

### 1. Add the Tree-sitter Grammar

Add to `mu-core/Cargo.toml`:
```toml
[dependencies]
tree-sitter-kotlin = "0.3"  # Example for Kotlin
```

### 2. Create the Extractor

Create `mu-core/src/parser/kotlin.rs`:

```rust
//! Kotlin-specific AST extractor using Tree-sitter.

use tree_sitter::Node;
use crate::types::{ModuleDef, ClassDef, FunctionDef, ImportDef};

pub struct KotlinExtractor;

impl KotlinExtractor {
    pub fn extract(&self, root: Node, source: &[u8], file_path: &str) -> ModuleDef {
        // Implement extraction logic
        todo!()
    }
}
```

### 3. Register in Parser Module

Update `mu-core/src/parser/mod.rs`:

```rust
mod kotlin;
pub use kotlin::KotlinExtractor;

pub fn get_extractor(lang: &str) -> Option<Box<dyn LanguageExtractor>> {
    match lang {
        // ... existing languages
        "kotlin" => Some(Box::new(KotlinExtractor)),
        _ => None,
    }
}
```

### 4. Add Language Detection

Update `mu-core/src/scanner/mod.rs`:

```rust
pub fn detect_language(path: &Path) -> Option<&'static str> {
    match path.extension()?.to_str()? {
        // ... existing extensions
        "kt" | "kts" => Some("kotlin"),
        _ => None,
    }
}
```

### 5. Add Tests

Create `mu-core/src/parser/tests/kotlin_tests.rs` with tests for:
- Function parsing
- Class/data class parsing
- Import parsing
- Method parsing

## Code Style

### Rust Style

- Use `Result<T, E>` for fallible operations
- Use `Option<T>` for optional values
- Prefer iterators over explicit loops
- Use `thiserror` for library errors, `anyhow` for application code
- Follow [Rust API Guidelines](https://rust-lang.github.io/api-guidelines/)

### Error Handling

```rust
// Library code (mu-core)
#[derive(thiserror::Error, Debug)]
pub enum ParseError {
    #[error("unsupported language: {0}")]
    UnsupportedLanguage(String),

    #[error("syntax error at line {line}: {message}")]
    SyntaxError { line: usize, message: String },
}

// Application code (mu-cli)
fn main() -> anyhow::Result<()> {
    // anyhow for CLI error handling
    Ok(())
}
```

### Documentation

- Add doc comments to public functions
- Update README if adding features
- Keep CLAUDE.md in sync with changes

### Testing

- Unit tests for individual functions
- Integration tests for full pipelines
- Use `#[test]` for unit tests
- Use `tests/` directory for integration tests

## Architecture Decisions

### Why Tree-sitter?
- Language-agnostic parsing
- Excellent error recovery
- Active community with many grammars
- Incremental parsing support

### Why DuckDB?
- Embedded database (no server)
- Fast analytical queries
- SQL interface for MUQL
- Good Rust bindings

### Why Candle for Embeddings?
- Pure Rust (no Python dependency)
- Compiles model into binary
- Fast inference on CPU
- No external dependencies

## Pre-PR Checklist

Before submitting:

- [ ] `cargo fmt` applied
- [ ] `cargo clippy` passes with no warnings
- [ ] `cargo test` passes all tests
- [ ] New code has corresponding tests
- [ ] No `#[allow(...)]` without justification
- [ ] README updated if adding features

## Getting Help

- **Questions:** Open a GitHub Discussion
- **Bugs:** Open a GitHub Issue
- **Features:** Open an Issue to discuss first

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
