# PRD: MU Intelligence Layer

## Overview

**Product**: MU Intelligence Layer
**Version**: 2.0
**Author**: Claude (AI Alpha Tester)
**Date**: 2025-12-08
**Status**: Draft

### Executive Summary

MU v1 excels at structural analysis ("what exists" and "what connects"). MU v2 introduces the Intelligence Layer - features that answer "what should I do?", "how should I do it?", and "did I do it right?" This transforms MU from a code analysis tool into an AI coding assistant's essential companion.

### The Problem

AI coding assistants currently spend 30-50% of their token budget on codebase exploration before writing a single line of code. This exploration is:

1. **Expensive**: 50-100K tokens per task at $3/1M tokens = $0.15-0.30 per exploration
2. **Slow**: 30-60 seconds of grep/read cycles before productive work
3. **Incomplete**: Pattern discovery is accidental, not systematic
4. **Repetitive**: Same discoveries made every session (no memory)
5. **Risky**: Changes made without understanding blast radius

### The Solution

The Intelligence Layer provides task-aware context, pattern recognition, change validation, and proactive guidance - reducing exploration to 2-5K tokens while improving code quality.

### Success Metrics

| Metric | Current | Target | Improvement |
|--------|---------|--------|-------------|
| Tokens per task exploration | 50-100K | 2-5K | 95% reduction |
| Time to first productive code | 30-60s | 5-10s | 6x faster |
| Pattern violations caught | ~20% (in review) | 80% (pre-commit) | 4x improvement |
| Files forgotten per PR | 2-3 | 0-1 | 70% reduction |

---

## Phase 0: Foundation Fixes (Prerequisites)

> **Source**: Stress test against Gateway codebase (7,138 nodes, 6,782 edges, with embeddings)
> **Date**: 2025-12-08
> **Tester**: Claude (parallel session)

Before building the Intelligence Layer, these foundational bugs must be fixed. The new features depend on working MUQL queries, context extraction, and MCP tools.

### Critical Bugs (P0 - Fix First)

#### B1: MUQL Parser Crashes

| Query | Error | Root Cause |
|-------|-------|------------|
| `WHERE name CONTAINS 'Service'` | `too many values to unpack (expected 2)` | `contains_comparison` transformer bug |
| `WHERE name IN ('A', 'B')` | `too many values to unpack (expected 2)` | `in_comparison` transformer bug |
| `GROUP BY type` | `Unexpected character 'G' at position 34` | Grammar doesn't support GROUP BY |
| `WHERE complexity > 30 AND name LIKE '%Async'` | `Error: None` | Compound WHERE with AND + LIKE fails silently |

**Fix Locations**:
- `src/mu/kernel/muql/parser.py:119` - `in_comparison` transformer
- `src/mu/kernel/muql/parser.py:127` - `contains_comparison` transformer
- `src/mu/kernel/muql/grammar.lark` - Add GROUP BY support

**Fix for GROUP BY** (grammar.lark):
```lark
select_query: SELECT_KW select_list FROM_KW node_type [where_clause] [group_by_clause] [order_by_clause] [limit_clause]
group_by_clause: GROUP_KW BY_KW IDENTIFIER ("," IDENTIFIER)*
GROUP_KW: /group/i
```

#### B2: Context Extraction Returns Nothing for Valid Queries

| Query | Result | Expected |
|-------|--------|----------|
| `"JWT authentication"` | No relevant context | Should find `JwtAuthenticationMiddleware` |
| `"authentication"` | No relevant context | Should find auth-related classes |
| `"transaction refund"` | ✅ 29 nodes | Works |

**Root Cause**: Embeddings exist but context extractor isn't using them effectively for certain query patterns. Likely embedding similarity threshold too high for short/common terms.

**Fix Location**: `src/mu/kernel/context/extractor.py`

#### B3: MCP Tools Fail When Daemon Running

All MCP tools fail with DuckDB lock error when daemon is running. MCP tools try to open `.mubase` directly instead of routing through daemon HTTP API.

**Fix**: MCP tools should detect running daemon and route requests through HTTP API.

**Fix Location**: `src/mu/mcp/server.py` - Add daemon detection + HTTP fallback

