# MU CLI Reference

## Quick Start

```bash
mu bootstrap          # Initialize MU for your codebase
mu status             # See what's indexed and next steps
mu q "SELECT * FROM nodes LIMIT 10"  # Query the graph
```

## Command Categories

### Core
- `mu bootstrap` - Initialize and build the MU graph
- `mu status` - Show project status and guidance
- `mu compress` - Compress code to MU format for LLMs

### Query & Navigation
- `mu query` / `mu q` - Execute MUQL queries
- `mu context` - Smart context extraction for questions
- `mu read` - Read source code for a node
- `mu search` - Search for code entities

### Graph Reasoning
- `mu deps` - Show what a node depends on
- `mu impact` - What breaks if I change this?
- `mu ancestors` - What depends on this node?
- `mu cycles` - Find circular dependencies
- `mu related` - Find related files (tests, deps)

### Intelligence
- `mu patterns` - Detect codebase patterns
- `mu warn` - Proactive warnings before changes
- `mu diff` - Semantic diff between git refs

### Vibes
Fun aliases for common operations:
- `mu omg` - OMEGA compressed context
- `mu grok` - Smart context extraction
- `mu wtf` - Git archaeology (why does this exist?)
- `mu yolo` - Impact analysis
- `mu sus` - Suspicious code warnings
- `mu vibe` - Pattern validation
- `mu zen` - Cache cleanup

### Services
- `mu serve` - Start MU server (daemon with HTTP/WebSocket API)
  - `mu serve` - Start in background
  - `mu serve -f` - Run in foreground
  - `mu serve --stop` - Stop running daemon
  - `mu serve --status` - Check daemon status
  - `mu serve --mcp` - Start MCP server for Claude Code
- `mu mcp serve` - Start MCP server for Claude Code

### Advanced
- `mu kernel export` - Export graph in various formats
- `mu kernel history` - Show node change history
- `mu kernel snapshot` - Create temporal snapshot
- `mu kernel blame` - Show who last modified a node
- `mu kernel search` - Semantic search
- `mu kernel embed` - Generate embeddings

## Deprecated Commands

These still work but will be removed in v2.0:

| Old | New |
|-----|-----|
| `mu daemon start` | `mu serve` |
| `mu daemon stop` | `mu serve --stop` |
| `mu daemon status` | `mu serve --status` |
| `mu daemon run` | `mu serve -f` |
| `mu kernel init` | `mu bootstrap` |
| `mu kernel build` | `mu bootstrap` |
| `mu kernel context` | `mu context` |
| `mu kernel muql` | `mu query` |
| `mu kernel stats` | `mu status` |
| `mu kernel deps` | `mu deps` |

## Common Workflows

### Initial Setup
```bash
cd your-project
mu bootstrap       # One-time setup
mu serve           # Start daemon (optional, enables real-time updates)
```

### Explore Codebase
```bash
mu q "SELECT name, complexity FROM functions ORDER BY complexity DESC LIMIT 10"
mu context "How does authentication work?"
mu deps AuthService
```

### Before Making Changes
```bash
mu warn src/auth.py    # Check for risks
mu impact AuthService  # See what might break
```

### Code Review
```bash
mu diff main HEAD      # Semantic diff for PR review
mu patterns            # Check code follows patterns
```

### MCP Integration (Claude Code)
```bash
# Add to claude_desktop_config.json or use Claude Code MCP settings
mu serve --mcp
```
