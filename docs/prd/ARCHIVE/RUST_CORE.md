# PRD: MU Rust Core (mu-core)

## Overview

**Project:** MU Rust Core - High-performance parsing and transformation engine
**Priority:** P1 (after CLI refactor ships)
**Effort:** 4-8 hours (AI-assisted)
**Risk:** Low (additive, Python CLI unchanged)

## Problem Statement

MU's hot paths are CPU-bound Python operations:
1. **Parsing** - Tree-sitter via Python bindings (py-tree-sitter)
2. **Reducing** - AST transformation with recursive traversal
3. **Graph building** - Node/edge creation and indexing

On large codebases (10K+ files), these operations dominate execution time. Python's GIL prevents true parallel parsing.

## Goals

| Goal | Metric | Target |
|------|--------|--------|
| Parse speed | Time to parse 1000 files | < 2 sec (from ~8 sec) |
| Memory usage | Peak RSS on large repo | < 250 MB (from ~800 MB) |
| Parallel parsing | CPU utilization | 90%+ across all cores |
| Zero API changes | Python interface | Identical function signatures |
| Incremental adoption | Fallback to Python | Feature flag to disable Rust |

## Non-Goals

- Rewriting CLI in Rust (stays Python)
- Rewriting LLM integration (stays Python)
- Rewriting MCP server (stays Python)
- Rewriting MUQL engine (stays Python, queries DuckDB)
- Changing user-facing behavior

## Architecture

### Current (Python Only)

```
mu compress .
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  Python                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │ Scanner  │→ │ Parser   │→ │ Reducer  │→ Output  │
│  │          │  │(py-tree- │  │          │          │
│  │          │  │ sitter)  │  │          │          │
│  └──────────┘  └──────────┘  └──────────┘          │
│                     ↓                               │
│              [GIL bottleneck]                       │
│              [Sequential only]                      │
└─────────────────────────────────────────────────────┘
```

### Target (Rust Core + Python Shell)

```
mu compress .
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  Python CLI                                         │
│  ┌──────────┐                                       │
│  │ Scanner  │  (stays Python - I/O bound anyway)   │
│  └────┬─────┘                                       │
│       │ paths: list[str]                            │
│       ▼                                             │
│  ┌─────────────────────────────────────────────┐   │
│  │  mu._core (Rust via PyO3)                   │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  │   │
│  │  │ Parser   │→ │ Reducer  │→ │ Exporter │  │   │
│  │  │(native   │  │          │  │          │  │   │
│  │  │tree-     │  │          │  │          │  │   │
│  │  │sitter)   │  │          │  │          │  │   │
│  │  └──────────┘  └──────────┘  └──────────┘  │   │
│  │       ↓                                     │   │
│  │  [No GIL - true parallelism with rayon]    │   │
│  └─────────────────────────────────────────────┘   │
│       │                                             │
│       ▼ ReducedCodebase                            │
│  ┌──────────┐                                       │
│  │ Assembler│  (stays Python - simple glue)        │
│  └──────────┘                                       │
└─────────────────────────────────────────────────────┘
```

## Technical Design

### Directory Structure

```
mu/
├── mu-core/                      # New Rust crate
│   ├── Cargo.toml
│   ├── pyproject.toml            # maturin config
│   ├── src/
│   │   ├── lib.rs                # PyO3 module exports
│   │   ├── types.rs              # Shared types (ModuleDef, FunctionDef, etc.)
│   │   ├── parser/
│   │   │   ├── mod.rs
│   │   │   ├── python.rs         # Python-specific parsing
│   │   │   ├── typescript.rs     # TypeScript/JS parsing
│   │   │   ├── rust.rs           # Rust parsing
│   │   │   ├── go.rs             # Go parsing
│   │   │   ├── java.rs           # Java parsing
│   │   │   └── csharp.rs         # C# parsing
│   │   ├── reducer/
│   │   │   ├── mod.rs
│   │   │   ├── rules.rs          # Transformation rules
│   │   │   └── complexity.rs     # Cyclomatic complexity
│   │   ├── security/
│   │   │   ├── mod.rs
│   │   │   └── redact.rs         # Secret redaction
│   │   └── exporter/
│   │       ├── mod.rs
│   │       ├── mu_format.rs      # MU format output
│   │       ├── json.rs           # JSON output
│   │       └── markdown.rs       # Markdown output
│   └── tests/
│       ├── parser_tests.rs
│       ├── reducer_tests.rs
│       └── fixtures/             # Test files per language
│
└── src/mu/
    ├── _core.pyi                 # Type stubs for Rust module
    ├── parser/
    │   ├── __init__.py           # Delegates to _core or fallback
    │   └── fallback.py           # Pure Python (if Rust unavailable)
    └── ...
```

