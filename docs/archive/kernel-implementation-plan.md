# MU Kernel Implementation Plan

## Overview

Add a graph-based storage layer on top of the existing parser infrastructure. This creates a queryable `.mubase` file (DuckDB) that stores the codebase as nodes and edges.

**Key Principle:** Layer on top, don't rewrite. The parser/reducer pipeline is stable.

```
Source → Parser → ModuleDef → [NEW: GraphBuilder] → MUbase (.mubase)
                      ↓
              Reducer → MU text export (existing, unchanged)
```

## Scope (MVP)

### In Scope
- DuckDB schema (nodes, edges tables)
- Node types: MODULE, CLASS, FUNCTION, EXTERNAL
- Edge types: CONTAINS, IMPORTS, INHERITS
- GraphBuilder: ModuleDef → nodes + edges
- MUbase class with CRUD + recursive queries
- CLI commands: `mu kernel init`, `mu kernel build`, `mu kernel stats`

### Out of Scope (Phase 2+)
- Vector embeddings
- MUQL parser
- Temporal snapshots
- Daemon mode
- Smart context extraction

## File Structure

```
src/mu/kernel/
├── __init__.py      # Public API exports
├── schema.py        # NodeType, EdgeType enums + SCHEMA_SQL
├── models.py        # Node, Edge dataclasses
├── builder.py       # GraphBuilder (ModuleDef → Graph)
└── mubase.py        # MUbase class (DuckDB wrapper)

tests/unit/
└── test_kernel.py   # Kernel tests
```

## Implementation Order

### 1. schema.py

```python
from enum import Enum

class NodeType(Enum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    EXTERNAL = "external"

class EdgeType(Enum):
    CONTAINS = "contains"      # Module→Class, Class→Function, Module→Function
    IMPORTS = "imports"        # Module→Module (internal deps)
    INHERITS = "inherits"      # Class→Class (inheritance)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS nodes (
    id VARCHAR PRIMARY KEY,
    type VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    qualified_name VARCHAR,
    file_path VARCHAR,
    line_start INTEGER,
    line_end INTEGER,
    properties JSON,
    complexity INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS edges (
    id VARCHAR PRIMARY KEY,
    source_id VARCHAR NOT NULL,
    target_id VARCHAR NOT NULL,
    type VARCHAR NOT NULL,
    properties JSON,
    UNIQUE(source_id, target_id, type)
);

CREATE TABLE IF NOT EXISTS metadata (
    key VARCHAR PRIMARY KEY,
    value VARCHAR
);

CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file_path);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(type);
"""
```

### 2. models.py

```python
@dataclass
class Node:
    id: str
    type: NodeType
    name: str
    qualified_name: str | None = None
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    complexity: int = 0

    def to_tuple(self) -> tuple: ...
    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_row(cls, row: tuple) -> Node: ...

@dataclass
class Edge:
    id: str
    source_id: str
    target_id: str
    type: EdgeType
    properties: dict[str, Any] = field(default_factory=dict)

    def to_tuple(self) -> tuple: ...
    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_row(cls, row: tuple) -> Edge: ...
```

### 3. builder.py

