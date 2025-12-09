# MU CLI Audit Results

**Date:** 2025-12-09
**Auditor:** Claude
**Branch:** feature/omega-lisp-exporter

## Executive Summary

The MU CLI has **42 commands** across multiple categories. Key findings:

- **8 duplicates/overlaps** identified (kernel commands vs top-level)
- **Agent commands** recommended for NUKE (obsoleted by MCP)
- **Vibes commands** are fun aliases - KEEP all 7
- **Daemon dependency** in 11 commands (all have local fallback)

## Command Audit Table

### Top-Level Commands

| Command | Purpose | Last Touched | Duplicate Of | Verdict |
|---------|---------|--------------|--------------|---------|
| `mu bootstrap` | One-step init: creates .murc.toml + builds graph | 2025-12-09 | `mu kernel init` + `mu kernel build` | **KEEP** - Primary entry point |
| `mu status` | Show MU status and next action guidance | 2025-12-09 | None | **KEEP** - Essential for UX |
| `mu read` | Read source code for a node (find->read loop) | 2025-12-09 | None | **KEEP** - Closes the query loop |
| `mu context` | Smart context extraction for questions | 2025-12-09 | `mu kernel context` | **KEEP** - Simpler interface |
| `mu search` | Semantic search for code nodes | 2025-12-09 | `mu kernel search` | **KEEP** - Top-level for discoverability |
| `mu related` | Suggest related files (tests, deps, co-changes) | 2025-12-09 | None | **KEEP** - Unique value |
| `mu compress` | Compress source into MU format | 2025-12-09 | None | **KEEP** - Core feature |
| `mu diff` | Semantic diff between git refs | 2025-12-08 | `mu kernel diff` | **KEEP** - Different interface (terminal format) |
| `mu describe` | CLI introspection for AI agents | 2025-12-07 | None | **NUKE** - Rarely used |
| `mu view` | Render MU file with syntax highlighting | 2025-12-07 | None | **NUKE** - Rarely used |
| `mu patterns` | Detect codebase patterns | 2025-12-08 | None | **KEEP** - Intelligence Layer |
| `mu warn` | Proactive warnings before modification | 2025-12-08 | None | **KEEP** - Intelligence Layer |
| `mu migrate` | Migrate legacy .mubase to .mu/ directory | 2025-12-08 | None | **NUKE** - One-time migration |
| `mu query` | Execute MUQL queries | 2025-12-09 | `mu kernel muql` | **KEEP** - Promoted from kernel |
| `mu q` | Short alias for `mu query` | 2025-12-09 | `mu query` | **KEEP** - Developer convenience |
| `mu impact` | Impact analysis (what breaks if I change X?) | 2025-12-08 | None | **KEEP** - Graph reasoning |
| `mu ancestors` | Find upstream dependencies | 2025-12-08 | None | **KEEP** - Graph reasoning |
| `mu cycles` | Detect circular dependencies | 2025-12-08 | None | **KEEP** - Graph reasoning |
| `mu man` | Display MU manual | 2025-12-07 | None | **NUKE** - Use online docs |
| `mu llm` | Output MU format spec for LLM consumption | 2025-12-07 | None | **NUKE** - Niche use case |

### Vibes Commands (KEEP ALL)

Fun, memorable aliases that improve developer experience.

| Command | Purpose | Maps To | Verdict |
|---------|---------|---------|---------|
| `mu omg` | OMEGA compressed context | `mu context --format omega` | **KEEP** |
| `mu grok` | Smart context extraction | `mu context` | **KEEP** |
| `mu wtf` | Git archaeology (why does this exist?) | History + blame | **KEEP** |
| `mu yolo` | Impact analysis | `mu impact` | **KEEP** |
| `mu sus` | Proactive warnings (suspicious code) | `mu warn` | **KEEP** |
| `mu vibe` | Pattern validation (does it vibe?) | Pattern check | **KEEP** |
| `mu zen` | Cache cleanup | `mu cache clear` | **KEEP** |

### Kernel Subcommands (Candidates for Promotion/Nuking)