### Rust Types (Mirror Python Exactly)

```rust
// mu-core/src/types.rs
use pyo3::prelude::*;
use serde::{Deserialize, Serialize};

#[pyclass]
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ModuleDef {
    #[pyo3(get, set)]
    pub name: String,
    #[pyo3(get, set)]
    pub file_path: String,
    #[pyo3(get, set)]
    pub language: String,
    #[pyo3(get, set)]
    pub imports: Vec<ImportDef>,
    #[pyo3(get, set)]
    pub classes: Vec<ClassDef>,
    #[pyo3(get, set)]
    pub functions: Vec<FunctionDef>,
    #[pyo3(get, set)]
    pub constants: Vec<ConstantDef>,
}

#[pyclass]
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct FunctionDef {
    #[pyo3(get, set)]
    pub name: String,
    #[pyo3(get, set)]
    pub qualified_name: String,
    #[pyo3(get, set)]
    pub parameters: Vec<ParameterDef>,
    #[pyo3(get, set)]
    pub return_type: Option<String>,
    #[pyo3(get, set)]
    pub decorators: Vec<String>,
    #[pyo3(get, set)]
    pub is_async: bool,
    #[pyo3(get, set)]
    pub is_generator: bool,
    #[pyo3(get, set)]
    pub body_complexity: u32,
    #[pyo3(get, set)]
    pub docstring: Option<String>,
    #[pyo3(get, set)]
    pub line_start: u32,
    #[pyo3(get, set)]
    pub line_end: u32,
}

#[pyclass]
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ClassDef {
    #[pyo3(get, set)]
    pub name: String,
    #[pyo3(get, set)]
    pub qualified_name: String,
    #[pyo3(get, set)]
    pub bases: Vec<String>,
    #[pyo3(get, set)]
    pub decorators: Vec<String>,
    #[pyo3(get, set)]
    pub methods: Vec<FunctionDef>,
    #[pyo3(get, set)]
    pub attributes: Vec<AttributeDef>,
    #[pyo3(get, set)]
    pub docstring: Option<String>,
    #[pyo3(get, set)]
    pub line_start: u32,
    #[pyo3(get, set)]
    pub line_end: u32,
}

// ... ParameterDef, ImportDef, ConstantDef, AttributeDef
```

### PyO3 Module Interface

