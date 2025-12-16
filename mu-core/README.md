# mu-core

High-performance Rust core for MU (Machine Understanding).

## Overview

`mu-core` provides native Rust implementations of CPU-bound operations for MU:

- **Multi-language parsing** using tree-sitter (Python, TypeScript, JavaScript, Go, Java, Rust, C#)
- **Parallel file processing** with rayon
- **Cyclomatic complexity calculation**
- **Secret detection and redaction**
- **MU/JSON/Markdown export**

## Performance

- 4x faster than Python implementation
- 70% memory reduction
- Parallel parsing with GIL release

## Installation

```bash
pip install mu-core
```

Or build from source:

```bash
maturin develop --release
```

## Usage

```python
from mu._core import parse_file, parse_files, FileInfo

# Parse single file
result = parse_file(source, "main.py", "python")
if result.module:
    print(result.module.name)

# Parse multiple files in parallel
files = [
    FileInfo(path="a.py", source="...", language="python"),
    FileInfo(path="b.ts", source="...", language="typescript"),
]
results = parse_files(files)
```

## Feature Flag

Set `MU_USE_RUST=0` to fall back to Python implementation:

```bash
MU_USE_RUST=0 mu compress .
```

## License

MIT