| Command | Purpose | Last Touched | Duplicate Of | Verdict |
|---------|---------|--------------|--------------|---------|
| `mu kernel init` | Initialize .mu/mubase | 2025-12-07 | Subsumed by `mu bootstrap` | **NUKE** |
| `mu kernel build` | Build graph from codebase | 2025-12-07 | Subsumed by `mu bootstrap` | **NUKE** |
| `mu kernel context` | Smart context extraction (verbose) | 2025-12-09 | `mu context` | **NUKE** |
| `mu kernel deps` | Show dependencies | 2025-12-08 | None (different from ancestors) | **PROMOTE** to `mu deps` |
| `mu kernel diff` | Semantic diff between commits | 2025-12-08 | `mu diff` (different format) | **NUKE** |
| `mu kernel embed` | Generate embeddings | 2025-12-07 | `mu bootstrap --embed` | **NUKE** |
| `mu kernel export` | Export graph formats | 2025-12-09 | None | **KEEP** (power user) |
| `mu kernel history` | Node change history | 2025-12-08 | None | **KEEP** (power user) |
| `mu kernel muql` | MUQL REPL | 2025-12-07 | `mu query -i` | **NUKE** |
| `mu kernel search` | Semantic search | 2025-12-08 | `mu search` | **NUKE** |
| `mu kernel snapshot` | Create temporal snapshot | 2025-12-07 | None | **KEEP** (power user) |
| `mu kernel stats` | Graph statistics | 2025-12-07 | Part of `mu status` | **NUKE** |
| `mu kernel blame` | Who modified a node | 2025-12-08 | None | **KEEP** (power user) |

### Agent Commands (NUKE CANDIDATES)

| Command | Purpose | Verdict | Reason |
|---------|---------|---------|--------|
| `mu agent ask` | Ask questions via LLM | **NUKE** | Obsoleted by MCP tools |
| `mu agent interactive` | Interactive session | **NUKE** | Obsoleted by MCP tools |
| `mu agent query` | Direct MUQL query | **NUKE** | Use `mu query` |
| `mu agent deps` | Show dependencies | **NUKE** | Use `mu kernel deps` or promote |
| `mu agent impact` | Impact analysis | **NUKE** | Use `mu impact` |
| `mu agent cycles` | Detect cycles | **NUKE** | Use `mu cycles` |

### Service Commands

| Command | Purpose | Daemon Required | Verdict |
|---------|---------|-----------------|---------|
| `mu daemon start` | Start daemon in background | N/A | **MERGE** into `mu serve` |
| `mu daemon stop` | Stop running daemon | N/A | **MERGE** into `mu serve` |
| `mu daemon status` | Check daemon status | N/A | **MERGE** into `mu status` |
| `mu daemon run` | Run daemon in foreground | N/A | **MERGE** into `mu serve --foreground` |
| `mu mcp serve` | Start MCP server | No | **KEEP** |
| `mu mcp tools` | List MCP tools | No | **KEEP** |
| `mu mcp test` | Test MCP tools | No | **KEEP** |
| `mu cache stats` | Cache statistics | No | **NUKE** (rare use) |
| `mu cache clear` | Clear cache | No | **KEEP** (or use `mu zen`) |
| `mu cache expire` | Expire old entries | No | **NUKE** (rare use) |

## Daemon Dependency Analysis

### Commands that TRY daemon first (with local fallback):

All these commands work with OR without the daemon running:

1. `mu status` - Uses daemon for live stats, falls back to local DB
2. `mu read` - Uses daemon client, falls back to local DB
3. `mu context` - Uses daemon, falls back to local SmartContextExtractor
4. `mu patterns` - Uses daemon, falls back to local
5. `mu query` / `mu q` - Uses daemon, falls back to local
6. `mu impact` - Uses daemon, falls back to local GraphManager
7. `mu ancestors` - Uses daemon, falls back to local GraphManager
8. `mu cycles` - Uses daemon, falls back to local GraphManager
9. `mu kernel context` - Uses daemon, falls back to local (with `--offline` flag)
10. `mu kernel stats` - Uses daemon, falls back to local
11. All vibes commands (`omg`, `grok`, `wtf`, `yolo`, `sus`, `vibe`)

### Commands that work ONLY locally (no daemon):