```rust
// mu-core/src/lib.rs
use pyo3::prelude::*;
use rayon::prelude::*;

mod types;
mod parser;
mod reducer;
mod security;
mod exporter;

use types::*;

/// Parse multiple files in parallel
#[pyfunction]
#[pyo3(signature = (file_infos, num_threads=None))]
fn parse_files(
    py: Python<'_>,
    file_infos: Vec<FileInfo>,
    num_threads: Option<usize>,
) -> PyResult<Vec<ParseResult>> {
    // Release GIL for parallel execution
    py.allow_threads(|| {
        // Configure thread pool
        let pool = rayon::ThreadPoolBuilder::new()
            .num_threads(num_threads.unwrap_or(0)) // 0 = auto
            .build()
            .unwrap();

        pool.install(|| {
            file_infos
                .par_iter()
                .map(|info| parser::parse_file(info))
                .collect()
        })
    })
}

/// Reduce parsed modules (apply transformation rules)
#[pyfunction]
fn reduce_modules(modules: Vec<ModuleDef>) -> PyResult<Vec<ModuleDef>> {
    Ok(modules
        .into_iter()
        .map(|m| reducer::reduce_module(m))
        .collect())
}

/// Calculate cyclomatic complexity for a function body
#[pyfunction]
fn calculate_complexity(
    source: &str,
    language: &str,
    start_byte: usize,
    end_byte: usize,
) -> PyResult<u32> {
    reducer::complexity::calculate(source, language, start_byte, end_byte)
}

/// Redact secrets from source code
#[pyfunction]
fn redact_secrets(source: &str, language: &str) -> PyResult<(String, Vec<RedactedSecret>)> {
    security::redact::redact(source, language)
}

/// Export to MU format
#[pyfunction]
fn export_mu(modules: Vec<ModuleDef>, config: ExportConfig) -> PyResult<String> {
    exporter::mu_format::export(&modules, &config)
}

/// Export to JSON format
#[pyfunction]
fn export_json(modules: Vec<ModuleDef>, config: ExportConfig) -> PyResult<String> {
    exporter::json::export(&modules, &config)
}

#[pymodule]
fn _core(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<ModuleDef>()?;
    m.add_class::<ClassDef>()?;
    m.add_class::<FunctionDef>()?;
    m.add_class::<ParameterDef>()?;
    m.add_class::<ImportDef>()?;
    m.add_class::<AttributeDef>()?;
    m.add_class::<ConstantDef>()?;
    m.add_class::<FileInfo>()?;
    m.add_class::<ParseResult>()?;
    m.add_class::<ExportConfig>()?;
    m.add_class::<RedactedSecret>()?;

    m.add_function(wrap_pyfunction!(parse_files, m)?)?;
    m.add_function(wrap_pyfunction!(reduce_modules, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_complexity, m)?)?;
    m.add_function(wrap_pyfunction!(redact_secrets, m)?)?;
    m.add_function(wrap_pyfunction!(export_mu, m)?)?;
    m.add_function(wrap_pyfunction!(export_json, m)?)?;

    Ok(())
}
```

### Python Integration Layer

```python
# src/mu/parser/__init__.py
"""MU Parser - delegates to Rust core or Python fallback."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mu.scanner import FileInfo
    from mu.parser.models import ModuleDef, ParseResult

# Try to import Rust core
_USE_RUST_CORE = os.environ.get("MU_USE_RUST", "1") != "0"
_core = None

if _USE_RUST_CORE:
    try:
        from mu import _core
    except ImportError:
        _core = None

def parse_files(file_infos: list[FileInfo], num_threads: int | None = None) -> list[ParseResult]:
    """Parse multiple files, using Rust core if available."""
    if _core is not None:
        # Use Rust parallel parser
        return _core.parse_files(file_infos, num_threads)
    else:
        # Fallback to Python sequential parser
        from mu.parser.fallback import parse_files_python
        return parse_files_python(file_infos)

def parse_file(file_path: str, language: str) -> ParseResult:
    """Parse a single file."""
    if _core is not None:
        from mu.scanner import FileInfo
        info = FileInfo(path=file_path, language=language, size_bytes=0, hash="", lines=0)
        results = _core.parse_files([info], 1)
        return results[0]
    else:
        from mu.parser.fallback import parse_file_python
        return parse_file_python(file_path, language)
```

### Cargo.toml

