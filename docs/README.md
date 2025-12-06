# MU Documentation

This directory contains all project documentation for MU (Machine Understanding).

## Structure

```
docs/
├── README.md              # This file
├── adr/                   # Architecture Decision Records
│   ├── README.md          # ADR index and template
│   ├── 0001-*.md          # Individual ADRs
│   └── ...
├── security/              # Security documentation
│   ├── README.md          # Security overview
│   ├── SECURITY.md        # Security policy
│   └── threat-model.md    # Threat modeling
├── guides/                # User and developer guides
│   ├── getting-started.md # Quick start guide
│   ├── configuration.md   # Configuration reference
│   └── contributing.md    # Contributor guide
├── api/                   # API documentation
│   ├── README.md          # API overview
│   ├── cli.md             # CLI reference
│   └── python.md          # Python API reference
└── assets/                # Images, diagrams, logos
    └── mu-logo.svg
```

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