```python
class GraphBuilder:
    @staticmethod
    def from_module_defs(
        modules: list[ModuleDef],
        root_path: Path
    ) -> tuple[list[Node], list[Edge]]:
        """Convert parsed modules to graph nodes and edges."""
        nodes: list[Node] = []
        edges: list[Edge] = []

        for module in modules:
            # 1. Create MODULE node
            module_node = Node(
                id=f"mod:{module.path}",
                type=NodeType.MODULE,
                name=module.name,
                qualified_name=module.name,
                file_path=module.path,
                properties={
                    "language": module.language,
                    "total_lines": module.total_lines,
                    "docstring": module.module_docstring,
                }
            )
            nodes.append(module_node)

            # 2. Create CLASS nodes + CONTAINS edges
            for cls in module.classes:
                class_node = Node(
                    id=f"cls:{module.path}:{cls.name}",
                    type=NodeType.CLASS,
                    name=cls.name,
                    qualified_name=f"{module.name}.{cls.name}",
                    file_path=module.path,
                    line_start=cls.start_line,
                    line_end=cls.end_line,
                    properties={
                        "bases": cls.bases,
                        "decorators": cls.decorators,
                        "docstring": cls.docstring,
                    }
                )
                nodes.append(class_node)

                # Module CONTAINS Class
                edges.append(Edge(
                    id=f"edge:{module_node.id}:contains:{class_node.id}",
                    source_id=module_node.id,
                    target_id=class_node.id,
                    type=EdgeType.CONTAINS,
                ))

                # INHERITS edges
                for base in cls.bases:
                    # Create edge to base class (may be external)
                    edges.append(Edge(
                        id=f"edge:{class_node.id}:inherits:{base}",
                        source_id=class_node.id,
                        target_id=f"cls:?:{base}",  # Placeholder, resolve later
                        type=EdgeType.INHERITS,
                        properties={"base_name": base}
                    ))

                # 3. Create FUNCTION nodes for methods + CONTAINS edges
                for method in cls.methods:
                    method_node = Node(
                        id=f"fn:{module.path}:{cls.name}.{method.name}",
                        type=NodeType.FUNCTION,
                        name=method.name,
                        qualified_name=f"{module.name}.{cls.name}.{method.name}",
                        file_path=module.path,
                        line_start=method.start_line,
                        line_end=method.end_line,
                        complexity=method.body_complexity,
                        properties={
                            "is_async": method.is_async,
                            "is_static": method.is_static,
                            "is_classmethod": method.is_classmethod,
                            "is_property": method.is_property,
                            "decorators": method.decorators,
                            "return_type": method.return_type,
                            "parameters": [p.to_dict() for p in method.parameters],
                        }
                    )
                    nodes.append(method_node)

                    # Class CONTAINS Method
                    edges.append(Edge(
                        id=f"edge:{class_node.id}:contains:{method_node.id}",
                        source_id=class_node.id,
                        target_id=method_node.id,
                        type=EdgeType.CONTAINS,
                    ))

            # 4. Create FUNCTION nodes for module-level functions
            for func in module.functions:
                func_node = Node(
                    id=f"fn:{module.path}:{func.name}",
                    type=NodeType.FUNCTION,
                    name=func.name,
                    qualified_name=f"{module.name}.{func.name}",
                    file_path=module.path,
                    line_start=func.start_line,
                    line_end=func.end_line,
                    complexity=func.body_complexity,
                    properties={
                        "is_async": func.is_async,
                        "decorators": func.decorators,
                        "return_type": func.return_type,
                        "parameters": [p.to_dict() for p in func.parameters],
                    }
                )
                nodes.append(func_node)

                # Module CONTAINS Function
                edges.append(Edge(
                    id=f"edge:{module_node.id}:contains:{func_node.id}",
                    source_id=module_node.id,
                    target_id=func_node.id,
                    type=EdgeType.CONTAINS,
                ))

            # 5. Create IMPORTS edges (reuse existing assembler logic)
            # TODO: Integrate with ImportResolver

        return nodes, edges
```

### 4. mubase.py

