# MU Technical Specification v1.0

> Complete technical specification for the MU semantic compression tool.
>
> **Status:** Implemented
> **Last Updated:** December 2024
> **Author:** Winston (Architect Agent) + Yavor Kangalov

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Technology Stack](#technology-stack)
4. [Pipeline Components](#pipeline-components)
5. [Error Handling](#error-handling)
6. [Security & Privacy](#security--privacy)
7. [Configuration](#configuration)
8. [LLM Integration](#llm-integration)
9. [Caching Strategy](#caching-strategy)
10. [Output Format Specification](#output-format-specification)
11. [Implementation Roadmap](#implementation-roadmap)
12. [Performance Requirements](#performance-requirements)
13. [Testing Strategy](#testing-strategy)

---

## Overview

### What is MU?

MU (Machine Understanding) is a semantic compression format that translates codebases into token-efficient representations optimized for LLM comprehension. It enables AI systems to understand entire software architectures by compressing thousands of lines of code into dense, meaningful summaries.

### Design Principles

| Principle | Description |
|-----------|-------------|
| **Token Density** | Every character earns its place. No syntactic noise. |
| **Semantic Preservation** | Architectural meaning survives compression (validated via benchmark suite). |
| **LLM-Native** | Optimized for how language models process and reason about code. |
| **Language Agnostic** | One output format regardless of source language. |
| **Fail Gracefully** | Partial output is better than no output. |
| **Privacy First** | Local-only mode available; no code leaves machine without explicit consent. |

---

## Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        MU CLI                                    │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐     │
│  │ Scanner  │ → │  Parser  │ → │ Reducer  │ → │Assembler │     │
│  │ (Triage) │   │(Tree-sit)│   │ (Rules)  │   │ (Stitch) │     │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘     │
│       ↓              ↓              ↓              ↓            │
│  [manifest]      [AST data]    [MU chunks]    [output.mu]      │
├─────────────────────────────────────────────────────────────────┤
│                     Support Services                             │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐     │
│  │  Cache   │   │ LLM Pool │   │  Config  │   │  Logger  │     │
│  │ Manager  │   │ (Multi)  │   │ Manager  │   │          │     │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Input:** Source code directory or file
2. **Scanner:** Produces `manifest.json` with file list, languages detected, structure
3. **Parser:** Produces AST data per file using Tree-sitter
4. **Reducer:** Applies transformation rules, optionally calls LLM for complex bodies
5. **Assembler:** Stitches file-level MU, builds cross-file relationships
6. **Output:** `.mu` file (or `.json`/`.md` variants)

---

## Technology Stack

### Core Stack (MVP)

| Component | Technology | Rationale |
|-----------|------------|-----------|
| **Language** | Python 3.11+ | Fast iteration, rich ecosystem, easy distribution |
| **CLI Framework** | Click | Mature, well-documented, supports complex CLIs |
| **Parser** | Tree-sitter | Language-agnostic AST, incremental parsing, 50+ grammars |
| **LLM Client** | LiteLLM | Unified interface for Anthropic, OpenAI, Ollama, etc. |
| **Caching** | diskcache | Simple file-based cache with TTL support |
| **Config** | Pydantic + TOML | Type-safe config with human-readable files |
| **Testing** | pytest + hypothesis | Property-based testing for parser edge cases |

### Why Not Rust for MVP?

Rust was considered but deferred because:
- Python is fast enough for CLI tools (not a hot loop)
- Tree-sitter has excellent Python bindings
- Distribution via `pip` is simpler than cross-compiling Rust binaries
- Rewrites are expensive; prove the concept first

**Future:** If profiling shows Python is the bottleneck (unlikely), critical paths can be rewritten in Rust and called via PyO3.

---

## Pipeline Components

### 1. Scanner (Triage)

**Responsibility:** Walk filesystem, identify processable files, filter noise.

**Input:** Directory path
**Output:** `manifest.json`

```json
{
  "version": "1.0",
  "root": "/path/to/codebase",
  "scanned_at": "2024-12-06T10:00:00Z",
  "files": [
    {
      "path": "src/auth/service.py",
      "language": "python",
      "size_bytes": 4521,
      "hash": "sha256:abc123..."
    }
  ],
  "stats": {
    "total_files": 150,
    "total_lines": 45000,
    "languages": {"python": 80, "typescript": 50, "yaml": 20}
  },
  "skipped": [
    {"path": "node_modules/", "reason": "default_ignore"},
    {"path": "src/legacy.vb", "reason": "unsupported_language"}
  ]
}
```

**Default Ignore Patterns:**
```
node_modules/
.git/
__pycache__/
*.pyc
.venv/
venv/
dist/
build/
*.min.js
*.bundle.js
*.lock
```

**Language Detection:** File extension mapping + shebang detection for extensionless files.

### 2. Parser

**Responsibility:** Extract AST from source files using Tree-sitter.

**Input:** Source file
**Output:** Structured AST data

**Supported Languages:**

| Language | Grammar | Status |
|----------|---------|--------|
| Python | tree-sitter-python | ✅ Implemented |
| TypeScript/JavaScript | tree-sitter-typescript | ✅ Implemented |
| C# | tree-sitter-c-sharp | ✅ Implemented |
| Go | tree-sitter-go | ✅ Implemented |
| Rust | tree-sitter-rust | ✅ Implemented |
| Java | tree-sitter-java | ✅ Implemented |

**Extracted Elements:**
- Module/namespace declarations
- Class definitions with inheritance
- Function/method signatures
- Import statements (explicit only for MVP)
- Type annotations where available
- Decorators/attributes

**Unsupported Language Handling:**
- Log warning to manifest
- Skip file (do not fail entire pipeline)
- Include in `skipped` array with reason

### 3. Reducer

**Responsibility:** Transform AST into MU format, apply compression rules.

**Transformation Rules:**

| Category | Action | Example |
|----------|--------|---------|
| **STRIP** | Imports | Unless unique external dep |
| **STRIP** | Boilerplate | Getters, setters, constructors |
| **STRIP** | Defensive code | Standard null checks, try/catch |
| **STRIP** | Verbose logging | `logger.info()` calls |
| **STRIP** | Object mapping | `x.A = y.A` blocks |
| **STRIP** | Syntax keywords | async/await, public/private |
| **KEEP** | Signatures | Function inputs/outputs |
| **KEEP** | Dependencies | @deps list mandatory |
| **KEEP** | State mutations | DB writes, file uploads (=>) |
| **KEEP** | Control flow | Loops, recursion, branching |
| **KEEP** | External I/O | API calls, queues, 3rd party |
| **KEEP** | Business rules | Invariants, guards, validation |
| **KEEP** | Transactions | Atomic ops, rollback behavior |

**LLM Summarization (Optional):**

When `--llm` flag is set and function body exceeds complexity threshold:
1. Send function body to configured LLM
2. Request 3-5 bullet point summary
3. Cache response keyed by content hash
4. Insert as `:: summary:` annotation

**Complexity Threshold:** Functions with >20 AST nodes or >3 control flow branches.

### 4. Assembler

**Responsibility:** Stitch file-level MU into cohesive codebase representation.

**Cross-File Resolution (MVP Scope):**

For MVP, only **explicit imports** are resolved:
- Python: `import x`, `from x import y`
- TypeScript: `import { x } from 'y'`
- C#: `using Namespace;`

**Deferred to Phase 2:**
- Dynamic imports (`importlib`, dynamic `import()`)
- Dependency injection resolution
- Reflection-based dependencies

**Output Structure:**
```
# MU v1.0 | generated 2024-12-06T10:00:00Z | source: /path/to/codebase

## Module Graph
!auth -> !database, !logging
!api -> !auth, !models

## Modules

!module auth
@deps [$DbContext, $Logger, $JwtService]
...

!module api
@deps [$AuthService, $UserModel]
...
```

---

## Error Handling

### Philosophy

**Partial output is better than no output.** MU should never crash entirely due to a single bad file.

### Failure Modes

| Scenario | Behavior | User Feedback |
|----------|----------|---------------|
| **Unparseable file** | Skip file, continue | Warning in manifest + stderr |
| **Unsupported language** | Skip file, continue | Info in manifest |
| **LLM API timeout** | Retry 2x, then skip summarization | Warning, proceed without summary |
| **LLM API rate limit** | Exponential backoff (max 60s) | Progress indicator shows waiting |
| **LLM API auth failure** | Fail fast with clear message | Exit code 1, actionable error |
| **Invalid config file** | Fail fast with validation errors | Exit code 1, show what's wrong |
| **Out of memory** | Stream processing, fail gracefully | Error with file that caused OOM |
| **Disk full** | Fail fast | Clear error message |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Configuration/auth error (user fixable) |
| 2 | Partial success (some files skipped) |
| 3 | Fatal error (unexpected crash) |

### Error Output Format

```json
{
  "success": false,
  "exit_code": 2,
  "processed": 148,
  "skipped": 2,
  "errors": [
    {
      "file": "src/legacy.py",
      "error": "parse_error",
      "message": "Syntax error at line 45: unexpected indent",
      "recoverable": true
    }
  ]
}
```

---

## Security & Privacy

### Threat Model

| Threat | Mitigation |
|--------|------------|
| **Secrets in source code** | Secret detection + redaction |
| **Code sent to external LLM** | Local-only mode, explicit consent |
| **Malicious input files** | Sandboxed parsing, size limits |
| **Dependency confusion** | Pin all dependencies, verify checksums |

### Secret Detection

MU includes a built-in secret scanner that detects and redacts:

- API keys (AWS, GCP, Azure, Stripe, etc.)
- Private keys (RSA, SSH, PGP)
- Passwords in config files
- JWT tokens
- Database connection strings

**Behavior:**
```
# Original
api_key = "sk-live-abc123xyz789"

# MU Output
@config api_key :: REDACTED:api_key_pattern
```

**Disable with:** `--no-redact` (for trusted environments)

### Privacy Modes

| Mode | Flag | LLM Calls | Data Sent |
|------|------|-----------|-----------|
| **Local Only** | `--local` | Ollama only | Nothing external |
| **Redacted Cloud** | (default) | Cloud LLMs | Secrets redacted |
| **Full Cloud** | `--no-redact` | Cloud LLMs | Everything (with warning) |

### Local-Only Mode

```bash
mu compress ./src --local --llm-provider ollama --llm-model codellama
```

In local mode:
- No network calls except to localhost
- Requires Ollama running locally
- Full functionality, zero data leakage

---

## Configuration

### Configuration File

MU looks for configuration in this order:
1. CLI flags (highest priority)
2. `.murc.toml` in current directory
3. `.murc.toml` in home directory
4. Built-in defaults (lowest priority)

### Configuration Schema

```toml
# .murc.toml

[mu]
version = "1.0"

[scanner]
ignore = [
  "node_modules/",
  ".git/",
  "**/*.test.ts",
  "**/__tests__/**"
]
include_hidden = false
max_file_size_kb = 1000

[parser]
languages = ["python", "typescript", "csharp"]
# "auto" = detect from extensions
# explicit list = only process these

[reducer]
strip_comments = true
strip_docstrings = false  # Keep for semantic value
complexity_threshold = 20  # AST nodes before LLM summarization

[llm]
enabled = false  # Must explicitly enable
provider = "anthropic"  # anthropic | openai | ollama
model = "claude-3-haiku-20240307"
timeout_seconds = 30
max_retries = 2

[llm.ollama]
base_url = "http://localhost:11434"
model = "codellama"

[security]
redact_secrets = true
secret_patterns = "default"  # or path to custom patterns file

[output]
format = "mu"  # mu | json | markdown
include_line_numbers = false
include_file_hashes = true

[cache]
enabled = true
directory = ".mu-cache"
ttl_hours = 168  # 1 week
```

### Environment Variables

All config options can be overridden via environment variables:

```bash
MU_LLM_PROVIDER=openai
MU_LLM_MODEL=gpt-4o-mini
MU_SECURITY_REDACT_SECRETS=false
```

Pattern: `MU_<SECTION>_<KEY>` in uppercase.

---

## LLM Integration

### Multi-Provider Architecture

MU uses LiteLLM as a unified interface to support multiple LLM providers:

```python
# Internal architecture
class LLMPool:
    providers: dict[str, LLMProvider]

    def summarize(self, code: str, context: str) -> str:
        provider = self.get_provider()
        return provider.complete(self.build_prompt(code, context))
```

### Supported Providers

| Provider | Models | Use Case |
|----------|--------|----------|
| **Anthropic** | claude-3-haiku, claude-3-sonnet | Best quality, cloud |
| **OpenAI** | gpt-4o-mini, gpt-4o | Alternative cloud |
| **Ollama** | codellama, deepseek-coder | Local, private |
| **OpenRouter** | Various | Fallback, cost optimization |

### Provider Configuration

```bash
# Anthropic (default)
export ANTHROPIC_API_KEY=sk-ant-...
mu compress ./src --llm

# OpenAI
export OPENAI_API_KEY=sk-...
mu compress ./src --llm --llm-provider openai

# Ollama (local)
mu compress ./src --llm --llm-provider ollama --local
```

### Prompt Templates

**Function Summarization:**
```
You are summarizing code for an AI-readable format called MU.

Given this function:
```{language}
{function_code}
```

Provide a 3-5 bullet point summary covering:
- Primary purpose
- Key inputs and outputs
- Important side effects (DB writes, API calls, state mutations)
- Business rules or invariants

Be extremely concise. Each bullet should be <15 words.
```

### Cost Estimation

Before LLM calls, MU estimates token usage:

```
Estimated LLM usage for ./src:
- Files requiring summarization: 23
- Estimated input tokens: ~45,000
- Estimated cost: ~$0.02 (Claude Haiku)

Proceed? [y/N]
```

Skip with `--yes` flag for CI/CD.

---

## Caching Strategy

### Cache Architecture

```
.mu-cache/
├── manifest.json          # Cache metadata
├── files/
│   ├── abc123.mu          # Cached MU output (keyed by content hash)
│   └── def456.mu
└── llm/
    ├── xyz789.json        # Cached LLM responses
    └── ...
```

### Cache Keys

| Data Type | Key Strategy |
|-----------|--------------|
| **File MU output** | SHA-256 of file content |
| **LLM responses** | SHA-256 of prompt + model name |
| **Cross-file graph** | Hash of all file hashes |

### Cache Invalidation

- **Automatic:** File content change invalidates that file's cache
- **Manual:** `mu cache clear`
- **TTL:** Default 1 week, configurable

### Incremental Processing

On subsequent runs:
1. Compute file hashes
2. Compare to cached manifest
3. Only process changed files
4. Rebuild cross-file graph if any file changed

**Performance impact:** 10x faster for unchanged codebases.

---

## Output Format Specification

### MU Format v1.0

#### Header

```
# MU v1.0
# generated: 2024-12-06T10:00:00Z
# source: /path/to/codebase
# files: 150
# compression: 87%
```

#### Sigil Reference

| Sigil | Meaning | Example |
|-------|---------|---------|
| `!` | Module/Service | `!service AuthService` |
| `$` | Entity/Data Shape | `$User { id: uuid, email: str }` |
| `#` | Function/Logic Block | `#CreateUser(email) -> Result<$User>` |
| `@` | Metadata/Config/Deps | `@deps [$DbContext, $Logger]` |
| `?` | Conditional/Branch | `? not_found -> err(404)` |
| `::` | Annotation/Invariant | `:: guard: status != PAID` |

#### Operators

| Operator | Meaning | Example |
|----------|---------|---------|
| `->` | Pure data flow | `#func(x) -> Result<Y>` |
| `=>` | State mutation | `status => PAID` |
| `\|` | Match/switch case | `\| "US" -> 1.5%` |
| `~` | Iteration/loop | `~ for each invoice` |

#### Special Annotations

| Annotation | Meaning |
|------------|---------|
| `!transaction: atomic` | Block uses DB transactions |
| `!warning: <type>` | Flags race conditions, O(n^2), side effects |
| `:: guard: <cond>` | Business rule precondition |
| `:: NOTE: <text>` | Architectural observation |
| `:: REDACTED: <type>` | Secret was removed |
| `:: SKIP: <reason>` | Section couldn't be processed |

### Shell-Safe Mode

When outputting to terminal or piping, use `--shell-safe` to escape sigils:

```bash
mu compress ./src --shell-safe | claude "analyze this"
```

Escaping: `#` -> `\#`, `$` -> `\$`, etc.

### JSON Output

```json
{
  "version": "1.0",
  "metadata": {
    "generated": "2024-12-06T10:00:00Z",
    "source": "/path/to/codebase",
    "compression_ratio": 0.87
  },
  "modules": [
    {
      "name": "AuthService",
      "type": "service",
      "dependencies": ["DbContext", "Logger"],
      "functions": [...]
    }
  ],
  "entities": [...],
  "relationships": [...]
}
```

---

## Implementation Status

All planned features have been implemented:

### Core CLI
- [x] Project setup (pyproject.toml, structure)
- [x] Configuration system (Pydantic models, TOML loading)
- [x] Error handling framework
- [x] Logging setup with Rich
- [x] Filesystem walker with ignore patterns
- [x] Language detection (7 languages)
- [x] Manifest generation
- [x] CLI commands (`mu scan`, `mu compress`, `mu view`, `mu diff`, `mu cache`, `mu init`)

### Parser
- [x] Tree-sitter integration
- [x] Python extractor
- [x] TypeScript/JavaScript extractor
- [x] C# extractor
- [x] Go extractor
- [x] Rust extractor
- [x] Java extractor
- [x] Dynamic import detection

### Reducer & Assembler
- [x] Transformation rules engine
- [x] Sigil generation
- [x] MU format output
- [x] Cross-file import resolution
- [x] Module graph generation
- [x] JSON/Markdown/MU export

### LLM & Caching
- [x] LiteLLM integration
- [x] Anthropic provider
- [x] OpenAI provider
- [x] Ollama provider
- [x] OpenRouter provider
- [x] Prompt templates
- [x] Cost estimation
- [x] File hash caching
- [x] LLM response caching
- [x] Incremental processing

### Security & Privacy
- [x] Secret detection patterns (AWS, GCP, Azure, Stripe, etc.)
- [x] Redaction logic
- [x] Local-only mode (`--local`)
- [x] Privacy documentation

### Viewer & Output
- [x] Terminal renderer with syntax highlighting
- [x] HTML export
- [x] Markdown export
- [x] MU format rendering

### Advanced Features
- [x] `mu diff` - semantic diff between git refs
- [x] VS Code extension (syntax highlighting, commands)
- [x] GitHub Action for CI integration

---

## Performance Requirements

### Benchmarks

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Scan speed** | <100ms for 10k files | Time to generate manifest |
| **Parse speed** | <500ms per 1k lines | Without LLM |
| **Full pipeline** | <5s for 50k lines | Without LLM |
| **With LLM** | <30s for 50k lines | Parallel LLM calls |
| **Memory** | <500MB for 100k lines | Peak RSS |
| **Compression ratio** | >80% | Tokens reduced |

### Optimization Strategies

1. **Parallel file processing:** Use `concurrent.futures` for parsing
2. **Streaming output:** Don't hold entire AST in memory
3. **Lazy LLM calls:** Only summarize when complexity threshold exceeded
4. **Connection pooling:** Reuse HTTP connections for LLM APIs

---

## Testing Strategy

### Test Categories

| Category | Tools | Coverage Target |
|----------|-------|-----------------|
| **Unit tests** | pytest | Core logic, transformations |
| **Property tests** | hypothesis | Parser edge cases |
| **Integration tests** | pytest | Full pipeline |
| **Snapshot tests** | pytest-snapshot | Output format stability |
| **Benchmark tests** | pytest-benchmark | Performance regression |

### Test Fixtures

Maintain a `fixtures/` directory with:
- Small reference codebases in each supported language
- Expected MU output for each fixture
- Edge case files (unicode, huge functions, deeply nested)

### Semantic Preservation Benchmark

**The "50 Questions" Test:**

For each reference codebase, define 50 architectural questions:
1. "What services does AuthService depend on?"
2. "Which functions mutate database state?"
3. "What is the data shape of User?"
...

**Pass criteria:** MU output must enable an LLM to answer all 50 questions correctly.

### CI Pipeline

```yaml
# .github/workflows/ci.yml
jobs:
  test:
    - Unit tests
    - Integration tests
    - Snapshot tests

  benchmark:
    - Performance tests
    - Memory profiling

  quality:
    - Type checking (mypy)
    - Linting (ruff)
    - Security scan (bandit)
```

---

## Appendix A: CLI Reference

```
mu - Machine Understanding CLI

USAGE:
    mu <COMMAND> [OPTIONS]

COMMANDS:
    init        Initialize .murc.toml with sensible defaults
    scan        Analyze codebase structure
    compress    Generate MU output
    view        Render MU in human-readable format
    diff        Show semantic diff between branches
    cache       Manage cache

GLOBAL OPTIONS:
    -v, --verbose    Increase verbosity
    -q, --quiet      Suppress non-error output
    --config PATH    Path to config file
    --version        Show version

EXAMPLES:
    mu init
    mu scan ./src
    mu compress ./src --output system.mu
    mu compress ./src --llm --local
    mu view system.mu --format markdown
    mu diff main feature-branch
```

---

## Appendix B: Migration from PRD

| PRD Item | Spec Change | Rationale |
|----------|-------------|-----------|
| Python/Rust hybrid | Python only for v1 | Avoid premature optimization |
| 7-day timeline | 10-day timeline | Added Day 0 + security phase |
| Cross-file resolution | MVP: explicit imports only | Reduce scope, defer complexity |
| No caching mentioned | Full caching system | Critical for large codebases |
| No security section | Comprehensive security model | Required for enterprise adoption |
| Single LLM provider | Multi-provider support | User choice, offline capability |

---

---

*This specification documents the implemented MU system. See [CONTRIBUTING.md](../CONTRIBUTING.md) for development guidelines.*
