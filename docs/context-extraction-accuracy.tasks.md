# Context Extraction Accuracy Improvement - Task Breakdown

## Business Context

**Problem**: MU's semantic compression led to incorrect diagnosis during a daemon audit. When asked "how does cwd propagate", MU concluded "cwd is not being passed" when the actual code clearly passes `cwd=str(cwd)`. This happened because context extraction prioritizes *structural understanding* (function signatures) over *behavioral accuracy* (call sites with actual arguments).

**Outcome**: When users ask "how does X work", MU should include call sites showing HOW functions are actually used, not just their definitions. This transforms MU from a "documentation tool" into an "investigative tool".

**Users**: AI agents (Claude Code), developers debugging issues, code reviewers understanding data flow.

---

## Existing Patterns Found

| Pattern | File | Relevance |
|---------|------|-----------|
| Strategy pattern for extraction | `src/mu/kernel/context/strategies.py` | Each intent (EXPLAIN, IMPACT, LOCATE) has its own strategy class. Call site inclusion needs EXPLAIN strategy enhancement. |
| EdgeType.CALLS exists | `src/mu/kernel/schema.py:37` | CALLS edges are already in the graph! Just need to use them in context extraction. |
| CallSiteDef model | `src/mu/parser/models.py:30-44` | Already captures callee, line, is_method_call, receiver. Missing: arguments. |
| Graph builder creates CALLS edges | `src/mu/kernel/builder.py:239-282` | Already creates CALLS edges with `properties={"line": call.line}`. Missing: argument values. |
| MUbase.get_edges() | `src/mu/kernel/mubase.py:257-293` | Supports filtering by edge_type. Can query CALLS edges directly. |
| ContextResult model | `src/mu/kernel/context/models.py:212-256` | Has `extraction_stats` dict - can add warnings here. |
| TokenBudgeter.fit_to_budget() | `src/mu/kernel/context/budgeter.py` | Need to allocate budget for call site context. |
| Intent classification | `src/mu/kernel/context/intent.py` | EXPLAIN and DEBUG intents should trigger call site inclusion. |
| SmartContextExtractor._expand_graph() | `src/mu/kernel/context/smart.py:419-462` | Currently expands via get_dependencies/get_dependents. Need to add CALLS expansion. |

---

## Task Breakdown

### Task 1: Add `get_callers()` and `get_callees()` Methods to MUbase

**File(s)**: `src/mu/kernel/mubase.py`

**Pattern**: Follow `get_dependencies()` at line 295 and `get_dependents()` at line 349

**Description**: Add convenience methods to query CALLS edges specifically, returning both the calling/called function and the edge metadata (line number, future: arguments).

```python
def get_callers(self, node_id: str, limit: int = 5) -> list[tuple[Node, Edge]]:
    """Get functions that call this function.

    Returns (caller_node, edge) tuples with edge.properties["line"] for call site location.
    """

def get_callees(self, node_id: str, limit: int = 5) -> list[tuple[Node, Edge]]:
    """Get functions that this function calls."""
```

**Acceptance**:
- [ ] `get_callers()` returns up to `limit` caller nodes with their CALLS edges
- [ ] `get_callees()` returns up to `limit` callee nodes with their CALLS edges
- [ ] Edge properties include call site line number
- [ ] Unit tests added following `tests/unit/test_context.py` patterns

---

### Task 2: Enhance ExplainStrategy with Call Site Inclusion

**File(s)**: `src/mu/kernel/context/strategies.py`

**Pattern**: Follow `ImpactStrategy` at line 182 which already expands via `get_dependents()`

**Description**: Modify `DefaultStrategy` (which handles EXPLAIN intent) to include call sites when extracting context for functions. When a function node is found, also include:
1. Top N callers (who calls this function?)
2. Top N callees (what does this function call?)

