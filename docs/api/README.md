# API Documentation

This directory contains API reference documentation for MU.

## Contents

| Document | Description |
|----------|-------------|
| [cli.md](cli.md) | Command-line interface reference |
| [python.md](python.md) | Python API reference |

## Quick Reference

### CLI

```bash
mu compress <path>      # Generate MU output
mu scan <path>          # Analyze codebase structure
mu diff <base> <head>   # Semantic diff between git refs
mu view <file.mu>       # Render with syntax highlighting
mu cache stats          # Cache statistics
```

### Python API

```python
from mu.parser import parse_file
from mu.reducer import reduce_module
from mu.assembler import build_graph

# Parse a single file
module_def = parse_file("src/main.py")

# Reduce to compressed form
reduced = reduce_module(module_def)

# Build dependency graph
graph = build_graph([reduced])
```

## API Stability

- **CLI**: Stable, follows semantic versioning
- **Python API**: Internal, may change between minor versions
- **MU Format**: Stable, versioned in output header
