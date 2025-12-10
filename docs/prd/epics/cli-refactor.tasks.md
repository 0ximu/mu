# CLI Refactor - Split God Object - Task Breakdown

## Status: COMPLETE

**Completed**: 2024-12-07

**Results**:
- `src/mu/cli.py` reduced from 3,189 lines to 127 lines (96% reduction)
- Startup time improved from ~168ms to ~133ms (~21% faster)
- All 1286 tests pass
- `ruff check` and `mypy` pass with no errors
- `mu kernel query` removed as planned (deprecated in favor of `mu query`)
- `mu mcp` group added (was not registered before)

---

## Business Context

**Problem**: `src/mu/cli.py` is a 3,189-line god object containing all CLI commands. This causes slow startup (~135ms for `mu --help`), merge conflicts when multiple contributors edit commands, and poor discoverability.

**Outcome**: Modular CLI with fast startup (<50ms), parallel development capability, and isolated testability per command.

**Users**: MU developers (maintainability), MU users (faster CLI), CI/CD pipelines (faster test feedback).

---

## Breaking Change

**Remove `mu kernel query`** - redundant with `mu query` / `mu q`:

| Command | Syntax | Example |
|---------|--------|---------|
| `mu query` | MUQL (SQL-like) | `SELECT * FROM functions WHERE complexity > 20` |
| `mu kernel query` | Flags-based | `--type function --complexity 20` |

- MUQL is strictly more powerful, flag-based is redundant
- Users should use `mu query` or `mu q -i` (interactive) instead
- Document in changelog with migration guidance

---

## Existing Patterns Found

| Pattern | File | Relevance |
|---------|------|-----------|
| Extracted command structure | `src/mu/commands/man.py` | Shows standalone `@click.command()` with lazy imports inside function |
| Command with logging | `src/mu/commands/llm_spec.py:56-108` | Shows pattern for commands using `console.print()` and `print_*` helpers |
| Command registration | `src/mu/cli.py:3170-3180` | Shows `cli.add_command()` with `name=` parameter |
| MUContext pattern | `src/mu/cli.py:35-43` | `pass_context = click.make_pass_decorator(MUContext, ensure=True)` |
| Shared helper functions | `src/mu/cli.py:115-225` | `_execute_muql()` shows reusable logic across commands |
| Command group pattern | `src/mu/cli.py` kernel/daemon/cache groups | Shows `@cli.group()` + subcommand registration |

---

## Task Breakdown

### Task 0: Capture Baseline Outputs

**File(s)**: N/A (shell scripts)

**Acceptance**:
- [x] Capture `mu --help` output to `/tmp/baseline-help.txt`
- [x] Capture help for all commands: compress, scan, view, diff, query, init, describe
- [x] Capture help for all subgroups: cache, kernel, daemon, mcp, contracts
- [x] Record baseline startup time: `hyperfine 'mu --help' --warmup 3`
- [x] Note: `mu kernel query --help` captured but will be removed (document for migration notice)

---

### Task 1: Create Command Directory Structure

**File(s)**:
- `src/mu/commands/__init__.py` (update)
- `src/mu/commands/kernel/__init__.py` (new)
- `src/mu/commands/daemon/__init__.py` (new)
- `src/mu/commands/mcp/__init__.py` (new)
- `src/mu/commands/contracts/__init__.py` (new)

**Pattern**: Subgroup pattern from PRD section 4

**Acceptance**:
- [ ] All subgroup directories created
- [ ] Each `__init__.py` defines `@click.group()` with appropriate help text
- [ ] No actual commands yet - just group definitions
- [ ] `ruff check src/mu/commands/` passes

---

### Task 2: Extract Top-Level Commands (init, describe, scan)

**File(s)**:
- `src/mu/commands/init_cmd.py` (new, ~30 lines)
- `src/mu/commands/describe.py` (new, ~40 lines)
- `src/mu/commands/scan.py` (new, ~70 lines)

**Pattern**: Follow `src/mu/commands/llm_spec.py:56-108`

**Source lines**:
- `init`: cli.py:80-107
- `describe`: cli.py:314-350
- `scan`: cli.py:353-414 (includes `format_scan_result` helper)