```python
def _get_data_source():
    """Get daemon client if running, else direct MUbase access."""
    client = DaemonClient()
    if client.is_running():
        return client  # Use HTTP API
    return MUbase(_find_mubase())  # Direct access
```

### High Priority Bugs (P1 - Fix Soon)

#### B4: No Semantic Search Endpoint

Embeddings are generated but `/search` endpoint doesn't exist. MCP has `mu_search` but it's pattern-based (LIKE), not semantic (embeddings).

**Action**: Add `POST /search` to daemon API:
```json
POST /search
{"query": "JWT token validation", "limit": 5}
```

**Fix Location**: `mu-daemon/src/server/` or `src/mu/daemon/server.py`

#### B5: ~~No `mu_read` MCP Tool~~ ✅ DONE

~~Critical missing tool. After finding something interesting via query, need to read actual source code.~~

**Status**: COMPLETED (2025-12-08)

Implemented as:
- CLI: `mu read <node>` - Top-level command
- MCP: `mu_read` tool

```bash
mu read AuthService              # Read source for a node
mu read AuthService --context 10 # With more context lines
```

#### B6: FIND Queries Not Implemented

| Query | Error |
|-------|-------|
| `FIND functions CALLING TransactionService` | `Operation not implemented: find_calling` |
| `FIND classes INHERITING BaseService` | Not implemented |

**Fix Location**: `src/mu/kernel/muql/executor.py:292-300` - `_execute_find_graph` is a stub

**Implementation**: Use existing `GraphManager` methods for reverse edge lookups.

#### B7: `mu agent query` Output Bug

CLI `mu agent query` returns "Error: None" for successful queries. The daemon API returns correct results.

**Fix Location**: `src/mu/agent/` - output handling

### Medium Priority (P2 - Polish)

#### B8: API Inconsistency

- `/impact` expects `node_id` but `SHOW IMPACT` uses `node_name`
- Should support both with smart resolution (already have `_resolve_node_id`)

#### B9: DESCRIBE Functions Returns Empty Names

`DESCRIBE functions` returns rows with empty `name` column. Schema introspection broken.

#### B10: Aggregation Without GROUP BY

`SELECT type, COUNT(*) FROM nodes` should work with implicit grouping or clear error.

---

### CLI Improvements Shipped ✅

> **Date**: 2025-12-08
> **Status**: COMPLETED

The following CLI improvements have been implemented, addressing UX friction and CLI/MCP alignment:

#### New Top-Level Commands

| Command | Purpose | MCP Equivalent |
|---------|---------|----------------|
| `mu bootstrap` | One-command setup (config + graph + embeddings) | `mu_bootstrap` |
| `mu status` | Health check with next action guidance | `mu_status` |
| `mu read` | Read source code for a node | `mu_read` |
| `mu context` | Smart context extraction (promoted) | `mu_context` |
| `mu search` | Semantic search (promoted) | `mu_search` |

#### Simplified User Flow

**Before** (14 steps):
```bash
mu init
mu kernel init .
mu kernel build .
mu kernel embed .
mu kernel context "question"
```

**After** (2 steps):
```bash
mu bootstrap --embed
mu context "question"
```

#### CLI/MCP Alignment

All primary commands now have 1:1 MCP tool equivalents, enabling seamless switching between CLI (humans) and MCP (AI agents).

#### Impact on Intelligence Layer

- **F1 (`mu_task_context`)**: Can leverage `mu bootstrap` for setup, `mu context` for extraction
- **B5 (`mu_read`)**: ✅ Resolved - `mu read` command now exists
- **DX**: Foundation is now user-friendly enough for Intelligence Layer features

---

### Validation Test Suite

After fixes, these should all pass:

```bash
# Setup (new simplified flow)
mu bootstrap --embed

# MUQL parser fixes
mu q "SELECT name FROM classes WHERE name CONTAINS 'Service'"
mu q "SELECT type, COUNT(*) FROM nodes GROUP BY type"
mu q "SELECT name FROM functions WHERE name IN ('Create', 'Update')"
mu q "SELECT name FROM functions WHERE complexity > 30 AND name LIKE '%Async%'"

# FIND queries
mu q "FIND functions CALLING TransactionService"
mu q "FIND classes INHERITING BaseService"

# New top-level commands (CLI improvements)
mu status                        # Should show "ready" with no next_action
mu read AuthService              # Should return source code
mu context "authentication"      # Should return auth-related classes
mu search "JWT token validation" # Should use semantic search

# MCP with daemon running
mu daemon start . && mu mcp test  # All should pass
```