```python
class MUbase:
    VERSION = "1.0.0"

    def __init__(self, path: Path = Path(".mubase")):
        self.path = path
        self.conn = duckdb.connect(str(path))
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database schema."""
        try:
            version = self.conn.execute(
                "SELECT value FROM metadata WHERE key = 'version'"
            ).fetchone()
            if version and version[0] != self.VERSION:
                self._migrate(version[0])
        except:
            self.conn.execute(SCHEMA_SQL)
            self.conn.execute(
                "INSERT INTO metadata VALUES ('version', ?)",
                [self.VERSION]
            )

    def build(self, modules: list[ModuleDef], root_path: Path) -> None:
        """Build graph from parsed modules."""
        nodes, edges = GraphBuilder.from_module_defs(modules, root_path)

        # Clear existing data
        self.conn.execute("DELETE FROM edges")
        self.conn.execute("DELETE FROM nodes")

        # Insert nodes
        for node in nodes:
            self.add_node(node)

        # Insert edges
        for edge in edges:
            self.add_edge(edge)

    def add_node(self, node: Node) -> None:
        self.conn.execute("""
            INSERT OR REPLACE INTO nodes
            (id, type, name, qualified_name, file_path,
             line_start, line_end, properties, complexity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, node.to_tuple())

    def add_edge(self, edge: Edge) -> None:
        self.conn.execute("""
            INSERT OR REPLACE INTO edges
            (id, source_id, target_id, type, properties)
            VALUES (?, ?, ?, ?, ?)
        """, edge.to_tuple())

    def get_node(self, node_id: str) -> Node | None:
        row = self.conn.execute(
            "SELECT * FROM nodes WHERE id = ?", [node_id]
        ).fetchone()
        return Node.from_row(row) if row else None

    def get_nodes(self, node_type: NodeType | None = None) -> list[Node]:
        if node_type:
            rows = self.conn.execute(
                "SELECT * FROM nodes WHERE type = ?", [node_type.value]
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM nodes").fetchall()
        return [Node.from_row(r) for r in rows]

    def get_dependencies(
        self,
        node_id: str,
        depth: int = 1,
        edge_types: list[EdgeType] | None = None
    ) -> list[Node]:
        """Get nodes that this node depends on (outgoing edges)."""
        type_filter = ""
        if edge_types:
            types = ", ".join(f"'{t.value}'" for t in edge_types)
            type_filter = f"AND e.type IN ({types})"

        if depth == 1:
            rows = self.conn.execute(f"""
                SELECT n.* FROM nodes n
                JOIN edges e ON n.id = e.target_id
                WHERE e.source_id = ? {type_filter}
            """, [node_id]).fetchall()
        else:
            # Recursive CTE for multi-level traversal
            rows = self.conn.execute(f"""
                WITH RECURSIVE deps AS (
                    SELECT target_id, 1 as depth
                    FROM edges
                    WHERE source_id = ? {type_filter}

                    UNION ALL

                    SELECT e.target_id, d.depth + 1
                    FROM deps d
                    JOIN edges e ON e.source_id = d.target_id
                    WHERE d.depth < ? {type_filter}
                )
                SELECT DISTINCT n.* FROM nodes n
                JOIN deps d ON n.id = d.target_id
            """, [node_id, depth]).fetchall()

        return [Node.from_row(r) for r in rows]

    def get_dependents(
        self,
        node_id: str,
        depth: int = 1,
        edge_types: list[EdgeType] | None = None
    ) -> list[Node]:
        """Get nodes that depend on this node (incoming edges)."""
        type_filter = ""
        if edge_types:
            types = ", ".join(f"'{t.value}'" for t in edge_types)
            type_filter = f"AND e.type IN ({types})"

        if depth == 1:
            rows = self.conn.execute(f"""
                SELECT n.* FROM nodes n
                JOIN edges e ON n.id = e.source_id
                WHERE e.target_id = ? {type_filter}
            """, [node_id]).fetchall()
        else:
            rows = self.conn.execute(f"""
                WITH RECURSIVE deps AS (
                    SELECT source_id, 1 as depth
                    FROM edges
                    WHERE target_id = ? {type_filter}

                    UNION ALL

                    SELECT e.source_id, d.depth + 1
                    FROM deps d
                    JOIN edges e ON e.target_id = d.source_id
                    WHERE d.depth < ? {type_filter}
                )
                SELECT DISTINCT n.* FROM nodes n
                JOIN deps d ON n.id = d.source_id
            """, [node_id, depth]).fetchall()

        return [Node.from_row(r) for r in rows]

    def find_by_complexity(self, min_complexity: int) -> list[Node]:
        """Find nodes with complexity >= threshold."""
        rows = self.conn.execute("""
            SELECT * FROM nodes
            WHERE complexity >= ?
            ORDER BY complexity DESC
        """, [min_complexity]).fetchall()
        return [Node.from_row(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        """Get database statistics."""
        node_count = self.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        edge_count = self.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

        by_type = {}
        for row in self.conn.execute("""
            SELECT type, COUNT(*) FROM nodes GROUP BY type
        """).fetchall():
            by_type[row[0]] = row[1]

        return {
            "nodes": node_count,
            "edges": edge_count,
            "by_type": by_type,
            "file_size_kb": self.path.stat().st_size / 1024 if self.path.exists() else 0,
            "version": self.VERSION,
        }

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()
```

