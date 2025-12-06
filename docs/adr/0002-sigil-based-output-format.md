# ADR-0002: Sigil-based MU Output Format

## Status

Accepted

## Date

2025-01

## Context

MU needs an output format that:
- Maximizes semantic signal per token
- Is easily parsed by LLMs
- Remains human-readable
- Compresses effectively (90%+ reduction from source)
- Represents code structure unambiguously

## Decision

Use a custom sigil-based format where special characters denote semantic elements:

| Sigil | Meaning | Example |
|-------|---------|---------|
| `!` | Module/Service | `!module AuthService` |
| `$` | Entity/Class | `$User < BaseModel` |
| `#` | Function/Method | `#authenticate(email) -> User` |
| `@` | Metadata/Deps | `@deps [jwt, bcrypt]` |
| `::` | Annotation | `:: complexity:146` |
| `->` | Returns | `#func(x) -> Result` |
| `=>` | State mutation | `status => PAID` |
| `<` | Inherits from | `$Admin < User` |

## Consequences

### Positive
- Extremely token-efficient (single character conveys type)
- LLMs can easily learn the pattern
- Human-readable at a glance
- Language-agnostic representation
- Easy to grep/search

### Negative
- Custom format requires documentation
- Not a standard (no existing tooling)
- May conflict with source code symbols in edge cases

### Neutral
- Requires syntax highlighting support for best experience (VS Code extension created)
- Multiple output formats supported (MU, JSON, Markdown) for flexibility

## Alternatives Considered

### Alternative 1: JSON
- Pros: Standard, well-supported, easy to parse
- Cons: Verbose, poor token efficiency, hard to read in bulk
- Why rejected: 3-5x more tokens than sigil format

### Alternative 2: YAML
- Pros: Human-readable, less verbose than JSON
- Cons: Still verbose, indentation-sensitive
- Why rejected: Not compact enough for LLM context windows

### Alternative 3: Markdown with conventions
- Pros: Familiar, renders nicely
- Cons: Ambiguous parsing, no semantic markers
- Why rejected: Lacks precision for code representation

## References

- MU format specification in README.md
- VS Code extension: `tools/vscode-mu/`
