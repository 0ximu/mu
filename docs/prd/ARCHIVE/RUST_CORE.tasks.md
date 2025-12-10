# MU Rust Core (mu-core) - Task Breakdown

## Business Context

**Problem**: MU's hot paths (parsing, reducing, graph building) are CPU-bound Python operations bottlenecked by the GIL. On large codebases (10K+ files), parsing alone takes ~8 seconds with py-tree-sitter.

**Outcome**: 4x speedup (8s -> <2s for 1000 files), 70% memory reduction (800MB -> <250MB peak), true parallel parsing across all CPU cores.

**Users**: Any developer using `mu compress` or `mu kernel build` on medium-to-large codebases.

**Approach**: Implement core parsing and reduction logic in Rust via PyO3, maintaining identical Python interfaces for zero-friction adoption.

---

## Existing Patterns Found

| Pattern | File | Relevance |
|---------|------|-----------|
| LanguageExtractor Protocol | `/Users/imu/Dev/work/mu/src/mu/parser/base.py:16-21` | Rust parsers mirror this interface |
| Python Extractor Implementation | `/Users/imu/Dev/work/mu/src/mu/parser/python_extractor.py` | Reference for Python parsing logic |
| TypeScript Extractor | `/Users/imu/Dev/work/mu/src/mu/parser/typescript_extractor.py` | Handles JS/TS/JSX/TSX |
| Go Extractor | `/Users/imu/Dev/work/mu/src/mu/parser/go_extractor.py` | Methods with receivers, structs, interfaces |
| Rust Extractor | `/Users/imu/Dev/work/mu/src/mu/parser/rust_extractor.py` | Traits, impl blocks, use statements |
| Java Extractor | `/Users/imu/Dev/work/mu/src/mu/parser/java_extractor.py` | Annotations, generics, packages |
| C# Extractor | `/Users/imu/Dev/work/mu/src/mu/parser/csharp_extractor.py` | Async/await, nullable types |
| Data Models | `/Users/imu/Dev/work/mu/src/mu/parser/models.py` | ModuleDef, ClassDef, FunctionDef, etc. |
| Cyclomatic Complexity | `/Users/imu/Dev/work/mu/src/mu/parser/base.py:193-320` | DECISION_POINTS by language |
| Transformation Rules | `/Users/imu/Dev/work/mu/src/mu/reducer/rules.py` | TransformationRules dataclass |
| Reducer Generator | `/Users/imu/Dev/work/mu/src/mu/reducer/generator.py` | ReducedModule, reduce_codebase |
| Secret Detection | `/Users/imu/Dev/work/mu/src/mu/security/__init__.py` | DEFAULT_PATTERNS, SecretScanner |
| Exporters | `/Users/imu/Dev/work/mu/src/mu/assembler/exporters.py` | export_json, export_markdown, export_mu |
| MU Generator | `/Users/imu/Dev/work/mu/src/mu/reducer/generator.py:161-406` | MUGenerator class with sigils |
| Parser Tests | `/Users/imu/Dev/work/mu/tests/unit/test_parser.py` | Test patterns for all 7 languages |
| pyproject.toml | `/Users/imu/Dev/work/mu/pyproject.toml` | Build system uses hatchling |
| CI Workflow | `/Users/imu/Dev/work/mu/.github/workflows/ci.yml` | Python 3.11/3.12 on Linux/macOS |

---

## Task Breakdown

### Task 1: Project Setup & Type Definitions

**Files:**
- `mu-core/Cargo.toml`
- `mu-core/pyproject.toml` (maturin config)
- `mu-core/src/lib.rs` (module exports skeleton)
- `mu-core/src/types.rs` (all type definitions)
- `mu-core/.gitignore`

**Pattern Reference:**
- Mirror types from `/Users/imu/Dev/work/mu/src/mu/parser/models.py`
- Use PyO3 `#[pyclass]` and `#[pyo3(get, set)]` for Python interop

