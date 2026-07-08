# MU Quick Start Guide

> **tl;dr**: `cargo build --release && mu bootstrap && mu mcp`
>
> Give your AI assistant deep codebase understanding in under 5 minutes.

## 1. Install MU

Grab a prebuilt binary from [Releases](https://github.com/0ximu/mu/releases), or build from source:

```bash
# Build from source (Rust 1.70+)
git clone https://github.com/0ximu/mu.git
cd mu
cargo build --release

# Put mu on your PATH (required - the MCP config runs `mu` by name)
sudo cp target/release/mu /usr/local/bin/
```

Verify:
```bash
mu --version
```

## 2. Bootstrap Your Codebase

```bash
cd /path/to/your/project
mu bootstrap
```

This builds the semantic graph: nodes (files, classes, functions), edges (imports, calls, inheritance), PageRank importance scores, heuristic summaries, and a BM25 search index. Everything is stored in `.mu/mubase` (DuckDB).

## 3. Connect to Your AI Assistant

### Claude Code

```bash
claude mcp add mu -- mu mcp
```

Or, to share the config with your team, create `.mcp.json` in the project root:

```json
{
  "mcpServers": {
    "mu": {
      "command": "mu",
      "args": ["mcp"]
    }
  }
}
```

Your assistant now has 13 tools for searching, navigating, reviewing, and understanding your code.

### Other MCP-compatible clients

Start the server manually:
```bash
mu mcp
```

MU speaks MCP over stdio - any MCP client can connect.

## 4. What Your AI Can Do Now

Once connected, your AI assistant can:

- **`mu_grok`** - "Find code related to authentication"
- **`mu_impact`** - "What breaks if I change this function?"
- **`mu_review`** - "Review the changes on this branch"
- **`mu_sus`** - "Find suspicious or complex code"
- **`mu_compress`** - "Give me an architectural overview"
- **`mu_enrich`** - "Improve search quality by writing better summaries"

You don't call these directly - your AI assistant calls them as MCP tools.

## 5. CLI Commands (For Humans)

```bash
mu compress               # Compress codebase for LLM context
mu status                 # Project stats
mu deps MyClass           # Show dependencies
mu impact Parser          # What breaks if Parser changes?
mu diff main HEAD         # Semantic diff
mu review                 # Review uncommitted changes
mu audit                  # Code quality check
mu doctor                 # Health checks
```

### Compress (The Killer Feature)

Feed your entire codebase to an LLM in seconds:

```bash
mu compress > codebase.txt

# Or pipe directly
mu compress | pbcopy
```

MU compresses 66k lines into ~2k tokens while preserving semantic structure.

## Common Workflows

### Onboarding to a new codebase
Bootstrap, then ask your AI: "Explain the architecture of this system."

### Code review
```bash
mu review main..feature   # Or let your AI call mu_review
```

### Finding complexity hotspots
```bash
mu audit                  # Or let your AI call mu_audit / mu_sus
```

### Understanding impact before a refactor
```bash
mu impact ServiceName     # Or let your AI call mu_impact
```

## Troubleshooting

### "No supported files found"
MU supports: Python, TypeScript, JavaScript, Go, Rust, Java, C#. Make sure you're in the right directory.

### Database errors
```bash
rm -rf .mu && mu bootstrap
```

### Can't bootstrap while MCP server is running
DuckDB is single-writer. Stop the MCP server first, bootstrap, then restart.

---

**MU: Because life's too short to grep through 500k lines of code.**
