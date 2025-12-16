# MU Quick Start Guide

> **tl;dr**: `cargo build --release && mu bootstrap && mu omg`
>
> Get your codebase into an LLM's context in under 5 minutes.

## 1. Install MU

```bash
# Build from source (Rust 1.70+)
git clone https://github.com/0ximu/mu.git
cd mu
cargo build --release

# Add to PATH (optional)
sudo cp target/release/mu /usr/local/bin/
```

Verify installation:
```bash
mu --version
# mu 0.1.0-alpha.1
```

## 2. Bootstrap Your Codebase

```bash
# Navigate to your project
cd /path/to/your/project

# Initialize MU (builds graph database)
mu bootstrap
```

You'll see output like:
```
Scanning...
Found 283 files
Parsing files... 283/283
Built graph: 517 classes, 577 functions
Database: .mu/mubase
```

## 3. Query Your Code

### Quick Queries (Terse Syntax)

```bash
# Find complex functions
mu q "fn c>50"

# Classes matching a pattern
mu q "cls n~'Service'"

# Dependencies of a module
mu q "deps Auth d2"
```

### Full SQL Syntax

```bash
mu query "SELECT name, complexity FROM functions WHERE complexity > 10 ORDER BY complexity DESC LIMIT 20"
```

## 4. Generate LLM-Ready Output

```bash
# Export semantic summary
mu export > system.mu

# Copy to clipboard (macOS)
mu export | pbcopy

# Pipe to Claude CLI
mu export | claude "What are the main services in this codebase?"
```

## 5. Ask Architectural Questions

Once the LLM has your MU output, try these prompts:

**Understanding Structure:**
```
"What is the overall architecture of this codebase?"
"List all the main domain services and their responsibilities"
"What are the database models and their relationships?"
```

**Tracing Flows:**
```
"How does user authentication work?"
"Walk me through what happens when [feature X] is triggered"
"What's the data flow from API request to database?"
```

**Dependency Analysis:**
```
"Which services would be affected if Redis goes down?"
"What external APIs does this system integrate with?"
"Identify the most critical dependencies"
```

## 6. Enable Semantic Search (Optional)

```bash
# Generate embeddings (~1 min per 1000 files)
mu embed

# Now search by meaning, not just keywords
mu search "error handling logic"
mu search "authentication flow"
```

## 7. Graph Analysis

```bash
# What does this depend on?
mu deps UserService

# What depends on this? (reverse)
mu deps UserService -r

# What breaks if I change this?
mu impact PaymentProcessor

# Find circular dependencies
mu cycles
```

## Common Use Cases

### Onboarding to a New Codebase
```bash
mu bootstrap && mu omg
# Then ask: "Explain the architecture of this system to a new developer"
```

### Code Review Prep
```bash
mu diff main HEAD
# "What are the semantic changes in this diff?"
```

### Documentation Generation
```bash
mu export -F json > graph.json
# "Generate API documentation from this code graph"
```

### Debugging Complex Issues
```bash
mu grok "How does data flow through the matching service?"
```

## Output Formats

```bash
mu export                # MU format (LLM-optimized, default)
mu export -F json        # JSON (structured data)
mu export -F mermaid     # Mermaid diagram
mu export -F d2          # D2 diagram
```

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

## Vibes

Commands that do real work with real personality.

```bash
mu yolo Auth          # "What breaks if I mass deploy this on Friday?"
mu sus                # "Find the code that makes you go 'hmm'"
mu wtf src/utils.ts   # "Git archaeology: who did this and WHY?"
mu omg                # "Monday standup: the tea, the drama"
mu zen                # "Clear cache, achieve inner peace"
```

> Most CLI tools are either boring or try-hard. MU aims for the sweet spot.

## Tips for Best Results

1. **Start with bootstrap** - Always run `mu bootstrap` first
2. **Use terse syntax** - 60-85% fewer tokens: `fn c>50` vs full SQL
3. **Check complexity** - High complexity functions often need attention
4. **Enable embeddings** - `mu embed` unlocks semantic search
5. **Iterate on questions** - Start broad, then drill down

## Troubleshooting

### "No supported files found"
Check that your directory contains supported files:
- Python (.py)
- TypeScript (.ts, .tsx)
- JavaScript (.js, .jsx)
- Go (.go)
- Rust (.rs)
- Java (.java)
- C# (.cs)

### Database errors
```bash
# Fresh start (clears database and rebuilds)
rm -rf .mu && mu bootstrap
```

### Output is too large
```bash
# Limit export size
mu export -l 100

# Or filter by type
mu export -F json | jq '.nodes | map(select(.type == "function"))'
```

## Next Steps

- [README.md](./README.md) - Full documentation
- [CLI Reference](./docs/api/cli.md) - Complete command reference
- [Architecture](./docs/architecture.md) - System design

---

**MU: Because life's too short to grep through 500k lines of code.**
