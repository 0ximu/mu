# MU Quick Start Guide

Get your codebase into an LLM's context in under 5 minutes.

## 1. Install MU

```bash
git clone https://github.com/dominaite/mu.git
cd mu
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

Verify installation:
```bash
mu --version
# mu, version 0.1.0
```

## 2. Compress Your Codebase

```bash
# Navigate to your project
cd /path/to/your/project

# Compress the source directory
mu compress ./src --output system.mu
```

You'll see output like:
```
Scanning src...
Found 283 files
Parsing files... ━━━━━━━━━━━━━━━━━━━━ 283/283 100%
Parsed 257 files successfully
Applying transformation rules...
Reduced to 517 classes, 577 functions, 1300 methods
Output written to system.mu
```

## 3. Feed to an LLM

### Option A: Copy to Clipboard (macOS)
```bash
cat system.mu | pbcopy
```
Then paste into Claude, ChatGPT, Gemini, or any LLM interface.

### Option B: Direct Terminal Output
```bash
mu compress ./src  # Prints to stdout
```

### Option C: Pipe to Claude CLI
```bash
cat system.mu | claude "What are the main services in this codebase?"
```

## 4. Ask Architectural Questions

Once the LLM has your MU file, try these prompts:

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

**Code Quality:**
```
"Are there any potential race conditions?"
"Which functions are flagged as complex?"
"Identify tightly coupled components"
```

## 5. Customize (Optional)

Create a config file for project-specific settings:

```bash
mu init  # Creates .murc.toml
```

Edit `.murc.toml`:
```toml
[scanner]
ignore = [
    "node_modules/",
    ".git/",
    "**/*.test.ts",
    "**/__mocks__/**",
]

[reducer]
complexity_threshold = 30  # Higher = fewer LLM flags
```

## Common Use Cases

### Onboarding to a New Codebase
```bash
mu compress ./src -o overview.mu
# "Explain the architecture of this system to a new developer"
```

### Code Review Prep
```bash
mu compress ./src -o current.mu
# "What would be the impact of changing the UserService?"
```

### Documentation Generation
```bash
mu compress ./src -o docs.mu
# "Generate API documentation for the public endpoints"
```

### Debugging Complex Issues
```bash
mu compress ./src -o debug.mu
# "How does data flow through the matching service?"
```

## Output Formats

### MU Format (Default)
Human-readable sigil-based format, optimized for LLMs.
```bash
mu compress ./src --format mu
```

### JSON Format
Structured data for programmatic use.
```bash
mu compress ./src --format json -o system.json
```

## Tips for Best Results

1. **Be specific with paths** - Compress only relevant directories
   ```bash
   mu compress ./src/domain/auth  # Just auth domain
   ```

2. **Check compression stats** - Higher compression = more efficient context use
   ```
   Input:  66,493 lines
   Output:  5,156 lines (92% compression)
   ```

3. **Provide context to LLM** - Include a brief project description with your MU file
   ```
   "This is a ride-sharing backend in Python/FastAPI. Here's the MU:
   [paste system.mu]
   How does ride matching work?"
   ```

4. **Iterate on questions** - Start broad, then drill down
   ```
   1. "What are the main services?"
   2. "Tell me more about AuthService"
   3. "How does OAuth token refresh work?"
   ```

## Troubleshooting

### "No supported files found"
Your directory might only contain unsupported file types. MU supports:
- Python (.py)
- TypeScript (.ts, .tsx)
- JavaScript (.js, .jsx)
- C# (.cs)
- Go (.go)
- Rust (.rs)
- Java (.java)

### "Failed to parse X files"
Some files may have syntax errors or use unsupported language features. MU continues with parseable files.

### Output is too large
Use more aggressive filtering:
```bash
mu compress ./src/core  # Compress a subdirectory
```

Or add ignores to `.murc.toml`:
```toml
[scanner]
ignore = ["**/*.test.ts", "**/migrations/**"]
```

## Advanced Features

### Semantic Diff
Compare changes between git refs semantically:
```bash
mu diff main feature-branch
mu diff HEAD~5 HEAD
```

### MUQL Queries
Query your codebase using SQL-like syntax for quick insights:
```bash
# Find complex functions
mu query "SELECT * FROM functions WHERE complexity > 20"

# Show dependencies of a class
mu q "SHOW dependencies OF MyClass"

# List all methods in a service
mu query "SELECT name, parameters FROM methods WHERE class = 'UserService'"

# Find circular dependencies
mu q "SHOW cycles"
```

Use the shorter `mu q` alias for quick queries. Run `mu describe --format json` to see all available commands (useful for AI agents and automation).

### VS Code Extension
Install the VS Code extension from `tools/vscode-mu/` for:
- Syntax highlighting for `.mu` files
- Commands to compress directories
- Hover information for sigils

### GitHub Actions
Use the GitHub Action from `tools/action-mu/` to automatically post semantic diffs on PRs.

## Next Steps

- Read the full [README.md](./README.md) for detailed documentation
- Check [docs/MU-TECH-SPEC.md](./docs/MU-TECH-SPEC.md) for the technical specification
- See [examples/](./examples/) for sample outputs

---

**Questions?** Open an issue at https://github.com/dominaite/mu/issues
