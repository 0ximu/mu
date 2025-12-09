# PRD: OMEGA Compression Integration for `mu compress`

## Overview

Wire up the OMEGA macro compression engine to the `mu compress` CLI command, enabling S-expression output with synthesized macros for maximum token efficiency.

**Current State:**
- `mu compress . -f lisp` outputs raw S-expressions (50,193 tokens)
- `mu compress . -f mu` outputs sigil format (47,371 tokens)
- MU sigils are 5.6% more efficient than raw Lisp

**Target State:**
- `mu compress . -f omega` outputs macro-compressed S-expressions
- OMEGA should achieve 15-30% better compression than sigils via pattern-based macros

## Architecture

### Existing Components

```
src/mu/kernel/mubase.py          # MUbase - DuckDB graph database
  └── build(modules, root_path)  # Loads ModuleDef[] into graph

src/mu/kernel/builder.py         # GraphBuilder - AST to graph conversion
  └── from_module_defs(modules, root_path) -> (nodes, edges)

src/mu/intelligence/synthesizer.py  # MacroSynthesizer - pattern->macro
  └── synthesize() -> SynthesisResult
  └── _build_node_macro_map() -> dict[node_id, MacroDefinition]

src/mu/kernel/export/omega.py    # OmegaExporter - macro-compressed output
  └── export(mubase, options) -> ExportResult
```

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        mu compress . -f omega                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  1. PARSE: Scanner + Parser                                             │
│     scan_codebase_auto(path) -> ScanResult                             │
│     parse_file(path, lang) -> ModuleDef[]                              │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  2. REDUCE: Transformation Rules                                        │
│     reduce_codebase(modules, rules) -> ReducedCodebase                 │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  3. BUILD GRAPH: In-Memory MUbase                                       │
│     mubase = MUbase(":memory:")  # DuckDB in-memory                    │
│     mubase.build(modules, root_path)  # Load graph                     │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  4. SYNTHESIZE MACROS: Pattern Detection + Macro Generation            │
│     synthesizer = MacroSynthesizer(mubase)                             │
│     result = synthesizer.synthesize()                                   │
│     -> SynthesisResult(macros, node_macro_map, compression_estimate)   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  5. EXPORT: OMEGA-Compressed S-Expressions                              │
│     exporter = OmegaExporter()                                          │
│     output = exporter.export(mubase, OmegaExportOptions(...))          │
│     -> ExportResult(output, node_count, compression_ratio)             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  OUTPUT: codebase.omega.lisp                                            │
│                                                                         │
│  ;; MU-Lisp Macro Definitions                                          │
│  (defmacro api [method path name params] "REST API endpoint")          │
│  (defmacro test [name target] "Test function")                         │
│  (defmacro service [name deps methods] "Service class")                │
│                                                                         │
│  ;; Codebase Context                                                   │
│  (mu-lisp :version "1.0"                                               │
│    :core [module class defn]                                           │
│    :standard [api test service]                                        │
│    (module auth :file "src/auth.py"                                    │
│      (api post "/login" authenticate [user:str pass:str])              │
│      (service Auth [db cache] ...)))                                   │
└─────────────────────────────────────────────────────────────────────────┘
```

## Implementation

### File: `src/mu/commands/compress.py`

#### 1. Add Format Option

```python
@click.option(
    "--format",
    "-f",
    type=click.Choice(["mu", "json", "markdown", "lisp", "omega"]),
    default="mu",
    help="Output format",
)
```

#### 2. Add OMEGA Export Branch

After the existing assembler step (Step 5), add:

```python
# Step 6: Generate output
if format == "omega":
    # OMEGA requires graph intelligence - build in-memory MUbase
    from mu.kernel.mubase import MUbase
    from mu.kernel.export.omega import OmegaExporter, OmegaExportOptions

    print_info("Building intelligence graph...")
    mubase = MUbase(":memory:")
    mubase.build(parsed_modules, path.resolve())

    print_info("Synthesizing macros...")
    exporter = OmegaExporter()
    result = exporter.export(
        mubase,
        OmegaExportOptions(
            include_synthesized=True,
            max_synthesized_macros=5,
            include_header=True,
            pretty_print=True,
        )
    )

    output_str = result.output

    # Report compression metrics
    if hasattr(result, 'compression_ratio'):
        print_info(f"OMEGA compression: {result.compression_ratio:.1%} reduction")

    mubase.close()

