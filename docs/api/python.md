# Python API Reference (Legacy)

> **ARCHIVED**: This document describes the Python implementation of MU which has been superseded by the Rust rewrite.
>
> MU is now a pure Rust project. See the [CLI Reference](./cli.md) for current documentation.

---

## Historical Context

The original MU was implemented in Python with the following architecture:

```
Scanner -> Parser -> Reducer -> Assembler -> Exporter
```

Key technologies used:
- **Tree-sitter** for multi-language parsing
- **Click** for CLI
- **Pydantic** for configuration
- **Rich** for terminal output
- **DiskCache** for caching

## Migration to Rust

The Rust rewrite (v0.1.0-alpha.1) provides:
- **10-100x faster parsing** via native tree-sitter bindings
- **Single binary distribution** (no Python runtime)
- **Built-in embeddings** via Candle (no external API required)
- **DuckDB storage** for fast analytical queries

## Current Architecture

See [Architecture](../architecture.md) for the current Rust-based design:

```
mu-cli/          # CLI application (clap)
mu-core/         # Parser, scanner, graph algorithms
mu-daemon/       # DuckDB storage layer
mu-embeddings/   # MU-SIGMA-V2 model (Candle)
```

## For Python Integration

If you need to integrate MU with Python, use the CLI:

```python
import subprocess
import json

def mu_query(query: str) -> dict:
    result = subprocess.run(
        ["mu", "query", query, "-F", "json"],
        capture_output=True,
        text=True
    )
    return json.loads(result.stdout)

def mu_export() -> str:
    result = subprocess.run(
        ["mu", "export"],
        capture_output=True,
        text=True
    )
    return result.stdout

# Example usage
nodes = mu_query("SELECT * FROM functions WHERE complexity > 20")
mu_output = mu_export()
```

Or use the HTTP API:

```python
import httpx

async def mu_query(query: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:9120/query",
            json={"query": query}
        )
        return response.json()
```

---

*This document is preserved for historical reference. For current documentation, see [CLI Reference](./cli.md).*
