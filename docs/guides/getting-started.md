# Getting Started with MU

This guide will help you get up and running with MU in minutes.

## Installation

### From Source (Recommended)

```bash
git clone https://github.com/0ximu/mu.git
cd mu
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### Verify Installation

```bash
mu --version
mu --help
```

## Quick Start

### 1. Compress Your First Codebase

```bash
mu compress ./your-project -o project.mu
```

This will:
- Scan all supported files (Python, TypeScript, JavaScript, Go, Rust, Java, C#)
- Parse and extract semantic information
- Apply compression rules
- Output a token-efficient `.mu` file

### 2. View the Output

```bash
mu view project.mu
```

Or copy to clipboard for LLM:
```bash
cat project.mu | pbcopy  # macOS
cat project.mu | xclip   # Linux
```

### 3. Ask Your LLM

Paste the MU output into ChatGPT, Claude, or your preferred LLM and ask:
- "What is the authentication flow in this codebase?"
- "How does the payment processing work?"
- "Which services would be affected if Redis goes down?"

## Common Workflows

### Analyze a Codebase

```bash
# See structure without generating output
mu scan ./src

# Get JSON statistics
mu scan ./src -f json
```

### Compare Versions

```bash
# Semantic diff between commits
mu diff abc123 def456

# Diff against main branch
mu diff main HEAD

# See what changed in working directory
mu diff HEAD
```

### Use LLM Summarization

For complex functions, MU can generate AI summaries:

```bash
# With Anthropic (default)
export ANTHROPIC_API_KEY=your-key
mu compress ./src --llm

# With OpenAI
export OPENAI_API_KEY=your-key
mu compress ./src --llm --llm-provider openai

# Fully local (requires Ollama)
mu compress ./src --llm --local
```

## Configuration

Create `.murc.toml` in your project:

```toml
[scanner]
ignore = [
    "node_modules/",
    ".git/",
    "__pycache__/",
    "*.test.ts",
    "*.spec.py"
]
max_file_size_kb = 1000

[reducer]
complexity_threshold = 20  # Flag complex functions for LLM

[output]
format = "mu"
```

Or generate a default config:

```bash
mu init
```

## Understanding MU Output

MU uses sigils to represent code structure:

```mu
!module auth_service
@deps [jwt, bcrypt, sqlalchemy]

$User < BaseModel
  @attrs [id, email, hashed_password]
  #authenticate(email: str, password: str) -> Optional[User]
  #async create(data: UserCreate) -> User

#async login(credentials: LoginRequest) -> TokenResponse
```

| Sigil | Meaning |
|-------|---------|
| `!` | Module/Service |
| `$` | Class/Entity |
| `#` | Function/Method |
| `@` | Metadata |
| `<` | Inherits from |
| `->` | Returns |

## Next Steps

- [CLI Reference](../api/cli.md) - Complete command documentation
- [Configuration](configuration.md) - All configuration options
- [Security](../security/README.md) - Secret detection and privacy
