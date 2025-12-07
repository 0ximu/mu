# PRD: CLI Refactor - Split God Object

## Overview

**Project:** MU CLI Refactor
**Priority:** P1 (post-bug-fixes)
**Effort:** Medium (4-6 hours)
**Risk:** Low (mechanical refactor, no behavior changes)

## Problem Statement

`src/mu/cli.py` is a 3,114-line god object containing all CLI commands. This causes:

1. **Slow startup** - Every command loads all 3K lines (~120ms overhead)
2. **Merge conflicts** - Multiple contributors touching same file
3. **Poor discoverability** - Hard to find specific command logic
4. **Test complexity** - Must mock entire CLI to test one command

## Goals

| Goal | Metric | Target |
|------|--------|--------|
| Improve startup time | `time mu --help` | < 50ms (from 135ms) |
| Enable parallel development | Separate files per command | 10+ files |
| Improve testability | Direct command function imports | 100% commands testable in isolation |
| Maintain behavior | All existing tests pass | 0 regressions |

## Non-Goals

- Adding new commands
- Changing command signatures or behavior
- Refactoring internals of commands (just moving them)
- Performance optimization of command execution

## Technical Design

### Current Structure

```
src/mu/
├── cli.py              # 3,114 lines - EVERYTHING
└── commands/
    ├── __init__.py     # Empty
    ├── llm_spec.py     # Only llm spec logic
    └── man.py          # Only man page logic
```

### Target Structure

```
src/mu/
├── cli.py              # ~150 lines - group definition, shared options, imports
└── commands/
    ├── __init__.py     # Exports all command groups
    ├── compress.py     # compress command (~200 lines)
    ├── scan.py         # scan command (~50 lines)
    ├── view.py         # view command (~100 lines)
    ├── diff.py         # diff command (~150 lines)
    ├── query.py        # query/q commands (~100 lines)
    ├── kernel/
    │   ├── __init__.py # kernel subgroup
    │   ├── build.py    # kernel build
    │   ├── query.py    # kernel query (muql)
    │   └── export.py   # kernel export
    ├── contracts/
    │   ├── __init__.py # contracts subgroup
    │   ├── init.py     # contracts init
    │   └── verify.py   # contracts verify
    ├── daemon/
    │   ├── __init__.py # daemon subgroup
    │   ├── start.py
    │   ├── stop.py
    │   ├── status.py
    │   └── run.py
    ├── mcp/
    │   ├── __init__.py # mcp subgroup
    │   ├── serve.py
    │   └── tools.py
    ├── cache.py        # cache subgroup (~80 lines)
    ├── init.py         # init command (~50 lines)
    ├── describe.py     # describe command (~50 lines)
    └── man.py          # existing, keep as-is
```

### Implementation Pattern

Each command file follows this pattern:

```python
# src/mu/commands/compress.py
"""MU compress command - transform source to MU format."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from mu.cli import MUContext

# Lazy imports inside function to speed up CLI startup
# DO NOT import heavy modules at top level


@click.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("-o", "--output", type=click.Path(path_type=Path), help="Output file")
@click.option("--llm", is_flag=True, help="Enable LLM summarization")
# ... other options
@click.pass_obj
def compress(ctx: MUContext, path: Path, output: Path | None, llm: bool, ...) -> None:
    """Compress source code into MU format."""
    # Lazy imports for speed
    from mu.assembler import assemble
    from mu.scanner import scan_codebase
    # ... rest of implementation
```

Main CLI becomes:

```python
# src/mu/cli.py
"""MU CLI - Machine Understanding command-line interface."""

import click

from mu import __version__

# Lazy command imports
def register_commands(cli: click.Group) -> None:
    """Register all commands lazily."""
    from mu.commands.compress import compress
    from mu.commands.scan import scan
    from mu.commands.view import view
    from mu.commands.diff import diff
    from mu.commands.query import query, q
    from mu.commands.init import init
    from mu.commands.describe import describe
    from mu.commands.cache import cache
    from mu.commands.kernel import kernel
    from mu.commands.contracts import contracts
    from mu.commands.daemon import daemon
    from mu.commands.mcp import mcp

    cli.add_command(compress)
    cli.add_command(scan)
    cli.add_command(view)
    cli.add_command(diff)
    cli.add_command(query)
    cli.add_command(q)
    cli.add_command(init)
    cli.add_command(describe)
    cli.add_command(cache)
    cli.add_command(kernel)
    cli.add_command(contracts)
    cli.add_command(daemon)
    cli.add_command(mcp)


class MUContext:
    """Shared context for CLI commands."""
    # ... keep as-is


@click.group()
@click.option("-v", "--verbose", is_flag=True)
@click.option("-q", "--quiet", is_flag=True)
@click.option("--config", type=click.Path(exists=True, path_type=Path))
@click.version_option(__version__)
@click.pass_context
def cli(ctx: click.Context, verbose: bool, quiet: bool, config: Path | None) -> None:
    """MU - Machine Understanding: Semantic compression for AI-native development."""
    ctx.ensure_object(MUContext)
    # ... setup logic


# Register commands after cli is defined
register_commands(cli)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
```

