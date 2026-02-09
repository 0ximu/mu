# mu-core

High-performance Rust core for MU (Machine Understanding).

## Overview

`mu-core` is the parsing and analysis engine used by the MU CLI and storage layer.

It provides:

- Multi-language parsing via tree-sitter (Python, TypeScript/JavaScript, Go, Java, Rust, C#)
- Common AST/types for downstream graph construction
- Cyclomatic complexity calculation
- Secret detection and redaction
- Exporters for MU/JSON/Markdown
- Parallel parsing for large codebases

## Build

From the repository root:

```bash
cargo build --package mu-core
```

Run tests:

```bash
cargo test --package mu-core
```

## API Example

```rust
use mu_core::{parse_file, FileInfo};

let result = parse_file("fn main() {}", "src/main.rs", "rust");
assert!(result.success);

let _info = FileInfo {
    path: "src/lib.rs".to_string(),
    source: "pub fn add(a: i32, b: i32) -> i32 { a + b }".to_string(),
    language: "rust".to_string(),
};
```

## License

Apache License 2.0
