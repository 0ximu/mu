# MU Trimming Phase 4: Bug Fixes & Polish

**Status:** Draft
**Author:** Claude + imu
**Created:** 2025-12-09
**Depends on:** Phase 1-3
**Target:** Fix broken functionality discovered during audit

## Executive Summary

During hands-on testing, several bugs and UX issues were discovered. This phase addresses them to ensure the trimmed MU works correctly.

## Goals

1. **Fix broken tools** - Tools that return wrong/empty results
2. **Improve error messages** - Clear guidance when things fail
3. **Node resolution** - Accept multiple node reference formats
4. **Token counting** - Fix the "0 tokens" bug

## Non-Goals

- Adding new features
- Performance optimization (separate effort)
- UI/UX improvements beyond error messages

---

## Bug List

### P0: Critical (Blocks Core Functionality)

#### BUG-001: mu_deps Returns Empty Results

**Observed:**
```python
mu_deps("MUbase", depth=2) → {"dependencies": []}
```

**Expected:** Should return dependencies of MUbase class

**Root Cause:** Node resolution fails to find class by short name

**Fix:**
1. Improve `_resolve_node_id()` to search by name
2. Try multiple patterns: exact match, suffix match, type-prefixed

**Files:** `src/mu/mcp/server.py` (or new `tools/analysis.py`)

---

#### BUG-002: mu_warn Returns "Target Not Found"

**Observed:**
```python
mu_warn("src/mu/mcp/server.py") → {"target": "src/mu/mcp/server.py", "warnings": [], "summary": "Target not found"}
```

**Expected:** Should analyze the file and return warnings

**Root Cause:** File path not converted to node ID correctly

**Fix:**
1. Accept both file paths and node IDs
2. Convert file path to `mod:{path}` format
3. Handle relative vs absolute paths

**Files:** `src/mu/intelligence/warnings.py`, `src/mu/mcp/server.py`

---

#### BUG-003: "0 Tokens" in Context Fallback

**Observed:** When context extraction falls back to a message, token_count = 0

**Expected:** Should count actual tokens in the fallback message

**Root Cause:** `smart.py:142` returns hardcoded `token_count=0` in fallback path

**Fix:**
```python
# Before
return ContextResult(
    mu_text=f"No relevant code found for: {question}",
    token_count=0,  # BUG
    nodes=[],
)

# After
fallback_msg = f"No relevant code found for: {question}"
return ContextResult(
    mu_text=fallback_msg,
    token_count=len(fallback_msg) // 4,  # Rough token estimate
    nodes=[],
)
```

**Files:** `src/mu/kernel/context/smart.py`

---

### P1: High (Degrades UX Significantly)

#### BUG-004: mu_read Requires Full Node ID

**Observed:**
```python
mu_read("MUbase") → Error: "Node not found: MUbase"
mu_read("cls:src/mu/kernel/mubase.py:MUbase") → Works
```

**Expected:** Should accept short names and resolve them

**Fix:**
1. Add resolution logic to mu_read
2. Try patterns: exact ID, name match, qualified name match
3. Return helpful error if ambiguous (multiple matches)

**Files:** `src/mu/mcp/server.py`

---

#### BUG-005: mu_cycles Always Empty

**Observed:**
```python
mu_cycles() → {"cycles": [], "cycle_count": 0}
```

**Note:** This might be correct (no cycles in MU codebase), but we can't verify.

**Fix:**
1. Add debug logging to cycle detection
2. Create test case with known cycle
3. Verify algorithm correctness

**Files:** `src/mu/mcp/server.py`, graph reasoning code

---

#### BUG-006: OMEGA Seed Overhead

**Observed:** OMEGA seed is 445 tokens of schema boilerplate

**Problem:** For small contexts, seed exceeds the benefit

**Fix:**
1. Add `--no-seed` flag to skip seed in follow-up queries
2. Make seed optional in mu_context_omega
3. Cache seed in conversation context

**Files:** `src/mu/kernel/context/omega.py`, `src/mu/mcp/server.py`

---

### P2: Medium (Annoying but Workaroundable)

#### BUG-007: Inconsistent Path Handling

**Observed:** Some commands want absolute paths, some want relative

**Fix:**
1. Standardize on relative paths from project root
2. Auto-convert absolute to relative
3. Document expected format

**Files:** Multiple

---

#### BUG-008: mu_context Returns Tests When Unwanted

**Observed:** Context includes test files even when asking about production code

**Fix:**
1. Add `exclude_tests` parameter (exists but may not work)
2. Improve filtering logic
3. Default to excluding tests for certain query patterns

**Files:** `src/mu/kernel/context/smart.py`

---

#### BUG-009: Pattern Detection Noise

**Observed:** Patterns include low-value detections like "file_extension_py"

**Fix:**
1. Filter out obvious patterns
2. Raise confidence threshold
3. Group related patterns

**Files:** `src/mu/intelligence/patterns.py`

---

### P3: Low (Nice to Fix)

#### BUG-010: mu_related Returns Too Many Files

**Observed:** Returns 100+ related files for a single change

**Fix:**
1. Limit output to top 20 by confidence
2. Add pagination
3. Group by source (convention vs git)

**Files:** `src/mu/intelligence/related.py`

---

#### BUG-011: mu_why Missing Issue Links

**Observed:** Issue references not always extracted from commit messages

