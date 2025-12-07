# MU Rust Core - Claude Code Instructions

High-performance Rust core for MU. Provides parallel parsing, complexity analysis, secret detection, and multi-format export via PyO3 bindings.

## ⚠️ CRITICAL: Build System

**DO NOT use `cargo build` directly** - it will fail with linker errors:

```
ld: symbol(s) not found for architecture arm64
error: linking with `cc` failed: exit status: 1
```

PyO3 `cdylib` crates **must** be built with maturin to link against Python correctly.

### Correct Build Commands

```bash
# Development (from repo root, with venv active)
pip install maturin
maturin develop --manifest-path mu-core/Cargo.toml

# Or from mu-core directory
cd mu-core && maturin develop

# Release build
maturin develop --release --manifest-path mu-core/Cargo.toml

# Build wheel for distribution
maturin build --release --manifest-path mu-core/Cargo.toml
```

### Post-Build Step for Editable Install

After `maturin develop`, the `.so` file goes to site-packages. For the editable install to work:

```bash
# Copy .so to src/mu/ for editable install integration
cp $(python -c "import mu._core; print(mu._core.__file__)") src/mu/_core.abi3.so
```

### Cargo Commands That DO Work

```bash
cargo check                    # Type checking (no linking)
cargo clippy                   # Linting
cargo test                     # Unit tests (uses rlib, not cdylib)
cargo bench                    # Benchmarks
cargo doc --open               # Documentation
```

## Quick Reference

```bash
# Check for errors without building
cargo check

# Run clippy for lints
cargo clippy -- -W clippy::all

# Format code
cargo fmt

# Run tests
cargo test

# Run benchmarks
cargo bench

# Build and install to Python (ALWAYS use this for full builds)
maturin develop --release
```

## Project Structure

```
mu-core/
├── Cargo.toml              # Rust config - cdylib + PyO3
├── pyproject.toml          # Maturin config - module-name = "mu._core"
├── src/
│   ├── lib.rs              # Python module definition, exposed functions
│   ├── types.rs            # Data models (PyClass + Serde)
│   ├── graph.rs            # petgraph-based dependency analysis
│   ├── parser/             # Tree-sitter AST extraction (7 languages)
│   │   ├── mod.rs          # Dispatcher + parallel parsing
│   │   ├── helpers.rs      # Shared tree-sitter utilities
│   │   ├── python.rs       # Python extractor
│   │   ├── typescript.rs   # TS/JS extractor
│   │   ├── go.rs           # Go extractor
│   │   ├── java.rs         # Java extractor
│   │   ├── rust_lang.rs    # Rust extractor
│   │   └── csharp.rs       # C# extractor
│   ├── reducer/            # Code metrics and transformation
│   │   ├── complexity.rs   # Cyclomatic complexity
│   │   └── rules.rs        # Transformation rules
│   ├── security/           # Secret detection
│   │   ├── patterns.rs     # Regex patterns
│   │   └── redact.rs       # Redaction logic
│   └── exporter/           # Output formats
│       ├── mu_format.rs    # MU sigil format
│       ├── json.rs         # JSON via Serde
│       └── markdown.rs     # Markdown format
└── benches/
    └── parsing.rs          # Criterion benchmarks
```

## Key Dependencies