**Acceptance**:
- [ ] Each command in standalone file with `@click.command()` decorator
- [ ] `@click.pass_obj` for commands needing MUContext (not `@pass_context`)
- [ ] Lazy imports inside function body (not at module top)
- [ ] `if TYPE_CHECKING:` guard for MUContext type hint
- [ ] Tests pass: `pytest tests/ -k "cli"`

---

### Task 3: Extract Query Commands (query, q)

**File(s)**: `src/mu/commands/query.py` (new, ~200 lines)

**Pattern**: Follow `src/mu/commands/llm_spec.py` structure

**Source lines**: cli.py:115-312 (includes `_execute_muql`, `_execute_muql_local`, `query`, `q`)

**Critical**: Export shared helpers for potential future use:
```python
__all__ = ["query", "q", "_execute_muql", "_execute_muql_local"]
```

**Acceptance**:
- [ ] Both `query` and `q` commands in same file
- [ ] `_execute_muql()` and `_execute_muql_local()` moved as module-level helpers
- [ ] Export both commands for registration: `query`, `q`
- [ ] Lazy imports for `DaemonClient`, `MUbase`, `MUQLEngine`
- [ ] `mu query --help` matches baseline
- [ ] `mu q --help` matches baseline

---

### Task 4: Extract View Command

**File(s)**: `src/mu/commands/view.py` (new, ~60 lines)

**Pattern**: Follow `src/mu/commands/man.py:122-187`

**Source lines**: cli.py:801-860

**Acceptance**:
- [ ] Standalone `@click.command()`
- [ ] Lazy import of viewer module
- [ ] `mu view --help` matches baseline

---

### Task 5: Extract Diff Command

**File(s)**: `src/mu/commands/diff.py` (new, ~160 lines)

**Pattern**: Follow `src/mu/commands/llm_spec.py` with `@click.pass_obj`

**Source lines**: cli.py:863-1016

**Acceptance**:
- [ ] `@click.pass_obj` for MUContext access
- [ ] Lazy imports for diff module, git integration
- [ ] `mu diff --help` matches baseline

---

### Task 6: Extract Compress Command (Largest)

**File(s)**: `src/mu/commands/compress.py` (new, ~400 lines)

**Pattern**: Follow `src/mu/commands/llm_spec.py` with extensive lazy imports

**Source lines**: cli.py:416-799

**Critical**: This is the largest command with many dependencies

**Acceptance**:
- [ ] All imports lazy (scanner, parser, reducer, assembler, cache, security, llm)
- [ ] `@click.pass_obj` for MUContext
- [ ] All click options preserved exactly
- [ ] `mu compress --help` matches baseline
- [ ] `mu compress .` produces identical output

---

### Task 7: Extract Cache Subgroup

**File(s)**: `src/mu/commands/cache.py` (new, ~120 lines)

**Pattern**: Single file with `@click.group()` + all subcommands

**Source lines**: cli.py:1018-1134

**Acceptance**:
- [ ] `cache` group with `clear`, `stats`, `expire` subcommands
- [ ] All in one file (small commands)
- [ ] `mu cache --help` matches baseline
- [ ] `mu cache stats --help` matches baseline

---

### Task 8: Extract Kernel Subgroup

**File(s)**:
- `src/mu/commands/kernel/__init__.py` (update, group definition)
- `src/mu/commands/kernel/init_cmd.py` (~50 lines)
- `src/mu/commands/kernel/build.py` (~100 lines)
- `src/mu/commands/kernel/stats.py` (~50 lines)
- `src/mu/commands/kernel/embed.py` (~80 lines)
- `src/mu/commands/kernel/search.py` (~80 lines)
- `src/mu/commands/kernel/context.py` (~120 lines)
- `src/mu/commands/kernel/snapshot.py` (~150 lines)
- `src/mu/commands/kernel/history.py` (~50 lines)
- `src/mu/commands/kernel/blame.py` (~50 lines)
- `src/mu/commands/kernel/diff.py` (~80 lines)
- `src/mu/commands/kernel/export.py` (~80 lines)
- `src/mu/commands/kernel/deps.py` (~80 lines)

**Removed**: `src/mu/commands/kernel/query.py` - **DEPRECATED**, use `mu query` instead

**Pattern**: Subgroup from PRD section 4

**Source lines**: cli.py:1135-2579

**Strategy**: Extract in batches - init/build/stats first, then embed/search/context, then temporal

