# ADR-0005: Node Resolution & Disambiguation Strategy

## Status

Accepted

## Date

2025-12-10

## Context

When users reference a node by name (e.g., `mu deps PayoutService`), MU often resolves to the wrong node when multiple matches exist. This was observed in several scenarios:

1. **Silent wrong choice**: `mu deps PayoutService` silently picked `PayoutServiceTests` instead of `PayoutService`
2. **Alphabetical bias**: Resolution appeared to use alphabetical sorting, causing test files to win over source files
3. **No user choice**: Messages said "Multiple matches found" but didn't let users select
4. **Inconsistent interfaces**: Some commands accepted class names, others required file paths

Node resolution code was duplicated across 4+ locations with subtle differences:
- MUQL Executor: `_resolve_node_id()`
- Graph Commands: `_resolve_node()`
- Core Commands: Inline resolution
- Daemon Client: `find_node()`

All followed the same anti-pattern: **first match wins** without source-vs-test preference.

## Decision

Implement a centralized `NodeResolver` class with configurable disambiguation strategies:

### Resolution Strategies

1. **PREFER_SOURCE** (default): Automatically prefer source files over test files using scoring
2. **INTERACTIVE**: Prompt CLI users to choose when multiple matches exist
3. **FIRST_MATCH**: Legacy alphabetical behavior for backward compatibility
4. **STRICT**: Error on any ambiguity (for scripts requiring determinism)

### Scoring System

| Match Type | Base Score | Description |
|------------|------------|-------------|
| Exact ID | 100 | Full node ID like `cls:src/foo.py:MyClass` |
| Exact Name | 80 | Class/function name exactly matches |
| Suffix Match | 60 | Reference matches end of name |
| Fuzzy Match | 40 | Case-insensitive substring match |

Source files receive a +10 bonus over test files.

### Test File Detection

Language-agnostic heuristics detect test files across all supported languages:
- Python: `tests/`, `test_*.py`, `*_test.py`
- TypeScript/JS: `__tests__/`, `*.test.ts`, `*.spec.ts`
- Go: `*_test.go`
- Java: `src/test/`, `*Test.java`
- C#: `.Tests/`, `*Tests.cs`, `UnitTests/`
- Rust: `tests/`, `*_test.rs`

## Consequences

### Positive

- **Consistent resolution**: All commands use the same logic
- **Better defaults**: Source files selected over test files automatically
- **User control**: Interactive mode and `--no-interactive` flag provide flexibility
- **Extensible**: Strategy pattern allows easy addition of new resolution strategies
- **Deterministic**: Tiebreaker on node ID ensures reproducible results
- **Language-agnostic**: Works across Python, TypeScript, Go, Java, C#, Rust

### Negative

- **Learning curve**: Users must understand new `--no-interactive` flag for scripts
- **Behavior change**: Existing scripts may get different (correct) results
- **Performance**: Slightly slower due to scoring calculation (negligible: <10ms)

### Neutral

- Requires updating CLI commands to use new resolver
- Test file heuristics may need expansion for uncommon patterns

## Alternatives Considered

### Alternative 1: Always Prompt for Selection

- Pros: Maximum user control, no wrong guesses
- Cons: Breaks scripting, annoying for single-match cases
- Why rejected: Poor UX for common case (unique match)

### Alternative 2: Require Full Node IDs

- Pros: No ambiguity, deterministic
- Cons: Terrible UX, defeats purpose of MU's convenient queries
- Why rejected: Makes CLI unusable

### Alternative 3: Shortest Path Wins

- Pros: Simple heuristic
- Cons: Doesn't distinguish source from test, unreliable
- Why rejected: Would still pick `Tests/PayoutService.cs` over `Services/PayoutService.cs`

## References

- PRD: `/docs/prd/prd2-node-resolution.md`
- Task Breakdown: `/docs/prd/prd2-node-resolution.tasks.md`
- Implementation: `/src/mu/kernel/resolver.py`
- Tests: `/tests/unit/test_resolver.py`, `/tests/integration/test_node_resolution.py`