elif format == "json":
    # ... existing code
```

### File: `src/mu/kernel/export/omega.py`

The `OmegaExporter` already exists and works correctly. Minor enhancements needed:

#### 1. Use Reduced Module Data (Memory-First Strategy)

**Problem:** MUbase nodes store minimal data (name, type, file_path, properties dict). The rich AST data (parameters with types, return types, decorators) lives in `ReducedModule` objects that we already have in memory.

**Solution:** Pass reduced modules directly to OmegaExporter to avoid redundant queries:

```python
def export(
    self,
    mubase: MUbase,
    options: OmegaExportOptions | None = None,
    reduced_modules: list[ReducedModule] | None = None,  # NEW: In-memory AST
) -> ExportResult:
    """Export with memory-first data access.

    Data Resolution Order:
    1. reduced_modules (in-memory, richest data)
    2. MUbase nodes (graph relationships, pattern matching)

    MUbase is used for:
    - MacroSynthesizer pattern detection (needs graph queries)
    - Node→Macro mapping (needs node IDs)

    reduced_modules is used for:
    - Actual S-expression generation (needs full AST)
    """
```

**Implementation Pattern:**

```python
# Build lookup from reduced modules
module_lookup: dict[str, ReducedModule] = {}
class_lookup: dict[str, ClassDef] = {}
func_lookup: dict[str, FunctionDef] = {}

if reduced_modules:
    for rm in reduced_modules:
        module_lookup[rm.path] = rm
        for cls in rm.classes:
            class_lookup[f"{rm.path}:{cls.name}"] = cls
        for func in rm.functions:
            func_lookup[f"{rm.path}:{func.name}"] = func

# During export: prefer in-memory data
def _node_to_lisp(self, node: Node) -> str:
    # Try in-memory first
    if node.type == NodeType.CLASS:
        key = f"{node.file_path}:{node.name}"
        if key in class_lookup:
            cls = class_lookup[key]
            return self._class_def_to_lisp(cls)  # Rich data!

    # Fallback to node properties
    return self._node_properties_to_lisp(node)
```

**Why This Matters:**

| Source | Parameters | Return Type | Decorators | Docstring |
|--------|------------|-------------|------------|-----------|
| `ReducedModule` | `[ParameterDef(name, type_annotation, default)]` | `str` | `list[str]` | `str` |
| MUbase Node | `properties["parameters"]` (JSON) | `properties["return_type"]` | `properties["decorators"]` | `properties["docstring"]` |

The `ReducedModule` has typed objects; MUbase has serialized JSON. Using in-memory data is both faster and richer.

#### 2. Add Compression Metrics

```python
@dataclass
class ExportResult:
    output: str
    format: str
    node_count: int
    edge_count: int
    error: str | None = None
    compression_ratio: float = 0.0  # NEW: tokens saved vs raw lisp
    macros_applied: int = 0          # NEW: number of macro applications
```

### File: `src/mu/intelligence/synthesizer.py`

Already complete. Key methods:

- `synthesize()` - Main entry point, returns `SynthesisResult`
- `_build_node_macro_map()` - Pre-computes node→macro mapping for O(1) lookup
- `STANDARD_MACROS` - Hardcoded macros for common patterns (api, test, service, etc.)

### Macro Application Logic

The `OmegaExporter._generate_compressed_body()` method already handles macro application:

```python
for node in nodes:
    if node.id in node_macro_map:
        macro = node_macro_map[node.id]
        node_data = macro.extract_node_data(node)
        output.append(macro.apply(node_data))
    else:
        output.append(self._node_to_lisp(node))  # Fallback
