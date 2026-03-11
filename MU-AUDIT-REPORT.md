# MU Self-Audit Report

**Date**: 2026-03-10
**Codebase**: 772 nodes, 1778 edges, 64 files (Rust-only)
**Bootstrap version**: V3 (BM25 + PageRank + heuristic summaries)

---

## 1. Search Quality Scorecard

10 queries evaluated against `mu_grok` (5-result limit). Scoring: 1 (garbage) to 5 (exactly right).

| # | Query | Score | Notes |
|---|-------|-------|-------|
| 1 | "how does tenant isolation work" | 2/5 | Only 2 results. Found `test_parallel_execution_isolation` — word overlap, but not real tenant isolation. Reasonable for a codebase that doesn't have tenancy. |
| 2 | "where are database migrations defined" | 5/5 | All 5 results are from `migrations.rs`. Perfect. |
| 3 | "how does the enrichment flywheel work" | 3/5 | Found `mu_enrich` and `enrich_nodes_tool` correctly. Also pulled in `truncate_str` and `type_sigil` (called by enrich, but not the flywheel itself). Missing the conceptual answer — no search_text/summary pipeline nodes. |
| 4 | "what happens when a payment fails" | 3/5 | 0 results. **Correct behavior** — there is no payment code. Returning nothing is better than hallucinating. Scored 3 because "no results" with no explanation of why is suboptimal UX. |
| 5 | "how are webhook signatures validated" | 1/5 | Returned `generate_signature` (differ), `extract_signature` — these are code *signatures*, not webhook/HMAC signatures. Pure keyword collision. No webhooks exist in this codebase. Should return 0 results like query #4. |
| 6 | "error handling patterns" | 3/5 | Found `EmbeddingError`, `From` impls, `SecretPattern`. The error module is relevant but `SecretPattern` is noise from "patterns" keyword. Missed the dominant pattern: `anyhow::Result` used everywhere. |
| 7 | "how does the context packer decide what to include" | 4/5 | Found `pack_context_tool` (#2) and `pack_node_from_row` (#3). Good. `include_hidden` (#1) is noise. Missing the budget logic in `budget.rs`. |
| 8 | "rate limiting implementation" | 1/5 | Top result is `hit_rate` (cache stats). No rate limiting exists. All results are irrelevant keyword overlap. Should return 0 results. |
| 9 | "how does incremental parsing work" | 2/5 | Found `parse_source` and `parse_file` but not any incremental/diff-based parsing logic. Results are generic parse functions, not incremental-specific. No incremental parsing exists — should ideally return nothing or the diff comparator. |
| 10 | "security sensitive code" | 4/5 | Found `SecretPattern`, `find_secrets`, `redact`, security module. Good. `compute_code_hash` (#1) is borderline — it's hashing, not really security-sensitive. |

**Average: 2.8/5**

### Key Search Issues

1. **False positives from keyword overlap** (queries 5, 8): BM25 can't distinguish semantic meaning. "signature" = HMAC vs code signature. "rate" = rate limiting vs hit_rate.
2. **No semantic understanding**: All matches are lexical. The system can't reason about "does X exist in this codebase?"
3. **No "not found" intelligence**: When a concept genuinely doesn't exist (payments, webhooks, rate limiting), the system either returns nothing silently or returns misleading keyword matches. It should say "this concept doesn't appear to exist in this codebase."

---

## 2. Graph Accuracy Audit

### Edges Checked

Expanded 11 seed nodes across 3 queries. ~200 edges examined.

**MUbase class graph**: 45 edges, all correct.
- `contains` edges for all methods: accurate
- `calls` edges from methods to `acquire_conn`: accurate (verified against source)
- `uses` edges to `SearchResult`, `Node`, `Edge`, `QueryResult`, `GraphStats`: accurate
- `ProjectState -> uses -> MUbase`: accurate

**Parser helpers graph**: 125 edges, all accurate.
- `get_node_text` has 38 incoming `calls` edges from 6 language parsers — verified, this is genuinely called from everywhere
- `find_child_by_type` has 22 incoming `calls` edges — correct
- `count_nodes` self-recursive edge: correct

**No phantom edges detected.** The graph is built from explicit call-site resolution, not ORM/reflection, so Rust codebases don't suffer from the phantom edge problem that plagues Java/.NET codebases with DI containers.

### Issue: Macro-dispatched functions invisible to the graph

All 13 MCP `#[tool(...)]` handlers (`mu_grok`, `mu_find`, `mu_expand`, etc.) show **zero incoming edges**. The `#[tool_router]` and `#[tool_handler]` macros from `rmcp` wire these at compile time, but the parser can't track this. This means:
- All MCP handlers appear as orphans in the audit
- Their importance scores are artificially low
- Impact analysis can't show that changing `ensure_state` affects all MCP tools

### Issue: `to_table` and trait impl methods also invisible

Functions implementing `TableDisplay::to_table` show as orphans because trait dispatch is invisible to the call-graph builder. Same for `Default::default`, `From::from`, `Display::fmt`, etc.

---

## 3. PageRank Sanity Check

Top nodes from `mu_oracle` (no task, budget=4000):

| Rank | Node | Importance | Verdict |
|------|------|-----------|---------|
| 1 | `get_node_text` | ~0.22 | **Inflated but defensible.** Called by 38+ parser functions. Genuinely the most called function, but it's a 7-line utility. High PageRank != high importance for understanding the system. |
| 2 | `find_child_by_type` | ~0.18 | Same as above — utility with massive fan-in. |
| 3 | `get_start_line` | ~0.15 | 3-line function. Pure inflation. |
| 4 | `get_end_line` | ~0.12 | Same — trivial utility. |
| 5 | `acquire_conn` | ~0.22 | **Genuinely important.** Central to all DB access. Good rank. |
| 6-8 | `get_builtins_for_language`, `extract_referenced_types`, `collect_type_strings_from_methods` | ~0.08-0.12 | Mid-level helpers. Reasonable. |
| 9-10 | `run_mu`, `create_sample_python_file` (test helpers) | ~0.10 | **Test infrastructure inflated.** These shouldn't rank above real production code. |

### Verdict

**PageRank is dominated by utility functions.** The top 4 nodes are all trivial tree-sitter helpers (get_node_text, find_child_by_type, get_start_line, get_end_line). They have high in-degree because every parser calls them, but they tell you almost nothing about how the system works.

The oracle's context budget gets burned on these trivial functions, leaving less room for the genuinely important code like `search_nodes`, `pack_context_tool`, `bootstrap::run`, etc.

**Recommendations:**
- Dampen utility functions: if LOC < 10 and in-degree > 20, reduce importance score
- Exclude test files from PageRank or apply a 0.5x multiplier
- Weight by complexity * PageRank, not just PageRank alone

---

## 4. Concrete Bugs Found

### BUG-1: Node IDs never emitted in tool output (CRITICAL)

**Impact**: The tool pipeline is broken at its joints.

`search_nodes_tool` (line 46-48 of tools_v3.rs) builds results from `SearchResult` which includes `node_id`, but the output format only shows `sigil + name`:
```
1. #acquire_conn [function] -- mu-cli/src/engine/storage/mubase.rs:77
```

The actual DB ID is `fn:mu-cli/src/engine/storage/mubase.rs:MUbase.acquire_conn`, but this is never printed. Users who see search results and try to pass them to `mu_expand` or `mu_read` get empty results because `$MUbase` != `cls:mu-cli/src/engine/storage/mubase.rs:MUbase`.

**Same issue in**: `mu_find` (server.rs:253-317), `mu_compress` (formatter.rs), `mu_oracle` (no IDs in packed output).

**Fix**: Add `r.node_id` to the search output format on line 46-48 of tools_v3.rs. Show it as `[id: fn:path:name]` after each result.

### BUG-2: SQL injection via string formatting in MCP tools

**Location**: 12 instances in `mu-cli/src/commands/mcp/server.rs` and `tools_v3.rs`.

All SQL queries in the MCP layer use `format!("SELECT ... WHERE id = '{}'", escaped)` with manual `replace('\'', "''")` escaping. While `search.rs` correctly uses parameterized queries (`?1` params), the MCP tool layer bypasses this entirely.

**Risk**: Low (local tool, not internet-facing), but it's a code quality gap. A malicious node ID containing `'` could still cause query errors.

**Fix**: Use `params![]` consistently, like `search.rs` does.

### BUG-3: Orphan detection false positives for macro-dispatched code

**Location**: `mu-cli/src/commands/audit.rs` (R1-orphan rule)

All 13 MCP `#[tool]` handlers, all `TableDisplay::to_table` impls, all `Default::default` impls, and all `Display::fmt` impls are flagged as orphans. That's ~60 of the 229 info-level findings — roughly 25% are false positives from trait/macro dispatch.

**Fix**: Add suppression for functions inside `#[tool_router]` impl blocks and for known trait method names (`to_table`, `default`, `fmt`, `from`, `from_str`).

### BUG-4: `mu_find` doesn't query by full node ID

**Location**: server.rs:259-262

```rust
let sql = format!(
    "SELECT type, name, file_path, line_start, line_end FROM nodes WHERE name = '{}' OR name LIKE '%.{}'",
    params.symbol, params.symbol
);
```

This only searches by `name`, never by `id`. If a user gets a node ID from somewhere and tries `mu_find` with it, it won't find anything. The tool description says "Find a specific symbol by exact name" but should also accept IDs.

### BUG-5: Ignored integration tests create false confidence

**Location**: search.rs:464-489

Four integration tests are `#[ignore]`d with messages like "Requires V3 schema":
- `test_search_nodes_exact_match`
- `test_search_nodes_bm25_with_importance`
- `test_search_nodes_fallback_keyword`
- `test_search_nodes_dedup_exact_over_bm25`

These are the most important search correctness tests and they're never run. The search pipeline's actual behavior is verified only by unit tests on `top_n` sorting.

---

## 5. Missing Capabilities / Tool Gaps

During this audit, I wanted to:

| What I Tried | What Happened | What's Missing |
|---|---|---|
| Get node IDs from search results to feed into expand | Search shows `#name`, expand needs `fn:path:Class.name` | **Node ID passthrough** (BUG-1) |
| Ask "does this codebase have rate limiting?" | Got misleading results instead of "no" | **Negative search / concept detection** |
| See all callers of a function across the codebase | `mu_impact` works but output doesn't include the actual call sites (file:line) | **Call site locations in impact** |
| Check if a function is actually dead code vs macro-invoked | Orphan report can't distinguish | **Macro/trait dispatch awareness** |
| Search by file path pattern (e.g., "all functions in mcp/") | No tool supports this | **File-scoped search** |
| Get a "what changed since last bootstrap" | No tool for this | **Incremental diff since bootstrap** |
| See the raw SQL queries being executed for debugging | No debug/verbose mode in MCP tools | **Query explain/debug mode** |

---

## 6. Performance Notes

All tool calls completed in <500ms. The MCP server response times were consistently fast:

- `mu_grok`: ~50-100ms (BM25 search is fast)
- `mu_expand`: ~30-80ms (SQL joins are efficient)
- `mu_find`: ~20-50ms (direct name lookup)
- `mu_compress`: ~100-200ms (loads all nodes, builds tree)
- `mu_oracle`: ~150-300ms (PageRank sort + source file reads)
- `mu_sus`: ~200ms (scans all 772 nodes)
- `mu_audit`: 216ms for 772 nodes across 7 rules

No performance concerns observed. DuckDB is doing its job.

---

## 7. Prioritized Fix List

Ordered by impact on tool usability:

| Priority | Issue | Impact | Effort |
|----------|-------|--------|--------|
| **P0** | BUG-1: Emit node IDs in all tool outputs | Without this, the search→expand→read pipeline is broken. Users can't flow between tools. | Low — add `r.node_id` to format strings in 3-4 places |
| **P1** | PageRank utility dampening | Top oracle results are 3-line helpers that burn context budget. Weight by `complexity * pagerank` or dampen low-LOC high-fan-in nodes. | Medium — modify `compute_pagerank` or post-process scores |
| **P1** | Suppress orphan false positives | 25% of audit findings are noise from macro/trait dispatch. Add known-trait-method suppression list. | Low — ~20 lines in audit.rs |
| **P2** | BUG-4: `mu_find` should accept node IDs | Finding by ID is the complement to finding by name. Add `OR id = ?1` to the query. | Trivial |
| **P2** | Search false positive reduction | Queries 5, 8 returned misleading results. Consider: minimum BM25 score threshold, or require >1 keyword match for multi-word queries. | Medium |
| **P3** | BUG-2: Parameterized SQL in MCP layer | Code quality / consistency. Not a security risk in practice. | Medium — refactor 12 call sites |
| **P3** | BUG-5: Un-ignore integration tests | Write proper V3 schema test fixtures so these tests actually run. | Medium |
| **P3** | File-scoped search | Add `file_path` filter parameter to `mu_grok`. | Low — add WHERE clause |
| **P4** | Negative search / concept detection | Hard problem. Could use compress output to check if query keywords appear anywhere. | High |

---

## Summary

MU's graph and edge data are **accurate** — no phantom edges, no broken references. The Rust parser does a solid job with call-site resolution. Performance is excellent across all tools.

The critical gap is **tool interoperability**: search results don't include the IDs that other tools need. This makes the MCP tool pipeline feel like individual tools that happen to share a database, rather than an integrated system. Fix BUG-1 and the tool experience improves dramatically.

The second biggest issue is **PageRank inflation of trivial utilities**, which causes the oracle to burn its context budget on `get_node_text` instead of `pack_context_tool`. A complexity-weighted importance score would fix this.

Search quality is **adequate for exact lookups but weak for conceptual queries**. BM25 on heuristic summaries gets you 60% of the way there; the missing 40% requires either embeddings (semantic search) or richer summaries that capture what code does conceptually.