**Implementation Notes:**
- Use `maturin` for build tooling (module-name: `mu._core`)
- Types must implement `Clone`, `Debug`, `Serialize`, `Deserialize`
- All fields exposed to Python via `#[pyo3(get, set)]`

**Rust Types to Define:**
```rust
// Must match Python dataclasses exactly
pub struct ParameterDef { name, type_annotation, default_value, is_variadic, is_keyword }
pub struct FunctionDef { name, parameters, return_type, decorators, is_async, is_method, is_static, is_classmethod, is_property, docstring, body_complexity, body_source, start_line, end_line }
pub struct ClassDef { name, bases, decorators, methods, attributes, docstring, start_line, end_line }
pub struct ImportDef { module, names, alias, is_from, is_dynamic, dynamic_pattern, dynamic_source, line_number }
pub struct ModuleDef { name, path, language, imports, classes, functions, module_docstring, total_lines }
pub struct FileInfo { path, language, size_bytes, hash, lines }
pub struct ParseResult { success, module, error }
```

**Acceptance Criteria:**
- [ ] `maturin develop` succeeds without errors
- [ ] `python -c "from mu import _core; print(_core)"` works
- [ ] All type structs importable from Python
- [ ] Types serialize to JSON matching Python `to_dict()` output

---

### Task 2: Parser - Python Language

**Files:**
- `mu-core/src/parser/mod.rs`
- `mu-core/src/parser/python.rs`

**Pattern Reference:** `/Users/imu/Dev/work/mu/src/mu/parser/python_extractor.py`

**Implementation Notes:**
- Extract: module docstring, imports (regular + from + dynamic), classes, functions, decorated definitions
- Handle dynamic imports: `importlib.import_module()`, `__import__()`
- Use `tree-sitter-python` crate

**Key AST Node Types:**
- `import_statement`, `import_from_statement` -> ImportDef
- `class_definition` -> ClassDef (with bases from `argument_list`)
- `function_definition` -> FunctionDef (with `async` check)
- `decorated_definition` -> unwrap decorators, then class/function

**Acceptance Criteria:**
- [ ] Parse Python files matching `/Users/imu/Dev/work/mu/tests/unit/test_parser.py::TestPythonParser` output
- [ ] Extract docstrings from module, classes, and functions
- [ ] Detect dynamic imports (importlib, __import__)
- [ ] Calculate cyclomatic complexity using DECISION_POINTS from base.py

---

### Task 3: Parser - TypeScript/JavaScript

**Files:**
- `mu-core/src/parser/typescript.rs`
- `mu-core/src/parser/javascript.rs` (re-exports typescript with js-specific handling)

**Pattern Reference:** `/Users/imu/Dev/work/mu/src/mu/parser/typescript_extractor.py`

**Implementation Notes:**
- Same extractor handles TS/JS/TSX/JSX (minor AST differences)
- Handle: function declarations, arrow functions, class declarations, interfaces
- Detect dynamic `import()` expressions and `require()` calls

**Key AST Node Types:**
- `import_statement` -> ImportDef
- `function_declaration`, `arrow_function` -> FunctionDef
- `class_declaration` -> ClassDef
- `interface_declaration` -> ClassDef with `interface` decorator
- `call_expression` with `import` or `require` -> dynamic ImportDef

**Acceptance Criteria:**
- [ ] Parse TS/JS/TSX/JSX files
- [ ] Handle arrow functions, classes, interfaces
- [ ] Detect dynamic import() and require() patterns
- [ ] Match TestTypeScriptParser test output

---

### Task 4: Parser - Go

**Files:**
- `mu-core/src/parser/go.rs`

**Pattern Reference:** `/Users/imu/Dev/work/mu/src/mu/parser/go_extractor.py`

**Implementation Notes:**
- Extract package name from `package_clause`
- Handle method receivers (pointer vs value)
- Mark exported symbols (uppercase first letter)
- Struct embedded types go to `bases`

