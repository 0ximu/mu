# MUQL Module - MU Query Language

The MUQL module provides a SQL-like query language for exploring codebases stored in MUbase graph databases.

## Architecture

```
Query String → MUQLParser → AST → QueryPlanner → ExecutionPlan → QueryExecutor → QueryResult
                  │                    │                              │
              grammar.lark          SQLPlan           MUbase (DuckDB)
                                   GraphPlan
                                 AnalysisPlan
```

### Files

| File | Purpose |
|------|---------|
| `grammar.lark` | Lark grammar defining MUQL syntax |
| `ast.py` | AST node dataclasses for all query types |
| `parser.py` | MUQLParser and MUQLTransformer |
| `planner.py` | QueryPlanner converts AST to execution plans |
| `executor.py` | QueryExecutor runs plans against MUbase |
| `formatter.py` | Result formatters (table, JSON, CSV, tree) |
| `engine.py` | MUQLEngine unified facade |
| `repl.py` | Interactive REPL with history |

## Query Types

### SELECT - Query nodes with filters

```sql
SELECT * FROM functions WHERE complexity > 20
SELECT name, complexity FROM classes LIMIT 10
SELECT COUNT(*) FROM modules
```

### SHOW - Explore relationships

```sql
SHOW dependencies OF MUbase DEPTH 2
SHOW dependents OF cli
SHOW children OF MyClass
SHOW inheritance OF UserService
```

### FIND - Pattern-based search

```sql
FIND functions MATCHING "test_%"
FIND classes CALLING parse_file
FIND functions WITH DECORATOR "cache"
```

### PATH - Find paths between nodes

```sql
PATH FROM cli TO parser MAX DEPTH 5
PATH FROM UserController TO Database VIA imports
```

### ANALYZE - Built-in analysis

```sql
ANALYZE complexity
ANALYZE hotspots FOR kernel
ANALYZE circular
ANALYZE impact FOR UserService
```

## Usage

### Programmatic API

```python
from mu.kernel import MUbase
from mu.kernel.muql import MUQLEngine

# Open database
db = MUbase(Path(".mubase"))

# Create engine
engine = MUQLEngine(db)

# Execute query
result = engine.execute("SELECT * FROM functions WHERE complexity > 20")

# Access results
for row in result.as_dicts():
    print(f"{row['name']}: {row['complexity']}")

# Formatted output
print(engine.execute_formatted(query, format="table"))
```

### CLI Usage

```bash
# Single query
mu kernel muql . "SELECT * FROM functions LIMIT 10"

# Interactive REPL
mu kernel muql . -i

# JSON output
mu kernel muql . -f json "SELECT name FROM classes"

# Show execution plan
mu kernel muql . --explain "SELECT * FROM functions"
```

### REPL Commands

| Command | Description |
|---------|-------------|
| `.help` | Show help |
| `.exit` / `.quit` | Exit REPL |
| `.format <fmt>` | Set output format (table/json/csv) |
| `.explain` | Toggle explain mode |
| `.history` | Show query history |
| `.clear` | Clear screen |

## Resource Limits

The planner enforces resource limits to prevent abuse:

- `MAX_LIMIT = 10000` - Maximum rows returned
- `MAX_DEPTH = 20` - Maximum graph traversal depth

## Security

All SQL queries use parameterized queries to prevent SQL injection. User input is never interpolated into SQL strings.

## AST Model

All query types have corresponding dataclass models with `to_dict()` methods:

```python
@dataclass
class SelectQuery:
    fields: list[SelectField]
    node_type: NodeTypeFilter
    where: Condition | None = None
    order_by: list[OrderField] | None = None
    limit: int | None = None
```

## Extension Points

### Adding New Analysis Types

1. Add to `AnalysisType` enum in `ast.py`
2. Handle in `_execute_analysis()` in `executor.py`
3. Update grammar if new syntax needed

### Adding New Show Types

1. Add to `ShowType` enum in `ast.py`
2. Map to operation in `_show_type_to_operation()` in `planner.py`
3. Handle in `_execute_graph()` in `executor.py`

## Anti-Patterns

1. **Never** concatenate user input into SQL - use parameterized queries
2. **Never** bypass resource limits without good reason
3. **Never** expose internal DuckDB errors to users without wrapping

## Testing

```bash
pytest tests/unit/test_muql_parser.py -v
pytest tests/unit/test_muql_executor.py -v
pytest tests/integration/test_muql_integration.py -v
```