```python
class ExplainStrategy:
    """Strategy for 'how does X work' questions.

    Includes function definitions AND their call sites to show behavior, not just interface.
    """

    def _expand_with_calls(self, seed_nodes: list[str], budget: int) -> list[str]:
        """Expand seed nodes to include relevant call sites."""
```

**Scoring Adjustment**:
```python
# Call sites are context, not primary results
CALLER_SCORE_MULTIPLIER = 0.7   # Callers are supporting context
CALLEE_SCORE_MULTIPLIER = 0.8   # Callees are more relevant for EXPLAIN
```

**Acceptance**:
- [ ] For function nodes, callers are included (up to 3 per function)
- [ ] For function nodes, callees are included for EXPLAIN intent (up to 3 per function)
- [ ] Callers scored at 0.7x of primary node score
- [ ] Callees scored at 0.8x of primary node score
- [ ] Stays within 80% of token budget before call site expansion
- [ ] Test case: "how does query work" includes routing.py call site

---

### Task 3: Add Compression Warnings to ContextResult

**File(s)**:
- `src/mu/kernel/context/models.py` (add fields)
- `src/mu/kernel/context/smart.py` (populate warnings)

**Pattern**: Follow `extraction_stats` field pattern in `ContextResult`

**Description**: Add a `warnings` field to ContextResult that alerts users when high compression might hide behavioral details.

```python
@dataclass
class ContextResult:
    # ... existing fields ...

    warnings: list[str] = field(default_factory=list)
    """Warnings about potential information loss from compression."""

    compression_ratio: float = 0.0
    """Ratio of output tokens to estimated full source tokens."""
```

Warning conditions:
1. Compression > 90%: "High compression: behavioral details may be hidden"
2. Call sites excluded due to budget: "N call sites excluded due to budget"
3. Complex function bodies summarized: "M functions had bodies truncated"

**Acceptance**:
- [ ] `warnings` field added to ContextResult
- [ ] Warning generated when compression > 90%
- [ ] Warning generated when call sites excluded
- [ ] Warnings displayed in CLI output (mu context command)
- [ ] Warnings included in MCP tool response

---

### Task 4: Extend CallSiteDef with Argument Tracking (Parser Change)

**File(s)**:
- `src/mu/parser/models.py` (extend CallSiteDef)
- `mu-core/src/parser/python.rs` (Rust parser enhancement)

**Pattern**: Follow existing `CallSiteDef` at `src/mu/parser/models.py:30`

**Description**: Add argument capture to call site extraction so we can show "cwd is passed as str(cwd)".

**Risk**: This is the highest-risk task. Rust parser AST traversal for argument extraction is non-trivial.

```python
@dataclass
class CallSiteDef:
    callee: str
    line: int = 0
    is_method_call: bool = False
    receiver: str | None = None
    arguments: list[tuple[str, str]] = field(default_factory=list)  # NEW: [(param_name, arg_expression)]
```

**Argument Complexity Levels**:
```python
# Easy - capture directly:
client.query(muql, cwd=str(cwd))
# -> [("", "muql"), ("cwd", "str(cwd)")]

client.query("SELECT *", cwd="/tmp")
# -> [("", '"SELECT *"'), ("cwd", '"/tmp"')]

# Medium - capture as expression text:
client.query(build_query(), cwd=get_cwd())
# -> [("", "build_query()"), ("cwd", "get_cwd()")]

# Hard - mark as <complex>:
client.query(*args, **kwargs)
# -> [("*", "<spread>"), ("**", "<spread>")]

client.query(muql, cwd=cwd if flag else None)
# -> [("", "muql"), ("cwd", "<conditional>")]
```

**Recommendation**: Start with Python-only (tree-sitter-python), verify it works, then port to TypeScript/other languages.

Rust parser change:
```rust
struct CallSite {
    callee: String,
    line: u32,
    is_method_call: bool,
    receiver: Option<String>,
    arguments: Vec<(String, String)>,  // NEW
}

fn extract_arguments(call_node: Node, source: &str) -> Vec<(String, String)> {
    // Find argument_list child
    // For each argument:
    //   - positional: ("", node_text)
    //   - keyword: (keyword_name, value_text)
    //   - *args: ("*", "<spread>")
    //   - **kwargs: ("**", "<spread>")
}
```