**Fix:**
1. Improve regex for issue detection
2. Support more formats (#123, GH-123, JIRA-123)

**Files:** `src/mu/intelligence/why.py`

---

## Implementation Plan

### Day 1: P0 Bugs

1. **BUG-001**: Fix mu_deps node resolution
   - Add `_resolve_node_by_name()` helper
   - Try exact match, then suffix match
   - Return first match or error with suggestions

2. **BUG-002**: Fix mu_warn path handling
   - Accept file paths directly
   - Convert to node ID internally
   - Handle both relative and absolute

3. **BUG-003**: Fix 0 tokens bug
   - Add token counting to fallback path
   - Use tiktoken if available, else estimate

### Day 2: P1 Bugs

4. **BUG-004**: Fix mu_read resolution
   - Reuse resolver from BUG-001
   - Add helpful error messages

5. **BUG-005**: Verify mu_cycles
   - Add test with synthetic cycle
   - Add debug logging
   - Document if working correctly

6. **BUG-006**: OMEGA seed optimization
   - Add `include_seed` parameter
   - Default to True for first query
   - Document caching strategy

### Day 3: P2 Bugs + Testing

7. **BUG-007**: Path standardization
   - Create `normalize_path()` utility
   - Apply consistently

8. **BUG-008**: Test exclusion
   - Fix exclude_tests logic
   - Add tests

9. **BUG-009**: Pattern filtering
   - Add quality threshold
   - Filter obvious patterns

10. Integration testing for all fixes

---

## Node Resolution Strategy

### Current State

Node IDs have this format:
```
mod:src/mu/kernel/mubase.py           # Module
cls:src/mu/kernel/mubase.py:MUbase    # Class
fn:src/mu/kernel/mubase.py:get_node   # Function
ext:duckdb                            # External
```

### Resolution Order

When given a reference like "MUbase":

1. **Exact ID match**: Check if input is a valid node ID
2. **Name match**: Search `name = 'MUbase'`
3. **Suffix match**: Search `name LIKE '%MUbase'`
4. **Qualified name match**: Search `qualified_name LIKE '%MUbase%'`
5. **File path match**: If looks like path, try `mod:{path}`

### Ambiguity Handling

If multiple matches:
```
Error: Ambiguous reference "Service" matches 5 nodes:
  1. cls:src/auth.py:AuthService
  2. cls:src/user.py:UserService
  3. cls:src/payment.py:PaymentService
  ...
Use full node ID or be more specific.
```

---

## Testing Plan

### Unit Tests

```python
class TestNodeResolution:
    def test_exact_id_match(self):
        assert resolve("cls:src/foo.py:Bar") == "cls:src/foo.py:Bar"

    def test_name_match(self):
        assert resolve("MUbase") == "cls:src/mu/kernel/mubase.py:MUbase"

    def test_suffix_match(self):
        assert resolve("base") in [...possible matches...]

    def test_file_path(self):
        assert resolve("src/mu/mcp/server.py") == "mod:src/mu/mcp/server.py"

    def test_ambiguous_error(self):
        with pytest.raises(AmbiguousNodeError):
            resolve("Service")  # Multiple matches
```

### Integration Tests

```python
class TestMCPToolsFixes:
    def test_mu_deps_finds_dependencies(self, mubase):
        result = mu_deps("MUbase")
        assert len(result["dependencies"]) > 0

    def test_mu_warn_accepts_file_path(self, mubase):
        result = mu_warn("src/mu/mcp/server.py")
        assert result["target_type"] == "file"
        assert len(result["warnings"]) >= 0  # May have warnings or not

    def test_mu_context_counts_tokens(self, mubase):
        result = mu_context("nonexistent query xyz")
        assert result["token_count"] > 0  # Even fallback has tokens

    def test_mu_read_accepts_short_name(self, mubase):
        result = mu_read("MUbase")
        assert "class MUbase" in result["source"]
```

---

## Success Criteria

- [ ] mu_deps returns non-empty results for known nodes
- [ ] mu_warn works with file paths
- [ ] mu_context never returns token_count=0
- [ ] mu_read accepts short names
- [ ] All P0 and P1 bugs fixed
- [ ] Integration tests pass
- [ ] No regressions in existing functionality

---

## Rollback Plan

Each bug fix should be a separate commit:

```bash
git revert <commit>  # Revert specific fix if problematic
```

---

## Appendix: Node Resolution Helper

```python
def resolve_node_reference(
    db: MUbase,
    ref: str,
    node_type: str | None = None,
) -> str:
    """Resolve a user-provided reference to a node ID.

    Args:
        db: MUbase instance
        ref: User reference (ID, name, path, etc.)
        node_type: Optional filter by type (module, class, function)

    Returns:
        Resolved node ID

    Raises:
        NodeNotFoundError: If no match found
        AmbiguousNodeError: If multiple matches found
    """
    # 1. Check if already a valid node ID
    if db.get_node(ref):
        return ref

    # 2. Try as file path
    if "/" in ref or ref.endswith(".py"):
        # Normalize path
        normalized = ref.lstrip("./")
        node_id = f"mod:{normalized}"
        if db.get_node(node_id):
            return node_id

    # 3. Search by name
    matches = db.find_by_name(ref, node_type=node_type)
    if len(matches) == 1:
        return matches[0].id

    if len(matches) > 1:
        raise AmbiguousNodeError(ref, matches)

    # 4. Try suffix match
    matches = db.find_by_name(f"%{ref}", node_type=node_type)
    if len(matches) == 1:
        return matches[0].id

    if len(matches) > 1:
        raise AmbiguousNodeError(ref, matches)

    # 5. No matches
    raise NodeNotFoundError(ref)
```