---

### Implementation Priority

**Week 0** (Before Intelligence Layer):

| Priority | Bug | Effort | Status |
|----------|-----|--------|--------|
| 1 | B1: MUQL `CONTAINS` fix | 1h | 🔴 TODO |
| 2 | B1: MUQL `IN` fix | 1h | 🔴 TODO |
| 3 | B1: MUQL `GROUP BY` | 2h | 🔴 TODO |
| 4 | B2: Context extraction threshold | 2h | 🔴 TODO |
| 5 | B3: MCP daemon routing | 3h | 🔴 TODO |
| 6 | B5: `mu_read` tool | ~~2h~~ | ✅ DONE |
| 7 | B4: Semantic search endpoint | 3h | 🔴 TODO |
| 8 | B6: FIND queries | 4h | 🔴 TODO |

**Remaining**: ~16 hours of bug fixes (B5 completed).

---

## Feature Specifications

### F1: Task-Aware Context (`mu_task_context`)

**Priority**: P0 (Critical)
**Complexity**: High
**Dependencies**: mu_context, mu_patterns, mu_impact

#### Description

Given a natural language task description, return a curated context bundle containing everything an AI assistant needs to complete the task.

#### Interface

```python
@mcp.tool()
def mu_task_context(
    task: str,
    max_tokens: int = 8000,
    include_tests: bool = True,
    include_patterns: bool = True,
) -> TaskContextResult:
    """Extract comprehensive context for a development task.

    Args:
        task: Natural language task description
        max_tokens: Maximum tokens in output
        include_tests: Include relevant test patterns
        include_patterns: Include codebase patterns

    Returns:
        TaskContextResult with files, patterns, warnings, suggestions
    """
```

#### Output Structure

```python
@dataclass
class TaskContextResult:
    # Core context
    relevant_files: list[FileContext]      # Files to read/modify
    entry_points: list[str]                # Where to start

    # Patterns
    patterns: list[Pattern]                # Relevant codebase patterns
    examples: list[CodeExample]            # Similar implementations

    # Guidance
    warnings: list[Warning]                # Impact, staleness, security
    suggestions: list[Suggestion]          # Related changes, alternatives

    # Metadata
    mu_text: str                           # MU format context
    token_count: int
    confidence: float                      # 0-1 relevance confidence
```

#### Implementation Approach

1. **Task Analysis**: Use lightweight LLM (Haiku) to extract:
   - Entity types (API endpoint, hook, component, etc.)
   - Action type (create, modify, delete, refactor)
   - Domain keywords (auth, payment, user, etc.)

2. **Multi-Signal Retrieval**:
   - Semantic search on embeddings (question → relevant nodes)
   - Keyword extraction → MUQL queries
   - Entity type → structural patterns

3. **Context Assembly**:
   - Rank files by relevance score
   - Include dependency context (what they import/export)
   - Add pattern examples from similar code
   - Attach warnings from impact analysis

4. **Token Budgeting**:
   - Allocate tokens: 60% core files, 20% patterns, 10% deps, 10% warnings
   - Truncate intelligently (signatures > bodies)

#### Example

**Input**:
```
mu_task_context("Add rate limiting to the API endpoints")
```

**Output**:
```
TaskContextResult(
    relevant_files=[
        FileContext(path="src/middleware/auth.ts", relevance=0.9, reason="Existing middleware pattern"),
        FileContext(path="src/app/api/users/route.ts", relevance=0.8, reason="Example API route"),
        FileContext(path="src/lib/redis.ts", relevance=0.7, reason="Redis client for storage"),
    ],
    entry_points=["src/middleware/"],
    patterns=[
        Pattern(name="middleware", description="Express-style middleware with next()", example="src/middleware/auth.ts:12-45"),
    ],
    examples=[
        CodeExample(description="Auth middleware implementation", file="src/middleware/auth.ts", lines="12-45"),
    ],
    warnings=[
        Warning(level="info", message="23 API routes will be affected"),
        Warning(level="warn", message="No existing rate limiting - new pattern"),
    ],
    suggestions=[
        Suggestion(type="related_change", message="Consider adding rate limit headers to responses"),
        Suggestion(type="test", message="Add integration tests in tests/api/"),
    ],
    token_count=1847,
    confidence=0.85,
)
```

