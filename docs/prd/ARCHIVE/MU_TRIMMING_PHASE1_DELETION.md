# MU Trimming Phase 1: Dead Code Deletion

**Status:** Draft
**Author:** Claude + imu
**Created:** 2025-12-09
**Target:** Reduce codebase by ~3,500 LOC of unused/low-value code

## Executive Summary

MU has accumulated significant dead code and over-engineered features that add complexity without proportional value. This phase focuses on surgical removal of unused modules before restructuring.

## Goals

1. **Reduce cognitive load** - Less code to understand and maintain
2. **Faster CI/CD** - Fewer tests, faster builds
3. **Cleaner dependency graph** - Remove unused import chains
4. **Foundation for Phase 2** - Clean slate for vibes-first CLI

## Non-Goals

- Changing public APIs (yet)
- Adding new features
- Refactoring working code

---

## Deletion Targets

### 1. Intelligence Layer Trimming

#### 1.1 DELETE: `src/mu/intelligence/generator.py` (1,292 LOC)

**Reason:** Oversold as "pattern-based code generation" but it's hardcoded templates. The value prop doesn't justify the complexity.

**What it does:**
- `CodeGenerator` class with template methods for hooks, services, components, etc.
- Language-specific templates (Python, TypeScript)
- Pattern matching to suggest templates

**Why delete:**
- Templates are generic and not codebase-specific
- Users can write their own boilerplate faster
- Marketed as AI-powered but it's string concatenation
- 0 usage in actual workflows observed

**Files to delete:**
```
src/mu/intelligence/generator.py
tests/unit/test_generator.py
src/mu/commands/generate.py
```

**MCP tool to remove:** `mu_generate`

**CLI command to remove:** `mu generate`

---

#### 1.2 DELETE: `src/mu/intelligence/memory.py` (~200 LOC)

**Reason:** Cross-session memory is a novelty feature. LLMs have their own context management, and this adds database complexity without clear use cases.

**What it does:**
- `MemoryManager` for storing learnings/decisions
- Categories: preference, decision, context, learning, pitfall, convention, todo, reference
- Persistence in MUbase

**Why delete:**
- Not core to code understanding
- Adds schema complexity to MUbase
- No observed usage in real workflows
- LLM context windows are large enough now

**Files to delete:**
```
src/mu/intelligence/memory.py
tests/unit/test_memory.py
```

**MCP tools to remove:** `mu_remember`, `mu_recall`

**Database cleanup:** Remove `memories` table from schema (migration needed)

---

#### 1.3 DELETE: `src/mu/intelligence/task_context.py` (~350 LOC)

**Reason:** Duplicates `mu_context` with extra complexity. The "task-aware" aspect doesn't provide meaningful differentiation.

**What it does:**
- `TaskContextExtractor` wraps SmartContextExtractor
- Adds "suggestions" and "warnings" to context output
- Attempts to understand task type (create, modify, delete)

**Why delete:**
- 90% overlap with `mu_context`
- Extra abstraction layer without value
- "Task awareness" is keyword matching, not intelligence
- Can merge useful bits into `mu_context`

**Files to delete:**
```
src/mu/intelligence/task_context.py
tests/unit/test_task_context.py
```

**MCP tool to remove:** `mu_task_context`

**Migration:** Port `_generate_warnings()` and `_generate_suggestions()` to `mu_context` if valuable

---

#### 1.4 DELETE: `src/mu/intelligence/validator.py` (~300 LOC)

**Reason:** Pattern validation sounds useful but the implementation is shallow regex matching. Better to focus on patterns detection only.

**What it does:**
- `PatternValidator` checks new code against detected patterns
- Generates "violations" with suggestions
- Pre-commit hook integration

**Why delete:**
- Validation is too simplistic (regex matching)
- High false positive rate in practice
- Patterns detection (`mu_patterns`) is sufficient
- Users can manually review patterns

**Files to delete:**
```
src/mu/intelligence/validator.py
tests/unit/test_validator.py
```

**MCP tool to remove:** `mu_validate`

