# UX Improvements & Bug Fixes - Task Breakdown

## Business Context

**Problem**: MU's complexity metrics, table output, and cache system have usability issues that reduce confidence in analysis results and degrade terminal experience.

**Outcome**: Accurate cyclomatic complexity metrics, clean terminal output, SQL-familiar schema discovery, and functional caching.

**Users**: Developers using MU for codebase analysis, AI assistants querying via MUQL/MCP.

---

## Priority Order (Ship Order)

| Task | Item | Effort | Impact | Notes |
|------|------|--------|--------|-------|
| **1** | SHOW TABLES Syntax | 30-45 min | Medium | Grammar + transformer + executor aliases |
| **2** | Table Path Truncation | 1 hr | Medium | Formatter + CLI flag threading |
| **3** | Cache Bug Fix | 1-1.5 hr | Medium | Codebase-level caching strategy |
| **4** | MCP Test Command | 45 min | Low | Optional, nice-to-have |
| **5** | Complexity Metric | 2-3 hr | High | **Separate PR** - 7 files, language research needed |

**Recommendation**: Ship Tasks 1-4 together, Task 5 as separate PR.

---

## Existing Patterns Found

| Pattern | File | Relevance |
|---------|------|-----------|
| AST node counting | `src/mu/parser/base.py:185-190` | Current `count_nodes()` - needs replacement |
| Body extraction | `src/mu/parser/python_extractor.py:227-230` | Where `body_complexity` is set |
| Table formatting | `src/mu/kernel/muql/formatter.py:60-115` | `format_table()` builds column widths |
| DESCRIBE grammar | `src/mu/kernel/muql/grammar.lark:175-183` | Schema introspection rules |
| DESCRIBE transformer | `src/mu/kernel/muql/parser.py` | `describe_tables`, `describe_columns` methods |
| Cache set/get | `src/mu/cache/__init__.py:266-304` | `set_file_result()` pattern |
| MCP tool pattern | `src/mu/mcp/server.py:88-138` | `@mcp.tool()` decorator usage |

---

## Task 1: Add SHOW TABLES/COLUMNS Syntax (30-45 min)

**File(s)**:
- `src/mu/kernel/muql/grammar.lark` - Grammar rules
- `src/mu/kernel/muql/parser.py` - Transformer methods
- `src/mu/kernel/muql/executor.py` - Execution (reuse existing DESCRIBE logic)

**Pattern**: Follow `describe_query` at `grammar.lark:175-183` and transformer in `parser.py`

**Implementation**:

```lark
// grammar.lark - Add after describe_query

// SHOW syntax (SQL-compatible aliases)
show_tables_query: SHOW_KW TABLES_KW
show_columns_query: SHOW_KW COLUMNS_KW FROM_KW node_type

// Update query alternatives (add to ?query rule)
?query: select_query
      | show_query
      | show_tables_query   // NEW
      | show_columns_query  // NEW
      | find_query
      | path_query
      | analyze_query
      | history_query
      | blame_query
      | describe_query
```

```python
# parser.py - Add transformer methods

def show_tables_query(self, items: list[Any]) -> DescribeQuery:
    """SHOW TABLES -> DESCRIBE tables"""
    return DescribeQuery(target=DescribeTarget.TABLES)

def show_columns_query(self, items: list[Any]) -> DescribeQuery:
    """SHOW COLUMNS FROM <node_type> -> DESCRIBE columns from <node_type>"""
    node_type = items[0]  # Already transformed by node_type rule
    return DescribeQuery(target=DescribeTarget.COLUMNS, node_type=node_type)
```

**Acceptance**:
- [x] `SHOW TABLES` works (alias to `DESCRIBE tables`)
- [x] `SHOW COLUMNS FROM functions` works (alias to `DESCRIBE columns from functions`)
- [x] Case insensitive (`show tables`, `SHOW TABLES`, `Show Tables`)
- [x] Tests for both new syntaxes in `tests/unit/test_muql_parser.py`
- [x] REPL `.help` updated to mention new syntax

---

## Task 2: Fix Table Output Path Truncation (1 hr)

**File(s)**:
- `src/mu/kernel/muql/formatter.py` - Add truncation logic
- `src/mu/cli.py` - Add `--full-paths` flag to `query` and `kernel query` commands
- `src/mu/kernel/muql/engine.py` - Thread flag through to formatter

**Pattern**: Follow existing `format_table()` at line 60-115

**Implementation**:

