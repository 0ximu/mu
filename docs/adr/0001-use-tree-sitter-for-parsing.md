# ADR-0001: Use Tree-sitter for AST Parsing

## Status

Accepted

## Date

2025-01

## Context

MU needs to parse source code from multiple programming languages (Python, TypeScript, JavaScript, Go, Rust, Java, C#) to extract semantic information like classes, functions, and imports.

We need a parsing solution that:
- Supports multiple languages with consistent API
- Handles syntax errors gracefully (partial parsing)
- Is fast enough for large codebases
- Produces detailed AST for semantic extraction

## Decision

Use Tree-sitter as the unified parsing library for all supported languages.

Tree-sitter is a parser generator tool and incremental parsing library. It builds a concrete syntax tree for a source file and efficiently updates it as the source file is edited.

## Consequences

### Positive
- Single API for all languages reduces complexity
- Excellent error recovery - can parse partially valid code
- Very fast (written in C with Python bindings)
- Active community with grammars for 100+ languages
- Incremental parsing enables future caching optimizations

### Negative
- Tree-sitter types must be isolated to `parser/` module to prevent leakage
- Each language requires its own grammar package (`tree-sitter-python`, etc.)
- Learning curve for writing language-specific extractors
- Some language features may not be perfectly represented in AST

### Neutral
- Requires maintaining language-specific extractors that convert Tree-sitter AST to common `ModuleDef` format

## Alternatives Considered

### Alternative 1: Language-specific parsers
- Pros: Native understanding of each language
- Cons: Different APIs, maintenance burden, inconsistent behavior
- Why rejected: Too much complexity for multi-language support

### Alternative 2: Regex-based parsing
- Pros: Simple, no dependencies
- Cons: Fragile, can't handle complex syntax, poor error handling
- Why rejected: Not robust enough for production use

### Alternative 3: Language Server Protocol (LSP)
- Pros: Rich semantic information
- Cons: Heavy runtime dependency, complex setup, overkill for our needs
- Why rejected: We need parsing, not full IDE features

## References

- [Tree-sitter documentation](https://tree-sitter.github.io/tree-sitter/)
- [py-tree-sitter](https://github.com/tree-sitter/py-tree-sitter)
