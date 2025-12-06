# CLI Reference

Complete reference for the MU command-line interface.

## Global Options

| Option | Description |
|--------|-------------|
| `--help` | Show help message |
| `--version` | Show version |
| `-v, --verbose` | Increase verbosity |
| `-q, --quiet` | Suppress non-essential output |

## Commands

### `mu init`

Create a `.murc.toml` configuration file in the current directory.

```bash
mu init
```

### `mu scan`

Analyze codebase structure without generating output.

```bash
mu scan <path> [options]
```

**Arguments:**
- `path`: Directory or file to scan

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--format, -f` | `text` | Output format: `text`, `json` |

**Example:**
```bash
mu scan ./src --format json
```

### `mu compress`

Generate compressed MU representation of a codebase.

```bash
mu compress <path> [options]
```

**Arguments:**
- `path`: Directory or file to compress

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--output, -o` | stdout | Output file path |
| `--format, -f` | `mu` | Output format: `mu`, `json`, `md` |
| `--llm` | false | Enable LLM summarization |
| `--llm-provider` | `anthropic` | LLM provider to use |
| `--local` | false | Use local LLM (Ollama) |
| `--no-redact` | false | Disable secret redaction |
| `--include` | `*` | Glob patterns to include |
| `--exclude` | - | Glob patterns to exclude |

**Examples:**
```bash
# Basic compression
mu compress ./src -o system.mu

# With LLM summarization
mu compress ./src --llm -o system.mu

# Local-only mode
mu compress ./src --llm --local -o system.mu

# JSON output
mu compress ./src -f json -o system.json

# Filter files
mu compress ./src --include "*.py" --exclude "*_test.py"
```

### `mu view`

Render MU file with syntax highlighting.

```bash
mu view <file> [options]
```

**Arguments:**
- `file`: MU file to view

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--format, -f` | `terminal` | Output: `terminal`, `html`, `md` |
| `--output, -o` | stdout | Output file (for html/md) |

**Examples:**
```bash
# View in terminal
mu view system.mu

# Export to HTML
mu view system.mu -f html -o docs/system.html
```

### `mu diff`

Compute semantic diff between git refs.

```bash
mu diff <base> <head> [options]
```

**Arguments:**
- `base`: Base git ref (commit, branch, tag)
- `head`: Head git ref (default: current working tree)

**Options:**
| Option | Default | Description |
|--------|---------|-------------|
| `--format, -f` | `text` | Output: `text`, `json`, `mu` |
| `--output, -o` | stdout | Output file |

**Examples:**
```bash
# Diff between commits
mu diff abc123 def456

# Diff against main branch
mu diff main HEAD

# Diff current changes
mu diff HEAD
```

### `mu cache`

Manage the MU cache.

```bash
mu cache <subcommand>
```

**Subcommands:**

| Command | Description |
|---------|-------------|
| `stats` | Show cache statistics |
| `clear` | Clear all cached data |
| `expire` | Remove expired entries |

**Examples:**
```bash
mu cache stats
mu cache clear
mu cache expire
```

## Configuration

MU looks for configuration in this order:
1. CLI flags
2. `.murc.toml` in current directory
3. `.murc.toml` in home directory
4. Environment variables (`MU_*` prefix)
5. Built-in defaults

### `.murc.toml` Example

```toml
[scanner]
ignore = ["node_modules/", ".git/", "__pycache__/", "*.test.ts"]
max_file_size_kb = 1000

[reducer]
complexity_threshold = 20

[output]
format = "mu"

[llm]
provider = "anthropic"
model = "claude-3-haiku-20240307"
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `MU_CONFIG` | Path to config file |
| `MU_CACHE_DIR` | Cache directory |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `OPENROUTER_API_KEY` | OpenRouter API key |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Configuration error |
| 3 | Parse error |
| 4 | IO error |
