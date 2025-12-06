# MU - VS Code Extension

Syntax highlighting and tooling for [MU (Machine Understanding)](https://github.com/dominaite/mu) semantic compression format.

## Features

### Syntax Highlighting

Full syntax highlighting for `.mu` files with support for:

- **Module declarations** (`!module`, `§`)
- **Type/Class definitions** (`$`, `τ`)
- **Function signatures** (`#`, `λ`)
- **Annotations & decorators** (`@`, `::`)
- **Operators** (`->`, `=>`, `→`, `⟹`, `|`, `~`, `<`)
- **Metadata** (`@attrs`, `@deps`)
- **Comments and headers**

### Commands

Access via Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`):

| Command | Description |
|---------|-------------|
| `MU: Compress Directory` | Select a folder and generate MU output |
| `MU: Compress Workspace` | Compress the entire workspace |
| `MU: Preview Output` | Preview MU output for current file's directory |
| `MU: Semantic Diff` | Compare two git refs semantically |

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
- Right-click in editor → "MU: Preview Output"

## Requirements

- [MU CLI](https://github.com/dominaite/mu) installed and available in PATH
- VS Code 1.85.0 or higher

### Installing MU CLI

```bash
pip install mu-compression
# or
pipx install mu-compression
```

## Extension Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `mu.executablePath` | `mu` | Path to the mu CLI executable |
| `mu.defaultFormat` | `mu` | Default output format (mu, json, markdown) |
| `mu.autoPreview` | `false` | Auto-show preview pane when compressing |

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

## Development

```bash
# Install dependencies
npm install

# Compile TypeScript
npm run compile

# Watch mode
npm run watch

# Package extension
npm run package
```

### Testing Locally

1. Open this folder in VS Code
2. Press `F5` to launch Extension Development Host
3. Open a `.mu` file to test highlighting
4. Use Command Palette to test commands

## License

MIT - See [LICENSE](../../LICENSE) for details.