1. `mu bootstrap` - Always runs locally
2. `mu compress` - File-based, no daemon
3. `mu diff` - Git-based comparison
4. `mu search` - Local embeddings
5. `mu kernel embed` - Generates embeddings locally
6. `mu cache *` - Local cache operations
7. `mu migrate` - Local file migration

### Commands that ARE the daemon:

1. `mu daemon *` - Controls the daemon
2. `mu mcp serve` - Is an MCP server

## Test Coverage Analysis

```bash
# Commands with dedicated test coverage:
tests/unit/test_context.py          # context, grok, omg
tests/unit/test_patterns.py         # patterns, vibe
tests/unit/test_warnings.py         # warn, sus
tests/unit/test_related.py          # related
tests/unit/test_cli_commands.py     # Various CLI tests
tests/integration/test_context_integration.py  # Full context flow
tests/integration/test_omega_integration.py    # OMEGA format

# Commands with NO direct tests (tested implicitly or untested):
- mu describe
- mu view
- mu migrate
- mu man
- mu llm
- mu agent *
- mu daemon *
```

## Proposed New CLI Structure

```
mu                          # Smart help with getting started
mu bootstrap                # THE entry point - builds everything
mu status                   # What's the state? What do I do next?

# Query & Navigation
mu query "MUQL"             # Primary query interface
mu q "MUQL"                 # Alias
mu read NODE                # Read source code
mu context "question"       # Smart context

# Graph Reasoning (promoted from graph.py)
mu impact NODE              # What breaks if I change this?
mu deps NODE                # What does this depend on? (promoted from kernel)
mu ancestors NODE           # What depends on this?
mu cycles                   # Find circular dependencies

# Intelligence Layer
mu patterns                 # Detect codebase patterns
mu warn TARGET              # Proactive warnings
mu related FILE             # Find related files

# Compression & Diff
mu compress PATH            # Compress to MU format
mu diff BASE HEAD           # Semantic diff

# Vibes (fun aliases)
mu omg "question"           # OMEGA context
mu grok "question"          # Smart context
mu wtf FILE                 # Git archaeology
mu yolo NODE                # Impact (YOLO mode)
mu sus FILE                 # Suspicious code check
mu vibe                     # Pattern validation
mu zen                      # Cache cleanup

# Services (simplified)
mu serve                    # Run MCP + daemon (replaces: daemon start/run)
mu serve --stop             # Stop all services
mu mcp serve                # MCP only (for Claude Code config)

# Hidden from main help (advanced/power user)
mu kernel export            # Graph export formats
mu kernel history           # Node history
mu kernel snapshot          # Temporal snapshots
mu kernel blame             # Who changed what
mu cache clear              # Cache management

# NUKED (removed in v1.0)
mu kernel init              # Use bootstrap
mu kernel build             # Use bootstrap
mu kernel context           # Use context
mu kernel deps              # Promoted to mu deps
mu kernel diff              # Use diff
mu kernel embed             # Use bootstrap --embed
mu kernel muql              # Use query -i
mu kernel search            # Use search
mu kernel stats             # Use status
mu describe                 # Rarely used
mu view                     # Rarely used
mu migrate                  # One-time
mu man                      # Use online docs
mu llm                      # Niche
mu agent *                  # Obsoleted by MCP
```

## Implementation Recommendations

### Phase 1: Immediate (This Sprint)
1. **Promote `mu kernel deps` to `mu deps`** - It's the missing graph command
2. **NUKE `mu agent`** - Already obsolete, just dead code
3. **Hide from main help**: describe, view, man, llm, migrate

### Phase 2: Next Sprint
1. **Merge daemon commands into `mu serve`**
2. **Remove kernel duplicates** (init, build, muql, stats)
3. **Add deprecation warnings** for nuked commands

### Phase 3: v1.0 Release
1. **Remove deprecated commands entirely**
2. **Update documentation**
3. **Simplify help output**

## Final Command Count

| Category | Current | After Cleanup |
|----------|---------|---------------|
| Core | 18 | 12 |
| Vibes | 7 | 7 |
| Kernel | 13 | 5 (hidden) |
| Agent | 6 | 0 |
| Services | 8 | 4 |
| **Total** | **52** | **28** |

---

*Audit complete. 52 commands reduced to 28 visible, 5 hidden. Agent module is ready for NUKE.*
