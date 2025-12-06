# MU - Claude Code Kickoff Document

> **Status**: ARCHIVED - Implementation Complete
>
> This document was the original kickoff specification used to build MU. All features described here have been implemented. For current documentation, see:
> - [README.md](../README.md) - User guide
> - [MU-TECH-SPEC.md](./MU-TECH-SPEC.md) - Technical specification
> - [CONTRIBUTING.md](../CONTRIBUTING.md) - Development guide
>
> **Author**: Yavor Kangalov (0ximu)
> **Original Date**: December 2024

---

## Project Overview

**MU (Machine Understanding)** is a semantic compression format that translates codebases into token-efficient representations optimized for LLM comprehension.

### The One-Liner
```
Any codebase → MU translator → 80-95% token reduction → LLM understands entire architecture
```

### Why This Exists
- LLMs choke on large codebases (500k+ lines exceed context windows)
- 90% of code is boilerplate, patterns, syntactic noise
- MU preserves meaning, discards syntax
- Validated: 93% compression on real C# services with 100% semantic preservation

---

## Technology Stack

| Component | Technology | Why |
|-----------|------------|-----|
| Language | Python 3.11+ | Fast iteration, rich ecosystem, easy pip distribution |
| CLI Framework | Click | Mature, well-documented, supports complex CLIs |
| Parser | Tree-sitter | Language-agnostic AST, 50+ grammars, battle-tested |
| LLM Client | LiteLLM | Unified interface for Anthropic/OpenAI/Ollama |
| Caching | diskcache | Simple file-based cache with TTL |
| Config | Pydantic + TOML | Type-safe config, human-readable files |
| Testing | pytest + hypothesis | Property-based testing for parser edge cases |

---

## Project Structure

```
mu/
├── pyproject.toml
├── README.md
├── .murc.toml.example
├── src/
│   └── mu/
│       ├── __init__.py
│       ├── __main__.py           # Entry point
│       ├── cli.py                # Click CLI definitions
│       ├── config.py             # Pydantic config models
│       ├── errors.py             # Error types and handling
│       ├── scanner/
│       │   ├── __init__.py
│       │   ├── scanner.py        # Filesystem walker
│       │   ├── language.py       # Language detection
│       │   └── ignore.py         # Ignore pattern matching
│       ├── parser/
│       │   ├── __init__.py
│       │   ├── base.py           # Abstract extractor
│       │   ├── python.py         # Python extractor
│       │   ├── typescript.py     # TypeScript extractor
│       │   └── csharp.py         # C# extractor
│       ├── reducer/
│       │   ├── __init__.py
│       │   ├── rules.py          # Transformation rules
│       │   ├── generator.py      # MU syntax generator
│       │   └── sigils.py         # Sigil definitions
│       ├── assembler/
│       │   ├── __init__.py
│       │   ├── assembler.py      # Stitches file-level MU
│       │   └── graph.py          # Cross-file relationships
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── pool.py           # Multi-provider LLM pool
│       │   ├── prompts.py        # Prompt templates
│       │   └── cost.py           # Cost estimation
│       ├── security/
│       │   ├── __init__.py
│       │   ├── secrets.py        # Secret detection
│       │   └── patterns.py       # Detection patterns
│       ├── cache/
│       │   ├── __init__.py
│       │   └── manager.py        # Cache operations
│       └── output/
│           ├── __init__.py
│           ├── mu.py             # .mu format writer
│           ├── json.py           # JSON format writer
│           └── markdown.py       # Markdown format writer
├── tests/
│   ├── conftest.py
│   ├── fixtures/                 # Test codebases
│   ├── test_scanner.py
│   ├── test_parser.py
│   ├── test_reducer.py
│   └── test_integration.py
└── fixtures/
    ├── python/                   # Reference Python codebase
    ├── typescript/               # Reference TS codebase
    └── csharp/                   # Reference C# codebase
```

---

## MU Format Specification

### Sigils
| Sigil | Meaning | Example |
|-------|---------|---------|
| `!` | Module/Service | `!service AuthService` |
| `$` | Entity/Data Shape | `$User { id: uuid, email: str }` |
| `#` | Function/Logic Block | `#CreateUser(email) -> Result<$User>` |
| `@` | Metadata/Config/Deps | `@deps [$DbContext, $Logger]` |
| `?` | Conditional/Branch | `? not_found -> err(404)` |
| `::` | Annotation/Invariant | `:: guard: status != PAID` |

### Operators
| Operator | Meaning | Example |
|----------|---------|---------|
| `->` | Pure data flow | `#func(x) -> Result<Y>` |
| `=>` | State mutation | `status => PAID` |
| `\|` | Match/switch case | `\| "US" -> 1.5%` |
| `~` | Iteration/loop | `~ for each invoice` |

