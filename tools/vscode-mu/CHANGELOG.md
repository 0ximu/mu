# Changelog

All notable changes to the MU VS Code extension will be documented in this file.

## [0.1.0] - 2024-12-06

### Added

- Initial release
- Syntax highlighting for `.mu` files
  - Module declarations (`!`, `§`)
  - Type/Class definitions (`$`, `τ`)
  - Function signatures (`#`, `λ`)
  - Annotations and decorators (`@`, `::`)
  - All MU operators (`->`, `=>`, `|`, `~`, `<`)
  - Metadata directives (`@attrs`, `@deps`)
- Commands
  - `MU: Compress Directory` - Compress selected folder
  - `MU: Compress Workspace` - Compress entire workspace
  - `MU: Preview Output` - Preview in side panel
  - `MU: Semantic Diff` - Diff between git refs
- Hover provider for sigil documentation
- Language configuration with bracket matching and folding
- Context menu integration
- Keyboard shortcut `Ctrl+Shift+M` / `Cmd+Shift+M` for preview