```python
# formatter.py - Add helper functions

import shutil

def _truncate_path(path: str, max_segments: int = 3) -> str:
    """Truncate path to show only last N segments."""
    parts = path.replace("\\", "/").split("/")
    if len(parts) <= max_segments:
        return path
    return ".../" + "/".join(parts[-max_segments:])

def _get_terminal_width() -> int:
    """Get terminal width, default to 120 if unavailable."""
    return shutil.get_terminal_size((120, 24)).columns

def _is_path_column(col_name: str) -> bool:
    """Check if column contains paths."""
    return col_name.lower() in ("path", "file_path", "source_path", "module_path")

# Update format_table signature and logic
def format_table(
    result: QueryResult,
    no_color: bool = False,
    truncate_paths: bool = True,
) -> str:
    """Format with optional path truncation."""
    # ... existing setup ...

    # Apply truncation to path columns
    if truncate_paths:
        path_indices = [i for i, col in enumerate(columns) if _is_path_column(col)]
        for row in rows:
            for idx in path_indices:
                if idx < len(row) and isinstance(row[idx], str):
                    row[idx] = _truncate_path(row[idx])

    # ... rest of existing logic ...
```

```python
# cli.py - Add flag to query commands

@cli.command("query")
@click.argument("muql_query")
@click.option("--full-paths", is_flag=True, help="Show full file paths without truncation")
def query_command(muql_query: str, full_paths: bool):
    # ... existing logic ...
    output = format_result(result, truncate_paths=not full_paths)
```

**Acceptance**:
- [x] Paths truncated to last 3 segments by default
- [x] `--full-paths` flag shows complete paths
- [x] Works for columns: `path`, `file_path`, `source_path`, `module_path`
- [x] Windows backslashes handled correctly
- [x] Existing tests still pass

---

## Task 3: Fix Cache Population (Codebase-Level Caching) (1-1.5 hr)

**File(s)**:
- `src/mu/cache/__init__.py` - Add `get_codebase_result()` and `set_codebase_result()`
- `src/mu/cli.py` - Integrate caching in compress command (~line 500-700)

**Root Cause Analysis**:
- `CacheConfig` has `enabled=True` by default
- `CacheManager` is instantiated at `cli.py:498`
- Cache directory `.mu-cache` is **never created** because `_ensure_initialized()` is lazy
- `compress` command **never calls** any cache methods after parsing
- **Bug**: The file cache feature exists but is completely unused

**Better Strategy**: Codebase-level caching (not per-file)
- Compute single cache key from hash of all file hashes (already in `scan_result`)
- Cache the final assembled/exported output once
- Simple invalidation: any file change = new combined hash = cache miss
- Avoids N serializations during parse loop

**Implementation**:

```python
# cache/__init__.py - Add codebase-level caching

@dataclass
class CachedCodebaseResult:
    """Cached compress output for entire codebase."""
    codebase_hash: str
    output: str
    format: str  # "mu", "json", "markdown"
    cached_at: str
    file_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "codebase_hash": self.codebase_hash,
            "output": self.output,
            "format": self.format,
            "cached_at": self.cached_at,
            "file_count": self.file_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CachedCodebaseResult:
        return cls(**data)


class CacheManager:
    # ... existing methods ...

    @staticmethod
    def compute_codebase_hash(file_hashes: list[str]) -> str:
        """Compute combined hash from all file hashes."""
        combined = "|".join(sorted(file_hashes))
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def get_codebase_result(self, codebase_hash: str, format: str) -> CachedCodebaseResult | None:
        """Get cached codebase compress result."""
        if not self.enabled:
            return None
        self._ensure_initialized()
        key = f"codebase:{format}:{codebase_hash}"
        try:
            data = self._file_cache.get(key)
            if data:
                self._update_stats("hits")
                return CachedCodebaseResult.from_dict(data)
        except Exception as e:
            logger.warning(f"Error reading codebase cache: {e}")
        self._update_stats("misses")
        return None

    def set_codebase_result(
        self,
        codebase_hash: str,
        output: str,
        format: str,
        file_count: int,
    ) -> None:
        """Cache codebase compress result."""
        if not self.enabled:
            return
        self._ensure_initialized()
        key = f"codebase:{format}:{codebase_hash}"
        result = CachedCodebaseResult(
            codebase_hash=codebase_hash,
            output=output,
            format=format,
            cached_at=datetime.now(UTC).isoformat(),
            file_count=file_count,
        )
        try:
            self._file_cache.set(key, result.to_dict(), expire=self.ttl_seconds)
            self._update_stats("file_entries")
        except Exception as e:
            logger.warning(f"Error writing codebase cache: {e}")
```

