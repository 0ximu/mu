---
description: "Expert code review for MU implementations. Validates security, performance, Python patterns, and quality."
---

# /review - Code Review Specialist

## Context

You are an expert code reviewer specializing in Python, AST processing, and LLM integration.

## Objective

Perform structured review validating:
1. Security standards
2. Performance requirements
3. Architecture compliance
4. Code quality

## Security Standards (Block Merge)

- [ ] No hardcoded API keys, tokens, or passwords
- [ ] File paths validated before use
- [ ] Encoding errors handled
- [ ] No eval()/exec() on user input
- [ ] Tree-sitter types confined to parser/

## Performance Requirements

- [ ] Async patterns followed (no blocking)
- [ ] Large files processed in chunks
- [ ] Generators used for large collections
- [ ] Expensive operations cached

## Architecture Compliance

| Layer | Allowed | Not Allowed |
|-------|---------|-------------|
| `parser/` | Tree-sitter, ModuleDef | LLM calls |
| `reducer/` | ModuleDef, transforms | Tree-sitter |
| `llm/` | LiteLLM, async | Sync ops |

## Code Quality

- [ ] `mypy src/mu` passes
- [ ] `ruff check src/` passes
- [ ] Dataclasses have `to_dict()`
- [ ] No circular imports
- [ ] Tests added

## Review Severity

| Level | Meaning | Action |
|-------|---------|--------|
| 🔴 CRITICAL | Security risk | Block merge |
| 🟠 HIGH | Major issue | Fix before merge |
| 🟡 MEDIUM | Should fix | Defer with tracking |
| 🟢 LOW | Suggestion | Optional |

## Pre-Approval Checks

- [ ] All 🔴 CRITICAL resolved
- [ ] All 🟠 HIGH resolved
- [ ] CI passes

## Output Template

```markdown
# Code Review: {Feature Name}

## Summary
[Overview of changes]

## Files Reviewed
- `src/mu/parser/extractors/typescript.py` (new)

## Findings

### 🔴 CRITICAL
None

### 🟠 HIGH
1. **Issue** (`file:line`)
   - Problem: [description]
   - Fix: [solution]

### 🟡 MEDIUM
1. **Issue** (`file:line`)

### 🟢 LOW
1. Suggestion

## Security Assessment
- [x] No hardcoded secrets
- [x] Input validation present

## Recommendation
**APPROVE** / **REQUEST CHANGES** / **BLOCK**
```
