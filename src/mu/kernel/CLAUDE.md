# Kernel Module - Graph Database for Code Analysis

The kernel module provides a DuckDB-based graph storage layer for the MU codebase analysis pipeline.

## Architecture

```
ModuleDef[] → GraphBuilder → Nodes + Edges → MUbase (.mubase file)
                                                 ↓
                                          Query Methods
                                          (dependencies, dependents, complexity, etc.)
```

### Files

| File | Purpose |
|------|---------|
| `schema.py` | NodeType/EdgeType enums, SCHEMA_SQL for DuckDB |
| `models.py` | Node and Edge dataclasses |
| `builder.py` | GraphBuilder converts ModuleDef → nodes/edges |
| `mubase.py` | MUbase class - DuckDB wrapper with query methods |

## Node Types

```python
class NodeType(Enum):
    MODULE = "module"    # File/module level
    CLASS = "class"      # Class/struct/interface
    FUNCTION = "function"  # Function/method
    EXTERNAL = "external"  # External dependency
```

## Edge Types

```python
class EdgeType(Enum):
    CONTAINS = "contains"  # Module→Class, Class→Function
    IMPORTS = "imports"    # Module→Module (internal deps)
    INHERITS = "inherits"  # Class→Class (inheritance)
```

## Usage

### Building a Graph

```python
from mu.kernel import MUbase
from mu.parser.base import parse_file
from mu.scanner import scan_codebase

# Scan and parse
scan_result = scan_codebase(root_path, config)
modules = [parse_file(f.path, f.language).module for f in scan_result.files]

# Build graph
db = MUbase(root_path / ".mubase")
db.build(modules, root_path)
```

### Querying

```python
# Get all functions
functions = db.get_nodes(NodeType.FUNCTION)

# Find complex functions
complex_funcs = db.find_by_complexity(min_complexity=50)

# Get dependencies (what does this node depend on?)
deps = db.get_dependencies("mod:src/cli.py", depth=2)

# Get dependents (what depends on this node?)
users = db.get_dependents("cls:src/kernel/mubase.py:MUbase")

# Get children (CONTAINS edges)
methods = db.get_children("cls:src/kernel/mubase.py:MUbase")

# Find by name pattern
tests = db.find_by_name("test_%", NodeType.FUNCTION)

# Path finding
path = db.find_path("mod:a.py", "mod:b.py", max_depth=5)
```

### CLI Commands

```bash
# Initialize empty .mubase
mu kernel init [path]

# Build graph from codebase
mu kernel build [path] [--output file.mubase]

# Show statistics
mu kernel stats [path] [--json]

# Query nodes
mu kernel query [path] --type function --complexity 20
mu kernel query [path] --name "test_%"

# Show dependencies
mu kernel deps NodeName [path] --depth 2 --reverse
```

## Node ID Format

Node IDs follow a consistent format:

```
mod:{file_path}                    # Modules
cls:{file_path}:{class_name}       # Classes
fn:{file_path}:{func_name}         # Module functions
fn:{file_path}:{class}.{method}    # Class methods
```

Examples:
- `mod:src/mu/cli.py`
- `cls:src/mu/kernel/mubase.py:MUbase`
- `fn:src/mu/kernel/mubase.py:MUbase.build`

## Edge ID Format

```
edge:{source_id}:{edge_type}:{target_id}
```

## GraphBuilder

The builder converts parser output (ModuleDef) to graph structures:

1. Creates MODULE node for each file
2. Creates CLASS nodes for classes + CONTAINS edges from module
3. Creates FUNCTION nodes for methods/functions + CONTAINS edges
4. Creates INHERITS edges from class bases
5. Creates IMPORTS edges for internal module dependencies

## Recursive Queries

Dependencies and dependents support multi-level traversal using recursive CTEs:

```python
# Direct dependencies only
deps = db.get_dependencies(node_id, depth=1)

# Transitive dependencies (3 levels deep)
deps = db.get_dependencies(node_id, depth=3)

# Filter by edge type
deps = db.get_dependencies(node_id, edge_types=[EdgeType.IMPORTS])
```

## Anti-Patterns

1. **Never** use raw SQL with user input - use parameterized queries
2. **Never** forget to call `db.close()` - use context manager instead
3. **Never** assume node exists - check for `None` returns
4. **Never** modify ModuleDef objects - builder is read-only

## Testing

```bash
pytest tests/unit/test_kernel.py -v
```

Test classes:
- `TestSchema` - Enum definitions
- `TestNodeModel` - Node serialization
- `TestEdgeModel` - Edge serialization
- `TestGraphBuilder` - ModuleDef → Graph conversion
- `TestMUbase` - Database operations
- `TestBuildIntegration` - End-to-end tests