```toml
[package]
name = "mu-core"
version = "0.1.0"
edition = "2021"
license = "MIT"

[lib]
name = "_core"
crate-type = ["cdylib"]

[dependencies]
pyo3 = { version = "0.20", features = ["extension-module"] }
rayon = "1.8"
tree-sitter = "0.20"
tree-sitter-python = "0.20"
tree-sitter-typescript = "0.20"
tree-sitter-javascript = "0.20"
tree-sitter-go = "0.20"
tree-sitter-java = "0.20"
tree-sitter-rust = "0.20"
tree-sitter-c-sharp = "0.20"
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
regex = "1.10"
once_cell = "1.19"
thiserror = "1.0"

[dev-dependencies]
criterion = "0.5"

[[bench]]
name = "parsing"
harness = false

[profile.release]
lto = true
codegen-units = 1
opt-level = 3
```

### maturin pyproject.toml

```toml
[build-system]
requires = ["maturin>=1.4,<2.0"]
build-backend = "maturin"

[project]
name = "mu-core"
version = "0.1.0"
description = "High-performance Rust core for MU"
requires-python = ">=3.10"
classifiers = [
    "Programming Language :: Rust",
    "Programming Language :: Python :: Implementation :: CPython",
]

[tool.maturin]
features = ["pyo3/extension-module"]
module-name = "mu._core"
python-source = "python"
```

---

## Implementation Tasks

### Task 1: Project Setup (30 min)

**Files:**
- `mu-core/Cargo.toml`
- `mu-core/pyproject.toml`
- `mu-core/src/lib.rs` (skeleton)
- `mu-core/src/types.rs` (all type definitions)

**Acceptance:**
- `maturin develop` succeeds
- `python -c "from mu import _core; print(_core)"` works
- All types importable from Python

---

### Task 2: Parser - Python Language (1 hour)

**Files:**
- `mu-core/src/parser/mod.rs`
- `mu-core/src/parser/python.rs`

**Source reference:** `src/mu/parser/python_extractor.py`

**Implementation:**
```rust
// mu-core/src/parser/python.rs
use tree_sitter::{Language, Parser, Node};
use crate::types::*;

extern "C" { fn tree_sitter_python() -> Language; }

pub fn parse(source: &str, file_path: &str) -> ParseResult {
    let mut parser = Parser::new();
    let language = unsafe { tree_sitter_python() };
    parser.set_language(language).unwrap();

    let tree = parser.parse(source, None).unwrap();
    let root = tree.root_node();

    let mut module = ModuleDef::new(file_path);

    for child in root.children(&mut root.walk()) {
        match child.kind() {
            "import_statement" | "import_from_statement" => {
                module.imports.push(extract_import(&child, source));
            }
            "class_definition" => {
                module.classes.push(extract_class(&child, source));
            }
            "function_definition" => {
                module.functions.push(extract_function(&child, source));
            }
            _ => {}
        }
    }

    ParseResult::success(module)
}

fn extract_function(node: &Node, source: &str) -> FunctionDef {
    // Mirror python_extractor.py logic
    let name = get_child_by_field(node, "name")
        .map(|n| node_text(&n, source))
        .unwrap_or_default();

    let parameters = get_child_by_field(node, "parameters")
        .map(|n| extract_parameters(&n, source))
        .unwrap_or_default();

    let return_type = get_child_by_field(node, "return_type")
        .map(|n| node_text(&n, source));

    let body = get_child_by_field(node, "body").unwrap();
    let complexity = crate::reducer::complexity::calculate_for_node(&body, source, "python");

    FunctionDef {
        name,
        parameters,
        return_type,
        body_complexity: complexity,
        is_async: has_child_of_type(node, "async"),
        line_start: node.start_position().row as u32 + 1,
        line_end: node.end_position().row as u32 + 1,
        ..Default::default()
    }
}
```

**Acceptance:**
- Parse Python files matching Python extractor output
- Test: `parse_file("test.py", "python")` returns correct ModuleDef
- Benchmark: 1000 Python files < 2 sec

---

### Task 3: Parser - TypeScript/JavaScript (45 min)

**Files:**
- `mu-core/src/parser/typescript.rs`
- `mu-core/src/parser/javascript.rs`

**Source reference:** `src/mu/parser/typescript_extractor.py`