---

### F2: Pattern Library (`mu_patterns`)

**Priority**: P0 (Critical)
**Complexity**: Medium
**Dependencies**: mu_query, embeddings

#### Description

Automatically extract and catalog recurring patterns in the codebase. Patterns include error handling, state management, API conventions, file organization, and naming conventions.

#### Interface

```python
@mcp.tool()
def mu_patterns(
    category: str | None = None,
    refresh: bool = False,
) -> PatternsResult:
    """Get codebase patterns by category.

    Args:
        category: Optional filter (error_handling, state, api, naming, testing, etc.)
        refresh: Force re-analysis of patterns

    Returns:
        PatternsResult with categorized patterns and examples
    """
```

#### Pattern Categories

| Category | Description | Example Patterns |
|----------|-------------|------------------|
| `error_handling` | How errors are created, thrown, caught | Custom error classes, try/catch style, error responses |
| `state_management` | How state is managed | Zustand slices, React Query, local state |
| `api` | API conventions | Response envelope, route structure, middleware |
| `naming` | Naming conventions | Files, functions, components, constants |
| `testing` | Test patterns | File location, naming, mocking approach |
| `components` | Component patterns | Props interface, composition, styling |
| `imports` | Import organization | Grouping, aliases, barrel files |

#### Pattern Detection Algorithm

1. **Structural Clustering**:
   - Group similar AST structures (functions with same decorator, classes with same base)
   - Identify repeated file naming patterns (*.test.ts, *.stories.tsx)

2. **Naming Convention Extraction**:
   - Analyze function/class/file names for prefixes/suffixes
   - Detect casing conventions (camelCase, PascalCase, snake_case)

3. **Import Pattern Analysis**:
   - Common import groupings
   - Alias usage (@/, ~/, etc.)
   - Barrel file patterns

4. **Code Shape Analysis**:
   - Error handling shapes (try/catch, Result types, error callbacks)
   - Async patterns (async/await, .then(), callbacks)

#### Output Structure

```python
@dataclass
class Pattern:
    name: str                      # "error_handling.custom_class"
    category: str                  # "error_handling"
    description: str               # Human-readable description
    frequency: int                 # How many times it appears
    confidence: float              # Detection confidence
    examples: list[PatternExample] # Code examples with locations
    anti_patterns: list[str]       # What NOT to do

@dataclass
class PatternExample:
    file_path: str
    line_start: int
    line_end: int
    code_snippet: str              # Actual code
    annotation: str                # Why this is a good example
```

#### Example

**Input**:
```
mu_patterns("error_handling")
```

**Output**:
```
PatternsResult(
    patterns=[
        Pattern(
            name="custom_error_class",
            category="error_handling",
            description="Uses AppError class extending Error with code and status",
            frequency=47,
            confidence=0.95,
            examples=[
                PatternExample(
                    file_path="src/lib/errors.ts",
                    line_start=5,
                    line_end=25,
                    code_snippet="class AppError extends Error {\n  constructor(\n    public code: ErrorCode,\n    message: string,\n    public status: number = 500\n  ) {...}",
                    annotation="Base error class - all errors extend this"
                ),
            ],
            anti_patterns=[
                "throw new Error('message') - use AppError instead",
                "Catching errors without logging",
            ]
        ),
        Pattern(
            name="api_error_response",
            category="error_handling",
            description="API routes return { success: false, error: { code, message } }",
            frequency=23,
            confidence=0.92,
            examples=[...],
            anti_patterns=[...]
        ),
    ]
)
```

---

### F3: Change Validator (`mu_validate`)

**Priority**: P1 (High)
**Complexity**: Medium
**Dependencies**: mu_patterns, git integration

#### Description

Validate changes against codebase patterns and conventions before commit. Catches style violations, missing related files, and pattern deviations.

#### Interface

```python
@mcp.tool()
def mu_validate(
    path: str | None = None,
    diff: str | None = None,
    strict: bool = False,
) -> ValidationResult:
    """Validate changes against codebase patterns.

    Args:
        path: File or directory to validate (default: staged changes)
        diff: Git diff to validate (alternative to path)
        strict: Fail on warnings, not just errors

    Returns:
        ValidationResult with issues and suggestions
    """
```