```python
# cli.py compress command - Add caching integration

# After scan, before expensive work:
file_hashes = [f.hash for f in scan_result.files if f.hash]
codebase_hash = CacheManager.compute_codebase_hash(file_hashes)

# Check cache
cached = cache_manager.get_codebase_result(codebase_hash, output_format)
if cached:
    print_info(f"Using cached result ({cached.file_count} files)")
    click.echo(cached.output)
    return

# ... existing parsing, reducing, assembly logic ...

# After export, cache the result:
cache_manager.set_codebase_result(
    codebase_hash=codebase_hash,
    output=final_output,
    format=output_format,
    file_count=len(scan_result.files),
)
```

**Acceptance**:
- [x] `.mu-cache` directory created on first `mu compress` run
- [x] `mu cache stats` shows non-zero entries after compress
- [x] Second identical compress run returns instantly with "Using cached result"
- [x] Any file change invalidates cache (new hash)
- [x] Cache respects `--no-cache` flag
- [x] Different output formats cached separately (`mu`, `json`, `markdown`)

---

## Task 4: Add MCP Test Command (45 min) - Optional

**File(s)**:
- `src/mu/mcp/server.py` - Add `test_tools()` function
- `src/mu/cli.py` - Add `mu mcp test` command

**Pattern**: Follow `mu_status()` tool at `server.py:410-460`

**Implementation**:

```python
# server.py - Add test function

def test_tools() -> dict[str, Any]:
    """Test all MCP tools without starting server."""
    results = {}

    # Test mu_status (no database needed)
    try:
        status = mu_status()
        results["mu_status"] = {"ok": True, "daemon": status.get("daemon_running")}
    except Exception as e:
        results["mu_status"] = {"ok": False, "error": str(e)}

    # Test mu_query (requires .mubase)
    try:
        result = mu_query("DESCRIBE tables")
        results["mu_query"] = {"ok": True, "tables": len(result.rows)}
    except Exception as e:
        results["mu_query"] = {"ok": False, "error": str(e)}

    # Test mu_search
    try:
        result = mu_search("%", limit=1)
        results["mu_search"] = {"ok": True}
    except Exception as e:
        results["mu_search"] = {"ok": False, "error": str(e)}

    # Test mu_context (requires embeddings, may fail gracefully)
    try:
        result = mu_context("test", max_tokens=100)
        results["mu_context"] = {"ok": True, "tokens": result.token_count}
    except Exception as e:
        results["mu_context"] = {"ok": False, "error": str(e)}

    return results
```

```python
# cli.py - Add test command to mcp group

@mcp_group.command("test")
@click.pass_context
def mcp_test(ctx):
    """Test MCP tools without starting server."""
    from mu.mcp.server import test_tools

    results = test_tools()

    all_ok = all(r.get("ok") for r in results.values())

    for tool_name, result in results.items():
        status = "PASS" if result.get("ok") else "FAIL"
        color = "green" if result.get("ok") else "red"
        click.secho(f"  {status}: {tool_name}", fg=color)
        if not result.get("ok"):
            click.echo(f"        {result.get('error', 'Unknown error')}")

    sys.exit(0 if all_ok else 1)
```

**Acceptance**:
- [x] `mu mcp test` runs without starting server
- [x] Tests tools: `mu_status`, `mu_query`, `mu_search`, `mu_context`
- [x] Reports PASS/FAIL for each tool with colors
- [x] Exit code 0 if all pass, 1 if any fail
- [x] Shows helpful error messages for failures

---

## Task 5: Implement Cyclomatic Complexity Metric (2-3 hr) - SEPARATE PR

