# MU Trimming Phase 2: Vibes-First CLI

**Status:** Draft
**Author:** Claude + imu
**Created:** 2025-12-09
**Depends on:** Phase 1 (Dead Code Deletion)
**Target:** Make vibes commands the primary UX

## Executive Summary

MU's current CLI is enterprise-verbose (`mu kernel context --format omega`). Users prefer short, memorable commands. This phase promotes "vibes" commands (`mu omg`, `mu grok`, `mu wtf`) to primary status and adds new ones.

## Goals

1. **Better UX** - Short commands users actually remember
2. **Personality** - MU should feel fun, not corporate
3. **Discoverability** - Core features front and center
4. **Consistency** - All vibes follow same patterns

## Non-Goals

- Removing verbose alternatives (keep for scripts/docs)
- Changing underlying functionality
- Breaking existing workflows

---

## Command Design Philosophy

### Vibes Naming Principles

1. **Emotional resonance** - Commands express what you feel, not what you're doing
2. **4 characters or less** - Quick to type
3. **Memorable** - You'll remember it tomorrow
4. **Action-oriented** - Implies the response you'll get

### Examples

| Feeling | Command | Meaning |
|---------|---------|---------|
| "I need context" | `mu omg` | Give me OMEGA compressed context |
| "I want to understand" | `mu grok` | Smart context for my question |
| "Why is this here?" | `mu wtf` | Git archaeology - why does this exist |
| "What breaks?" | `mu yolo` | Impact analysis before change |
| "Is this safe?" | `mu sus` | Warnings before modifying |
| "Does this fit?" | `mu vibe` | Pattern check |
| "Show me changes" | `mu diff` | Semantic diff (already exists) |
| "Query the graph" | `mu q` | MUQL query (already exists) |

---

## Command Specifications

### Existing Vibes (Promote to Primary)

#### `mu omg` - OMEGA Context

**Current:** Alias for `mu kernel context --format omega`
**New status:** Primary command

```bash
# Usage
mu omg "How does authentication work?"
mu omg "What are the API endpoints?" --tokens 4000
mu omg  # Interactive mode - prompts for question

# Options
--tokens, -t    Max tokens (default: 8000)
--no-seed       Omit schema seed (for follow-up queries)
--raw           Output raw S-expressions only
```

**Output:**
```
 OMEGA Context (1,247 tokens)

;; Schema seed (445 tokens) - cache this
(defschema module [Name FilePath] ...)
...

;; Body (802 tokens)
(module src.auth ...)
...

 Compression: 67% (3,780 → 1,247 tokens)
```

---

#### `mu grok` - Smart Context

**Current:** Alias for `mu kernel context`
**New status:** Primary command

```bash
# Usage
mu grok "How does the parser work?"
mu grok "What imports MUbase?"
mu grok  # Interactive mode

# Options
--tokens, -t    Max tokens (default: 8000)
--format, -f    Output format: mu (default), json, markdown
--no-tests      Exclude test files
```

**Output:**
```
 Context for: "How does the parser work?"

! src/mu/parser/__init__.py
  $ PythonExtractor
    # extract_module(source, path) -> ModuleDef
    # _extract_class(node) -> ClassDef
...

 538 tokens | 12 nodes | 0.8 relevance
```

---

### New Vibes

#### `mu wtf` - Why Does This Exist?

**Purpose:** Git archaeology - understand why code exists

```bash
# Usage
mu wtf src/mu/mcp/server.py
mu wtf MUbase
mu wtf src/mu/mcp/server.py:100-150  # Line range

# Options
--commits, -c   Max commits to analyze (default: 20)
--no-cochange   Skip co-change analysis
```