| Crate | Purpose |
|-------|---------|
| `pyo3` | Python bindings with `abi3-py311` for stable ABI |
| `rayon` | Parallel iteration (GIL-released) |
| `tree-sitter-*` | Language grammars (Python, TS, JS, Go, Java, Rust, C#) |
| `petgraph` | Directed graph for dependency analysis |
| `serde` | Serialization for JSON export |
| `once_cell` | Lazy static initialization |
| `regex` | Secret pattern matching |

## PyO3 Patterns

### Exposing Types to Python

```rust
#[pyclass]
#[derive(Clone, Serialize, Deserialize)]
pub struct MyType {
    #[pyo3(get, set)]
    pub field: String,

    #[pyo3(get)]  // Read-only
    pub computed: u32,
}

#[pymethods]
impl MyType {
    #[new]
    #[pyo3(signature = (field, computed=0))]
    fn new(field: String, computed: Option<u32>) -> Self {
        Self { field, computed: computed.unwrap_or(0) }
    }

    fn to_dict(&self, py: Python<'_>) -> PyResult<PyObject> {
        // Convert to Python dict
    }
}
```

### GIL Release for Parallel Work

```rust
#[pyfunction]
fn parallel_work(py: Python<'_>, items: Vec<Item>) -> PyResult<Vec<Result>> {
    // Release GIL during CPU-bound work
    Ok(py.allow_threads(|| {
        items.par_iter()
            .map(|item| process(item))
            .collect()
    }))
}
```

### Function Signatures

```rust
#[pyfunction]
#[pyo3(signature = (required, optional=None, with_default=true))]
fn example(required: String, optional: Option<u32>, with_default: bool) -> PyResult<()> {
    // ...
}
```

## Tree-Sitter Patterns

### Basic Parsing

```rust
use tree_sitter::{Parser, Node};

let mut parser = Parser::new();
parser.set_language(&tree_sitter_python::LANGUAGE.into())?;
let tree = parser.parse(source, None).ok_or("Parse failed")?;
let root = tree.root_node();
```

### Node Traversal

```rust
// Cursor-based iteration
let mut cursor = root.walk();
for child in root.children(&mut cursor) {
    match child.kind() {
        "function_definition" => handle_function(child, source),
        "class_definition" => handle_class(child, source),
        _ => {}
    }
}

// Named children only
for child in root.named_children(&mut cursor) {
    // Skip anonymous nodes (punctuation, keywords)
}
```

### Extracting Text

```rust
fn get_node_text<'a>(node: &Node, source: &'a str) -> &'a str {
    &source[node.byte_range()]
}
```

### Finding Children

```rust
// By type name
fn find_child_by_type<'a>(node: &Node<'a>, type_name: &str) -> Option<Node<'a>> {
    let mut cursor = node.walk();
    node.children(&mut cursor)
        .find(|c| c.kind() == type_name)
}

// By field name (language-specific)
let name_node = node.child_by_field_name("name");
```

## Error Handling

- Return `ParseResult` with `success: bool` and optional `error: String`
- No panics in production paths
- Use `?` operator for propagating errors internally
- Wrap external errors in descriptive strings

```rust
pub fn parse_source(source: &str, path: &str, lang: &str) -> ParseResult {
    match parse_internal(source, path, lang) {
        Ok(module) => ParseResult { success: true, module: Some(module), error: None },
        Err(e) => ParseResult { success: false, module: None, error: Some(e) },
    }
}
```

## Adding a New Language

1. Add grammar to `Cargo.toml`:
   ```toml
   tree-sitter-newlang = "0.23"
   ```

2. Create `src/parser/newlang.rs` following existing patterns

3. Register in `src/parser/mod.rs`:
   ```rust
   pub mod newlang;

   // In parse_source():
   "newlang" => newlang::parse(source, file_path),
   ```

4. Add decision points in `src/reducer/complexity.rs`:
   ```rust
   ("newlang", hashset!["if_statement", "for_statement", ...])
   ```

## Performance Notes

- **GIL Release**: Always use `py.allow_threads()` for CPU-bound work
- **Rayon**: Thread pool scales to CPU count automatically
- **LTO**: Enabled in release for cross-crate optimization
- **Single codegen-unit**: Better optimization, slower compile

## Testing

```bash
# Run all tests
cargo test

# Run specific test
cargo test test_name

# Run with output
cargo test -- --nocapture

# Benchmarks
cargo bench
```

## Common Issues

### "symbol(s) not found for architecture"
Use `maturin develop` instead of `cargo build`.

### "maturin: command not found"
```bash
pip install maturin
```

### Type stubs out of sync
Regenerate `src/mu/_core.pyi` after API changes.

### macOS version warnings
Tree-sitter grammars may be built for newer macOS. Safe to ignore unless linking fails.

## Python API

After `maturin develop`, use from Python:

```python
from mu import _core

# Parse files in parallel
results = _core.parse_files(file_infos, num_threads=4)

# Single file
result = _core.parse_file(source, "path.py", "python")

# Complexity
score = _core.calculate_complexity(source, "python")

# Secrets
matches = _core.find_secrets(text)
redacted = _core.redact_secrets(text)

# Export
mu_text = _core.export_mu(module)
json_text = _core.export_json(module, pretty=True)
md_text = _core.export_markdown(module)

# Graph
engine = _core.GraphEngine()
engine.add_node("mod:src/main.py")
engine.add_edge("mod:src/main.py", "mod:src/utils.py", "imports")
cycles = engine.find_cycles()
```
