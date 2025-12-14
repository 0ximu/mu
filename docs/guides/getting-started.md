# Getting Started with MU

This guide will help you get up and running with MU in minutes.

## Installation

### From Source (Recommended)

```bash
# Clone the repository
git clone https://github.com/0ximu/mu.git
cd mu

# Build (requires Rust 1.70+)
cargo build --release

# Add to PATH (optional)
sudo cp target/release/mu /usr/local/bin/
```

### Verify Installation

```bash
mu --version
mu --help
```

## Quick Start

### 1. Bootstrap Your Codebase

```bash
cd /path/to/your/project
mu bootstrap
```

This will:
- Scan all supported files (Python, TypeScript, JavaScript, Go, Rust, Java, C#)
- Parse and extract semantic information (functions, classes, imports)
- Build a graph database in `.mu/mubase`

### 2. Check Status

```bash
mu status
```

### 3. Query Your Code

```bash
# Terse syntax (60-85% fewer tokens)
mu q "fn c>50"           # Functions with complexity > 50
mu q "cls n~'Service'"   # Classes matching 'Service'
mu q "deps Auth d2"      # Dependencies of Auth, depth 2

# Full SQL syntax
mu query "SELECT name, complexity FROM functions ORDER BY complexity DESC LIMIT 20"
```

### 4. Export for LLM

```bash
# Export semantic summary
mu export > system.mu

# Copy to clipboard (macOS)
mu export | pbcopy
```

Paste into ChatGPT, Claude, or your preferred LLM and ask:
- "What is the authentication flow in this codebase?"
- "Which services would be affected if Redis goes down?"
- "How does the payment processing work?"

## Common Workflows

### Graph Analysis

```bash
# What does this depend on?
mu deps UserService

# What depends on this? (reverse dependencies)
mu deps UserService -r

# What breaks if I change this?
mu impact PaymentProcessor

# Find circular dependencies
mu cycles
```

### Semantic Diff

```bash
# Diff between git refs
mu diff main HEAD

# Last 5 commits
mu diff HEAD~5 HEAD
```

### Enable Semantic Search

```bash
# Generate embeddings (uses built-in MU-SIGMA-V2 model)
mu embed

# Now search by meaning
mu search "authentication logic"
mu search "error handling" -t function
```

### Ask Questions with LLM

```bash
mu grok "How does user authentication work?"
mu grok "What would break if I changed the database schema?"
```

## Understanding MU Output

MU uses sigils to represent code structure compactly:

```mu
!auth_service
  Authentication and authorization module
  @deps [jwt, bcrypt, sqlalchemy]

$User < BaseModel
  @attrs [id, email, hashed_password, created_at]
  #authenticate(email: str, password: str) -> Optional[User]
  #async create(data: UserCreate) -> User

#async login(credentials: LoginRequest) -> TokenResponse
  Authenticate user and return JWT tokens
```

| Sigil | Meaning |
|-------|---------|
| `!` | Module/File |
| `$` | Class |
| `#` | Function/Method |
| `@` | Metadata (deps, attrs, decorators) |
| `<` | Inherits from |
| `->` | Returns |

## Configuration

Create `.murc.toml` in your project root:

```toml
[scanner]
ignore = ["vendor/", "node_modules/", "dist/"]
max_file_size_kb = 1024

[parser]
languages = ["python", "typescript", "rust"]

[output]
format = "table"
color = true
```

## Export Formats

```bash
mu export                # MU format (LLM-optimized, default)
mu export -F json        # JSON (structured)
mu export -F mermaid     # Mermaid diagram
mu export -F d2          # D2 diagram
```

## MCP Server for Claude Code

Integrate MU directly with Claude Code:

```bash
mu serve --mcp
```

Configure in `~/.claude/mcp_servers.json`:
```json
{
  "mu": {
    "command": "mu",
    "args": ["serve", "--mcp"]
  }
}
```

## Vibes

Commands that do real work with real personality.

```bash
mu yolo Auth          # "What breaks if I mass deploy this on Friday?"
mu sus                # "Find the code that makes you go 'hmm'"
mu wtf src/utils.ts   # "Git archaeology: who did this and WHY?"
mu omg                # "Monday standup: the tea, the drama"
mu zen                # "Clear cache, achieve inner peace"
```

## Troubleshooting

### Database errors
```bash
# Fresh start
rm -rf .mu && mu bootstrap
```

### Check database contents
```bash
duckdb .mu/mubase "SELECT type, COUNT(*) FROM nodes GROUP BY type"
```

## Next Steps

- [CLI Reference](../api/cli.md) - Complete command documentation
- [Architecture](../architecture.md) - System design overview
- [Security](../security/README.md) - Secret detection and privacy