**Output:**
```
 Why: src/mu/mcp/server.py

 Origin
  Commit: 91d8944 (2025-12-07)
  Author: Yavor Kangalov
  Reason: "extract commands into lazy-loaded modules"

 Evolution
  5 commits over 2 days by 2 contributors
  Last modified: today

 Co-changes (files that change together)
  • CLAUDE.md (60%)
  • src/mu/cli.py (60%)
  • src/mu/commands/query.py (60%)

 References
  • Issue #16
```

---

#### `mu yolo` - Impact Analysis

**Purpose:** "What breaks if I change this?"

```bash
# Usage
mu yolo src/mu/kernel/mubase.py
mu yolo MUbase
mu yolo --file src/mu/mcp/server.py

# Options
--depth, -d     Traversal depth (default: 2)
--type, -t      Edge types: imports, calls, inherits, contains
```

**Output:**
```
 Impact Analysis: src/mu/kernel/mubase.py

 66 nodes affected

 Direct dependents (12)
  • src/mu/mcp/server.py (imports)
  • src/mu/commands/kernel/build.py (imports)
  • src/mu/intelligence/patterns.py (imports)
  ...

 Transitive impact (54)
  • tests/unit/test_mcp.py
  • tests/unit/test_kernel.py
  ...

⚠️ High impact file - changes affect 66 downstream nodes
```

---

#### `mu sus` - Suspicious? Check Before Modifying

**Purpose:** Proactive warnings before touching code

```bash
# Usage
mu sus src/mu/mcp/server.py
mu sus MUbase

# Options
--strict        Fail on any warning (for CI)
```

**Output:**
```
 Warnings: src/mu/mcp/server.py

⚠️ HIGH IMPACT
  66 files depend on this module

⚠️ HIGH COMPLEXITY
  Function compress() has complexity 82

⚠️ STALE CODE
  Not modified in 30+ days (some sections)

 SECURITY SENSITIVE
  Contains authentication logic

Risk Score: 7/10 - Proceed with caution
```

---

#### `mu vibe` - Pattern Check

**Purpose:** Does this code match codebase patterns?

```bash
# Usage
mu vibe                           # Check all uncommitted changes
mu vibe --staged                  # Check staged changes only
mu vibe src/mu/new_feature.py     # Check specific file

# Options
--category, -c   Filter: naming, testing, api, imports, architecture
--fix            Auto-fix simple violations (future)
```

**Output:**
```
 Vibe Check: src/mu/new_feature.py

✓ Naming conventions (snake_case functions)
✓ Import organization
✗ Test coverage - no test file found
  → Expected: tests/unit/test_new_feature.py

⚠️ Async pattern - blocking call in async function
  Line 45: requests.get() should be aiohttp

2 issues found
```

---

### Command Aliases (Keep for Compatibility)

| Primary | Aliases |
|---------|---------|
| `mu omg` | `mu kernel context --format omega`, `mu context-omega` |
| `mu grok` | `mu kernel context`, `mu context` |
| `mu wtf` | `mu why` |
| `mu yolo` | `mu impact` |
| `mu sus` | `mu warn` |
| `mu vibe` | `mu patterns --check`, `mu validate` |
| `mu q` | `mu query`, `mu kernel muql` |
| `mu diff` | `mu kernel diff`, `mu semantic-diff` |

---

## Implementation Plan

### Step 1: Create Vibes Module

```python
# src/mu/commands/vibes.py

import click
from mu.commands.lazy import lazy_group

@lazy_group()
def vibes():
    """Vibes-first commands for MU."""
    pass

# Each command in separate file for lazy loading
# src/mu/commands/vibes/omg.py
# src/mu/commands/vibes/grok.py
# src/mu/commands/vibes/wtf.py
# etc.
```

### Step 2: Implement Core Vibes (Day 1)

1. `mu omg` - Wrap existing OMEGA context
2. `mu grok` - Wrap existing smart context
3. `mu q` - Already exists, ensure it's prominent
4. `mu diff` - Already exists

### Step 3: Implement New Vibes (Day 2)