## Migration Steps

### Phase 1: Extract Commands (No Behavior Change)

1. Create command file structure
2. Move each command function to its file
3. Update imports in `cli.py`
4. Run full test suite - must pass 100%

### Phase 2: Lazy Loading

1. Convert top-level imports to function-level imports in each command
2. Measure startup time improvement
3. Run full test suite

### Phase 3: Cleanup

1. Remove dead code from `cli.py`
2. Add `__all__` exports to command modules
3. Update any documentation referencing cli.py internals

## Command Inventory

Commands to extract from `cli.py`:

| Command | Type | Est. Lines | Dependencies |
|---------|------|------------|--------------|
| `compress` | command | ~200 | scanner, parser, reducer, assembler, security, cache |
| `scan` | command | ~50 | scanner |
| `view` | command | ~100 | viewer |
| `diff` | command | ~150 | diff module, git |
| `query` | command | ~80 | kernel.muql |
| `q` | alias | ~5 | query |
| `init` | command | ~50 | config |
| `describe` | command | ~50 | describe module |
| `kernel` | group | - | - |
| `kernel build` | command | ~100 | kernel.builder |
| `kernel query` | command | ~80 | kernel.muql |
| `kernel export` | command | ~60 | kernel.export |
| `contracts` | group | - | - |
| `contracts init` | command | ~40 | contracts |
| `contracts verify` | command | ~100 | contracts.verifier |
| `cache` | group | - | - |
| `cache stats` | command | ~30 | cache |
| `cache clear` | command | ~20 | cache |
| `cache expire` | command | ~20 | cache |
| `daemon` | group | - | - |
| `daemon start` | command | ~80 | daemon |
| `daemon stop` | command | ~30 | daemon |
| `daemon status` | command | ~40 | daemon |
| `daemon run` | command | ~60 | daemon |
| `mcp` | group | - | - |
| `mcp serve` | command | ~60 | mcp |
| `mcp tools` | command | ~40 | mcp |

## Acceptance Criteria

- [ ] `cli.py` is < 200 lines
- [ ] All commands in separate files under `commands/`
- [ ] `mu --help` < 50ms
- [ ] All existing tests pass
- [ ] No changes to CLI interface (commands, options, help text)
- [ ] Each command file has docstring explaining its purpose

## Testing Strategy

1. **Before refactor:** Capture output of all commands
   ```bash
   mu --help > baseline/help.txt
   mu compress --help > baseline/compress-help.txt
   # ... etc for all commands
   ```

2. **After refactor:** Compare output matches exactly
   ```bash
   mu --help | diff - baseline/help.txt
   ```

3. **Run existing test suite**
   ```bash
   pytest tests/ -v
   ```

4. **Measure startup time**
   ```bash
   hyperfine 'mu --help' --warmup 3
   ```

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Circular imports | Medium | High | Use TYPE_CHECKING guards, lazy imports |
| Missing command registration | Low | High | Test suite catches this |
| Import order issues | Low | Medium | Explicit imports, no star imports |

## Open Questions

None - this is a mechanical refactor with clear patterns.

## Appendix: Files to Create

```
commands/
├── __init__.py
├── compress.py
├── scan.py
├── view.py
├── diff.py
├── query.py
├── init.py
├── describe.py
├── cache.py
├── kernel/
│   ├── __init__.py
│   ├── build.py
│   ├── query.py
│   └── export.py
├── contracts/
│   ├── __init__.py
│   ├── init_cmd.py    # 'init' is reserved, use init_cmd
│   └── verify.py
├── daemon/
│   ├── __init__.py
│   ├── start.py
│   ├── stop.py
│   ├── status.py
│   └── run.py
└── mcp/
    ├── __init__.py
    ├── serve.py
    └── tools.py
```

Total: 24 new files
