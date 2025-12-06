<p align="center">
  <img src="docs/assets/mu-logo.svg" alt="MU Logo" width="400"/>
</p>

<h1 align="center">Machine Understanding</h1>

<p align="center">
  <strong>Semantic compression for AI-native development.</strong>
</p>

MU translates codebases into token-efficient representations optimized for LLM comprehension. Feed your entire codebase to an AI in seconds, not hours.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-passing-green.svg)]()

## The Problem

- LLMs choke on large codebases (500k+ lines exceed context windows)
- 90% of code is boilerplate, patterns, and syntactic noise
- Context windows are precious — wasted on syntax instead of semantics
- Current documentation is always out of date

## The Solution

MU is not a language you write — it's a language you **translate into**. Any codebase goes in, semantic signal comes out.

```
Input:  66,493 lines of Python
Output:  5,156 lines of MU (92% compression)
Result: LLM correctly answers architectural questions
```

## Validated Results

| Codebase | Original | MU Output | Compression |
|----------|----------|-----------|-------------|
| Production Backend (Python) | 66k lines | 5k lines | 92% |
| API Gateway (TypeScript) | 407k lines | 6.7k lines | 98% |

**Real test:** Fed MU output to Gemini, asked "How does ride matching work?" — it correctly explained the scoring pipeline, async event workflow, and identified Redis as a SPOF.

## Installation

```bash
# From source (recommended for now)
git clone https://github.com/dominaite/mu.git
cd mu
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Quick Start

```bash
# 1. Compress your codebase
mu compress ./src --output system.mu

# 2. Feed to any LLM
cat system.mu | pbcopy  # Copy to clipboard (macOS)

# 3. Ask architectural questions
# "What services would break if Redis goes down?"
# "How does authentication work?"
# "Explain the data flow for user registration"
```

## CLI Commands

```bash
mu init                             # Create .murc.toml config file
mu scan <path>                      # Analyze codebase structure
mu compress <path>                  # Generate MU output
mu compress <path> -o system.mu     # Save to file
mu compress <path> -f json          # JSON output format
mu compress <path> --llm            # Enable LLM summarization
mu compress <path> --local          # Local-only mode (Ollama)
mu view <file.mu>                   # Render MU with syntax highlighting
mu view <file.mu> -f html -o out.html  # Export to HTML
mu diff <base> <head>               # Semantic diff between git refs
mu cache clear                      # Clear cached data
mu cache stats                      # Show cache statistics
mu cache expire                     # Remove expired entries
```

## Output Format

MU uses a sigil-based syntax optimized for LLM parsing:

```mu
# MU v1.0
# source: /path/to/codebase
# modules: 257

## Module Dependencies
!auth_service -> jwt, bcrypt, sqlalchemy
!ride_service -> geoalchemy2, redis

## Modules

!module auth_service
@deps [jwt, bcrypt, sqlalchemy.ext.asyncio]

$User < BaseModel
  @attrs [id, email, hashed_password, created_at]
  #authenticate(email: str, password: str) -> Optional[User]
  #async create(data: UserCreate) -> User

#async login(credentials: LoginRequest) -> TokenResponse
#async refresh_token(token: str) -> TokenResponse
```

### Sigils

| Sigil | Meaning | Example |
|-------|---------|---------|
| `!` | Module/Service | `!module AuthService` |
| `$` | Entity/Class | `$User < BaseModel` |
| `#` | Function/Method | `#authenticate(email) -> User` |
| `@` | Metadata/Deps | `@deps [jwt, bcrypt]` |
| `::` | Annotation | `:: complexity:146` |

### Operators

| Operator | Meaning | Example |
|----------|---------|---------|
| `->` | Returns/Output | `#func(x) -> Result` |
| `=>` | State mutation | `status => PAID` |
| `<` | Inherits from | `$Admin < User` |

## Configuration

Create `.murc.toml` in your project:

```toml
[scanner]
ignore = ["node_modules/", ".git/", "__pycache__/", "*.test.ts"]
max_file_size_kb = 1000

[reducer]
complexity_threshold = 20  # Flag functions for LLM summarization

[output]
format = "mu"  # or "json"
```

## Supported Languages

| Language | Status |
|----------|--------|
| Python | ✅ Full support |
| TypeScript | ✅ Full support |
| JavaScript | ✅ Full support |
| C# | ✅ Full support |
| Go | ✅ Full support |
| Rust | ✅ Full support |
| Java | ✅ Full support |

## How It Works

```
Source Code → Scanner → Parser → Reducer → MU Output
                │          │         │
            manifest    AST     filtered &
                       data     formatted
```

1. **Scanner**: Walks filesystem, detects languages, filters noise
2. **Parser**: Tree-sitter extracts AST (classes, functions, imports)
3. **Reducer**: Applies transformation rules, strips boilerplate
4. **Generator**: Outputs MU format with sigils and dependency graph

### What Gets Stripped (Noise)

- Standard library imports
- Boilerplate (getters, setters, constructors)
- Dunder methods (`__repr__`, `__str__`, etc.)
- Trivial functions (< 3 AST nodes)
- `self`/`cls`/`this` parameters

### What Gets Kept (Signal)

- Function signatures with types
- Class inheritance
- External dependencies
- Async/static/decorator metadata
- Complex function annotations

## Example Prompts for LLMs

After generating MU output, try these prompts:

```
"What is the authentication flow in this codebase?"
"How does [feature X] work?"
"Which services would be affected if [dependency Y] goes down?"
"Explain the domain structure of this application"
"What are the main database models and their relationships?"
"Identify potential race conditions or concurrency issues"
```

## Development

```bash
# Run tests
pytest

# Run specific test file
pytest tests/unit/test_parser.py -v

# Type checking
mypy src/mu

# Linting
ruff check src/
```

## LLM Integration

MU supports multiple LLM providers for enhanced function summarization:

```bash
# With Anthropic (requires ANTHROPIC_API_KEY)
mu compress ./src --llm

# With OpenAI (requires OPENAI_API_KEY)
mu compress ./src --llm --llm-provider openai

# Local-only with Ollama (no data sent externally)
mu compress ./src --llm --local

# Disable secret redaction (use with caution)
mu compress ./src --llm --no-redact
```

### Security & Privacy

- **Secret detection**: Automatically redacts API keys, tokens, passwords, private keys
- **Local mode**: Process codebases without any external API calls
- **Privacy first**: No code leaves your machine without explicit consent

## Roadmap

- [x] Core CLI (scan, compress, view, diff)
- [x] Multi-language parsing (Python, TypeScript, JavaScript, C#, Go, Rust, Java)
- [x] Transformation rules engine
- [x] MU format generator
- [x] LLM-enhanced summarization (Anthropic, OpenAI, Ollama, OpenRouter)
- [x] Caching (incremental processing)
- [x] `mu view` - render MU with syntax highlighting
- [x] Secret detection and redaction
- [x] HTML/Markdown export
- [x] `mu diff` - semantic diff between git refs
- [x] VS Code extension (syntax highlighting, commands)
- [x] GitHub Action for CI/CD integration

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for guidelines.

## License

MIT License - see [LICENSE](./LICENSE) for details.

---

**Give AI the ability to understand any codebase in seconds, not hours.**