#### Validation Rules

| Rule | Severity | Description |
|------|----------|-------------|
| `naming_convention` | warning | Function/class names don't match pattern |
| `missing_test` | warning | New code without corresponding test |
| `missing_export` | error | Public API not exported from index |
| `pattern_deviation` | warning | Code structure differs from pattern |
| `import_style` | warning | Imports not grouped correctly |
| `error_handling` | warning | Error handling doesn't match pattern |
| `missing_types` | warning | Missing TypeScript types |
| `console_log` | error | Debug logging left in code |

#### Output Structure

```python
@dataclass
class ValidationResult:
    valid: bool                    # No errors (warnings OK)
    strict_valid: bool             # No errors or warnings
    issues: list[ValidationIssue]
    suggestions: list[Suggestion]
    files_checked: int

@dataclass
class ValidationIssue:
    severity: Literal["error", "warning", "info"]
    rule: str
    file_path: str
    line: int | None
    message: str
    suggestion: str | None         # How to fix
    example: str | None            # Correct pattern example
```

#### Example

**Input**:
```
mu_validate(path="src/hooks/useNewFeature.ts")
```

**Output**:
```
ValidationResult(
    valid=True,
    strict_valid=False,
    issues=[
        ValidationIssue(
            severity="warning",
            rule="missing_test",
            file_path="src/hooks/useNewFeature.ts",
            line=None,
            message="No test file found for this hook",
            suggestion="Create src/hooks/__tests__/useNewFeature.test.ts",
            example="See src/hooks/__tests__/useTransactions.test.ts for pattern"
        ),
        ValidationIssue(
            severity="warning",
            rule="missing_export",
            file_path="src/hooks/useNewFeature.ts",
            line=None,
            message="Hook not exported from src/hooks/index.ts",
            suggestion="Add: export { useNewFeature } from './useNewFeature'"
        ),
    ],
    suggestions=[
        Suggestion(type="related_file", message="Consider adding Storybook story"),
    ],
    files_checked=1
)
```

---

### F4: Related Changes Suggester (`mu_related`)

**Priority**: P1 (High)
**Complexity**: Medium
**Dependencies**: mu_patterns, file analysis

#### Description

Given a file being modified, suggest related files that typically change together based on codebase conventions and git history.

#### Interface

```python
@mcp.tool()
def mu_related(
    file_path: str,
    change_type: Literal["create", "modify", "delete"] = "modify",
) -> RelatedFilesResult:
    """Suggest related files that should change together.

    Args:
        file_path: The file being modified
        change_type: Type of change being made

    Returns:
        RelatedFilesResult with suggested files and reasons
    """
```

#### Detection Methods

1. **Convention-Based**:
   - `src/hooks/useFoo.ts` → `src/hooks/__tests__/useFoo.test.ts`
   - `src/components/Foo.tsx` → `src/components/Foo.stories.tsx`
   - New export → Update `index.ts`

2. **Git Co-Change Analysis**:
   - Files that historically change together
   - "When A changes, B changes 80% of the time"

3. **Dependency Analysis**:
   - Files that import the changed file
   - Type definition files

#### Output Structure

```python
@dataclass
class RelatedFilesResult:
    file_path: str
    related_files: list[RelatedFile]

@dataclass
class RelatedFile:
    path: str
    exists: bool
    action: Literal["update", "create", "review"]
    reason: str
    confidence: float
    template: str | None          # Template for new files
```

---

### F5: Proactive Warnings (`mu_warn`)

**Priority**: P1 (High)
**Complexity**: Low
**Dependencies**: mu_impact, git integration

#### Description

Provide proactive warnings about files/nodes before modification. Includes impact scope, staleness, security sensitivity, and ownership.

#### Interface

```python
@mcp.tool()
def mu_warn(
    target: str,
) -> WarningsResult:
    """Get proactive warnings about a target before modification.

    Args:
        target: File path or node ID

    Returns:
        WarningsResult with categorized warnings
    """
```

#### Warning Categories