**Acceptance**:
- [ ] CallSiteDef model extended with `arguments` field
- [ ] Python extractor captures simple arguments (identifiers, literals, single calls)
- [ ] Complex expressions marked as `<complex>` or `<conditional>` with raw text in properties
- [ ] Spread arguments marked as `<spread>`
- [ ] Arguments stored in CALLS edge properties
- [ ] Unit test: verify `client.query(muql, cwd=str(cwd))` captures `[("", "muql"), ("cwd", "str(cwd)")]`

---

### Task 5: Store Arguments in CALLS Edge Properties

**File(s)**: `src/mu/kernel/builder.py`

**Pattern**: Follow existing edge creation at line 274

**Description**: When creating CALLS edges, include argument information in the edge properties.

```python
Edge(
    id=edge_id,
    source_id=source_func_id,
    target_id=target_id,
    type=EdgeType.CALLS,
    properties={
        "line": call.line,
        "arguments": call.arguments,  # NEW
    },
)
```

**Acceptance**:
- [ ] CALLS edge properties include `arguments` when available
- [ ] GraphBuilder passes arguments from CallSiteDef to Edge
- [ ] Arguments are JSON-serializable
- [ ] Existing tests still pass (backward compatible)

---

### Task 6: Display Call Sites in MU Format Export

**File(s)**: `src/mu/kernel/context/export.py`

**Pattern**: Follow existing function export logic

**Description**: When exporting functions that have callers, add a call site annotation showing where and how they're called.

```
# Example output:
!module src/mu/commands/routing.py
  # query(muql: str) -> dict
    @ called from: run_query():47 with cwd=str(cwd)
```

**Acceptance**:
- [ ] Call site annotations included when callers available
- [ ] Format: `@ called from: {caller}:{line} [with {args}]`
- [ ] Limited to top 3 callers per function
- [ ] Optional: controlled by ExportConfig flag

---

### Task 7: Add "Trace" Query Type for Data Flow (Future)

**File(s)**:
- `src/mu/kernel/context/intent.py` (add TRACE intent)
- `src/mu/kernel/context/strategies.py` (TraceStrategy)
- `src/mu/cli.py` (mu trace command)

**Pattern**: Follow existing Intent enum and strategy pattern

**Description**: New capability to trace a variable/value through the call graph.

```bash
mu trace "cwd" --from routing.py --to daemon

# Output:
cwd flow: routing.py -> client.py -> HTTP request -> daemon
  1. routing.py:45    cwd = Path.cwd()
  2. routing.py:52    client.query(muql, cwd=str(cwd))
  3. client.py:127    requests.post(url, json={"muql": muql, "cwd": cwd})
```

**Acceptance**:
- [ ] TRACE intent recognized in IntentClassifier
- [ ] TraceStrategy follows call graph with argument tracking
- [ ] `mu trace` CLI command implemented
- [ ] Cross-file tracing works within same language
- [ ] Output shows complete data flow path

---

## Dependencies

```
Task 1 (MUbase methods) <- Task 2 (ExplainStrategy uses them)
                        <- Task 6 (Export uses caller info)

Task 4 (CallSiteDef) <- Task 5 (GraphBuilder stores args)
                     <- Task 6 (Export shows args)

Task 3 (Warnings) - Independent, can run in parallel

Task 7 (Trace) - Depends on Tasks 1, 4, 5 (needs full call graph with args)
```

## Implementation Order

