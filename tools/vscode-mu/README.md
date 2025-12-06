# MU - VS Code Extension

Syntax highlighting and tooling for [MU (Machine Understanding)](https://github.com/dominaite/mu) semantic compression format, with deep integration with the MU daemon for real-time code graph exploration.

## Features

### Code Graph Explorer (NEW)

When a `.mubase` file is present in your workspace, the MU sidebar provides interactive exploration of your codebase:

- **Modules View** - Browse all modules in your code graph
- **Classes View** - Explore class definitions and relationships
- **Functions View** - Navigate functions with complexity info
- **Hotspots View** - Quickly identify high-complexity code

Click any item to navigate to its source location.

### Complexity Badges (NEW)

Inline complexity badges appear at the end of function definition lines:
- **Blue** - Normal complexity
- **Yellow** - Warning (above configurable threshold)
- **Red** - High complexity (needs attention)

### Dependency CodeLens (NEW)

Above functions and classes, see "X deps, Y refs" showing:
- **deps** - Number of outgoing dependencies (things this code uses)
- **refs** - Number of incoming references (things that use this code)

Click to see the full list and navigate to related code.

### Smart Context (NEW)

Get AI-ready context from your codebase:
- **MU: Get Context for Question** - Extract relevant code context for any question
- Automatically copies MU-formatted context to clipboard
- Perfect for use with AI assistants like Copilot or Claude

### MUQL Queries (NEW)

Run semantic queries directly from VS Code:
- **MU: Run Query** - Execute MUQL queries with history support
- **MU: Find Path** - Find dependency paths between any two nodes

### Architecture Diagnostics (NEW)

Contract violations appear in the Problems panel:
- Warnings and errors from `.mu-contracts.yml`
- Click to navigate to the violation location
- Auto-refresh on file save

### Syntax Highlighting

Full syntax highlighting for `.mu` files with support for:

- **Module declarations** (`!module`, `§`)
- **Type/Class definitions** (`$`, `τ`)
- **Function signatures** (`#`, `λ`)
- **Annotations & decorators** (`@`, `::`)
- **Operators** (`->`, `=>`, `→`, `⟹`, `|`, `~`, `<`)
- **Metadata** (`@attrs`, `@deps`)
- **Comments and headers**

### CLI Commands

Access via Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`):

| Command | Description |
|---------|-------------|
| `MU: Compress Directory` | Select a folder and generate MU output |
| `MU: Compress Workspace` | Compress the entire workspace |
| `MU: Preview Output` | Preview MU output for current file's directory |
| `MU: Semantic Diff` | Compare two git refs semantically |
| `MU: Run Query` | Execute a MUQL query |
| `MU: Get Context for Question` | Extract smart context for AI assistants |
| `MU: Show Dependencies` | Show dependencies of function at cursor |
| `MU: Show Dependents` | Show what uses the function at cursor |
| `MU: Find Path` | Find dependency path between two nodes |
| `MU: Refresh Graph` | Force refresh of the code graph |
| `MU: Open Visualization` | Open the MU visualization web interface |

### Hover Information

Hover over MU sigils to see their meaning:

- `!` - Module/Service
- `$` - Entity/Class
- `#` - Function/Method
- `@` - Metadata/Decorator
- `?` - Conditional
- `::` - Annotation/Invariant

### Keyboard Shortcuts

| Shortcut | Command |
|----------|---------|
| `Ctrl+Shift+M` / `Cmd+Shift+M` | Preview MU output |

### Context Menus

- Right-click a folder in Explorer → "MU: Compress Directory"
- Right-click in editor → "MU: Preview Output" / "MU: Show Dependencies" / "MU: Show Dependents"

## Requirements

- [MU CLI](https://github.com/dominaite/mu) installed and available in PATH
- VS Code 1.85.0 or higher
- **For graph features**: MU daemon running (`mu daemon start .`)

### Installing MU CLI

```bash
pip install mu-compression
# or
pipx install mu-compression
```

### Starting the MU Daemon

To enable graph exploration, CodeLens, and diagnostics:

```bash
# Build the code graph
mu kernel build .

# Start the daemon in background
mu daemon start .

# Check status
mu daemon status
```

The VS Code extension will automatically connect when a `.mubase` file exists.

## Extension Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `mu.executablePath` | `mu` | Path to the mu CLI executable |
| `mu.defaultFormat` | `mu` | Default output format (mu, json, markdown) |
| `mu.autoPreview` | `false` | Auto-show preview pane when compressing |
| `mu.daemonUrl` | `http://localhost:8765` | MU daemon URL |
| `mu.complexity.warningThreshold` | `200` | Complexity threshold for warning badges |
| `mu.complexity.errorThreshold` | `500` | Complexity threshold for error badges |
| `mu.codeLens.enabled` | `true` | Show dependency CodeLens |
| `mu.badges.enabled` | `true` | Show complexity badges |
| `mu.context.maxTokens` | `8000` | Max tokens for smart context |

## Status Bar

The status bar shows the daemon connection status:
- **MU: Connected** (✓) - Daemon is running and connected
- **MU: Disconnected** (!) - Daemon not available

Click the status bar item to reconnect.

## MU Syntax Quick Reference

```mu
# MU v1.0
# source: /path/to/project

## Module Dependencies
!auth_service -> jwt, bcrypt

!module auth_service
@deps [jwt, bcrypt]

$User < BaseModel
  @attrs [id, email, password_hash]
  #verify_password(plain: str) -> bool
  #async get_by_email(db: Session, email: str) -> Optional[User]

#create_token(user_id: UUID) -> str
  :: guard: user exists
  1. generate JWT payload
  2. sign with secret
  3. return token

? invalid_token -> raise AuthError
```

### Sigil Reference

| Sigil | Unicode | Meaning |
|-------|---------|---------|
| `!` | - | Module/Service |
| `§` | U+00A7 | Module (alt) |
| `$` | - | Entity/Class |
| `τ` | U+03C4 | Type (alt) |
| `#` | - | Function/Method |
| `λ` | U+03BB | Lambda (alt) |
| `@` | - | Decorator/Metadata |
| `?` | - | Conditional |
| `::` | - | Annotation |
| `∅` | U+2205 | Empty marker |

### Operator Reference

| Operator | Unicode | Meaning |
|----------|---------|---------|
| `->` | `→` | Data flow / Return |
| `=>` | `⟹` | State mutation |
| `\|` | - | Match/Switch |
| `~` | - | Iteration |
| `<` | - | Inheritance |

## Troubleshooting

### Daemon not connecting

1. Ensure the MU daemon is running: `mu daemon status`
2. Check the daemon URL in settings matches your daemon
3. Restart the daemon: `mu daemon stop && mu daemon start .`

### Graph features not working

1. Ensure you have a `.mubase` file in your workspace
2. Build the graph if needed: `mu kernel build .`
3. Check VS Code output panel for MU errors

### High CPU usage

The daemon watches for file changes. If experiencing issues:
1. Exclude large directories (node_modules, etc.) from watch
2. Increase debounce delay in daemon config

## Development

```bash
# Install dependencies
npm install

# Compile TypeScript
npm run compile

# Watch mode
npm run watch

# Run tests
npm run test

# Package extension
npm run package
```

### Testing Locally

1. Open this folder in VS Code
2. Press `F5` to launch Extension Development Host
3. Open a `.mu` file to test highlighting
4. Open a project with `.mubase` to test graph features
5. Use Command Palette to test commands

## License

MIT - See [LICENSE](../../LICENSE) for details.