| Category | Trigger | Example |
|----------|---------|---------|
| `high_impact` | >20 dependents | "47 files depend on this" |
| `stale` | No changes >6 months | "Last modified 8 months ago" |
| `different_owner` | Different author | "Primary author: alice@company.com" |
| `security` | Auth/crypto/secrets | "Contains authentication logic" |
| `no_tests` | No test coverage | "No tests found for this module" |
| `deprecated` | Marked deprecated | "This module is deprecated, use X" |
| `complexity` | High complexity | "Complexity score: 145 (high)" |

---

### F6: Cross-Session Memory (`mu_remember`, `mu_recall`)

**Priority**: P2 (Medium)
**Complexity**: Medium
**Dependencies**: File storage

#### Description

Persist learnings and context across sessions. Allows AI assistants to remember discoveries about the codebase.

#### Interface

```python
@mcp.tool()
def mu_remember(
    key: str,
    content: str,
    category: str = "general",
    ttl_days: int | None = None,
) -> MemoryResult:
    """Store a memory about the codebase.

    Args:
        key: Short identifier for the memory
        content: What to remember
        category: Category (pattern, warning, decision, context)
        ttl_days: Auto-expire after N days (None = permanent)
    """

@mcp.tool()
def mu_recall(
    query: str | None = None,
    category: str | None = None,
    limit: int = 10,
) -> list[Memory]:
    """Recall stored memories.

    Args:
        query: Search query (semantic search)
        category: Filter by category
        limit: Maximum memories to return
    """
```

#### Storage

- File: `.mu-memory.jsonl` in project root
- Format: JSONL with timestamp, author, content
- Indexed for semantic search via embeddings

#### Example

```python
# Remember a decision
mu_remember(
    key="payments_deprecation",
    content="The payments module is deprecated. Use billing module instead. Migration planned for Q2.",
    category="decision"
)

# Later, recall it
mu_recall("payments")
# Returns: Memory(key="payments_deprecation", content="The payments module is deprecated...")
```

---

### F7: Why Layer (`mu_why`)

**Priority**: P2 (Medium)
**Complexity**: High
**Dependencies**: Git history, commit parsing

#### Description

Explain why code is structured the way it is by analyzing git history, commit messages, and related documentation.

#### Interface

```python
@mcp.tool()
def mu_why(
    target: str,
    depth: int = 5,
) -> WhyResult:
    """Explain why a code element exists and its history.

    Args:
        target: File path or node ID
        depth: How many historical commits to analyze

    Returns:
        WhyResult with history, decisions, and context
    """
```

#### Analysis Sources

1. **Git History**:
   - Initial commit message (why created)
   - Major change commits (why modified)
   - Related PRs/issues (linked context)

2. **Code Comments**:
   - TODO/FIXME/HACK annotations
   - JSDoc/docstring explanations
   - Inline comments

3. **Related Files**:
   - ADRs (Architecture Decision Records)
   - README files in same directory
   - CHANGELOG entries

#### Output Structure

```python
@dataclass
class WhyResult:
    target: str
    created: HistoryEntry          # When/why created
    major_changes: list[HistoryEntry]  # Significant modifications
    decisions: list[Decision]      # Related ADRs/decisions
    annotations: list[Annotation]  # Code comments explaining why
    related_docs: list[str]        # Related documentation files
    summary: str                   # AI-generated summary
```

---

### F8: Natural Language MUQL (`mu_ask`)

**Priority**: P2 (Medium)
**Complexity**: Medium
**Dependencies**: Haiku LLM, MUQL engine

#### Description

Translate natural language questions into MUQL queries and return results.

#### Interface

```python
@mcp.tool()
def mu_ask(
    question: str,
    explain: bool = False,
) -> AskResult:
    """Answer a question about the codebase using MUQL.

    Args:
        question: Natural language question
        explain: Include the generated MUQL query

    Returns:
        AskResult with answer and optional query explanation
    """
```

#### Translation Examples

| Question | Generated MUQL |
|----------|----------------|
| "What functions have high complexity?" | `SELECT name, file_path, complexity FROM functions WHERE complexity > 30 ORDER BY complexity DESC LIMIT 20` |
| "What depends on UserService?" | `SHOW dependents OF UserService DEPTH 2` |
| "Is there a path from auth to database?" | `PATH FROM auth_service TO database_client` |
| "Are there any circular dependencies?" | `FIND CYCLES WHERE edge_type = 'imports'` |

