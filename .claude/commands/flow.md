---
description: "Run complete Plan→Code→Test→Review workflow for MU features."
arguments:
  - name: feature_file
    description: "Path to feature description file"
---

# /flow - Complete Development Workflow

Run the full development workflow: Plan → Code → Test → Review

## Phase 1: Planner Agent (Business Discovery)

**Objective**: Create task breakdown with discovered patterns

1. Read the feature description
2. Search codebase for existing patterns
3. Create `{feature}.tasks.md` with:
   - Business context
   - Discovered patterns
   - Task breakdown with file paths

**Output**: `{feature}.tasks.md`

## Phase 2: Coder Agent (Implementation)

**Objective**: Execute tasks following discovered patterns

1. Read task breakdown
2. Execute tasks sequentially
3. Follow MU-specific standards:
   - Dataclasses with `to_dict()`
   - Error as data, not exceptions
   - Async for LLM calls
4. Run quality checks:
   - `ruff check src/`
   - `mypy src/mu`

**Output**: Updated `{feature}.tasks.md` with implementation status

## Phase 3: Tester Agent (QA)

**Objective**: Comprehensive test coverage

1. Create tests following existing patterns
2. Test by layer priority:
   - Parser (40%)
   - Reducer (30%)
   - Assembler (20%)
   - CLI (10%)
3. Verify coverage:
   - Lines: 80%
   - Branches: 65%

**Output**: Updated `{feature}.tasks.md` with test summary

## Phase 4: Reviewer Agent (Validation)

**Objective**: Security, performance, architecture review

1. Security audit:
   - No hardcoded secrets
   - Input validation
   - Tree-sitter isolation
2. Performance check:
   - Async compliance
   - Memory management
3. Architecture check:
   - Module boundaries
   - Data model patterns

**Output**: Structured code review

## MU Standards Enforced

| Standard | Enforcement |
|----------|-------------|
| Tree-sitter isolation | Parser only |
| Async LLM | All LLM calls |
| to_dict() | All dataclasses |
| Error as data | Return types |
| Type hints | mypy passes |
| Style | ruff passes |
| Coverage | 80% line, 65% branch |

## Example Execution

```
/flow docs/features/add-rust-support.md

Phase 1: Planner
→ Created rust-support.tasks.md
→ Found patterns: python_extractor.py, go_extractor.py
→ 5 tasks identified

Phase 2: Coder
→ Task 1: Created rust_extractor.py ✅
→ Task 2: Added language registration ✅
→ Task 3: Implemented transforms ✅
→ Task 4: Updated CLI ✅
→ Task 5: Added documentation ✅

Phase 3: Tester
→ 15 tests added
→ Coverage: 87% lines, 72% branches

Phase 4: Reviewer
→ Security: PASS
→ Performance: PASS
→ Architecture: PASS
→ Recommendation: APPROVE
```

## Workflow Diagram

```
Feature Card
    ↓
/plan (Planner) → {feature}.tasks.md
    ↓
/code (Coder) → Implementation + Updated tasks
    ↓
/test (Tester) → Test coverage + Updated tasks
    ↓
/review (Reviewer) → Code review report
    ↓
/ship (Commit + PR)
```