### Special Annotations
| Annotation | Meaning |
|------------|---------|
| `!transaction: atomic` | Block uses DB transactions with rollback |
| `!warning: <type>` | Flags race conditions, O(n²), side effects |
| `:: guard: <cond>` | Business rule that must be true |
| `:: NOTE: <text>` | Architectural observation |
| `:: REDACTED: <type>` | Secret was removed |
| `:: SKIP: <reason>` | Section couldn't be processed |

### Example MU Output
```mu
# MU v1.0 | generated 2024-12-07T10:00:00Z | source: ./src

!service AuthService
@deps [$DbContext, $Logger, $JwtService]
@const TOKEN_TTL = 30_days

#Login(email, password) -> Result<$Token>
  1. fetch $User by email
     ? not_found -> err(404)
  2. verify(password, $User.hash)
     ? false -> err(401)
  3. mint_token($User) -> $Token
     :: invariant: token.exp > now
     :: side_effect: log_login_event
  4. return $Token

#CreateUser(req) -> Result<$User>
  1. validate(req)
     :: guard: email is unique
  2. $User = { email, hash: bcrypt(password), created: now }
  3. _db.Users.Add($User) => persist
  4. return $User
```

---

## Transformation Rules

### STRIP (Noise)
- **Imports**: Unless unique external dependency
- **Boilerplate**: Getters, setters, constructors, DI wiring
- **Defensive code**: Standard null checks, try/catch (summarize as `:: guard`)
- **Verbose logging**: `logger.info()` calls (keep only audit/security)
- **Object mapping**: `x.A = y.A` blocks (summarize as `map(x) -> y`)
- **Syntax keywords**: async/await, public/private, static (implied)

### KEEP (Signal)
- **Signatures**: Function inputs/outputs are sacred
- **Dependencies**: `@deps` list mandatory for every service
- **State mutations**: DB writes, file uploads, global changes (`=>`)
- **Control flow**: Loops, recursion, branching
- **External I/O**: API calls, queues, third-party services
- **Business rules**: Invariants, guards, validation
- **Transactions**: Atomic ops, rollback behavior

---

## Configuration System

### Config File: `.murc.toml`
```toml
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

[reducer]
strip_comments = true
strip_docstrings = false
complexity_threshold = 20

[llm]
enabled = false
provider = "anthropic"  # anthropic | openai | ollama
model = "claude-3-haiku-20240307"
timeout_seconds = 30
max_retries = 2

[llm.ollama]
base_url = "http://localhost:11434"
model = "codellama"

[security]
redact_secrets = true

[output]
format = "mu"  # mu | json | markdown
include_file_hashes = true

[cache]
enabled = true
directory = ".mu-cache"
ttl_hours = 168
```

### Environment Variables
Pattern: `MU_<SECTION>_<KEY>` in uppercase
```bash
MU_LLM_PROVIDER=openai
MU_LLM_MODEL=gpt-4o-mini
MU_SECURITY_REDACT_SECRETS=false
```

---

## Error Handling

### Philosophy
**Partial output is better than no output.** MU should never crash entirely due to a single bad file.

### Failure Modes
| Scenario | Behavior |
|----------|----------|
| Unparseable file | Skip file, continue, warn in manifest |
| Unsupported language | Skip file, continue, info in manifest |
| LLM API timeout | Retry 2x, then skip summarization |
| LLM API rate limit | Exponential backoff (max 60s) |
| LLM API auth failure | Fail fast with clear message |
| Invalid config | Fail fast with validation errors |

### Exit Codes
| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Configuration/auth error (user fixable) |
| 2 | Partial success (some files skipped) |
| 3 | Fatal error (unexpected crash) |

---

## CLI Specification

```
mu - Machine Understanding CLI

USAGE:
    mu <COMMAND> [OPTIONS]

COMMANDS:
    scan        Analyze codebase structure
    compress    Generate MU output
    view        Render MU in human-readable format
    cache       Manage cache
    init        Create .murc.toml in current directory

GLOBAL OPTIONS:
    -v, --verbose    Increase verbosity
    -q, --quiet      Suppress non-error output
    --config PATH    Path to config file
    --version        Show version

EXAMPLES:
    mu scan ./src
    mu compress ./src --output system.mu
    mu compress ./src --llm
    mu compress ./src --llm --local
    mu view system.mu --format markdown
    mu cache clear
```

### Command Details

#### `mu scan <path>`
Analyze codebase structure without generating MU.
```
Options:
  --output, -o PATH    Output manifest file (default: stdout)
  --format [json|text] Output format (default: text)
```

