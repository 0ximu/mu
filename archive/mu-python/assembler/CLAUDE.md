# Assembler Module - Import Resolution & Dependency Graph

The assembler resolves imports across files and builds a complete dependency graph of the codebase.

## Architecture

```
ModuleDef[] -> ImportResolver -> ResolvedImport[] -> ModuleGraph
                    |                                     |
            Language-specific              Nodes + Edges + External Packages
              resolution
```

### Core Components

| Class | Purpose |
|-------|---------|
| `ImportResolver` | Resolves imports to actual file paths |
| `Assembler` | Builds dependency graph from resolved imports |
| `ModuleGraph` | Graph structure with nodes and edges |
| `ModuleNode` | Node with internal/external/stdlib/dynamic deps |

## Dependency Types

```python
class DependencyType(Enum):
    INTERNAL = "internal"   # Within scanned codebase
    EXTERNAL = "external"   # Third-party packages (pip, npm, etc.)
    STDLIB = "stdlib"       # Language standard library
    DYNAMIC = "dynamic"     # Runtime imports (not statically resolvable)
```

## Import Resolution by Language

### Python
```python
# Absolute import
from mu.parser.models import ModuleDef  # -> src/mu/parser/models.py

# Relative import
from ..assembler import ModuleGraph  # -> relative to current file

# Dynamic import
importlib.import_module(f"plugins.{name}")  # -> DependencyType.DYNAMIC
```

### TypeScript/JavaScript
```typescript
// Relative import
import { foo } from "./utils"  // -> ./utils.ts or ./utils/index.ts

// Package import
import express from "express"  // -> DependencyType.EXTERNAL

// Dynamic import
const mod = await import(`./plugins/${name}`)  // -> DependencyType.DYNAMIC
```

### Go
```go
import "github.com/pkg/errors"  // Domain-based -> EXTERNAL
import "fmt"                    // Single word stdlib -> STDLIB
import "./internal/utils"       // Relative path -> INTERNAL
```

### Java
```java
import java.util.List;          // java.* -> STDLIB
import com.myapp.utils.Helper;  // Project package -> INTERNAL
import org.apache.commons.*;    // External -> EXTERNAL
```

### Rust
```rust
use std::collections::HashMap;  // std/core/alloc -> STDLIB
use crate::parser::models;      // crate:: -> INTERNAL
use serde::Serialize;           // External crate -> EXTERNAL
```

### C#
```csharp
using System.Collections.Generic;  // System.* -> STDLIB
using Microsoft.Extensions.*;      // Microsoft.* -> STDLIB
using MyApp.Services;              // Project namespace -> INTERNAL
using Newtonsoft.Json;             // External -> EXTERNAL
```

## Standard Library Constants

Located at the top of `__init__.py`:

```python
PYTHON_STDLIB = {"os", "sys", "re", "json", ...}
GO_STDLIB = {"fmt", "net", "http", ...}
RUST_STDLIB = {"std", "core", "alloc", ...}
JAVA_STDLIB = {"java.lang", "java.util", ...}
```

When adding a new language:
1. Create stdlib constant: `{LANG}_STDLIB = {...}`
2. Add resolution method: `_resolve_{lang}()`
3. Add to `resolve()` dispatcher

## Graph Operations

### Building the Graph

```python
from mu.assembler import Assembler, assemble

assembler = Assembler(modules, root_path)
graph = assembler.build_graph()

# Or use convenience function
output = assemble(modules, reduced_codebase, root_path)
```

### Querying the Graph

```python
# Get internal dependency adjacency list
internal_graph = graph.get_internal_graph()
# {"src/cli.py": ["src/parser/base.py", "src/reducer/generator.py"], ...}

# Get all external packages
external = graph.get_external_packages()
# {"click", "tree-sitter", "litellm", ...}

# Get topological order (dependencies first)
order = assembler.get_topological_order()
```

### ModuleNode Structure

```python
@dataclass
class ModuleNode:
    name: str                    # "mu.parser.models"
    path: str                    # "src/mu/parser/models.py"
    language: str                # "python"
    internal_deps: list[str]     # Paths to internal modules
    external_deps: list[str]     # Package names
    stdlib_deps: list[str]       # Stdlib module names
    dynamic_deps: list[DynamicImportInfo]  # Runtime imports
    exports: list[str]           # Exported symbols
```

## Dynamic Import Tracking

Dynamic imports that can't be resolved statically are tracked separately:

```python
@dataclass
class DynamicImportInfo:
    pattern: str | None     # "f'plugins.{name}'"
    source: str | None      # "importlib", "import()", "require()"
    line: int               # Source line number
    resolved_path: str | None  # If partially resolvable
```

## Enhancing ReducedCodebase

The assembler enhances reduced output with dependency info:

```python
enhanced = assembler.enhance_reduced_codebase(reduced)

# Adds:
# - reduced.dependency_graph: dict[str, list[str]]
# - reduced.external_packages: list[str]
# - reduced.dynamic_dependencies: list[DynamicDependency]
# - reduced.stats["internal_dependencies"]: int
# - reduced.stats["external_packages"]: int
# - reduced.stats["dynamic_imports"]: int
```

## Anti-Patterns

1. **Never** hardcode stdlib lists in resolvers - use module constants
2. **Never** assume file paths are absolute - use `root_path.resolve()`
3. **Never** skip dynamic import tracking - it's valuable context for LLMs
4. **Never** modify `ModuleDef` objects - assembler is read-only
5. **Never** ignore circular dependencies - they're added at end of topological sort

## Testing

```bash
pytest tests/unit/test_assembler.py -v
```

Key test scenarios:
- Relative imports (`from ..utils import`)
- Circular dependencies
- External package detection
- Dynamic import patterns
- Multi-language resolution
