# MU Trimming Initiative - Master Plan

**Status:** Draft
**Author:** Claude + imu
**Created:** 2025-12-09
**Timeline:** 2 weeks (10 working days)

## Executive Summary

MU has accumulated scope creep and technical debt. This initiative trims the codebase from ~150K LOC to a focused, maintainable tool with a vibes-first CLI and reduced MCP footprint.

## The Problem

1. **God components**: `mcp/server.py` is 3,514 LOC
2. **Dead code**: ~3,500 LOC of unused/low-value features
3. **Too many MCP tools**: 25 tools, should be 12
4. **Broken functionality**: Several tools return wrong/empty results
5. **Poor UX**: Verbose commands hide the good stuff

## The Solution

Four phases over 2 weeks:

| Phase | Focus | Duration | LOC Impact |
|-------|-------|----------|------------|
| 1 | Delete dead code | 2 days | -3,500 |
| 2 | Vibes-first CLI | 3 days | +500 |
| 3 | MCP refactor | 3 days | -1,600 |
| 4 | Bug fixes | 2 days | ~0 |
| **Total** | | **10 days** | **-4,600** |

---

## Phase Summary

### Phase 1: Dead Code Deletion (Days 1-2)

**Goal:** Remove ~3,500 LOC of unused code

**Deletions:**
- `intelligence/generator.py` - Templates not worth complexity
- `intelligence/memory.py` - Not core value
- `intelligence/task_context.py` - Merge into context
- `intelligence/validator.py` - Pattern check is enough
- `intelligence/nl2muql.py` - MUQL is simple enough
- `security/` - Never integrated
- `cache/` - Barely used
- `contracts/` - Never got CLI integration
- `assembler/exporters.py` - Duplicate of kernel/export

**MCP tools removed:** 7 (generate, validate, task_context, remember, recall, ask, + merged)

**PRD:** [Phase 1: Deletion](./MU_TRIMMING_PHASE1_DELETION.md)

---

### Phase 2: Vibes-First CLI (Days 3-5)

**Goal:** Make short, memorable commands the primary UX

**New command hierarchy:**
```
mu omg    → OMEGA context
mu grok   → Smart context
mu wtf    → Why does this exist?
mu yolo   → Impact analysis
mu sus    → Warnings before change
mu vibe   → Pattern check
mu q      → MUQL query
mu diff   → Semantic diff
```

**Keep verbose alternatives** for scripts/documentation

**PRD:** [Phase 2: Vibes CLI](./MU_TRIMMING_PHASE2_VIBES_CLI.md)

---

### Phase 3: MCP Server Refactor (Days 6-8)

**Goal:** Break 3,514 LOC monolith into focused modules

**New structure:**
```
mcp/
├── server.py         # ~150 LOC (setup only)
├── models/           # ~500 LOC (all dataclasses)
└── tools/            # ~1,200 LOC (tool implementations)
    ├── setup.py      # status, bootstrap
    ├── graph.py      # query, read
    ├── context.py    # context, context_omega
    ├── analysis.py   # deps, impact, diff
    └── guidance.py   # patterns, warn
```

**Tool reduction:** 25 → 12

**PRD:** [Phase 3: MCP Refactor](./MU_TRIMMING_PHASE3_MCP_REFACTOR.md)

---

### Phase 4: Bug Fixes & Polish (Days 9-10)

**Goal:** Fix broken functionality discovered during audit

**P0 Bugs:**
- mu_deps returns empty results (node resolution)
- mu_warn returns "target not found" (path handling)
- "0 tokens" bug in context fallback

**P1 Bugs:**
- mu_read requires full node ID
- OMEGA seed overhead (445 tokens)

**PRD:** [Phase 4: Bug Fixes](./MU_TRIMMING_PHASE4_BUGFIXES.md)

---

## Success Metrics

| Metric | Before | After | Target |
|--------|--------|-------|--------|
| MCP tools | 25 | 12 | ≤14 |
| mcp/server.py LOC | 3,514 | ~150 | <200 |
| Total Python LOC | ~88K | ~84K | <85K |
| mu_deps works | No | Yes | Yes |
| mu_warn works | No | Yes | Yes |
| Vibes commands | 3 | 8 | ≥6 |

---

## Timeline

```
Week 1:
  Day 1-2: Phase 1 - Delete dead code
  Day 3-5: Phase 2 - Vibes CLI

Week 2:
  Day 6-8: Phase 3 - MCP refactor
  Day 9-10: Phase 4 - Bug fixes + polish
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Breaking existing users | Keep verbose command aliases |
| Import errors after deletion | Comprehensive grep + tests |
| MCP compatibility | Test with Claude Code after each phase |
| Timeline slip | Phases are independent, can reorder |

---

## What's NOT Changing

- Core functionality (compress, build, query, diff)
- Rust daemon (it's solid)
- MUQL query language
- Graph database (MUbase)
- Parser pipeline
- Semantic diff engine

---

## Post-Initiative Roadmap

After trimming, focus on:

1. **Performance** - Profile and optimize hot paths
2. **Documentation** - Update for new CLI
3. **Testing** - Improve coverage on remaining code
4. **Daemon stability** - Fix orphan process issues
5. **VSCode extension** - Update for new commands

---

## Decision Log

| Decision | Rationale | Date |
|----------|-----------|------|
| Keep vibes as primary | Better UX, memorable | 2025-12-09 |
| Delete memory layer | Not core value, adds complexity | 2025-12-09 |
| Delete code generator | Templates not worth MCP overhead | 2025-12-09 |
| Merge ancestors into deps | Redundant, direction param enough | 2025-12-09 |
| Keep mu_why and mu_related | Actually useful for workflows | 2025-12-09 |

---

## Appendix: File Changes Summary

### Files to Delete (~3,500 LOC)

```
src/mu/intelligence/generator.py      (1,292 LOC)
src/mu/intelligence/memory.py         (~200 LOC)
src/mu/intelligence/task_context.py   (~350 LOC)
src/mu/intelligence/validator.py      (~300 LOC)
src/mu/intelligence/nl2muql.py        (~250 LOC)
src/mu/security/                      (499 LOC)
src/mu/cache/                         (661 LOC)
src/mu/contracts/                     (~300 LOC)
src/mu/assembler/exporters.py         (~400 LOC)
src/mu/commands/generate.py
src/mu/commands/init_cmd.py
src/mu/commands/scan.py
src/mu/commands/contracts/
tests/unit/test_generator.py
tests/unit/test_memory.py
tests/unit/test_task_context.py
tests/unit/test_validator.py
tests/unit/test_nl2muql.py
tests/daemon/test_contracts_endpoint.py
```

### Files to Create

```
src/mu/commands/vibes/
  __init__.py
  omg.py
  grok.py
  wtf.py
  yolo.py
  sus.py
  vibe.py

src/mu/mcp/models/
  __init__.py
  common.py
  query.py
  context.py
  analysis.py
  guidance.py

src/mu/mcp/tools/
  __init__.py
  setup.py
  graph.py
  context.py
  analysis.py
  guidance.py
```

### Files to Significantly Modify

```
src/mu/cli.py                  # Add vibes commands
src/mu/mcp/server.py           # Slim down to ~150 LOC
src/mu/mcp/__init__.py         # Update exports
src/mu/intelligence/__init__.py # Remove deleted exports
CLAUDE.md                      # Update documentation
```

---

## Approval

- [ ] imu reviewed Phase 1 PRD
- [ ] imu reviewed Phase 2 PRD
- [ ] imu reviewed Phase 3 PRD
- [ ] imu reviewed Phase 4 PRD
- [ ] Ready to begin Phase 1