| Priority | Task | Effort | Dependencies |
|----------|------|--------|--------------|
| P0 | Task 1: MUbase caller/callee methods | Small (1h) | None |
| P0 | Task 2: ExplainStrategy call site inclusion | Medium (2h) | Task 1 |
| P1 | Task 3: Compression warnings | Small (1h) | None |
| P2 | Task 4a: CallSiteDef arguments (Python model) | Small (1h) | None |
| P2 | Task 4b: Rust parser argument extraction | Medium (3h) | Task 4a |
| P2 | Task 5: Store arguments in edges | Small (1h) | Task 4b |
| P2 | Task 6: Display call sites in export | Medium (2h) | Tasks 1, 5 |
| P3 | Task 7: Trace query type | Large (6h) | Tasks 1, 4, 5 |

### Execution Timeline

```
Week 1 (P0 - Ship immediately):
├── Task 1: get_callers/get_callees (1h)
├── Task 2: ExplainStrategy enhancement (2h)
└── Task 3: Compression warnings (1h)

Week 2 (P2 - Argument tracking):
├── Task 4a: CallSiteDef arguments - Python model (1h)
├── Task 4b: CallSiteDef arguments - Rust parser (3h) ← Highest risk
├── Task 5: Store in edges (1h)
└── Task 6: Display in export (2h)

Week 3 (P3 - Trace mode):
└── Task 7: Full implementation (6h)
```

---

## Edge Cases

1. **Recursive calls**: Function calls itself - include but don't loop infinitely
2. **Indirect calls**: `func = getattr(obj, 'method'); func()` - static analysis can't track, add warning
3. **External library calls**: Calls to functions not in codebase - skip (no node to link to)
4. **Many callers**: Popular utility function with 100+ callers - limit to top N by proximity
5. **Circular call chains**: A -> B -> A - detect and break cycle in traversal

---

## Security Considerations

- Argument values may contain secrets (e.g., `api_key=os.environ["KEY"]`)
- When capturing arguments, apply secret redaction from `mu.security`
- Never store actual secret values in edge properties
- Consider: Should argument capture be opt-in for sensitive codebases?

---

## Test Scenarios

### Integration Test: Daemon Audit E2E (Critical)

This test replays the exact query that gave wrong results:

```python
# tests/integration/test_context_accuracy.py

def test_daemon_audit_e2e():
    """Replay the exact query that gave wrong results.

    This is the regression test for the daemon audit failure where MU
    concluded 'cwd is not being passed' when it actually was.
    """
    # Bootstrap MU on itself
    from pathlib import Path
    from mu.kernel import MUbase
    from mu.kernel.context import SmartContextExtractor, ExtractionConfig

    project_root = Path(__file__).parents[3]
    db = MUbase(project_root / ".mu" / "mubase", read_only=True)
    extractor = SmartContextExtractor(db, ExtractionConfig(max_tokens=4000))

    result = extractor.extract("how does the CLI pass cwd to the daemon")

    # Must include the actual call site showing cwd IS passed
    mu_text_lower = result.mu_text.lower()

    # Should show the call site, not just the function signature
    assert any([
        "cwd=str(cwd)" in result.mu_text,
        "cwd=str(path" in mu_text_lower,
        "called from" in mu_text_lower,  # Call site annotation
    ]), f"Should show actual cwd argument being passed.\n\nGot:\n{result.mu_text[:1000]}"

    # Should include caller function (the one that MAKES the call)
    node_files = [n.file_path for n in result.nodes if n.file_path]
    assert any("routing" in f or "command" in f for f in node_files), \
        "Should include the calling code, not just the callee"
```

### Regression Test: Daemon Audit Case
```python
def test_daemon_audit_accuracy():
    """The question that exposed this bug should now work correctly."""
    result = extractor.extract("how does cwd propagate to the daemon")

    # Should include the actual call site
    assert "client.query" in result.mu_text
    assert "cwd=str(cwd)" in result.mu_text  # Actual argument!

    # Should NOT conclude "cwd is not passed"
    # (We can't test this directly, but call site inclusion makes it impossible to miss)
```