```

## Standard Macros

| Macro | Signature | Matches |
|-------|-----------|---------|
| `api` | `[method path name params]` | Functions with `@app.get/post/etc` decorators |
| `test` | `[name target]` | Functions starting with `test_` or in test files |
| `service` | `[name deps methods]` | Classes ending with `Service` |
| `repo` | `[name entity]` | Classes containing `Repository` or `Repo` |
| `model` | `[name fields]` | Classes with `@dataclass` or ending with `Model` |
| `hook` | `[name deps returns]` | Functions starting with `use` |
| `component` | `[name props]` | PascalCase classes/functions (React) |

## Expected Compression

Based on pattern frequency in the MU codebase:

| Pattern | Count | Tokens Saved/Instance | Total Savings |
|---------|-------|----------------------|---------------|
| test functions | 200+ | ~8 tokens | ~1,600 |
| service classes | 15 | ~12 tokens | ~180 |
| dataclass models | 50 | ~10 tokens | ~500 |
| API endpoints | 20 | ~15 tokens | ~300 |
| **Total** | | | **~2,580** |

**Projected:** 47,371 - 2,580 = **~44,791 tokens** (5.4% improvement over sigils)

With synthesized domain-specific macros: potentially **10-15% improvement**.

## Success Criteria

1. `mu compress . -f omega` produces valid S-expression output
2. Output includes macro definitions header
3. Nodes matching patterns use macro syntax instead of verbose S-expr
4. Token count is measurably lower than both `lisp` and `mu` formats
5. Output parses correctly (balanced parentheses, valid Lisp)

## Testing

### Unit Tests

```python
def test_omega_format_produces_macros():
    """OMEGA output should include defmacro definitions."""
    result = compress_codebase(path, format="omega")
    assert "(defmacro" in result

def test_omega_applies_test_macro():
    """Test functions should use (test ...) macro."""
    result = compress_codebase(test_file_path, format="omega")
    assert "(test " in result
    assert "(defn test_" not in result  # Should be compressed

def test_omega_token_efficiency():
    """OMEGA should use fewer tokens than raw lisp."""
    lisp_result = compress_codebase(path, format="lisp")
    omega_result = compress_codebase(path, format="omega")

    lisp_tokens = count_tokens(lisp_result)
    omega_tokens = count_tokens(omega_result)

    assert omega_tokens < lisp_tokens
```

### Integration Test

```bash
# Generate all formats and compare
uv run mu compress . -f mu -o codebase.mu
uv run mu compress . -f lisp -o codebase.lisp
uv run mu compress . -f omega -o codebase.omega.lisp

# Count tokens
python -c "
import tiktoken
enc = tiktoken.get_encoding('cl100k_base')
for f in ['codebase.mu', 'codebase.lisp', 'codebase.omega.lisp']:
    with open(f) as fp:
        tokens = len(enc.encode(fp.read()))
    print(f'{f}: {tokens:,} tokens')
"
```

## Timeline

1. **Phase 1:** Add `omega` format option to compress command (wiring)
2. **Phase 2:** Ensure OmegaExporter uses reduced module data for rich output
3. **Phase 3:** Add compression metrics reporting
4. **Phase 4:** Benchmark and tune macro thresholds

## Dependencies

- `src/mu/kernel/mubase.py` - MUbase class with `:memory:` support ✅
- `src/mu/kernel/builder.py` - GraphBuilder.from_module_defs() ✅
- `src/mu/intelligence/synthesizer.py` - MacroSynthesizer ✅
- `src/mu/intelligence/patterns.py` - PatternDetector ✅
- `src/mu/kernel/export/omega.py` - OmegaExporter ✅

All dependencies are implemented and tested.
