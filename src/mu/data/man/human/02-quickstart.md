# Quick Start

Get from zero to your first MU compression in 5 minutes.

## Installation

```bash
pip install mu-cli
```

## Your First Compression

```bash
# Analyze what MU sees
mu scan ./my-project

# Compress to MU format
mu compress ./my-project

# Save to file
mu compress ./my-project -o codebase.mu

# View with syntax highlighting
mu view codebase.mu
```

## What Just Happened?

MU walked your codebase and:

1. **Scanned** - Found all supported files (Python, TypeScript, Go, Rust, Java, C#)
2. **Parsed** - Built AST for each file using tree-sitter
3. **Reduced** - Applied transformation rules to strip noise
4. **Assembled** - Resolved cross-file dependencies
5. **Exported** - Generated the MU format output

## Output Formats

```bash
# MU format (default) - for LLMs
mu compress . -f mu

# JSON - for tooling
mu compress . -f json

# Markdown - for documentation
mu compress . -f markdown
```

## LLM Enhancement (Optional)

For complex functions, MU can use an LLM to generate semantic summaries:

```bash
# Enable LLM summarization
mu compress . --llm

# Use a specific provider
mu compress . --llm --llm-provider anthropic

# Local-only mode (Ollama)
mu compress . --llm --local
```

## Configuration

Create a `.murc.toml` for persistent settings:

```bash
mu init
```

This creates:
```toml
[scanner]
exclude = ["node_modules", ".git", "dist", "__pycache__"]

[reducer]
complexity_threshold = 20  # Functions above this get LLM summaries

[llm]
enabled = false
provider = "anthropic"
model = "claude-3-haiku-20240307"
```

## Workflow Tips

### For Code Reviews
```bash
# Compare branches semantically
mu diff main feature-branch
```

### For AI Context
```bash
# Copy MU output directly to clipboard
mu compress . | pbcopy  # macOS
mu compress . | xclip   # Linux
```

### For Large Codebases
```bash
# Build a queryable graph database
mu kernel build .

# Query specific patterns
mu kernel query --type function --complexity 30
```

---

*Press [n] for Sigils Reference, [p] for previous, [q] to quit*