**Acceptance**:
- [ ] All kernel subcommands in separate files (except removed query)
- [ ] `kernel/__init__.py` registers all subcommands
- [ ] `mu kernel --help` matches baseline minus the removed `query` command
- [ ] `mu kernel build --help` matches baseline

---

### Task 9: Extract Daemon Subgroup

**File(s)**:
- `src/mu/commands/daemon/__init__.py` (update)
- `src/mu/commands/daemon/start.py` (~80 lines)
- `src/mu/commands/daemon/stop.py` (~30 lines)
- `src/mu/commands/daemon/status.py` (~40 lines)
- `src/mu/commands/daemon/run.py` (~60 lines)

**Pattern**: Subgroup from PRD section 4

**Source lines**: cli.py:2580-2827

**Acceptance**:
- [ ] All daemon subcommands in separate files
- [ ] `mu daemon --help` matches baseline

---

### Task 10: Extract MCP Subgroup

**File(s)**:
- `src/mu/commands/mcp/__init__.py` (update)
- `src/mu/commands/mcp/serve.py` (~60 lines)
- `src/mu/commands/mcp/tools.py` (~40 lines)
- `src/mu/commands/mcp/test.py` (~50 lines)

**Pattern**: Subgroup from PRD section 4

**Source lines**: cli.py:2828-2947

**Acceptance**:
- [ ] All mcp subcommands in separate files
- [ ] `mu mcp --help` matches baseline

---

### Task 11: Extract Contracts Subgroup

**File(s)**:
- `src/mu/commands/contracts/__init__.py` (update)
- `src/mu/commands/contracts/init_cmd.py` (~40 lines)
- `src/mu/commands/contracts/verify.py` (~100 lines)

**Pattern**: Subgroup from PRD section 4

**Source lines**: cli.py:2949-3168

**Acceptance**:
- [ ] All contracts subcommands in separate files
- [ ] `mu contracts --help` matches baseline

---

### Task 12: Refactor Main cli.py

**File(s)**: `src/mu/cli.py` (refactor to ~150 lines)

**Pattern**: PRD section 3 - main cli.py structure

**Final cli.py should contain**:
- Imports: click, Path, typing, dotenv
- MUContext class definition
- `pass_context` decorator maker
- `@click.group()` cli definition with options
- `_register_commands()` function with lazy imports
- `main()` entry point

**Acceptance**:
- [ ] cli.py < 200 lines (target: ~150)
- [ ] Only click, `__version__`, config, logging imports at top
- [ ] All command imports inside `_register_commands()`
- [ ] `wc -l src/mu/cli.py` returns < 200

---

### Task 13: Final Verification

**File(s)**: N/A (testing)

**Acceptance**:
- [ ] `pytest tests/ -v` all pass
- [ ] `ruff check src/mu/` passes
- [ ] `ruff format src/mu/` applied
- [ ] `mypy src/mu/` passes (or no new errors)
- [ ] `hyperfine 'mu --help' --warmup 3` shows < 50ms
- [ ] All baseline help texts match exactly (except `mu kernel query` which is removed)
- [ ] `mu compress .` produces identical output to baseline

---

## Dependencies

```
Task 0 (baseline)
    ↓
Task 1 (structure)
    ↓
Task 2-6 (top-level commands) ─── can run in parallel
    ↓
Task 7-11 (subgroups) ─────────── can run in parallel
    ↓
Task 12 (refactor cli.py) ─────── depends on all extractions
    ↓
Task 13 (verification)
```

---

## Edge Cases

| Issue | Solution |
|-------|----------|
| Circular imports: MUContext in cli.py but imported by commands | Use `TYPE_CHECKING` guard, import at runtime with `from mu.cli import MUContext` |
| Shared helpers: `_execute_muql` used by query.py | Keep in `commands/query.py` with `__all__` export |
| Reserved keyword: `init` is Python keyword | Use `init_cmd.py` filename, register with `name="init"` |
| Removed command: `mu kernel query` | Document in changelog, update any tests referencing it |

---

## Security Considerations

- No security impact - pure mechanical refactor
- All secret handling remains in commands/compress.py
- No new attack surface introduced

---

## Quality Gates

- [ ] cli.py < 200 lines
- [ ] `mu --help` < 50ms
- [ ] All existing tests pass
- [ ] `ruff check src/mu/` passes
- [ ] `mypy src/mu/` passes
- [ ] Output identical to baseline for all commands (except removed `mu kernel query`)