### 5. CLI Integration (cli.py additions)

```python
@main.group()
def kernel():
    """MU Kernel commands (graph database)."""
    pass

@kernel.command("init")
@click.argument("path", default=".", type=click.Path(exists=True))
@click.option("--force", is_flag=True, help="Overwrite existing .mubase")
def kernel_init(path: str, force: bool):
    """Initialize .mubase file."""
    mubase_path = Path(path) / ".mubase"
    if mubase_path.exists() and not force:
        raise click.ClickException(f"{mubase_path} already exists. Use --force to overwrite.")

    db = MUbase(mubase_path)
    db.close()
    click.echo(f"Created {mubase_path}")

@kernel.command("build")
@click.argument("path", default=".", type=click.Path(exists=True))
@click.pass_context
def kernel_build(ctx: click.Context, path: str):
    """Build graph from codebase."""
    root = Path(path).resolve()
    mubase_path = root / ".mubase"

    # Reuse existing scanner + parser
    config = ctx.obj.config or MUConfig()
    scan_result = scan_codebase(root, config)

    modules = []
    for file_info in scan_result.files:
        parsed = parse_file(Path(file_info.path), file_info.language)
        if parsed.success and parsed.module:
            modules.append(parsed.module)

    db = MUbase(mubase_path)
    db.build(modules, root)

    stats = db.stats()
    click.echo(f"Built graph: {stats['nodes']} nodes, {stats['edges']} edges")
    db.close()

@kernel.command("stats")
@click.argument("path", default=".", type=click.Path(exists=True))
def kernel_stats(path: str):
    """Show graph statistics."""
    mubase_path = Path(path) / ".mubase"
    if not mubase_path.exists():
        raise click.ClickException(f"No .mubase found. Run 'mu kernel init' first.")

    db = MUbase(mubase_path)
    stats = db.stats()

    click.echo(f"Nodes: {stats['nodes']}")
    click.echo(f"Edges: {stats['edges']}")
    click.echo(f"By type:")
    for node_type, count in stats['by_type'].items():
        click.echo(f"  {node_type}: {count}")
    click.echo(f"File size: {stats['file_size_kb']:.1f} KB")

    db.close()
```

## Testing Strategy

### test_kernel.py

```python
class TestSchema:
    def test_node_types_defined(self): ...
    def test_edge_types_defined(self): ...
    def test_schema_sql_valid(self): ...

class TestModels:
    def test_node_to_tuple_roundtrip(self): ...
    def test_edge_to_tuple_roundtrip(self): ...
    def test_node_from_row(self): ...

class TestGraphBuilder:
    def test_module_node_created(self): ...
    def test_class_node_created(self): ...
    def test_function_node_created(self): ...
    def test_contains_edges_created(self): ...
    def test_inherits_edges_created(self): ...
    def test_complex_module_structure(self): ...

class TestMUbase:
    def test_init_creates_schema(self): ...
    def test_add_and_get_node(self): ...
    def test_add_and_get_edge(self): ...
    def test_get_dependencies_depth_1(self): ...
    def test_get_dependencies_depth_n(self): ...
    def test_get_dependents(self): ...
    def test_find_by_complexity(self): ...
    def test_stats(self): ...
    def test_build_from_modules(self): ...
```

## Dependencies

Add to `pyproject.toml`:

```toml
dependencies = [
    # ... existing ...
    "duckdb>=1.0.0",
]
```

## Success Criteria

1. `mu kernel init .` creates `.mubase` file
2. `mu kernel build .` populates graph from codebase
3. `mu kernel stats` shows correct node/edge counts
4. `MUbase.get_dependencies()` returns correct transitive deps
5. All tests pass
6. Type checking passes (`mypy src/mu/kernel`)
7. Linting passes (`ruff check src/mu/kernel`)

## Next Steps (Phase 2)

After MVP is stable:
1. Add IMPORTS edges using existing `ImportResolver`
2. Add `find_path(from_id, to_id)` for path queries
3. Add `export_mu(node_ids)` to export subgraph as MU text
4. Consider local embeddings for semantic search