**CLI command to remove:** `mu validate`

---

#### 1.5 DELETE: `src/mu/intelligence/nl2muql.py` (~250 LOC)

**Reason:** Natural language to MUQL translation requires LLM calls and adds latency/cost. Users can learn MUQL (it's simple SQL-like syntax).

**What it does:**
- Translates "What are the most complex functions?" to MUQL
- Uses Claude Haiku for translation
- Caches translations

**Why delete:**
- Adds LLM dependency for simple queries
- MUQL is learnable (SQL-like)
- Translation errors cause confusion
- Cost/latency overhead not justified

**Files to delete:**
```
src/mu/intelligence/nl2muql.py
tests/unit/test_nl2muql.py
```

**MCP tool to remove:** `mu_ask`

---

### 2. Unused Module Deletion

#### 2.1 DELETE: `src/mu/security/` (499 LOC)

**Reason:** Secret scanning was planned but never integrated. Only 1 import exists in the entire codebase.

**What it does:**
- `SecretScanner` with regex patterns for API keys, passwords, etc.
- Redaction utilities
- Pattern definitions for various secret types

**Why delete:**
- Never integrated into compress/scan pipeline
- Users have dedicated tools (git-secrets, trufflehog, gitleaks)
- Single import, never called in practice

**Files to delete:**
```
src/mu/security/__init__.py
src/mu/security/scanner.py
src/mu/security/patterns.py
tests/unit/test_security.py (if exists)
```

---

#### 2.2 DELETE: `src/mu/cache/` (661 LOC)

**Reason:** Caching layer is over-engineered and barely integrated. File hashing happens elsewhere, LLM caching is handled by providers.

**What it does:**
- `FileCache` for file content caching
- `LLMCache` for response caching
- SQLite-based persistence
- TTL and invalidation logic

**Why delete:**
- LLM providers have their own caching
- File hashing is done in scanner
- Complex TTL logic unused
- `.mu/cache/` directory often empty

**Files to delete:**
```
src/mu/cache/__init__.py
src/mu/cache/file_cache.py
src/mu/cache/llm_cache.py
tests/unit/test_cache.py (if exists)
```

**CLI command to remove:** `mu cache stats`, `mu cache clear`, `mu cache expire`

---

#### 2.3 DELETE: `src/mu/contracts/` (~300 LOC)

**Reason:** Architecture contracts is a good idea but never got CLI integration or real usage. Either promote or kill.

**Decision:** KILL (can resurrect later if needed)

**What it does:**
- YAML-based architecture rules
- Layer dependency enforcement
- Import restrictions

**Why delete:**
- No CLI commands use it
- `.mu/contracts.yml` rarely created
- Validation never runs automatically
- Better tools exist (ArchUnit, etc.)

**Files to delete:**
```
src/mu/contracts/__init__.py
src/mu/contracts/models.py
src/mu/contracts/validator.py
src/mu/commands/contracts/__init__.py
src/mu/commands/contracts/init_cmd.py
src/mu/commands/contracts/verify.py
tests/unit/test_contracts.py (if exists)
tests/daemon/test_contracts_endpoint.py
```

**CLI commands to remove:** `mu contracts init`, `mu contracts verify`

---

#### 2.4 DELETE: `src/mu/assembler/exporters.py` (~400 LOC)

**Reason:** Duplicate of `kernel/export/`. Two export systems is confusing.

**What it does:**
- `export_mu()`, `export_json()`, `export_markdown()`
- ModuleGraph serialization
- Format-specific formatters

**Why delete:**
- `kernel/export/` is the canonical export system
- Duplicates logic and maintenance burden
- Confusing to have two ways to export

**Files to delete:**
```
src/mu/assembler/exporters.py
```

**Migration:** Ensure `kernel/export/` covers all formats from `assembler/exporters.py`

---

### 3. Legacy Command Cleanup

#### 3.1 SIMPLIFY: `src/mu/commands/describe.py`

**Reason:** CLI self-description for AI agents is niche. Keep minimal version.

**Action:** Reduce to single `--help` style output, remove JSON/markdown formats

---

#### 3.2 REMOVE: `src/mu/commands/init_cmd.py`

**Reason:** `mu init` creates `.murc.toml` but `mu bootstrap` (via MCP) does this automatically.

**Action:** Remove standalone init, let bootstrap handle it

---

#### 3.3 REMOVE: `src/mu/commands/scan.py`

**Reason:** `mu scan` is intermediate step. Users want `mu compress` or `mu build`.

**Action:** Remove, merge into other commands as needed

---

## Implementation Plan

### Step 1: Create Backup Branch
```bash
git checkout -b backup/pre-trimming
git push origin backup/pre-trimming
git checkout -b refactor/phase1-deletion
```

### Step 2: Delete Intelligence Layer (Day 1)

1. Remove `generator.py` + tests + command
2. Remove `memory.py` + tests + MCP tools
3. Remove `task_context.py` + tests + MCP tool
4. Remove `validator.py` + tests + MCP tool + command
5. Remove `nl2muql.py` + tests + MCP tool
6. Update `intelligence/__init__.py` exports
7. Run tests, fix imports

### Step 3: Delete Unused Modules (Day 1)

1. Remove `security/` directory
2. Remove `cache/` directory + commands
3. Remove `contracts/` directory + commands
4. Remove `assembler/exporters.py`
5. Update imports throughout codebase
6. Run tests, fix breakages

### Step 4: Clean Up MCP Server (Day 2)

1. Remove deleted tool registrations from `mcp/server.py`
2. Remove corresponding dataclasses/models
3. Update tool count in documentation
4. Test MCP server starts correctly

### Step 5: Clean Up CLI (Day 2)

1. Remove deleted commands from `cli.py`
2. Remove command modules
3. Update help text
4. Test CLI still works

### Step 6: Database Migration (Day 2)

1. Create migration to drop `memories` table
2. Create migration to drop `patterns` table (if validator used it)
3. Update schema.py
4. Test fresh build + migration

### Step 7: Documentation Update (Day 2)

1. Update CLAUDE.md files
2. Update README.md
3. Remove references to deleted features
4. Update MCP tool list

---

## Success Criteria

- [ ] ~3,500 LOC removed
- [ ] All tests pass
- [ ] `mu bootstrap`, `mu build`, `mu query`, `mu compress` work
- [ ] MCP server starts with reduced tool set
- [ ] No import errors
- [ ] CI passes

## Rollback Plan

If issues arise:
```bash
git checkout develop
git branch -D refactor/phase1-deletion
```

## Risks

| Risk | Mitigation |
|------|------------|
| Breaking imports | Comprehensive grep before deletion |
| Test failures | Fix or remove tests for deleted code |
| User complaints | Features were unused, document removal |
| Hidden dependencies | Run full test suite after each deletion |

---

## Appendix: Files to Delete

```
# Intelligence Layer (~2,400 LOC)
src/mu/intelligence/generator.py
src/mu/intelligence/memory.py
src/mu/intelligence/task_context.py
src/mu/intelligence/validator.py
src/mu/intelligence/nl2muql.py
tests/unit/test_generator.py
tests/unit/test_memory.py
tests/unit/test_task_context.py
tests/unit/test_validator.py
tests/unit/test_nl2muql.py
src/mu/commands/generate.py

# Unused Modules (~1,100 LOC)
src/mu/security/__init__.py
src/mu/security/scanner.py
src/mu/security/patterns.py
src/mu/cache/__init__.py
src/mu/cache/file_cache.py
src/mu/cache/llm_cache.py
src/mu/contracts/__init__.py
src/mu/contracts/models.py
src/mu/contracts/validator.py
src/mu/commands/contracts/__init__.py
src/mu/commands/contracts/init_cmd.py
src/mu/commands/contracts/verify.py
tests/daemon/test_contracts_endpoint.py
src/mu/assembler/exporters.py

# Legacy Commands
src/mu/commands/init_cmd.py
src/mu/commands/scan.py
```

**Total estimated deletion: ~3,500 LOC**