**Acceptance:**
- Parse TS/JS/TSX/JSX files
- Handle arrow functions, classes, interfaces
- Test against existing Python output

---

### Task 4: Parser - Go (30 min)

**Files:**
- `mu-core/src/parser/go.rs`

**Source reference:** `src/mu/parser/go_extractor.py`

**Acceptance:**
- Parse Go files
- Handle methods with receivers
- Test against existing Python output

---

### Task 5: Parser - Java (30 min)

**Files:**
- `mu-core/src/parser/java.rs`

**Source reference:** `src/mu/parser/java_extractor.py`

**Acceptance:**
- Parse Java files
- Handle annotations, generics
- Test against existing Python output

---

### Task 6: Parser - Rust (30 min)

**Files:**
- `mu-core/src/parser/rust.rs`

**Source reference:** `src/mu/parser/rust_extractor.py`

**Acceptance:**
- Parse Rust files
- Handle impl blocks, traits
- Test against existing Python output

---

### Task 7: Parser - C# (30 min)

**Files:**
- `mu-core/src/parser/csharp.rs`

**Source reference:** `src/mu/parser/csharp_extractor.py`

**Acceptance:**
- Parse C# files
- Handle async/await, nullable types, attributes
- Test against existing Python output

---

### Task 8: Parallel Parse Orchestration (30 min)

**Files:**
- `mu-core/src/parser/mod.rs` (update)
- `mu-core/src/lib.rs` (update)

**Implementation:**
```rust
// mu-core/src/parser/mod.rs
use rayon::prelude::*;
use std::fs;

pub fn parse_files_parallel(file_infos: Vec<FileInfo>) -> Vec<ParseResult> {
    file_infos
        .par_iter()
        .map(|info| {
            let source = fs::read_to_string(&info.path).unwrap_or_default();
            match info.language.as_str() {
                "python" => python::parse(&source, &info.path),
                "typescript" | "tsx" => typescript::parse(&source, &info.path),
                "javascript" | "jsx" => javascript::parse(&source, &info.path),
                "go" => go::parse(&source, &info.path),
                "java" => java::parse(&source, &info.path),
                "rust" => rust::parse(&source, &info.path),
                "csharp" => csharp::parse(&source, &info.path),
                _ => ParseResult::error(format!("Unsupported language: {}", info.language)),
            }
        })
        .collect()
}
```

**Acceptance:**
- `parse_files([...], num_threads=8)` uses 8 threads
- CPU utilization > 90% on multi-core machines
- Benchmark: 1000 mixed files < 2 sec

---

### Task 9: Reducer (45 min)

**Files:**
- `mu-core/src/reducer/mod.rs`
- `mu-core/src/reducer/rules.rs`
- `mu-core/src/reducer/complexity.rs`

**Source reference:**
- `src/mu/reducer/rules.py`
- `src/mu/parser/base.py` (complexity calculation)

**Implementation:**
```rust
// mu-core/src/reducer/complexity.rs
use tree_sitter::Node;
use once_cell::sync::Lazy;
use std::collections::{HashMap, HashSet};

static DECISION_POINTS: Lazy<HashMap<&str, HashSet<&str>>> = Lazy::new(|| {
    let mut m = HashMap::new();
    m.insert("python", HashSet::from([
        "if_statement", "for_statement", "while_statement",
        "except_clause", "with_statement", "assert_statement",
        "conditional_expression", "match_statement", "case_clause",
        "list_comprehension", "set_comprehension", "dict_comprehension",
        "generator_expression", "boolean_operator",
    ]));
    m.insert("typescript", HashSet::from([
        "if_statement", "for_statement", "while_statement",
        "for_in_statement", "do_statement", "switch_case",
        "catch_clause", "ternary_expression",
    ]));
    // ... other languages
    m
});

pub fn calculate_for_node(node: &Node, source: &str, language: &str) -> u32 {
    let decision_types = DECISION_POINTS.get(language).unwrap();
    let mut count = 1u32; // Base complexity

    fn traverse(node: &Node, source: &str, decision_types: &HashSet<&str>, count: &mut u32) {
        if decision_types.contains(node.kind()) {
            if node.kind() == "binary_expression" {
                // Check for && || operators
                if let Some(op) = node.child_by_field_name("operator") {
                    let op_text = &source[op.start_byte()..op.end_byte()];
                    if matches!(op_text, "&&" | "||" | "and" | "or" | "??") {
                        *count += 1;
                    }
                }
            } else {
                *count += 1;
            }
        }

        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            traverse(&child, source, decision_types, count);
        }
    }

    traverse(node, source, decision_types, &mut count);
    count
}
```