**Scope Warning**: This task is larger than initially estimated due to:
- 7 files across 6 language extractors need modification
- Each language has different tree-sitter node type names
- Missing node types need research: comprehensions (Python), optional chaining `?.`/`??` (TS/C#), switch expressions (C#)

**Recommendation**: Split into phases:
1. **Phase A**: Python extractor only (1 hr) - ship and validate approach
2. **Phase B**: TypeScript/JavaScript (45 min)
3. **Phase C**: Go, Java, Rust, C# (1-1.5 hr)

**File(s)**:
- `src/mu/parser/base.py:185-190` - Add `calculate_cyclomatic_complexity()`
- `src/mu/parser/python_extractor.py:227-228` - Replace `count_nodes(child)`
- `src/mu/parser/typescript_extractor.py:217,241,278` - Three locations
- `src/mu/parser/go_extractor.py:155,212` - Two locations
- `src/mu/parser/java_extractor.py:301,333` - Method and constructor
- `src/mu/parser/rust_extractor.py:229` - Single location
- `src/mu/parser/csharp_extractor.py:206,209,230` - Three locations

---

### Research Summary (Dec 2024)

**Sources Consulted:**
- [Radon Documentation - Code Metrics](https://radon.readthedocs.io/en/latest/intro.html)
- [Checkstyle - CyclomaticComplexity](https://checkstyle.org/checks/metrics/cyclomaticcomplexity.html)
- [Wikipedia - Cyclomatic Complexity](https://en.wikipedia.org/wiki/Cyclomatic_complexity)
- [McCabe NIST Paper](https://www.mccabe.com/pdf/mccabe-nist235r.pdf)
- [tree-sitter-python node-types.json](https://github.com/tree-sitter/tree-sitter-python/blob/master/src/node-types.json)
- [tree-sitter-typescript node-types.json](https://github.com/tree-sitter/tree-sitter-typescript/blob/master/tsx/src/node-types.json)
- [mccabe-cyclomatic Go implementation](https://github.com/freenerd/mccabe-cyclomatic)

**McCabe Cyclomatic Complexity Formula:**
- Base complexity = 1 (for method entry point)
- Add +1 for each decision point
- Formula: `M = D + 1` where D = number of decision points

**What Counts as Decision Points (Industry Consensus):**

| Construct | Adds | Notes |
|-----------|------|-------|
| `if` / `elif` | +1 | Each conditional branch |
| `for` / `while` / `do` | +1 | Loop decision at start |
| `except` / `catch` | +1 | Each exception handler |
| `case` (switch) | +1 | Each case branch (not default) |
| `with` (Python) | +1 | Context manager = implicit try |
| `assert` (Python) | +1 | Implicit conditional |
| Ternary (`?:`) | +1 | Inline conditional |
| Boolean `and`/`&&` | +1 | Short-circuit = branch |
| Boolean `or`/`||` | +1 | Short-circuit = branch |
| Nullish coalescing `??` | +1 | Conditional evaluation |
| Comprehensions (Python) | +1 | Per `for`/`if` clause |
| Match arms (Python/Rust) | +1 | Per case pattern |

**What Does NOT Count:**
- `else` / `default` - Not decision points (+0)
- `finally` - Always executes (+0)
- Loop expressions without decision (`loop {}` in Rust body counted by contents)

**Tree-sitter Node Types by Language (Verified):**

```python
DECISION_POINTS: dict[str, set[str]] = {
    "python": {
        # Control flow
        "if_statement",           # if/elif
        "for_statement",          # for loops
        "while_statement",        # while loops
        "except_clause",          # try/except handlers
        "with_statement",         # context managers
        "assert_statement",       # assertions
        # Expressions
        "boolean_operator",       # 'and', 'or' - tree-sitter wraps these
        "conditional_expression", # x if cond else y
        # Pattern matching (Python 3.10+)
        "match_statement",        # match keyword
        "case_clause",            # each case pattern
        # Comprehensions (each adds a decision point)
        "list_comprehension",     # [x for x in y]
        "set_comprehension",      # {x for x in y}
        "dict_comprehension",     # {k: v for k, v in y}
        "generator_expression",   # (x for x in y)
        # Note: for_in_clause and if_clause inside comprehensions
        # are children - the comprehension node itself counts as 1
    },
    "typescript": {
        # Control flow
        "if_statement",
        "for_statement",
        "while_statement",
        "for_in_statement",       # for...in loops
        "do_statement",           # do...while
        "switch_case",            # case label (not switch_statement itself)
        "catch_clause",
        # Expressions
        "ternary_expression",     # cond ? a : b
        "binary_expression",      # SPECIAL: check operator for && || ??
    },
    "javascript": {
        # Same as TypeScript (shared grammar base)
        "if_statement",
        "for_statement",
        "while_statement",
        "for_in_statement",
        "do_statement",
        "switch_case",
        "catch_clause",
        "ternary_expression",
        "binary_expression",      # SPECIAL: check operator
    },
    "go": {
        "if_statement",
        "for_statement",          # Go only has 'for' (no while)
        "expression_case",        # switch case
        "type_case",              # type switch case
        "communication_case",     # select case (channel ops)
        "binary_expression",      # SPECIAL: check for && ||
    },
    "java": {
        "if_statement",
        "for_statement",
        "while_statement",
        "do_statement",
        "enhanced_for_statement", # for-each
        "switch_block_statement_group",  # case blocks
        "catch_clause",
        "ternary_expression",
        "binary_expression",      # SPECIAL: check for && ||
    },
    "rust": {
        "if_expression",          # Rust uses expressions, not statements
        "for_expression",
        "while_expression",
        "loop_expression",        # infinite loop (body decisions count)
        "match_expression",       # match keyword
        "match_arm",              # each arm pattern
        "binary_expression",      # SPECIAL: check for && ||
    },
    "csharp": {
        "if_statement",
        "for_statement",
        "while_statement",
        "do_statement",
        "foreach_statement",
        "switch_section",         # case section
        "catch_clause",
        "conditional_expression", # ternary
        "binary_expression",      # SPECIAL: check for && || ??
        "switch_expression",      # C# 8.0+ switch expressions
        "switch_expression_arm",  # each arm
        "conditional_access_expression",  # ?. (null-conditional)
    },
}

# Binary operators that count as decision points
# Must check operator child node text for binary_expression
DECISION_OPERATORS: set[str] = {"&&", "||", "and", "or", "??"}
```

**Special Handling for binary_expression:**
Tree-sitter's `binary_expression` includes ALL binary ops (+, -, ==, &&, etc.).
Only `&&`, `||`, and `??` are decision points. Must inspect the operator:

```python
if n.type == "binary_expression":
    # Find operator child - may be unnamed node or have field name
    for child in n.children:
        text = source[child.start_byte:child.end_byte].decode()
        if text in DECISION_OPERATORS:
            count += 1
            break
```

**Python Comprehension Nuance:**
A comprehension like `[x for x in items if x > 0]` has tree structure:
```
list_comprehension
  └─ for_in_clause
       └─ if_clause
```
Radon counts each `for_in_clause` and `if_clause` as +1.
For simplicity, we can count the comprehension itself as +1 (conservative)
or walk children to count each clause (accurate).

**Recommended Approach:** Count each `for_in_clause` and `if_clause` inside comprehensions.

**Thresholds (Reference):**
- 1-10: Simple, low risk
- 11-20: Moderate complexity
- 21-50: High complexity, hard to test
- 50+: Untestable

---

**Implementation**:

```python
# base.py - Add cyclomatic complexity function

from tree_sitter import Node

# Decision point node types by language (tree-sitter node names)
DECISION_POINTS: dict[str, set[str]] = {
    "python": {
        "if_statement", "for_statement", "while_statement",
        "except_clause", "with_statement", "assert_statement",
        "boolean_operator",  # 'and', 'or' wrapped by tree-sitter
        "conditional_expression",  # ternary
        "match_statement", "case_clause",
        # Comprehension clauses (count each loop/condition inside)
        "for_in_clause", "if_clause",
    },
    "typescript": {
        "if_statement", "for_statement", "while_statement",
        "for_in_statement", "do_statement",
        "switch_case", "catch_clause",
        "ternary_expression",
        "binary_expression",  # SPECIAL: check operator
    },
    "javascript": {
        "if_statement", "for_statement", "while_statement",
        "for_in_statement", "do_statement",
        "switch_case", "catch_clause",
        "ternary_expression",
        "binary_expression",  # SPECIAL: check operator
    },
    "go": {
        "if_statement", "for_statement",
        "expression_case", "type_case", "communication_case",
        "binary_expression",  # SPECIAL: check operator
    },
    "java": {
        "if_statement", "for_statement", "while_statement",
        "do_statement", "enhanced_for_statement",
        "switch_block_statement_group", "catch_clause",
        "ternary_expression",
        "binary_expression",  # SPECIAL: check operator
    },
    "rust": {
        "if_expression", "for_expression", "while_expression",
        "loop_expression", "match_expression", "match_arm",
        "binary_expression",  # SPECIAL: check operator
    },
    "csharp": {
        "if_statement", "for_statement", "while_statement",
        "do_statement", "foreach_statement",
        "switch_section", "catch_clause",
        "conditional_expression",
        "binary_expression",  # SPECIAL: check operator
        "switch_expression", "switch_expression_arm",
        "conditional_access_expression",
    },
}

# Binary operators that count as decision points
DECISION_OPERATORS: set[str] = {"&&", "||", "and", "or", "??"}


def calculate_cyclomatic_complexity(node: Node, language: str, source: bytes) -> int:
    """Calculate McCabe cyclomatic complexity (decision point counting).

    Base complexity is 1. Each decision point adds 1.
    Decision points: if, for, while, case, catch, &&, ||, ternary, etc.

    Args:
        node: Tree-sitter AST node (typically function body)
        language: Programming language name
        source: Original source bytes for operator text extraction

    Returns:
        Cyclomatic complexity score (minimum 1)
    """
    decision_types = DECISION_POINTS.get(language, set())
    complexity = 1  # Base complexity

    def _is_decision_operator(n: Node) -> bool:
        """Check if binary_expression has a decision operator."""
        for child in n.children:
            text = source[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
            if text in DECISION_OPERATORS:
                return True
        return False

    def traverse(n: Node) -> None:
        nonlocal complexity

        if n.type in decision_types:
            if n.type == "binary_expression":
                # Only count if operator is && || or ??
                if _is_decision_operator(n):
                    complexity += 1
            else:
                complexity += 1

        for child in n.children:
            traverse(child)

    traverse(node)
    return complexity
```

**Implementation Note - Source Parameter Threading:**
The `source: bytes` parameter is required for `calculate_cyclomatic_complexity()` to check binary expression operators. However, the current `count_nodes()` function only takes `node: Node`. When replacing calls:

```python
# BEFORE (current code)
func_def.body_complexity = count_nodes(child)

# AFTER (new code)
func_def.body_complexity = calculate_cyclomatic_complexity(child, "python", source)
```

All extractors already have `source: bytes` available in their `extract()` and `_extract_function()` methods - it's passed from `base.py:169`. No new threading needed, just add `source` as third argument at each call site.

---

**Acceptance**:
- [ ] New function `calculate_cyclomatic_complexity()` in `base.py`
- [ ] Complete decision point mappings for all 6 languages
- [ ] All extractors call new function instead of `count_nodes()`
- [ ] Tests verify expected complexity values:
  - `if x: pass` = 2
  - `if x and y: pass` = 3
  - `for i in range(10): pass` = 2
  - `[x for x in y if z]` = 3 (Python)
  - Nested if: `if x: if y: pass` = 3 (base + 2 ifs)
- [ ] EF migrations show realistic complexity (not 48,986)
- [ ] Backward compatibility: field still named `body_complexity`

---

## Dependencies

```
Task 1 (SHOW syntax) - standalone
Task 2 (table output) - standalone
Task 3 (cache fix) - standalone
Task 4 (MCP test) - standalone
Task 5 (complexity) - standalone, but recommend separate PR

Ship order: 1 -> 2 -> 3 -> 4 (all one PR), then 5 (separate PR)
```

## Edge Cases

### Task 1 (SHOW Syntax)
- Case sensitivity (`SHOW tables` vs `show TABLES`) - grammar handles via `/i` flag
- Invalid table names (`SHOW COLUMNS FROM invalid`) - reuse existing error handling

### Task 2 (Table Output)
- Windows paths with backslashes - normalize to forward slashes
- Very short paths (< 3 segments) - show full path
- Unicode characters in paths - pass through unchanged
- Terminal width < 80 columns - still truncate, may wrap

### Task 3 (Cache)
- Disk full scenarios - catch exception, continue without caching
- Permission errors on cache directory - warn and continue
- Race conditions on concurrent compress - fine, both compute same result
- Different CLI flags (--no-llm) - include relevant flags in cache key

### Task 4 (MCP Test)
- No `.mubase` file present - report as expected failure with instructions
- Daemon running vs not running - test both code paths
- Embeddings not configured - mu_context may fail gracefully

### Task 5 (Complexity)
- Empty function body: complexity = 1 (base)
- Lambda/arrow functions: count inner decision points
- Nested functions: each function counted independently
- List comprehensions with conditionals (Python): count the `if`
- Short-circuit operators: each `&&`/`||` adds 1
- Nested ternaries: each `?:` adds 1

## Security Considerations

- Task 3 (Cache): Ensure cache directory permissions are restrictive (0700)
- Task 4 (MCP Test): No new attack surface as test runs locally
- All tasks: No user input interpolation into SQL (already parameterized)
