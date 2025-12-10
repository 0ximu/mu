# Graph-Based Context Extraction (Without Embeddings) - Task Breakdown

## Business Context

**Problem**: When embeddings are unavailable (the default state), MU's context extraction produces noisy, irrelevant results. On real codebases like Dominaite, asking "How does payout service work?" returns 104 nodes including Python chat agent code instead of the C# PayoutService class.

**Root Cause**: Without embeddings, `SmartContextExtractor` falls back to naive keyword matching that:
- Matches "service" to hundreds of unrelated services
- Has no understanding of code relationships (imports, calls, inheritance)
- Has no domain boundary awareness (Python vs C# in monorepos)
- Does not leverage the existing graph structure

**Outcome**: Context extraction without embeddings should leverage the **graph structure** that MU already has to produce precise, domain-aware results.

**Users**:
- AI agents (Claude Code) using MU MCP without OpenAI API key
- Developers who haven't run `mu bootstrap --embed`
- CI/CD systems where embedding generation is impractical

---

## Existing Patterns Found

| Pattern | File | Relevance |
|---------|------|-----------|
| `SmartContextExtractor` | `/Users/imu/Dev/work/mu/src/mu/kernel/context/smart.py:43` | Main extraction class - orchestrates the pipeline |
| `_find_seed_nodes()` | `/Users/imu/Dev/work/mu/src/mu/kernel/context/smart.py:244-277` | Current seed discovery - uses entity matching only |
| `_expand_graph()` | `/Users/imu/Dev/work/mu/src/mu/kernel/context/smart.py:419-464` | Graph expansion - BFS with fixed depth |
| `_vector_search()` | `/Users/imu/Dev/work/mu/src/mu/kernel/context/smart.py:312-392` | Checks embeddings availability, returns skip_reason |
| `embedding_stats()` | `/Users/imu/Dev/work/mu/src/mu/kernel/mubase.py:752-833` | Checks if embeddings exist |
| `EntityExtractor` | `/Users/imu/Dev/work/mu/src/mu/kernel/context/extractor.py:15-235` | Extracts code entities from questions |
| `RelevanceScorer` | `/Users/imu/Dev/work/mu/src/mu/kernel/context/scorer.py:19-253` | Multi-signal scoring (entity, vector, proximity) |
| `get_dependencies()` | `/Users/imu/Dev/work/mu/src/mu/kernel/mubase.py:295-347` | Get outgoing edges (dependencies) |
| `get_dependents()` | `/Users/imu/Dev/work/mu/src/mu/kernel/mubase.py:349-401` | Get incoming edges (what depends on this) |
| `get_edges()` | `/Users/imu/Dev/work/mu/src/mu/kernel/mubase.py:257-293` | Get edges with filtering |
| `EdgeType.CALLS` | `/Users/imu/Dev/work/mu/src/mu/kernel/schema.py:37` | Call graph edges exist |
| `EdgeType.IMPORTS` | `/Users/imu/Dev/work/mu/src/mu/kernel/schema.py:36` | Import edges exist |
| `EdgeType.INHERITS` | `/Users/imu/Dev/work/mu/src/mu/kernel/schema.py:35` | Inheritance edges exist |
| `get_language_stats()` | `/Users/imu/Dev/work/mu/src/mu/kernel/mubase.py:1594-1633` | Language distribution metadata |
| `ExtractionStrategy` Protocol | `/Users/imu/Dev/work/mu/src/mu/kernel/context/strategies.py:52-75` | Pattern for specialized strategies |
| `LocateStrategy` | `/Users/imu/Dev/work/mu/src/mu/kernel/context/strategies.py:83-179` | Example of targeted extraction |
| `ImpactStrategy` | `/Users/imu/Dev/work/mu/src/mu/kernel/context/strategies.py:182-306` | Uses `get_dependents()` for impact analysis |

**Key Finding**: The graph infrastructure exists! `_expand_graph()` is already in `SmartContextExtractor` but it's not being used effectively when embeddings are unavailable. The current fallback path through `_vector_search()` returns empty results with `skip_reason` but then the extraction continues with just entity-matched seeds.

---

## Task Breakdown

### Task 1: Enhance Seed Discovery with Graph-Aware Matching

**File(s)**: `/Users/imu/Dev/work/mu/src/mu/kernel/context/smart.py`

**Pattern**: Enhance existing `_find_seed_nodes()` method (line 244-277) following the matching priority from the PRD.

**Description**: The current `_find_seed_nodes()` does simple entity matching. When embeddings are unavailable, we need smarter seed discovery that:
1. Prioritizes exact name matches
2. Falls back to qualified name matches
3. Uses file path matching
4. Applies language filtering to avoid cross-language noise

**Implementation Details**:
- Add a new method `_find_seed_nodes_graph_aware()` that returns `tuple[list[Node], set[str], dict[str, float]]` (nodes, IDs, scores)
- Add `_detect_query_language()` method to infer target language from question text
- Add `_get_node_language()` helper to determine a node's language from file extension
- Matching priority with scores: exact match (1.0), qualified name (0.95), file path (0.8), suffix match (0.7)

**Acceptance Criteria**:
- [x] Exact name matches return score 1.0
- [x] Qualified name matches return score 0.95
- [x] Language detection works for C#, Python, TypeScript, JavaScript, Go, Rust, Java
- [x] Cross-language results are filtered when language is detected
- [x] File path matching finds module-level queries
- [x] Method returns scored results for downstream ranking

---

### Task 2: Implement Scored Graph Expansion

**File(s)**: `/Users/imu/Dev/work/mu/src/mu/kernel/context/smart.py`

**Pattern**: Enhance existing `_expand_graph()` method (line 419-464) to use relationship-type scoring.

**Description**: The current `_expand_graph()` does simple BFS expansion without considering edge types. We need expansion that:
1. Weights different edge types differently (CALLS > INHERITS > IMPORTS)
2. Decays scores with graph distance
3. Respects configurable limits

**Implementation Details**:
- Create `GraphExpansionConfig` dataclass with:
  - `max_depth: int = 2`
  - `max_nodes_per_depth: int = 15`
  - `weights: dict[str, float]` mapping EdgeType to weight (CALLS: 0.9, INHERITS: 0.85, IMPORTS: 0.7, CONTAINS: 0.95)
  - `depth_decay: float = 0.7`
- Add `_expand_graph_scored()` method that returns `dict[str, tuple[Node, float]]`
- Use existing `get_edges()` method from MUbase to get edges by source/target
- Implement BFS with score tracking and decay

**Acceptance Criteria**:
- [x] CALLS edges weighted higher than IMPORTS
- [x] Score decays with distance (depth 1 = 0.7x, depth 2 = 0.49x)
- [x] Maximum depth prevents runaway expansion
- [x] Returns both Node and score for downstream ranking
- [x] Preserves higher score when node reached via multiple paths

---

### Task 3: Add Domain Boundary Detection

**File(s)**: `/Users/imu/Dev/work/mu/src/mu/kernel/context/smart.py`

**Pattern**: Create new domain detection using existing `get_language_stats()` and query patterns.

**Description**: Prevent context from crossing domain boundaries in monorepos. A query about "C# PayoutService" should not return Python chat agent code.

**Implementation Details**:
- Create `DomainBoundary` dataclass with `root_path`, `language`, `name`
- Add `_detect_domains()` method that queries for distinct root_path + language combinations
- Add `_get_node_domain()` method to determine which domain a node belongs to
- Add `_filter_by_domain()` method that:
  - Keeps same-domain nodes at full score
  - Penalizes cross-domain nodes (0.3x score)
  - Handles unknown-domain nodes (0.8x score)

**Acceptance Criteria**:
- [x] Domains detected from directory structure and file extensions
- [x] Cross-domain nodes penalized but not excluded entirely
- [x] Same-domain nodes retain full scores
- [x] Works for monorepo structures with multiple languages
- [x] Python code penalized when query targets C#

---

### Task 4: Integrate Graph-Based Extraction Pipeline

**File(s)**: `/Users/imu/Dev/work/mu/src/mu/kernel/context/smart.py`

**Pattern**: Modify existing `extract()` method (line 98-229) to use graph-based extraction when embeddings unavailable.

**Description**: Wire together the new components into a cohesive pipeline that:
1. Checks if embeddings are available
2. Uses graph-based extraction when they're not
3. Reports extraction method in stats

**Implementation Details**:
- Add `_check_embeddings_available()` method (can use `self.mubase.embedding_stats()`)
- Add `_extract_with_graph()` method implementing the full graph-based pipeline:
  1. Find seed nodes with `_find_seed_nodes_graph_aware()`
  2. Detect seed domains
  3. Expand via `_expand_graph_scored()`
  4. Apply domain filtering with `_filter_by_domain()`
  5. Include call sites for functions
  6. Score and rank results
  7. Apply budget and export
- Modify `extract()` to branch based on embeddings availability
- Update stats to include `method: "graph"` vs `method: "embeddings"`

**Acceptance Criteria**:
- [x] Graph-based extraction used when `embedding_stats()` shows 0 embeddings
- [x] Embeddings-based extraction still works when available
- [x] Stats include `extraction_method` field
- [x] Call sites included for function nodes
- [x] Domain filtering applied before budgeting
- [x] Empty result returns helpful warning message

---

### Task 5: Add Extraction Method Indicator to Output

**File(s)**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/context/models.py`
- `/Users/imu/Dev/work/mu/src/mu/commands/core.py`

**Pattern**: Follow existing `ContextResult` model pattern (line 212-256 in models.py) and CLI output pattern (line 519-681 in core.py).

**Description**: Make it visible to users when graph-based extraction is being used, with a helpful tip to generate embeddings.

**Implementation Details**:
- Add `extraction_method: str = "unknown"` field to `ContextResult` (default "unknown", set to "embeddings" or "graph")
- Add `warnings: list[str] = field(default_factory=list)` field if not present
- Update CLI `context` command to:
  - Show info message when using graph-based extraction
  - Display tip: "Run 'mu bootstrap --embed' for better semantic search"
  - Display any warnings from result

**Acceptance Criteria**:
- [x] `extraction_method` field present in ContextResult
- [x] CLI shows informational message for graph-based extraction
- [x] Tip to run embeddings shown when in graph mode
- [x] Warnings displayed to user (stored in extraction_stats["warnings"])
- [x] No extra noise when embeddings ARE available

---

### Task 6: Unit Tests for Graph-Based Extraction

**File(s)**: `/Users/imu/Dev/work/mu/tests/unit/test_context_graph.py` (new file)

**Pattern**: Follow existing test patterns in `/Users/imu/Dev/work/mu/tests/unit/test_context.py`.

**Description**: Comprehensive unit tests for the graph-based extraction components.

**Test Cases**:
1. `TestGraphBasedExtraction`
   - `test_language_filtering`: C# query should not return Python code
   - `test_graph_expansion_includes_callers`: Connected nodes via edges included
   - `test_exact_match_prioritized`: Exact matches rank higher than fuzzy
   - `test_extraction_method_reported`: Stats include `method: "graph"`

2. `TestDomainBoundaryDetection`
   - `test_detect_language_from_query`: Detects C#, Python, TypeScript, etc.
   - `test_domain_filtering_reduces_noise`: Cross-language noise filtered

3. `TestGraphExpansionConfig`
   - `test_default_weights`: CALLS > IMPORTS
   - `test_depth_decay`: Score decays correctly

**Acceptance Criteria**:
- [x] All test cases pass
- [x] Tests use in-memory MUbase (`:memory:`)
- [x] Tests verify language filtering
- [x] Tests verify graph expansion
- [x] Tests verify domain boundaries

---

### Task 7: Integration Test - Dominaite Regression

**File(s)**: `/Users/imu/Dev/work/mu/tests/integration/test_context_accuracy.py` (new file)

**Pattern**: Follow existing integration test patterns in `/Users/imu/Dev/work/mu/tests/integration/test_context_integration.py`.

**Description**: Regression test that recreates the exact Dominaite scenario described in the PRD.

**Implementation Details**:
- Create fixture with:
  - C# PayoutService.cs
  - C# IPayoutService.cs (interface)
  - Python chat_agent/services/chat_service.py
  - Python chat_agent/handlers/payout_handler.py (has "payout" in name)
- Test query: "How does the payout service work?"
- Assert: PayoutService.cs in top 3, Python files NOT in top 3

**Acceptance Criteria**:
- [x] Test recreates Dominaite-like structure
- [x] C# PayoutService ranked in top results
- [x] Python code with "payout" in name NOT ranked above C#
- [x] Graph-based extraction confirmed in stats
- [x] Test marked as integration test (runs with `pytest -m integration`)

---

## Dependencies

```
Task 1 (Graph-Aware Seed Discovery)
    |
    v
Task 2 (Scored Graph Expansion) <--- Depends on seed scores from Task 1
    |
    v
Task 3 (Domain Detection) <---------- Filters expanded results
    |
    v
Task 4 (Integration) <---------------- Combines all components
    |
    v
Task 5 (Output Indicator)
    |
    v
Task 6 (Unit Tests) <----------------- Can start after Task 4
    |
    v
Task 7 (Integration Test)
```

**Parallelization Notes**:
- Tasks 1, 2, 3 can be developed somewhat in parallel (they have clear interfaces)
- Task 4 requires Tasks 1-3 to be complete
- Task 5 can be done in parallel with Task 4
- Tasks 6 and 7 should be done after Task 4

---

## Implementation Order

| Priority | Task | Effort | Risk |
|----------|------|--------|------|
| P0 | Task 1: Graph-Aware Seed Discovery | Medium (2h) | Medium - modifying core search |
| P0 | Task 2: Scored Graph Expansion | Medium (2h) | Medium - BFS with scoring |
| P1 | Task 3: Domain Boundary Detection | Medium (1.5h) | Low - additive feature |
| P1 | Task 4: Integration | Medium (2h) | Medium - wiring everything together |
| P2 | Task 5: Output Indicator | Small (30m) | Low - UI change only |
| P2 | Task 6: Unit Tests | Medium (1.5h) | Low |
| P2 | Task 7: Integration Test | Small (30m) | Low |

**Total Estimated Effort**: ~10 hours

---

## Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| No seed nodes found | Return empty result with helpful warning |
| Query spans multiple languages | Include both but warn user |
| Very generic query ("how does it work") | Use most connected nodes as proxy |
| Monorepo with 10+ languages | Detect language from explicit mentions |
| All seeds are tests | Expand to find source files |
| Graph has cycles | BFS handles cycles via visited set |
| Empty graph | Return graceful empty result |

---

## Success Metrics

1. **Precision**: Top 5 results should be from correct domain 90%+ of the time
2. **Recall**: Relevant nodes should appear in top 10 results
3. **No Cross-Language Noise**: C# query returns < 10% Python nodes
4. **Performance**: Graph-based extraction < 500ms for typical query

---

## Rollback Plan

If issues arise:
1. Feature flag: `MU_GRAPH_CONTEXT=0` environment variable to disable
2. Keep keyword matching as final fallback
3. Graph-based extraction only activates when embeddings unavailable (existing path unaffected)

---

## Files to Modify Summary

| File | Changes |
|------|---------|
| `src/mu/kernel/context/smart.py` | Add graph-aware methods, modify `extract()` |
| `src/mu/kernel/context/models.py` | Add `extraction_method` and `warnings` to `ContextResult` |
| `src/mu/commands/core.py` | Display extraction method and tips |
| `tests/unit/test_context_graph.py` | New file with unit tests |
| `tests/integration/test_context_accuracy.py` | New file with regression test |