**Acceptance:**
- Complexity matches Python implementation exactly
- All existing complexity tests pass
- Reducer transforms match Python output

---

### Task 10: Secret Redaction (30 min)

**Files:**
- `mu-core/src/security/mod.rs`
- `mu-core/src/security/redact.rs`

**Source reference:** `src/mu/security/__init__.py`

**Acceptance:**
- Detect API keys, passwords, tokens
- Return list of redacted secrets with positions
- Match Python redaction behavior exactly

---

### Task 11: Exporters (45 min)

**Files:**
- `mu-core/src/exporter/mod.rs`
- `mu-core/src/exporter/mu_format.rs`
- `mu-core/src/exporter/json.rs`
- `mu-core/src/exporter/markdown.rs`

**Source reference:** `src/mu/assembler/exporters.py`

**Acceptance:**
- MU format output identical to Python version
- JSON output identical to Python version
- Markdown output identical to Python version

---

### Task 12: Python Integration (30 min)

**Files:**
- `src/mu/_core.pyi` (type stubs)
- `src/mu/parser/__init__.py` (update)
- `src/mu/parser/fallback.py` (rename existing)
- `src/mu/cli.py` compress command (update to use _core)

**Acceptance:**
- `MU_USE_RUST=1 mu compress .` uses Rust core
- `MU_USE_RUST=0 mu compress .` uses Python fallback
- Output identical regardless of backend
- Type hints work in IDE

---

### Task 13: Testing & Benchmarks (30 min)

**Files:**
- `mu-core/tests/parser_tests.rs`
- `mu-core/tests/reducer_tests.rs`
- `mu-core/benches/parsing.rs`
- `tests/integration/test_rust_core.py`

**Acceptance:**
- All Rust unit tests pass
- All Python integration tests pass with Rust core
- Benchmark shows 3-5x improvement
- CI runs tests with both backends

---

### Task 14: CI/CD Integration (15 min)

**Files:**
- `.github/workflows/rust.yml` (new)
- `.github/workflows/release.yml` (update)
- `pyproject.toml` (update for maturin)

**Acceptance:**
- CI builds Rust core on Linux/macOS/Windows
- Wheels published for all platforms
- `pip install mu` includes Rust core

---

## Dependencies

```
Task 1 (setup)
    │
    ├── Task 2 (Python parser)
    │       │
    ├── Task 3 (TS/JS parser) ─┐
    │                          │
    ├── Task 4 (Go parser) ────┤
    │                          ├── Task 8 (parallel orchestration)
    ├── Task 5 (Java parser) ──┤
    │                          │
    ├── Task 6 (Rust parser) ──┤
    │                          │
    └── Task 7 (C# parser) ────┘
                               │
    ┌──────────────────────────┘
    │
    ├── Task 9 (reducer)
    │
    ├── Task 10 (security)
    │
    └── Task 11 (exporters)
            │
            ▼
    Task 12 (Python integration)
            │
            ▼
    Task 13 (testing)
            │
            ▼
    Task 14 (CI/CD)
```

**Parallelizable:** Tasks 2-7 (all parsers) can run in parallel after Task 1.

---

## Validation Strategy

### 1. Output Parity Testing