---

### F9: Diff Reviewer (`mu_review_diff`)

**Priority**: P2 (Medium)
**Complexity**: Medium
**Dependencies**: mu_validate, mu_semantic_diff

#### Description

Semantically review a diff for breaking changes, pattern violations, and suggestions.

#### Interface

```python
@mcp.tool()
def mu_review_diff(
    base_ref: str = "main",
    head_ref: str = "HEAD",
) -> DiffReviewResult:
    """Review a diff for issues and suggestions.

    Args:
        base_ref: Base git ref
        head_ref: Head git ref

    Returns:
        DiffReviewResult with issues, breaking changes, suggestions
    """
```

#### Review Checks

1. **Breaking Changes**: Removed public APIs, changed signatures
2. **Pattern Violations**: Deviations from codebase patterns
3. **Missing Pieces**: Tests, exports, documentation
4. **Duplication**: Similar code exists elsewhere
5. **Security**: New auth/crypto code review flags

---

### F10: Code Templates (`mu_generate`)

**Priority**: P3 (Low)
**Complexity**: High
**Dependencies**: mu_patterns, template engine

#### Description

Generate boilerplate code that matches codebase patterns.

#### Interface

```python
@mcp.tool()
def mu_generate(
    template_type: str,
    name: str,
    options: dict[str, Any] | None = None,
) -> GenerateResult:
    """Generate code following codebase patterns.

    Args:
        template_type: What to generate (hook, component, api_route, etc.)
        name: Name for the generated code
        options: Additional options (entity, fields, etc.)

    Returns:
        GenerateResult with generated files
    """
```

#### Template Types

| Type | Generated Files |
|------|-----------------|
| `hook` | Hook file, test file, index export |
| `component` | Component file, test file, story file |
| `api_route` | Route handler, validation schema, test |
| `service` | Service class, interface, test |

---

## Implementation Roadmap

### Phase 0: Bug Fixes (Week 0) - PREREQUISITE

> **Blockers**: Intelligence Layer features depend on working MUQL, context extraction, and MCP tools.

| Day | Task | Effort | Status |
|-----|------|--------|--------|
| 1 | B1: Fix MUQL `CONTAINS` + `IN` transformers | 2h | 🔴 TODO |
| 1 | B1: Add GROUP BY to grammar | 2h | 🔴 TODO |
| 2 | B2: Fix context extraction threshold | 2h | 🔴 TODO |
| 2 | B3: Add daemon routing to MCP tools | 3h | 🔴 TODO |
| 3 | B5: Add `mu_read` MCP tool | ~~2h~~ | ✅ DONE |
| 3 | B4: Add semantic search endpoint | 3h | 🔴 TODO |
| 4 | B6: Implement FIND queries | 4h | 🔴 TODO |
| 4 | B7-B10: Polish fixes | 2h | 🔴 TODO |
| - | CLI improvements (bootstrap, status, etc.) | - | ✅ DONE |

**Deliverable**: All validation tests pass (see Phase 0 section above).
**Progress**: 2/9 tasks completed.

---

### Phase 1: Foundation (Week 1-2)

1. **F2: Pattern Library** - Foundation for other features
   - Pattern detection algorithms
   - Pattern storage in .mubase
   - CLI: `mu patterns [category]`
   - MCP: `mu_patterns()`

2. **F5: Proactive Warnings** - Low complexity, high value
   - Warning detection rules
   - Integration with mu_impact
   - CLI: `mu warn <target>`
   - MCP: `mu_warn()`

### Phase 2: Validation (Week 3-4)

3. **F3: Change Validator** - Builds on patterns
   - Validation rule engine
   - Git staged files integration
   - CLI: `mu validate [path]`
   - MCP: `mu_validate()`

4. **F4: Related Changes** - Convention-based
   - File convention patterns
   - Git co-change analysis
   - CLI: `mu related <file>`
   - MCP: `mu_related()`

### Phase 3: Intelligence (Week 5-6)

5. **F1: Task-Aware Context** - The killer feature
   - Task analysis with Haiku
   - Multi-signal retrieval
   - Context assembly
   - CLI: `mu context --task "description"`
   - MCP: `mu_task_context()`