1. `mu wtf` - Wrap `mu_why` functionality
2. `mu yolo` - Wrap `mu_impact` functionality
3. `mu sus` - Wrap `mu_warn` functionality
4. `mu vibe` - Wrap pattern detection + simple validation

### Step 4: Update CLI Entry Point (Day 2)

```python
# src/mu/cli.py

@click.group()
def cli():
    """MU - Machine Understanding for codebases."""
    pass

# Register vibes as top-level commands
cli.add_command(omg)
cli.add_command(grok)
cli.add_command(wtf)
cli.add_command(yolo)
cli.add_command(sus)
cli.add_command(vibe)
cli.add_command(q)
cli.add_command(diff)

# Keep kernel subgroup for verbose alternatives
cli.add_command(kernel)
```

### Step 5: Update Help Text (Day 3)

```
$ mu --help

Usage: mu [OPTIONS] COMMAND [ARGS]...

MU - Machine Understanding for codebases

Quick Commands:
  omg      OMEGA compressed context
  grok     Smart context for questions
  wtf      Why does this code exist?
  yolo     What breaks if I change this?
  sus      Warnings before modifying
  vibe     Pattern check
  q        MUQL query
  diff     Semantic diff

Build & Setup:
  build    Build the code graph
  status   Show MU status

Advanced:
  kernel   Graph database operations
  mcp      MCP server commands
  daemon   Daemon management
```

### Step 6: Add Interactive Mode (Day 3)

Commands without arguments enter interactive mode:

```bash
$ mu grok
? What do you want to understand? > How does auth work?
...output...

$ mu omg
? Question for OMEGA context? > Show me the API endpoints
...output...
```

### Step 7: Add Shell Completions (Day 4)

```bash
# Bash
eval "$(_MU_COMPLETE=bash_source mu)"

# Zsh
eval "$(_MU_COMPLETE=zsh_source mu)"

# Fish
_MU_COMPLETE=fish_source mu | source
```

---

## Output Styling

### Consistent Icons

| Icon | Meaning |
|------|---------|
| ✓ | Success/pass |
| ✗ | Failure/error |
| ⚠️ | Warning |
|  | Info/result |
|  | Suggestion |
|  | File/module |
|  | Process/action |

### Color Scheme

```python
# Rich console styling
SUCCESS = "green"
ERROR = "red"
WARNING = "yellow"
INFO = "blue"
MUTED = "dim"
ACCENT = "cyan"
```

### Progress Indicators

```
 Analyzing codebase...
 Building context...
 Found 12 relevant nodes
```

---

## Success Criteria

- [ ] All vibes commands work as specified
- [ ] `mu --help` shows vibes prominently
- [ ] Interactive mode works for main commands
- [ ] Output is colorful and readable
- [ ] Shell completions work
- [ ] Documentation updated

## Testing Plan

1. **Unit tests** for each vibes command
2. **Integration tests** for full workflows
3. **UX testing** - Can someone use MU with just vibes?
4. **Performance** - Commands respond in <2s

---

## Future Vibes (Post-MVP)

| Command | Purpose |
|---------|---------|
| `mu rn` | Rename across codebase |
| `mu mv` | Move with import updates |
| `mu dead` | Find dead code |
| `mu hot` | Most modified files |
| `mu new` | Scaffold new module |

---

## Appendix: Full Command Reference

```
mu omg [QUESTION] [-t TOKENS] [--no-seed] [--raw]
mu grok [QUESTION] [-t TOKENS] [-f FORMAT] [--no-tests]
mu wtf TARGET [-c COMMITS] [--no-cochange]
mu yolo TARGET [-d DEPTH] [-t TYPES]
mu sus TARGET [--strict]
mu vibe [FILE] [--staged] [-c CATEGORY]
mu q QUERY [-f FORMAT] [--explain]
mu diff [BASE] [HEAD] [--breaking-only]
mu build [PATH] [--force]
mu status [--json]
```