**Key AST Node Types:**
- `package_clause` -> module name
- `import_declaration`, `import_spec` -> ImportDef
- `function_declaration` -> FunctionDef
- `method_declaration` -> FunctionDef with `receiver:Type` decorator
- `type_declaration` -> struct_type/interface_type -> ClassDef

**Acceptance Criteria:**
- [ ] Parse Go files
- [ ] Handle methods with receivers (pointer and value)
- [ ] Detect exported symbols
- [ ] Match TestGoParser test output

---

### Task 5: Parser - Java

**Files:**
- `mu-core/src/parser/java.rs`

**Pattern Reference:** `/Users/imu/Dev/work/mu/src/mu/parser/java_extractor.py`

**Implementation Notes:**
- Extract package name as module name
- Handle annotations (decorators)
- Handle generics in class/method signatures
- Parse extends/implements for bases

**Key AST Node Types:**
- `package_declaration` -> module name
- `import_declaration` -> ImportDef (check for static import)
- `class_declaration`, `interface_declaration`, `enum_declaration` -> ClassDef
- `method_declaration`, `constructor_declaration` -> FunctionDef
- `annotation` -> decorator

**Acceptance Criteria:**
- [ ] Parse Java files
- [ ] Handle annotations, generics
- [ ] Extract extends/implements hierarchy
- [ ] Match TestJavaParser test output

---

### Task 6: Parser - Rust

**Files:**
- `mu-core/src/parser/rust.rs`

**Pattern Reference:** `/Users/imu/Dev/work/mu/src/mu/parser/rust_extractor.py`

**Implementation Notes:**
- Handle `use` declarations (scoped, aliased, wildcard)
- Merge `impl` block methods with their types
- Parse traits with method signatures
- Mark `pub` visibility

**Key AST Node Types:**
- `use_declaration` -> ImportDef (convert `::` to `.`)
- `function_item` -> FunctionDef
- `struct_item`, `enum_item`, `trait_item` -> ClassDef
- `impl_item` -> extract methods, associate with type

**Acceptance Criteria:**
- [ ] Parse Rust files
- [ ] Handle impl blocks and traits
- [ ] Associate impl methods with structs
- [ ] Match TestRustParser test output

---

### Task 7: Parser - C#

**Files:**
- `mu-core/src/parser/csharp.rs`

**Pattern Reference:** `/Users/imu/Dev/work/mu/src/mu/parser/csharp_extractor.py`