### Call Site Inclusion Test
```python
def test_explain_includes_call_sites():
    """Context for 'how does query work' should include callers."""
    result = extractor.extract("how does the query function work")

    # Should include query() definition
    assert any("query" in n.name for n in result.nodes)

    # Should ALSO include callers of query()
    callers = [n for n in result.nodes if n.file_path and "routing" in n.file_path]
    assert len(callers) > 0, "Should include call sites from routing.py"
```

### Warning Test
```python
def test_high_compression_warning():
    """High compression should trigger a warning."""
    config = ExtractionConfig(max_tokens=500)  # Force high compression
    result = extractor.extract("explain the entire authentication system")

    assert len(result.warnings) > 0
    assert any("compression" in w.lower() for w in result.warnings)
```

---

## External Review: Claude Code Evaluation

*Another Claude Code instance evaluated MU without knowing the author, providing unbiased feedback on the improvement plan.*

### Validation of Core Problem

> "The daemon audit failure happened because MU showed you **function signatures** (what parameters a function accepts) but not **call sites** (how those parameters are actually used)."

The reviewer confirmed the diagnosis is correct:

```python
# What MU showed (signature):
def query(self, muql: str, cwd: str | None = None) -> dict:

# What MU missed (call site):
result = client.query(muql, cwd=str(cwd))  # <-- PROOF that cwd IS passed!
```

### Task Priority Validation

| Task | Reviewer Assessment |
|------|---------------------|
| Task 1+2 (P0) | "Immediate wins" - CALLS edges already exist, just need exposure |
| Task 4 (arguments) | "Game-changer but riskiest" - moves MU from "A calls B" to "A calls B with these args" |
| Task 7 (Trace) | "Defer it" - essentially dataflow analysis, a separate capability |

### Actionable Suggestions

#### 1. Phased Approach for Task 4b (Rust Parser)

Instead of full argument classification upfront:

```
Phase 1: Capture argument expressions as raw text (just slice the source)
Phase 2: Classify into simple/complex/spread
Phase 3: (Maybe never) Attempt to resolve variable values
```

**Rationale**: Phase 1 alone would have caught `cwd=str(cwd)`.

#### 2. Reserved Budget for Call Sites (Task 2 Enhancement)

Current approach uses score multipliers which may lose to competition:

```python
# Current: Score-based competition
caller_score = primary_score * 0.7  # Might still lose to other nodes

# Suggested: Reserved budget slice
token_budget = 4000
primary_budget = 3200  # 80%
call_site_budget = 800  # 20% reserved for call sites
```

**Rationale**: Guarantees call sites appear regardless of score competition.

#### 3. Fallback Mode: Raw Source Lines

If argument tracking isn't available, show raw source line of call site:

```
@ called from: run_query():47
  > client.query(muql, cwd=str(cwd))  # Raw line from source
```

**Rationale**: Better than nothing - immediate value before full argument tracking ships.

### Test Strategy Endorsement

> "Ship this test *before* the fix to prove it fails, then make it pass."

The regression test approach was validated as correct:

```python
def test_daemon_audit_e2e():
    result = extractor.extract("how does the CLI pass cwd to the daemon")
    assert "cwd=str(cwd)" in result.mu_text or "called from" in result.mu_text.lower()
```

### Overall Assessment

| Aspect | Rating |
|--------|--------|
| Problem diagnosis | ✅ Spot-on |
| Task breakdown | ✅ Well-scoped with clear acceptance criteria |
| Risk identification | ✅ Correctly flags Rust parser as high-risk |
| Dependency graph | ✅ Clean parallel paths |
| Test strategy | ✅ Regression test against actual failure |

### Incorporated Changes

Based on this review, the following modifications are recommended:

1. **Task 2**: Add reserved budget allocation (20% for call sites) as alternative to pure score competition
2. **Task 4**: Split into explicit phases (raw text → classification → resolution)
3. **Task 6**: Add fallback mode showing raw source lines when arguments unavailable
4. **New acceptance criterion**: Test must fail before fix, pass after (TDD approach)
