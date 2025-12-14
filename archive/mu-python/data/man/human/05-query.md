# MUbase - Querying Your Codebase

MU can build a **graph database** of your codebase, enabling powerful queries
about structure, dependencies, and complexity.

## Building the Graph

```bash
# Initialize in your project
mu kernel init

# Build the graph (scans all code)
mu kernel build .

# Check what was indexed
mu kernel stats
```

## Basic Queries

### Find by Type

```bash
# All functions
mu kernel query --type function

# All classes
mu kernel query --type class

# All modules
mu kernel query --type module

# External dependencies
mu kernel query --type external
```

### Find by Complexity

```bash
# Complex functions (complexity > 20)
mu kernel query --complexity 20

# Very complex (> 50)
mu kernel query --complexity 50
```

### Find by Name

```bash
# Exact match
mu kernel query --name "UserService"

# Wildcard search
mu kernel query --name "test_%"      # starts with test_
mu kernel query --name "%Service"    # ends with Service
mu kernel query --name "%user%"      # contains user
```

## Dependency Analysis

### Show Dependencies

What does this function/class depend on?

```bash
mu kernel deps UserService
mu kernel deps process_payment
mu kernel deps cli.py --depth 2
```

### Show Dependents (Reverse)

What depends on this function/class?

```bash
mu kernel deps Database --reverse
mu kernel deps validate --reverse --depth 3
```

## Output Formats

```bash
# Table format (default)
mu kernel query --type class

# JSON for scripting
mu kernel query --type class --json

# Pipe to jq for processing
mu kernel query --type function --json | jq '.[] | select(.complexity > 30)'
```

## Example Session

```bash
$ mu kernel build .
Scanning /Users/dev/myproject...
Found 142 files
Parsing files...
Building graph...
Built graph: 1,247 nodes, 3,891 edges

$ mu kernel stats
+------------------+--------+
| Metric           | Value  |
+------------------+--------+
| Total Nodes      | 1,247  |
| Total Edges      | 3,891  |
|                  |        |
| Module           | 142    |
| Class            | 89     |
| Function         | 847    |
| External         | 169    |
|                  |        |
| File Size        | 2.1 MB |
+------------------+--------+

$ mu kernel query --type function --complexity 30 --limit 5
+----------+------------------+---------------------------+------------+
| Type     | Name             | File                      | Complexity |
+----------+------------------+---------------------------+------------+
| function | parse_expression | parser/expression.py      | 67         |
| function | resolve_deps     | assembler/resolver.py     | 45         |
| function | transform_ast    | reducer/transform.py      | 42         |
| function | build_graph      | kernel/builder.py         | 38         |
| function | scan_directory   | scanner/walker.py         | 31         |
+----------+------------------+---------------------------+------------+

$ mu kernel deps parse_expression
Dependencies of parser/expression.py:parse_expression (depth=1):
  [function] tokenize
  [function] validate_syntax
  [class] ASTNode
  [class] ParseError
  [external] re.compile
  [external] typing.Optional
```

## Pro Tips

### Find Hotspots

Complex functions that many things depend on = refactoring candidates:

```bash
mu kernel query --complexity 30 --json | \
  jq -r '.[].name' | \
  while read fn; do
    count=$(mu kernel deps "$fn" --reverse --json | jq length)
    echo "$count dependents: $fn"
  done | sort -rn | head -10
```

### Detect Circular Dependencies

```bash
mu kernel deps ModuleA --depth 5 --json | \
  jq '.[] | select(.name == "ModuleA")'
```

### Export for Visualization

```bash
mu kernel query --json > nodes.json
# Use with graphviz, D3.js, or your favorite visualization tool
```

---

*Press [n] for Workflows, [p] for previous, [q] to quit*