```python
# tests/integration/test_rust_core.py
import os
import pytest

def test_output_parity():
    """Ensure Rust and Python produce identical output."""
    test_files = get_test_fixtures()

    # Parse with Python
    os.environ["MU_USE_RUST"] = "0"
    python_result = parse_files(test_files)

    # Parse with Rust
    os.environ["MU_USE_RUST"] = "1"
    rust_result = parse_files(test_files)

    assert python_result == rust_result
```

### 2. Benchmark Suite

```rust
// mu-core/benches/parsing.rs
use criterion::{criterion_group, criterion_main, Criterion};

fn bench_parse_1000_files(c: &mut Criterion) {
    let files = load_test_fixtures();

    c.bench_function("parse_1000_files", |b| {
        b.iter(|| parse_files_parallel(files.clone()))
    });
}

criterion_group!(benches, bench_parse_1000_files);
criterion_main!(benches);
```

### 3. Memory Profiling

```bash
# Before (Python)
/usr/bin/time -v mu compress large-repo/ 2>&1 | grep "Maximum resident"

# After (Rust core)
MU_USE_RUST=1 /usr/bin/time -v mu compress large-repo/ 2>&1 | grep "Maximum resident"
```

---

## Rollout Plan

### Phase 1: Opt-in (Week 1)
- Ship with `MU_USE_RUST=0` default
- Users can opt-in with `MU_USE_RUST=1`
- Gather feedback, fix edge cases

### Phase 2: Opt-out (Week 2)
- Change default to `MU_USE_RUST=1`
- Users can opt-out with `MU_USE_RUST=0`
- Monitor for issues

### Phase 3: Default (Week 3+)
- Remove fallback flag (or keep for debugging)
- Python fallback only used if Rust binary missing

---

## Risk Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Tree-sitter version mismatch | Medium | High | Pin exact versions in Cargo.toml |
| PyO3 GIL issues | Low | Medium | Test with `py.allow_threads()` pattern |
| Platform-specific bugs | Medium | Medium | CI tests on Linux/macOS/Windows |
| Output parity failures | Medium | High | Extensive comparison tests |
| Build complexity | Low | Low | maturin handles most complexity |

---

## Success Metrics

| Metric | Before | Target | Measured |
|--------|--------|--------|----------|
| Parse 1000 files | ~8 sec | < 2 sec | |
| `mu compress` on MU repo | ~5 sec | < 1.5 sec | |
| Peak memory (large repo) | ~800 MB | < 250 MB | |
| `mu --help` startup | ~50ms | ~50ms (unchanged) | |
| Test suite pass rate | 100% | 100% | |

---

## Open Questions

1. **DuckDB integration?** - Should graph building also move to Rust? (Probably not - DuckDB is already fast)

2. **WASM target?** - Should we compile to WASM for browser-based MU viewer? (Future consideration)

3. **Incremental parsing?** - Tree-sitter supports incremental parsing. Worth implementing for daemon? (Future consideration)

---

## Appendix: Source File Mapping

| Rust File | Python Source | Purpose |
|-----------|---------------|---------|
| `parser/python.rs` | `parser/python_extractor.py` | Python parsing |
| `parser/typescript.rs` | `parser/typescript_extractor.py` | TS/JS parsing |
| `parser/go.rs` | `parser/go_extractor.py` | Go parsing |
| `parser/java.rs` | `parser/java_extractor.py` | Java parsing |
| `parser/rust.rs` | `parser/rust_extractor.py` | Rust parsing |
| `parser/csharp.rs` | `parser/csharp_extractor.py` | C# parsing |
| `reducer/rules.rs` | `reducer/rules.py` | Transformation rules |
| `reducer/complexity.rs` | `parser/base.py:185-250` | Cyclomatic complexity |
| `security/redact.rs` | `security/__init__.py` | Secret redaction |
| `exporter/mu_format.rs` | `assembler/exporters.py:export_mu` | MU format |
| `exporter/json.rs` | `assembler/exporters.py:export_json` | JSON format |