**Implementation Notes:**
- Parse `using` directives
- Handle async/await methods
- Parse nullable types (C# 8+)
- Handle properties (mark with `is_property`)

**Key AST Node Types:**
- `using_directive` -> ImportDef
- `class_declaration`, `interface_declaration` -> ClassDef
- `method_declaration`, `constructor_declaration` -> FunctionDef
- `property_declaration` -> FunctionDef with `is_property=True`

**Acceptance Criteria:**
- [ ] Parse C# files
- [ ] Handle async methods, nullable types
- [ ] Parse properties and interfaces
- [ ] Match TestCSharpParser test output

---

### Task 8: Parallel Parse Orchestration

**Files:**
- `mu-core/src/parser/mod.rs` (update)
- `mu-core/src/lib.rs` (add `parse_files` function)

**Pattern Reference:** PRD design at `/Users/imu/Dev/work/mu/docs/prd/RUST_CORE.md:607-630`

**Implementation Notes:**
- Use `rayon::par_iter()` for parallel file processing
- Release GIL with `py.allow_threads()`
- Route to language-specific parser based on `FileInfo.language`
- Handle file I/O in Rust (read file contents)

**Key Function:**
```rust
#[pyfunction]
#[pyo3(signature = (file_infos, num_threads=None))]
fn parse_files(
    py: Python<'_>,
    file_infos: Vec<FileInfo>,
    num_threads: Option<usize>,
) -> PyResult<Vec<ParseResult>>
```

**Acceptance Criteria:**
- [ ] `parse_files([...], num_threads=8)` uses 8 threads
- [ ] CPU utilization > 90% on multi-core machines
- [ ] Benchmark: 1000 mixed files < 2 sec
- [ ] Graceful error handling (returns ParseResult with error field)

---

### Task 9: Cyclomatic Complexity & Reducer

**Files:**
- `mu-core/src/reducer/mod.rs`
- `mu-core/src/reducer/complexity.rs`
- `mu-core/src/reducer/rules.rs`

**Pattern Reference:**
- Complexity: `/Users/imu/Dev/work/mu/src/mu/parser/base.py:193-320`
- Rules: `/Users/imu/Dev/work/mu/src/mu/reducer/rules.py`

**Implementation Notes:**
- Port DECISION_POINTS and DECISION_OPERATORS to Rust
- Implement `calculate_cyclomatic_complexity(node, language, source)` -> u32
- Port TransformationRules with should_strip_import, should_strip_method, filter_parameters

**Key Data:**
```rust
static DECISION_POINTS: Lazy<HashMap<&str, HashSet<&str>>> = ...;
// python: if_statement, for_statement, while_statement, except_clause, ...
// typescript: if_statement, for_statement, ternary_expression, binary_expression (&&, ||), ...
// go: if_statement, for_statement, expression_case, ...
```

**Acceptance Criteria:**
- [ ] Complexity matches Python implementation exactly (test against TestCyclomaticComplexity)
- [ ] TransformationRules filtering matches Python output
- [ ] Reducer produces identical ReducedModule structure

---

### Task 10: Secret Redaction

**Files:**
- `mu-core/src/security/mod.rs`
- `mu-core/src/security/patterns.rs`
- `mu-core/src/security/redact.rs`

**Pattern Reference:** `/Users/imu/Dev/work/mu/src/mu/security/__init__.py`

**Implementation Notes:**
- Port DEFAULT_PATTERNS (AWS, GCP, Azure, Stripe, GitHub, etc.)
- Use `regex` crate with compiled patterns (once_cell::Lazy)
- Return `(redacted_source, Vec<RedactedSecret>)`

**Key Patterns to Port:**
- AWS: `AKIA...`, secret_access_key
- GCP: `AIza...`
- GitHub: `ghp_...`, `gho_...`
- OpenAI: `sk-...`, `sk-proj-...`
- Private keys: `-----BEGIN RSA PRIVATE KEY-----`
- Connection strings: postgres://, mongodb+srv://

**Acceptance Criteria:**
- [ ] Detect all patterns from DEFAULT_PATTERNS
- [ ] Redact format: `:: REDACTED:{pattern_name}`
- [ ] Match Python redaction behavior exactly

---

### Task 11: Exporters (MU, JSON, Markdown)

**Files:**
- `mu-core/src/exporter/mod.rs`
- `mu-core/src/exporter/mu_format.rs`
- `mu-core/src/exporter/json.rs`
- `mu-core/src/exporter/markdown.rs`

**Pattern Reference:** `/Users/imu/Dev/work/mu/src/mu/assembler/exporters.py`

**Implementation Notes:**
- MU format: sigils (`!`, `$`, `#`, `@`, `::`), operators (`->`, `=>`)
- JSON format: match structure from export_json
- Markdown format: match structure from export_markdown
- Support shell_safe mode for MU format

**MU Sigils (from generator.py:162-177):**
```rust
const SIGIL_MODULE: &str = "!";
const SIGIL_ENTITY: &str = "$";
const SIGIL_FUNCTION: &str = "#";
const SIGIL_METADATA: &str = "@";
const OP_FLOW: &str = "->";
const OP_MUTATION: &str = "=>";
```

**Acceptance Criteria:**
- [ ] MU format output identical to Python version
- [ ] JSON output identical to Python version
- [ ] Markdown output identical to Python version
- [ ] Shell-safe mode escapes `#`, `$`, `!`, `?`

---

### Task 12: Python Integration Layer

**Files:**
- `src/mu/_core.pyi` (type stubs)
- `src/mu/parser/__init__.py` (update)
- `src/mu/parser/fallback.py` (rename current implementation)

**Pattern Reference:** PRD Python integration at `/Users/imu/Dev/work/mu/docs/prd/RUST_CORE.md:319-361`

**Implementation Notes:**
- Feature flag: `MU_USE_RUST` environment variable (default: "1")
- Fallback to Python if `_core` import fails
- Type stubs for IDE support

**Integration Pattern:**
```python
_USE_RUST_CORE = os.environ.get("MU_USE_RUST", "1") != "0"
_core = None

if _USE_RUST_CORE:
    try:
        from mu import _core
    except ImportError:
        _core = None

def parse_files(file_infos, num_threads=None):
    if _core is not None:
        return _core.parse_files(file_infos, num_threads)
    else:
        from mu.parser.fallback import parse_files_python
        return parse_files_python(file_infos)
```

**Acceptance Criteria:**
- [ ] `MU_USE_RUST=1 mu compress .` uses Rust core
- [ ] `MU_USE_RUST=0 mu compress .` uses Python fallback
- [ ] Output identical regardless of backend
- [ ] Type hints work in IDE (via .pyi stub)

---

### Task 13: Testing & Benchmarks

**Files:**
- `mu-core/tests/parser_tests.rs`
- `mu-core/tests/reducer_tests.rs`
- `mu-core/tests/security_tests.rs`
- `mu-core/benches/parsing.rs`
- `tests/integration/test_rust_core.py`

**Pattern Reference:**
- Python tests: `/Users/imu/Dev/work/mu/tests/unit/test_parser.py`
- Test CLAUDE.md: `/Users/imu/Dev/work/mu/tests/CLAUDE.md`

**Implementation Notes:**
- Rust unit tests: cargo test
- Python integration tests: compare Rust vs Python output
- Criterion benchmarks for parsing performance

**Test Categories:**
1. **Parser tests per language**: port TestPythonParser, TestGoParser, etc.
2. **Complexity tests**: port TestCyclomaticComplexity
3. **Security tests**: port test_redact patterns
4. **Parity tests**: Rust output == Python output

**Acceptance Criteria:**
- [ ] All Rust unit tests pass (`cargo test`)
- [ ] All Python integration tests pass with Rust core
- [ ] Benchmark shows >= 3x improvement over Python
- [ ] Parity test confirms identical output

---

### Task 14: CI/CD Integration

**Files:**
- `.github/workflows/rust.yml` (new)
- `.github/workflows/ci.yml` (update)
- `pyproject.toml` (update for maturin)

**Pattern Reference:**
- Existing CI: `/Users/imu/Dev/work/mu/.github/workflows/ci.yml`
- maturin pyproject: PRD at `/Users/imu/Dev/work/mu/docs/prd/RUST_CORE.md:408-428`

**Implementation Notes:**
- New workflow for Rust builds
- Build wheels for Linux/macOS/Windows
- Install maturin in CI
- Run cargo test + pytest with Rust core

**CI Matrix:**
- Linux: x86_64, aarch64
- macOS: x86_64, aarch64 (Apple Silicon)
- Windows: x86_64

**Acceptance Criteria:**
- [ ] CI builds Rust core on Linux/macOS/Windows
- [ ] Cargo tests pass in CI
- [ ] Python tests pass with Rust core in CI
- [ ] Wheels published for all platforms

---

## Dependencies

```
Task 1 (Project Setup)
    |
    +-- Task 2 (Python parser)
    |
    +-- Task 3 (TS/JS parser)
    |
    +-- Task 4 (Go parser)          --> Task 8 (Parallel Orchestration)
    |                                         |
    +-- Task 5 (Java parser)                  |
    |                                         |
    +-- Task 6 (Rust parser)                  |
    |                                         |
    +-- Task 7 (C# parser)                    |
                                              v
                        +---------------------+---------------------+
                        |                     |                     |
                        v                     v                     v
              Task 9 (Reducer)      Task 10 (Security)    Task 11 (Exporters)
                        |                     |                     |
                        +---------------------+---------------------+
                                              |
                                              v
                                 Task 12 (Python Integration)
                                              |
                                              v
                                   Task 13 (Testing)
                                              |
                                              v
                                    Task 14 (CI/CD)
```

**Parallelizable:** Tasks 2-7 (all parsers) can run in parallel after Task 1.

**Sequential:** Tasks 9-11 depend on Task 8. Tasks 12-14 are sequential.

---

## Edge Cases

1. **Parse errors**: Return ParseResult with error field, don't crash
2. **Encoding issues**: Use lossy UTF-8 conversion (bytes that fail to decode -> replacement char)
3. **Missing grammars**: Return error for unsupported language (currently 7 supported)
4. **Empty files**: Return valid ModuleDef with empty collections
5. **Circular impl blocks**: Collect all impls, merge after first pass
6. **Large files (>1MB)**: May need chunked reading, test with real-world large files
7. **Symlinks**: Follow symlinks (consistent with Python scanner behavior)
8. **Unicode identifiers**: Tree-sitter handles these, ensure Rust->Python transfer preserves them

---

## Security Considerations

1. **Secret patterns**: Must match Python implementation exactly to avoid leaks
2. **User code parsing**: Sandboxed by design (no code execution)
3. **File access**: Only read files provided by scanner (no arbitrary path access)
4. **Memory safety**: Rust provides memory safety; verify no unsafe blocks unless necessary

---

## Performance Targets

| Metric | Python Baseline | Rust Target | Improvement |
|--------|-----------------|-------------|-------------|
| Parse 1000 files | ~8 sec | < 2 sec | 4x |
| `mu compress` on MU repo | ~5 sec | < 1.5 sec | 3x |
| Peak memory (large repo) | ~800 MB | < 250 MB | 70% reduction |
| Startup overhead | 0 | < 50ms | Negligible |

---

## Deviations from PRD

1. **Tree-sitter versions**: PRD specifies `tree-sitter = "0.20"`, but current Rust crate is `0.22+`. Use latest compatible versions.

2. **Build system**: Main project uses `hatchling`, not `maturin` for Python build. Need to integrate maturin as optional build for Rust extension.

3. **pyproject.toml location**: PRD shows `mu-core/pyproject.toml` for maturin, but main project pyproject.toml at root. May need workspace or separate build.

4. **Scanner stays Python**: Scanner is I/O bound and integrates with Python filesystem APIs - correctly kept in Python as PRD specifies.

---

## Rollout Plan (from PRD)

| Phase | Default | User Override | Duration |
|-------|---------|---------------|----------|
| Phase 1 | MU_USE_RUST=0 | MU_USE_RUST=1 to opt-in | Week 1 |
| Phase 2 | MU_USE_RUST=1 | MU_USE_RUST=0 to opt-out | Week 2 |
| Phase 3 | Rust only | Python fallback if binary missing | Week 3+ |

---

## File Mapping Reference

| Rust File | Python Source | Purpose |
|-----------|---------------|---------|
| `parser/python.rs` | `parser/python_extractor.py` | Python parsing |
| `parser/typescript.rs` | `parser/typescript_extractor.py` | TS/JS parsing |
| `parser/go.rs` | `parser/go_extractor.py` | Go parsing |
| `parser/java.rs` | `parser/java_extractor.py` | Java parsing |
| `parser/rust.rs` | `parser/rust_extractor.py` | Rust parsing |
| `parser/csharp.rs` | `parser/csharp_extractor.py` | C# parsing |
| `reducer/rules.rs` | `reducer/rules.py` | Transformation rules |
| `reducer/complexity.rs` | `parser/base.py:193-320` | Cyclomatic complexity |
| `security/redact.rs` | `security/__init__.py` | Secret redaction |
| `exporter/mu_format.rs` | `reducer/generator.py:161-406` | MU format |
| `exporter/json.rs` | `assembler/exporters.py:13-92` | JSON format |
| `exporter/markdown.rs` | `assembler/exporters.py:95-214` | Markdown format |