#### `mu compress <path>`
Generate MU output from source code.
```
Options:
  --output, -o PATH    Output file (default: stdout)
  --format [mu|json|md] Output format (default: mu)
  --llm                Enable LLM summarization
  --local              Use local LLM only (Ollama)
  --no-redact          Disable secret redaction
  --no-cache           Disable caching
  --yes                Skip confirmation prompts
```

#### `mu view <file.mu>`
Render MU in human-readable format.
```
Options:
  --format [terminal|html|markdown]
  --theme [dark|light]
```

#### `mu cache <command>`
Manage the MU cache.
```
Subcommands:
  clear    Remove all cached data
  stats    Show cache statistics
```

#### `mu init`
Create `.murc.toml` with sensible defaults.

---

## Implementation Roadmap

### Day 0: Foundation
- [ ] Initialize project with `pyproject.toml`
- [ ] Set up project structure (see above)
- [ ] Implement config system with Pydantic
- [ ] Implement error handling framework
- [ ] Set up logging
- [ ] Create basic CLI skeleton with Click

### Day 1: Scanner
- [ ] Implement filesystem walker
- [ ] Implement ignore pattern matching
- [ ] Implement language detection
- [ ] Generate manifest.json output
- [ ] Wire up `mu scan` command
- [ ] Write scanner tests

