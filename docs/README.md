# MU Documentation

This directory contains all project documentation for MU (Machine Understanding).

## Structure

```
docs/
├── README.md              # This file
├── architecture.md        # System architecture overview
├── architecture.tasks.md  # Implementation tracking
├── project_context.md     # AI agent development patterns
├── adr/                   # Architecture Decision Records
│   ├── README.md          # ADR index and template
│   ├── 0001-use-tree-sitter-for-parsing.md
│   ├── 0002-sigil-based-output-format.md
│   ├── 0003-litellm-for-llm-integration.md
│   └── 0004-vector-embeddings-for-semantic-search.md
├── security/              # Security documentation
│   ├── README.md          # Security overview
│   ├── SECURITY.md        # Security policy
│   └── threat-model.md    # Threat modeling
├── guides/                # User guides
│   └── getting-started.md # Quick start guide
├── api/                   # API documentation
│   ├── README.md          # API overview
│   ├── cli.md             # CLI reference
│   └── python.md          # Python API reference
├── epics/                 # Feature development epics
│   ├── README.md          # Epic roadmap and status
│   ├── 01-vector-layer.md # Vector embeddings (Done)
│   ├── 02-muql-parser.md  # MUQL query language (Done)
│   ├── 03-smart-context.md # Context extraction (Done)
│   ├── 04-temporal-layer.md # Time-travel features (Ready)
│   ├── 05-export-formats.md # Multi-format export (Ready)
│   ├── 06-daemon-mode.md  # Real-time daemon (Ready)
│   ├── 07-mu-contracts.md # Architecture contracts (Ready)
│   ├── 08-visualization.md # Graph visualization (Planned)
│   └── 09-ide-integration.md # IDE extensions (Planned)
├── future-improvements/   # Future feature ideas
│   ├── README.md
│   ├── muql-natural-language.md
│   └── mu-conductor-architecture.md
├── archive/               # Historical documentation
└── assets/                # Images, diagrams, logos
    └── intro.gif
```

> **Note**: The contributor guide is at [CONTRIBUTING.md](../CONTRIBUTING.md) in the project root.

## Documentation Standards

### When to Update Documentation

Documentation MUST be updated when:
- Adding new features or CLI commands
- Changing existing behavior
- Adding/modifying configuration options
- Making architectural decisions (create ADR)
- Discovering security considerations
- Changing public APIs

### Writing Style

- Use clear, concise language
- Include code examples where applicable
- Keep documentation close to the code it describes
- Use present tense ("MU compresses..." not "MU will compress...")
- Include version information for breaking changes

### ADR (Architecture Decision Records)

Use ADRs for significant architectural decisions. See [adr/README.md](adr/README.md) for the template and index.

### Security Documentation

Security-related documentation belongs in the `security/` directory. See [security/README.md](security/README.md) for guidelines.

## Quick Links

- [Getting Started](guides/getting-started.md)
- [CLI Reference](api/cli.md)
- [Security Policy](security/SECURITY.md)
- [ADR Index](adr/README.md)