6. **F8: Natural Language MUQL** - Accessibility
   - NL → MUQL translation
   - Query explanation
   - CLI: `mu ask "question"`
   - MCP: `mu_ask()`

### Phase 4: Memory & History (Week 7-8)

7. **F6: Cross-Session Memory** - Persistence
   - Memory storage format
   - Semantic search on memories
   - CLI: `mu remember`, `mu recall`
   - MCP: `mu_remember()`, `mu_recall()`

8. **F7: Why Layer** - Deep context
   - Git history analysis
   - Commit message parsing
   - Documentation linking
   - CLI: `mu why <target>`
   - MCP: `mu_why()`

### Phase 5: Polish (Week 9-10)

9. **F9: Diff Reviewer** - Quality gate
   - Semantic diff integration
   - Pattern violation detection
   - CLI: `mu review [base] [head]`
   - MCP: `mu_review_diff()`

10. **F10: Code Templates** - Productivity
    - Template extraction from patterns
    - Code generation engine
    - CLI: `mu generate <type> <name>`
    - MCP: `mu_generate()`

---

## Technical Architecture

### New Modules

```
src/mu/
├── intelligence/
│   ├── __init__.py
│   ├── CLAUDE.md
│   ├── task_context.py      # F1: Task-aware context
│   ├── patterns.py          # F2: Pattern detection
│   ├── validator.py         # F3: Change validation
│   ├── related.py           # F4: Related files
│   └── warnings.py          # F5: Proactive warnings
├── memory/
│   ├── __init__.py
│   ├── CLAUDE.md
│   ├── store.py             # F6: Memory storage
│   └── recall.py            # F6: Memory retrieval
├── history/
│   ├── __init__.py
│   ├── CLAUDE.md
│   ├── why.py               # F7: Why layer
│   └── git_analysis.py      # Git history parsing
└── templates/
    ├── __init__.py
    ├── CLAUDE.md
    └── generator.py         # F10: Code generation
```

### Database Schema Extensions

```sql
-- Pattern storage
CREATE TABLE patterns (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    frequency INTEGER,
    confidence REAL,
    examples JSON,
    anti_patterns JSON,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- Memory storage
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL,
    content TEXT NOT NULL,
    category TEXT,
    author TEXT,
    created_at TIMESTAMP,
    expires_at TIMESTAMP,
    embedding BLOB
);

-- File conventions
CREATE TABLE conventions (
    pattern TEXT PRIMARY KEY,  -- e.g., "src/hooks/*.ts"
    related_patterns JSON,     -- e.g., ["src/hooks/__tests__/*.test.ts"]
    confidence REAL
);
```

---

## Open Questions

1. **Pattern Confidence Threshold**: What confidence level before showing a pattern?
2. **Memory Sharing**: Should memories be shareable across team members?
3. **Template Customization**: How do users customize generated code?
4. **Performance**: How to keep task_context fast (<2s)?
5. **Privacy**: Should patterns/memories be git-ignored by default?

---

## Appendix: User Stories

### US1: Task-Aware Context
> As an AI assistant, I want to get all relevant context for a task in one call, so I can start writing code immediately instead of exploring.

### US2: Pattern Conformance
> As an AI assistant, I want to know the codebase patterns before writing code, so my code fits the existing style.

### US3: Pre-Commit Validation
> As an AI assistant, I want to validate my changes before committing, so I catch issues early.

### US4: Related File Awareness
> As an AI assistant, I want to know what related files I'm forgetting, so PRs are complete.

### US5: Informed Modification
> As an AI assistant, I want warnings before modifying critical code, so I'm appropriately cautious.

### US6: Persistent Learning
> As an AI assistant, I want to remember things about the codebase across sessions, so I don't rediscover the same things.

### US7: Historical Context
> As an AI assistant, I want to understand why code is structured a certain way, so I don't break assumptions.

### US8: Natural Queries
> As an AI assistant, I want to ask questions in natural language, so I don't need to learn MUQL syntax.

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 0.3 | 2025-12-08 | Marked B5 (`mu_read`) as DONE; Added CLI Improvements section; Updated validation tests |
| 0.2 | 2025-12-08 | Added Phase 0: Foundation Fixes from stress test results (parallel session) |
| 0.1 | 2025-12-08 | Initial draft from alpha tester feedback |