### Day 2: Parser
- [ ] Set up Tree-sitter with Python bindings
- [ ] Install language grammars (Python, TS, C#)
- [ ] Implement base extractor interface
- [ ] Implement Python extractor
- [ ] Implement TypeScript extractor
- [ ] Implement C# extractor
- [ ] Write parser tests

### Day 3: Reducer
- [ ] Implement transformation rules engine
- [ ] Implement sigil generation
- [ ] Implement MU syntax output
- [ ] Wire up `mu compress` for single files
- [ ] Write reducer tests

### Day 4: Error Handling & Polish
- [ ] Implement graceful failure for unparseable files
- [ ] Add progress indicators (rich or tqdm)
- [ ] Implement exit codes
- [ ] Polish error messages
- [ ] Full integration test

### Day 5: LLM Integration
- [ ] Integrate LiteLLM
- [ ] Implement Anthropic provider
- [ ] Implement OpenAI provider
- [ ] Implement Ollama provider
- [ ] Create prompt templates
- [ ] Implement cost estimation
- [ ] Wire up `--llm` flag

### Day 6: Caching
- [ ] Implement file hash caching
- [ ] Implement LLM response caching
- [ ] Implement incremental processing
- [ ] Wire up `mu cache` commands
- [ ] Test cache invalidation

### Day 7: Assembler
- [ ] Implement cross-file import resolution (explicit only)
- [ ] Implement module graph generation
- [ ] Implement unified output assembly
- [ ] JSON output format
- [ ] Markdown output format

### Day 8: Security
- [ ] Implement secret detection patterns
- [ ] Implement redaction logic
- [ ] Implement `--local` mode
- [ ] Implement `--no-redact` flag
- [ ] Document privacy model

### Day 9: Viewer & Init
- [ ] Implement terminal renderer with syntax highlighting
- [ ] Implement HTML export
- [ ] Implement markdown export
- [ ] Implement `mu init` command
- [ ] Wire up `mu view` command

### Day 10: Release
- [ ] PyPI packaging (`mucode` or `mu-cli`)
- [ ] Write comprehensive README
- [ ] Create example outputs
- [ ] Set up GitHub Actions CI
- [ ] Tag and release v0.1.0

---

## Key Implementation Details

### Tree-sitter Setup
```python
# Install grammars
pip install tree-sitter tree-sitter-python tree-sitter-typescript tree-sitter-c-sharp

# Usage
import tree_sitter_python as tspython
from tree_sitter import Language, Parser

PY_LANGUAGE = Language(tspython.language())
parser = Parser(PY_LANGUAGE)
tree = parser.parse(bytes(source_code, "utf8"))
```

### LiteLLM Setup
```python
from litellm import completion

# Anthropic
response = completion(
    model="claude-3-haiku-20240307",
    messages=[{"role": "user", "content": prompt}]
)

# Ollama (local)
response = completion(
    model="ollama/codellama",
    messages=[{"role": "user", "content": prompt}],
    api_base="http://localhost:11434"
)
```

### Click CLI Setup
```python
import click

@click.group()
@click.version_option()
@click.option('-v', '--verbose', is_flag=True)
@click.option('-q', '--quiet', is_flag=True)
@click.option('--config', type=click.Path(exists=True))
@click.pass_context
def cli(ctx, verbose, quiet, config):
    ctx.ensure_object(dict)
    ctx.obj['verbose'] = verbose
    ctx.obj['quiet'] = quiet
    ctx.obj['config'] = load_config(config)

@cli.command()
@click.argument('path', type=click.Path(exists=True))
@click.option('-o', '--output', type=click.Path())
@click.pass_context
def scan(ctx, path, output):
    """Analyze codebase structure."""
    pass

@cli.command()
@click.argument('path', type=click.Path(exists=True))
@click.option('-o', '--output', type=click.Path())
@click.option('--llm', is_flag=True)
@click.option('--local', is_flag=True)
@click.pass_context
def compress(ctx, path, output, llm, local):
    """Generate MU output from source code."""
    pass
```

### Pydantic Config
```python
from pydantic import BaseModel
from typing import Optional
import tomllib

class ScannerConfig(BaseModel):
    ignore: list[str] = ["node_modules/", ".git/", "__pycache__/"]
    include_hidden: bool = False
    max_file_size_kb: int = 1000

class LLMConfig(BaseModel):
    enabled: bool = False
    provider: str = "anthropic"
    model: str = "claude-3-haiku-20240307"
    timeout_seconds: int = 30
    max_retries: int = 2

class MuConfig(BaseModel):
    scanner: ScannerConfig = ScannerConfig()
    llm: LLMConfig = LLMConfig()
    # ... other sections

def load_config(path: Optional[str] = None) -> MuConfig:
    if path:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return MuConfig(**data)
    return MuConfig()
```

---

## Secret Detection Patterns

```python
SECRET_PATTERNS = [
    # AWS
    (r'AKIA[0-9A-Z]{16}', 'aws_access_key'),
    (r'aws_secret_access_key\s*=\s*["\']?[\w/+=]{40}', 'aws_secret_key'),
    
    # API Keys
    (r'sk-[a-zA-Z0-9]{48}', 'openai_api_key'),
    (r'sk-ant-[a-zA-Z0-9-]{95}', 'anthropic_api_key'),
    (r'sk_live_[a-zA-Z0-9]{24,}', 'stripe_live_key'),
    
    # Private Keys
    (r'-----BEGIN (?:RSA |DSA |EC )?PRIVATE KEY-----', 'private_key'),
    (r'-----BEGIN OPENSSH PRIVATE KEY-----', 'ssh_private_key'),
    
    # Connection Strings
    (r'postgres://[^\s]+', 'postgres_connection'),
    (r'mongodb://[^\s]+', 'mongodb_connection'),
    (r'mysql://[^\s]+', 'mysql_connection'),
    
    # Generic
    (r'password\s*=\s*["\'][^"\']{8,}["\']', 'password'),
    (r'api_key\s*=\s*["\'][^"\']{16,}["\']', 'api_key'),
]
```

---

## Performance Targets

| Metric | Target |
|--------|--------|
| Scan speed | <100ms for 10k files |
| Parse speed | <500ms per 1k lines (no LLM) |
| Full pipeline | <5s for 50k lines (no LLM) |
| With LLM | <30s for 50k lines |
| Memory | <500MB for 100k lines |
| Compression ratio | >80% token reduction |

---

## Testing Checklist

- [ ] Scanner correctly ignores patterns
- [ ] Scanner detects all supported languages
- [ ] Parser extracts classes, functions, imports
- [ ] Parser handles malformed files gracefully
- [ ] Reducer applies all transformation rules
- [ ] Reducer generates correct sigils
- [ ] LLM integration works with all providers
- [ ] LLM fallback works when API fails
- [ ] Cache invalidates on file change
- [ ] Secret detection catches all patterns
- [ ] Exit codes are correct for all scenarios
- [ ] Output formats are valid (MU, JSON, MD)

---

## Package Naming

- **PyPI package**: `mucode` (recommended) or `mu-cli`
- **CLI command**: `mu`
- **GitHub repo**: `0ximu/mu` or `0ximu/mucode`
- **Import**: `from mu import ...` or `from mucode import ...`

---

## First Commit Checklist

```bash
# Create repo
mkdir mu && cd mu
git init

# Create structure
mkdir -p src/mu/{scanner,parser,reducer,assembler,llm,security,cache,output}
mkdir -p tests/fixtures/{python,typescript,csharp}
touch src/mu/__init__.py src/mu/__main__.py

# Create pyproject.toml
# Create README.md
# Create .gitignore

# First commit
git add .
git commit -m "Initial project structure"
```

---

## Implementation Complete

All tasks in this kickoff document have been successfully implemented. The MU project now includes:

- Full CLI with all commands (scan, compress, view, diff, cache, init)
- 7 language parsers (Python, TypeScript, JavaScript, C#, Go, Rust, Java)
- Multi-provider LLM integration (Anthropic, OpenAI, Ollama, OpenRouter)
- Secret detection and redaction
- Persistent caching
- Semantic diff between git refs
- VS Code extension
- GitHub Action for CI/CD

See [MU-TECH-SPEC.md](./MU-TECH-SPEC.md) for the complete implementation status.
