# MU Product Requirements Document v3.0 — DIVINE EDITION

## The Vision

**MU is not a compression format. MU is a living, queryable, semantic graph of your codebase.**

Text output is just one export format. The graph is the product.

```
OLD THINKING:
Code → Parse → Reduce → TEXT OUTPUT → LLM reads it

DIVINE THINKING:
Code → Parse → GRAPH (source of truth) → Query / Visualize / Export / AI
                         ↓
              .mubase (single file)
              Contains everything:
              - Graph (structure)
              - Vectors (semantics)  
              - Temporal (history)
```

---

## Executive Summary

MU (Machine Understanding) is a **semantic kernel** that transforms codebases into queryable knowledge graphs with vector embeddings. It enables:

- **Structural queries**: "What depends on AuthService?"
- **Semantic search**: "Find code similar to this function"
- **Temporal analysis**: "When did this coupling appear?"
- **Smart AI context**: Extract perfect subgraphs for LLM consumption

**Core Innovation**: Graph + Vector + Temporal in a single portable file (`.mubase`)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            MU KERNEL                                     │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                         INGESTION LAYER                             │ │
│  │                                                                     │ │
│  │   Scanner → Parser → Reducer → Graph Builder → Vector Embedder     │ │
│  │                                                                     │ │
│  │   Supported: Python, TypeScript, JavaScript, C#, Go, Rust, Java    │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                    ↓                                     │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                         STORAGE LAYER                               │ │
│  │                                                                     │ │
│  │   .mubase file (DuckDB)                                            │ │
│  │   ├── Graph Tables (nodes, edges, properties)                      │ │
│  │   ├── Vector Index (embeddings for semantic search)                │ │
│  │   ├── Temporal Snapshots (git-linked history)                      │ │
│  │   └── Metadata (config, stats, version)                            │ │
│  │                                                                     │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                    ↓                                     │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                          QUERY LAYER                                │ │
│  │                                                                     │ │
│  │   MUQL - Unified Query Language                                    │ │
│  │   ├── Graph queries (paths, dependencies, impact)                  │ │
│  │   ├── Vector queries (semantic similarity)                         │ │
│  │   ├── Temporal queries (history, blame, evolution)                 │ │
│  │   └── Combined queries (all three!)                                │ │
│  │                                                                     │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                    ↓                                     │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                         EXPORT LAYER                                │ │
│  │                                                                     │ │
│  │   ├── MU Text (token-efficient LLM format)                         │ │
│  │   ├── JSON (structured data for tooling)                           │ │
│  │   ├── Mermaid / D2 (diagrams)                                      │ │
│  │   ├── Cytoscape / D3 (interactive visualization)                   │ │
│  │   └── Smart Context (AI-optimized subgraph extraction)             │ │
│  │                                                                     │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                    ↓                                     │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                        DAEMON LAYER                                 │ │
│  │                                                                     │ │
│  │   mu daemon - Always running, always current                       │ │
│  │   ├── File watcher (instant updates)                               │ │
│  │   ├── HTTP/WebSocket server                                        │ │
│  │   ├── IDE integration endpoints                                    │ │
│  │   └── AI context API                                               │ │
│  │                                                                     │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

# Phase 0: MU Kernel (THE FOUNDATION)

**Timeline**: This weekend + 1 week
**Priority**: P0 - Everything else depends on this

## 0.1 Graph Schema

### Node Types

```sql
-- Core node types
CREATE TYPE NodeType AS ENUM (
    'MODULE',      -- File/module level
    'CLASS',       -- Class/struct/interface
    'FUNCTION',    -- Function/method
    'ENTITY',      -- Data model/schema
    'PARAMETER',   -- Function parameter
    'EXTERNAL',    -- External dependency
    'ANNOTATION'   -- Decorator/attribute
);

-- Nodes table
CREATE TABLE nodes (
    id VARCHAR PRIMARY KEY,           -- Unique identifier
    type NodeType NOT NULL,
    name VARCHAR NOT NULL,
    qualified_name VARCHAR,           -- Full path (module.class.method)
    
    -- Location
    file_path VARCHAR,
    line_start INTEGER,
    line_end INTEGER,
    
    -- Metadata (type-specific)
    properties JSON,
    
    -- Computed
    complexity INTEGER,
    is_async BOOLEAN DEFAULT FALSE,
    is_static BOOLEAN DEFAULT FALSE,
    is_abstract BOOLEAN DEFAULT FALSE,
    visibility VARCHAR,               -- public, private, protected
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- Git info
    first_commit VARCHAR,
    last_commit VARCHAR
);

-- Indexes
CREATE INDEX idx_nodes_type ON nodes(type);
CREATE INDEX idx_nodes_name ON nodes(name);
CREATE INDEX idx_nodes_file ON nodes(file_path);
CREATE INDEX idx_nodes_complexity ON nodes(complexity);
```

### Edge Types

```sql
-- Relationship types
CREATE TYPE EdgeType AS ENUM (
    -- Structural
    'CONTAINS',        -- Module contains Class, Class contains Function
    'IMPORTS',         -- Module imports Module
    'INHERITS',        -- Class inherits Class
    'IMPLEMENTS',      -- Class implements Interface
    
    -- Behavioral
    'CALLS',           -- Function calls Function
    'RETURNS',         -- Function returns Type
    'USES',            -- Function uses Entity/Type
    'MUTATES',         -- Function mutates state (=> operator)
    
    -- Dependency
    'DEPENDS_ON',      -- High-level dependency
    'GUARDS',          -- Precondition relationship
    
    -- Metadata
    'ANNOTATED_WITH',  -- Has decorator/attribute
    'TYPED_AS'         -- Parameter/return typed as
);

-- Edges table
CREATE TABLE edges (
    id VARCHAR PRIMARY KEY,
    source_id VARCHAR NOT NULL REFERENCES nodes(id),
    target_id VARCHAR NOT NULL REFERENCES nodes(id),
    type EdgeType NOT NULL,
    
    -- Edge properties
    properties JSON,
    weight FLOAT DEFAULT 1.0,
    
    -- For CALLS edges
    call_count INTEGER,
    is_conditional BOOLEAN DEFAULT FALSE,
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    first_commit VARCHAR,
    
    UNIQUE(source_id, target_id, type)
);

-- Indexes
CREATE INDEX idx_edges_source ON edges(source_id);
CREATE INDEX idx_edges_target ON edges(target_id);
CREATE INDEX idx_edges_type ON edges(type);
```

### Node Properties by Type

```json
// MODULE
{
    "language": "python",
    "lines": 450,
    "docstring": "Authentication service module",
    "exports": ["AuthService", "login", "logout"]
}

// CLASS
{
    "bases": ["BaseService", "Auditable"],
    "is_dataclass": true,
    "is_abstract": false,
    "docstring": "Handles user authentication",
    "decorators": ["@injectable", "@cached"]
}

// FUNCTION
{
    "parameters": [
        {"name": "email", "type": "str", "default": null},
        {"name": "password", "type": "str", "default": null}
    ],
    "return_type": "Result[User]",
    "is_async": true,
    "is_generator": false,
    "decorators": ["@validate", "@log_call"],
    "docstring": "Authenticate user with credentials",
    "body_hash": "a1b2c3...",  -- For change detection
    "guards": ["email is valid", "password not empty"],
    "invariants": ["returns user or error, never null"]
}

// ENTITY
{
    "fields": [
        {"name": "id", "type": "UUID", "primary_key": true},
        {"name": "email", "type": "str", "unique": true},
        {"name": "created_at", "type": "datetime"}
    ],
    "table_name": "users",
    "is_orm_model": true
}

// EXTERNAL
{
    "package": "redis",
    "version": ">=4.0.0",
    "category": "database",  -- database, http, queue, auth, etc.
    "is_stdlib": false
}
```

---

## 0.2 Vector Layer

### Embeddings Table

```sql
-- Vector embeddings for semantic search
CREATE TABLE embeddings (
    node_id VARCHAR PRIMARY KEY REFERENCES nodes(id),
    
    -- Different embedding types
    code_embedding FLOAT[1536],      -- Embedding of actual code
    docstring_embedding FLOAT[1536], -- Embedding of documentation
    name_embedding FLOAT[384],       -- Embedding of names (smaller model)
    summary_embedding FLOAT[1536],   -- Embedding of MU summary
    
    -- Metadata
    model_version VARCHAR,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Vector index (using DuckDB vss extension or similar)
CREATE INDEX idx_code_embedding ON embeddings 
    USING HNSW (code_embedding) WITH (metric = 'cosine');
```

### Embedding Strategy

```python
class EmbeddingService:
    """Generate embeddings for semantic search."""
    
    def __init__(self, model: str = "text-embedding-3-small"):
        self.model = model
        self.local_model = None  # Fallback to local model
    
    async def embed_function(self, func: FunctionNode) -> FunctionEmbeddings:
        """Generate all embeddings for a function."""
        
        # Code embedding (what the code does)
        code_text = f"""
        Function: {func.qualified_name}
        Parameters: {func.parameters}
        Returns: {func.return_type}
        Body summary: {func.body_summary or func.body[:500]}
        """
        code_emb = await self.embed(code_text)
        
        # Docstring embedding (what docs say it does)
        doc_emb = await self.embed(func.docstring) if func.docstring else None
        
        # Name embedding (semantic meaning of name)
        name_emb = await self.embed_small(func.name)
        
        return FunctionEmbeddings(
            code=code_emb,
            docstring=doc_emb,
            name=name_emb
        )
    
    async def embed(self, text: str) -> list[float]:
        """Get embedding from OpenAI or local model."""
        if self.local_mode:
            return self.local_model.encode(text)
        return await openai_embed(text, self.model)
```

---

## 0.3 Temporal Layer

### Snapshots Table

```sql
-- Git-linked temporal snapshots
CREATE TABLE snapshots (
    id VARCHAR PRIMARY KEY,
    commit_hash VARCHAR NOT NULL,
    commit_message VARCHAR,
    commit_author VARCHAR,
    commit_date TIMESTAMP,
    
    -- Snapshot stats
    node_count INTEGER,
    edge_count INTEGER,
    
    -- Delta from previous
    nodes_added INTEGER,
    nodes_removed INTEGER,
    nodes_modified INTEGER,
    edges_added INTEGER,
    edges_removed INTEGER,
    
    created_at TIMESTAMP DEFAULT NOW()
);

-- Node history (which snapshots contain which nodes)
CREATE TABLE node_history (
    node_id VARCHAR,
    snapshot_id VARCHAR REFERENCES snapshots(id),
    
    -- State at this snapshot
    properties JSON,
    complexity INTEGER,
    
    -- Change type
    change_type VARCHAR,  -- added, modified, unchanged
    
    PRIMARY KEY (node_id, snapshot_id)
);

-- Edge history
CREATE TABLE edge_history (
    edge_id VARCHAR,
    snapshot_id VARCHAR REFERENCES snapshots(id),
    change_type VARCHAR,
    
    PRIMARY KEY (edge_id, snapshot_id)
);
```

### Temporal Queries

```sql
-- When did AuthService start depending on Redis?
SELECT s.commit_hash, s.commit_date, s.commit_author
FROM edge_history eh
JOIN snapshots s ON eh.snapshot_id = s.id
JOIN edges e ON eh.edge_id = e.id
WHERE e.source_id = 'AuthService' 
  AND e.target_id = 'redis'
  AND eh.change_type = 'added'
ORDER BY s.commit_date ASC
LIMIT 1;

-- How has complexity changed over time?
SELECT 
    s.commit_date,
    AVG(nh.complexity) as avg_complexity,
    MAX(nh.complexity) as max_complexity
FROM node_history nh
JOIN snapshots s ON nh.snapshot_id = s.id
JOIN nodes n ON nh.node_id = n.id
WHERE n.type = 'FUNCTION'
GROUP BY s.commit_date
ORDER BY s.commit_date;

-- What changed between two commits?
SELECT 
    n.name,
    n.type,
    old.complexity as old_complexity,
    new.complexity as new_complexity
FROM node_history old
JOIN node_history new ON old.node_id = new.node_id
JOIN nodes n ON n.id = old.node_id
WHERE old.snapshot_id = 'commit_abc'
  AND new.snapshot_id = 'commit_xyz'
  AND old.complexity != new.complexity;
```

---

## 0.4 Storage Implementation

### The .mubase File

```python
"""
.mubase is a DuckDB database file containing:
- Graph tables (nodes, edges)
- Vector indexes (embeddings)
- Temporal snapshots (history)
- Metadata (config, stats)

Single file. Portable. Version controlled.
"""

import duckdb
from pathlib import Path

class MUbase:
    """The MU kernel - a living graph of your codebase."""
    
    VERSION = "1.0.0"
    
    def __init__(self, path: Path = Path(".mubase")):
        self.path = path
        self.conn = duckdb.connect(str(path))
        self._init_schema()
        self._load_extensions()
    
    def _init_schema(self):
        """Initialize database schema if needed."""
        # Check version
        try:
            version = self.conn.execute(
                "SELECT value FROM metadata WHERE key = 'version'"
            ).fetchone()[0]
            if version != self.VERSION:
                self._migrate(version)
        except:
            self._create_schema()
    
    def _load_extensions(self):
        """Load DuckDB extensions for graph and vector."""
        self.conn.execute("INSTALL 'vss'")  # Vector similarity search
        self.conn.execute("LOAD 'vss'")
    
    def _create_schema(self):
        """Create all tables and indexes."""
        self.conn.execute(SCHEMA_SQL)
        self.conn.execute(
            "INSERT INTO metadata VALUES ('version', ?)", 
            [self.VERSION]
        )
    
    # === Graph Operations ===
    
    def add_node(self, node: Node) -> str:
        """Add or update a node in the graph."""
        self.conn.execute("""
            INSERT OR REPLACE INTO nodes 
            (id, type, name, qualified_name, file_path, 
             line_start, line_end, properties, complexity,
             is_async, is_static, visibility)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, node.to_tuple())
        return node.id
    
    def add_edge(self, edge: Edge) -> str:
        """Add or update an edge in the graph."""
        self.conn.execute("""
            INSERT OR REPLACE INTO edges
            (id, source_id, target_id, type, properties, weight)
            VALUES (?, ?, ?, ?, ?, ?)
        """, edge.to_tuple())
        return edge.id
    
    def get_node(self, node_id: str) -> Node | None:
        """Get a node by ID."""
        row = self.conn.execute(
            "SELECT * FROM nodes WHERE id = ?", [node_id]
        ).fetchone()
        return Node.from_row(row) if row else None
    
    def get_neighbors(
        self, 
        node_id: str, 
        edge_type: EdgeType | None = None,
        direction: str = "outgoing"  # outgoing, incoming, both
    ) -> list[Node]:
        """Get neighboring nodes."""
        if direction == "outgoing":
            query = "SELECT n.* FROM nodes n JOIN edges e ON n.id = e.target_id WHERE e.source_id = ?"
        elif direction == "incoming":
            query = "SELECT n.* FROM nodes n JOIN edges e ON n.id = e.source_id WHERE e.target_id = ?"
        else:
            query = """
                SELECT DISTINCT n.* FROM nodes n 
                JOIN edges e ON n.id = e.target_id OR n.id = e.source_id
                WHERE (e.source_id = ? OR e.target_id = ?) AND n.id != ?
            """
        
        if edge_type:
            query += f" AND e.type = '{edge_type.value}'"
        
        rows = self.conn.execute(query, [node_id]).fetchall()
        return [Node.from_row(r) for r in rows]
    
    # === Path Queries ===
    
    def find_path(
        self, 
        from_id: str, 
        to_id: str, 
        max_depth: int = 10
    ) -> list[list[str]] | None:
        """Find shortest path between two nodes."""
        result = self.conn.execute("""
            WITH RECURSIVE paths AS (
                SELECT 
                    source_id,
                    target_id,
                    [source_id, target_id] as path,
                    1 as depth
                FROM edges
                WHERE source_id = ?
                
                UNION ALL
                
                SELECT 
                    p.source_id,
                    e.target_id,
                    list_append(p.path, e.target_id),
                    p.depth + 1
                FROM paths p
                JOIN edges e ON p.target_id = e.source_id
                WHERE p.depth < ?
                  AND NOT list_contains(p.path, e.target_id)
            )
            SELECT path FROM paths
            WHERE target_id = ?
            ORDER BY depth
            LIMIT 1
        """, [from_id, max_depth, to_id]).fetchone()
        
        return result[0] if result else None
    
    def find_all_paths(
        self,
        from_id: str,
        to_id: str,
        max_depth: int = 5
    ) -> list[list[str]]:
        """Find all paths between two nodes."""
        # Similar to above but without LIMIT 1
        pass
    
    def get_dependency_tree(
        self, 
        node_id: str, 
        max_depth: int = 5,
        direction: str = "downstream"  # downstream or upstream
    ) -> dict:
        """Get full dependency tree as nested dict."""
        edge_direction = "target_id" if direction == "downstream" else "source_id"
        other_direction = "source_id" if direction == "downstream" else "target_id"
        
        result = self.conn.execute(f"""
            WITH RECURSIVE deps AS (
                SELECT 
                    e.{other_direction} as node_id,
                    e.type as edge_type,
                    1 as depth,
                    ['{node_id}', e.{other_direction}] as path
                FROM edges e
                WHERE e.{edge_direction} = ?
                
                UNION ALL
                
                SELECT
                    e.{other_direction},
                    e.type,
                    d.depth + 1,
                    list_append(d.path, e.{other_direction})
                FROM deps d
                JOIN edges e ON e.{edge_direction} = d.node_id
                WHERE d.depth < ?
                  AND NOT list_contains(d.path, e.{other_direction})
            )
            SELECT node_id, edge_type, depth, path
            FROM deps
            ORDER BY depth, node_id
        """, [node_id, max_depth]).fetchall()
        
        return self._build_tree(node_id, result)
    
    # === Vector Operations ===
    
    def add_embedding(
        self, 
        node_id: str, 
        embedding: list[float],
        embedding_type: str = "code"
    ):
        """Add or update embedding for a node."""
        column = f"{embedding_type}_embedding"
        self.conn.execute(f"""
            INSERT INTO embeddings (node_id, {column})
            VALUES (?, ?)
            ON CONFLICT (node_id) DO UPDATE SET {column} = ?
        """, [node_id, embedding, embedding])
    
    def vector_search(
        self,
        query_embedding: list[float],
        embedding_type: str = "code",
        limit: int = 10,
        node_type: NodeType | None = None
    ) -> list[tuple[Node, float]]:
        """Find similar nodes by vector similarity."""
        column = f"{embedding_type}_embedding"
        
        query = f"""
            SELECT 
                n.*,
                array_cosine_similarity(e.{column}, ?) as similarity
            FROM embeddings e
            JOIN nodes n ON n.id = e.node_id
            WHERE e.{column} IS NOT NULL
        """
        
        if node_type:
            query += f" AND n.type = '{node_type.value}'"
        
        query += f" ORDER BY similarity DESC LIMIT {limit}"
        
        rows = self.conn.execute(query, [query_embedding]).fetchall()
        return [(Node.from_row(r[:-1]), r[-1]) for r in rows]
    
    def semantic_search(
        self,
        query: str,
        limit: int = 10,
        node_type: NodeType | None = None
    ) -> list[tuple[Node, float]]:
        """Search nodes by natural language query."""
        query_embedding = self.embed(query)
        return self.vector_search(query_embedding, "code", limit, node_type)
    
    # === Temporal Operations ===
    
    def create_snapshot(self, commit_hash: str, commit_info: dict):
        """Create a temporal snapshot linked to git commit."""
        snapshot_id = f"snap_{commit_hash[:8]}"
        
        # Calculate deltas from previous snapshot
        prev = self._get_latest_snapshot()
        deltas = self._calculate_deltas(prev) if prev else {}
        
        self.conn.execute("""
            INSERT INTO snapshots 
            (id, commit_hash, commit_message, commit_author, commit_date,
             node_count, edge_count, nodes_added, nodes_removed, 
             nodes_modified, edges_added, edges_removed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            snapshot_id, commit_hash, 
            commit_info.get('message'), commit_info.get('author'),
            commit_info.get('date'),
            self.node_count(), self.edge_count(),
            deltas.get('nodes_added', 0), deltas.get('nodes_removed', 0),
            deltas.get('nodes_modified', 0), deltas.get('edges_added', 0),
            deltas.get('edges_removed', 0)
        ])
        
        # Record current state in history tables
        self._record_node_history(snapshot_id)
        self._record_edge_history(snapshot_id)
        
        return snapshot_id
    
    def at_commit(self, commit_hash: str) -> 'MUbaseSnapshot':
        """Get graph state at a specific commit."""
        return MUbaseSnapshot(self, commit_hash)
    
    def diff_commits(
        self, 
        from_commit: str, 
        to_commit: str
    ) -> GraphDiff:
        """Get semantic diff between two commits."""
        pass
    
    # === Export Operations ===
    
    def export_mu(
        self, 
        node_ids: list[str] | None = None,
        max_tokens: int | None = None
    ) -> str:
        """Export graph (or subgraph) as MU text format."""
        if node_ids:
            nodes = [self.get_node(id) for id in node_ids]
        else:
            nodes = self.get_all_nodes()
        
        if max_tokens:
            nodes = self._fit_to_tokens(nodes, max_tokens)
        
        return MUExporter().export(nodes, self)
    
    def export_json(self, node_ids: list[str] | None = None) -> dict:
        """Export graph as JSON."""
        pass
    
    def export_mermaid(self, node_ids: list[str] | None = None) -> str:
        """Export graph as Mermaid diagram."""
        pass
    
    def export_cytoscape(self, node_ids: list[str] | None = None) -> dict:
        """Export graph as Cytoscape-compatible JSON."""
        pass
    
    # === Smart Context ===
    
    def get_context_for_question(
        self,
        question: str,
        max_tokens: int = 8000
    ) -> ContextResult:
        """
        Extract optimal subgraph for answering a question.
        
        Combines:
        1. Entity extraction (mentioned names)
        2. Vector search (semantically relevant)
        3. Graph traversal (structurally connected)
        4. Token budgeting (fit to limit)
        """
        # 1. Extract entities from question
        entities = extract_entities(question)  # "AuthService", "Redis", etc.
        
        # 2. Find nodes by name match
        named_nodes = self.find_nodes_by_names(entities)
        
        # 3. Find semantically similar nodes
        similar_nodes = self.semantic_search(question, limit=20)
        
        # 4. Get structural context (neighbors of relevant nodes)
        seed_nodes = set(named_nodes + [n for n, _ in similar_nodes[:10]])
        expanded = set()
        for node_id in seed_nodes:
            neighbors = self.get_neighbors(node_id, direction="both")
            expanded.update(n.id for n in neighbors)
        
        all_relevant = seed_nodes | expanded
        
        # 5. Rank by relevance
        ranked = self._rank_nodes_for_question(
            list(all_relevant), 
            question,
            named_nodes
        )
        
        # 6. Fit to token budget
        fitted = self._fit_to_tokens(ranked, max_tokens)
        
        # 7. Export as MU
        mu_context = self.export_mu(node_ids=[n.id for n in fitted])
        
        return ContextResult(
            mu_text=mu_context,
            nodes=fitted,
            token_count=count_tokens(mu_context)
        )
    
    # === Stats ===
    
    def stats(self) -> dict:
        """Get database statistics."""
        return {
            "nodes": self.node_count(),
            "edges": self.edge_count(),
            "by_type": self._count_by_type(),
            "snapshots": self._snapshot_count(),
            "file_size_mb": self.path.stat().st_size / 1024 / 1024,
            "version": self.VERSION
        }
    
    def node_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    
    def edge_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
```

---

## 0.5 Query Language (MUQL)

### Grammar

```ebnf
(* MUQL - MU Query Language *)

query           = select_query | show_query | find_query | analyze_query ;

(* SELECT - Retrieve nodes with filters *)
select_query    = "SELECT" fields "FROM" node_type 
                  [where_clause] [order_clause] [limit_clause] ;
fields          = "*" | field_list ;
field_list      = field { "," field } ;
field           = identifier | aggregate ;
aggregate       = ("COUNT" | "AVG" | "MAX" | "MIN" | "SUM") "(" field ")" ;
node_type       = "functions" | "classes" | "modules" | "entities" | "externals" ;
where_clause    = "WHERE" condition ;
condition       = comparison { ("AND" | "OR") comparison } ;
comparison      = field operator value ;
operator        = "=" | "!=" | ">" | "<" | ">=" | "<=" 
                | "CONTAINS" | "LIKE" | "IN" | "SIMILAR TO" ;
value           = string | number | boolean | list ;
order_clause    = "ORDER BY" field ["ASC" | "DESC"] ;
limit_clause    = "LIMIT" number ;

(* SHOW - Display relationships *)
show_query      = "SHOW" show_type "OF" identifier [depth_clause] ;
show_type       = "dependencies" | "dependents" | "imports" | "callers" 
                | "callees" | "inheritance" | "implementations" ;
depth_clause    = "DEPTH" number ;

(* FIND - Pattern matching *)
find_query      = "FIND" node_type find_condition ;
find_condition  = "CALLING" identifier
                | "CALLED BY" identifier  
                | "IMPORTING" identifier
                | "IMPORTED BY" identifier
                | "SIMILAR TO" identifier
                | "IMPLEMENTING" identifier
                | "INHERITING" identifier
                | "MUTATING" identifier
                | "WITH" "DECORATOR" string
                | "WITH" "ANNOTATION" string
                | "MATCHING" pattern ;

(* PATH - Find paths between nodes *)
path_query      = "PATH" "FROM" identifier "TO" identifier 
                  ["MAX" "DEPTH" number] ["VIA" edge_type] ;

(* ANALYZE - Run analysis *)
analyze_query   = "ANALYZE" analysis_type ["FOR" identifier] ;
analysis_type   = "coupling" | "cohesion" | "complexity" | "hotspots"
                | "circular" | "unused" | "impact" ;

(* TEMPORAL - Time-based queries *)
temporal_query  = base_query "AT" commit_ref
                | base_query "BETWEEN" commit_ref "AND" commit_ref
                | "HISTORY OF" identifier
                | "BLAME" identifier ;
commit_ref      = string | "HEAD" | "HEAD~" number ;

(* Combined queries *)
combined_query  = select_query "AND" "SIMILAR TO" string  (* graph + vector *)
                | select_query "ADDED AFTER" date          (* graph + temporal *)
                | find_query "ADDED BY" string             (* pattern + temporal *)
                ;
```

### Examples

```sql
-- Basic SELECT
SELECT * FROM functions WHERE complexity > 500
SELECT name, complexity FROM functions ORDER BY complexity DESC LIMIT 10
SELECT COUNT(*) FROM classes WHERE is_abstract = true

-- SHOW relationships
SHOW dependencies OF AuthService
SHOW dependencies OF AuthService DEPTH 3
SHOW callers OF process_payment
SHOW inheritance OF AdminUser

-- FIND patterns  
FIND functions CALLING Redis
FIND functions CALLING Redis AND complexity > 100
FIND classes IMPLEMENTING Repository
FIND functions WITH DECORATOR "cache"
FIND functions MUTATING User

-- PATH queries
PATH FROM UserController TO Database
PATH FROM AuthService TO Redis MAX DEPTH 5

-- ANALYZE
ANALYZE coupling
ANALYZE complexity FOR src/services/
ANALYZE circular
ANALYZE impact FOR UserService  -- what breaks if this changes?

-- TEMPORAL
SELECT * FROM functions WHERE complexity > 500 AT HEAD~10
SHOW dependencies OF AuthService AT "abc123"
HISTORY OF AuthService
BLAME process_payment

-- Combined (graph + vector)
SELECT * FROM functions WHERE complexity > 100 AND SIMILAR TO "authentication"

-- Combined (graph + temporal)
FIND functions CALLING Redis ADDED AFTER "2024-01-01"
```

### Query Engine

```python
class MUQLEngine:
    """Execute MUQL queries against MUbase."""
    
    def __init__(self, mubase: MUbase):
        self.mubase = mubase
        self.parser = MUQLParser()
    
    def execute(self, query: str) -> QueryResult:
        """Parse and execute a MUQL query."""
        ast = self.parser.parse(query)
        plan = self.plan(ast)
        result = self.run(plan)
        return result
    
    def plan(self, ast: QueryAST) -> ExecutionPlan:
        """Create execution plan from AST."""
        match ast.type:
            case "select":
                return SelectPlan(ast)
            case "show":
                return ShowPlan(ast)
            case "find":
                return FindPlan(ast)
            case "path":
                return PathPlan(ast)
            case "analyze":
                return AnalyzePlan(ast)
            case "temporal":
                return TemporalPlan(ast)
            case "combined":
                return CombinedPlan(ast)
    
    def run(self, plan: ExecutionPlan) -> QueryResult:
        """Execute the plan."""
        # Convert to DuckDB SQL + vector operations
        sql = plan.to_sql()
        
        if plan.needs_vector_search:
            # Hybrid: run vector search first, then SQL
            vector_results = self.mubase.vector_search(
                plan.vector_query,
                limit=plan.vector_limit
            )
            sql = plan.to_sql_with_vector_filter(vector_results)
        
        rows = self.mubase.conn.execute(sql).fetchall()
        
        return QueryResult(
            columns=plan.columns,
            rows=[dict(zip(plan.columns, row)) for row in rows],
            total=len(rows),
            execution_time_ms=plan.execution_time
        )
```

---

## 0.6 CLI Commands

```bash
# Initialize MUbase
mu init [path]                    # Create .mubase in current/specified directory
mu init --from-git                # Initialize with full git history

# Build/Update graph
mu build [path]                   # Build/rebuild entire graph
mu build --incremental            # Only update changed files
mu sync                           # Sync with latest git changes

# Query
mu query "<MUQL>"                 # Execute MUQL query
mu query --interactive            # Enter MUQL REPL
mu query --file queries.muql      # Run queries from file

# Export
mu export [--format mu|json|mermaid|cytoscape]
mu export --nodes <ids>           # Export specific nodes
mu export --context "<question>"  # Smart context for question

# Daemon
mu daemon                         # Start watch daemon
mu daemon --serve 8080            # With HTTP server
mu daemon --ws                    # With WebSocket

# Analysis
mu analyze coupling               # Run coupling analysis
mu analyze complexity             # Complexity hotspots
mu analyze circular               # Find circular dependencies
mu analyze impact <node>          # Impact analysis

# Temporal
mu history <node>                 # Show history of node
mu blame <node>                   # Show who changed what
mu diff <commit1> <commit2>       # Semantic diff
mu at <commit> query "<MUQL>"     # Query at point in time

# Info
mu status                         # Show graph stats
mu info <node>                    # Detailed node info
mu tree <node>                    # Show dependency tree
```

---

# Phase 1: Launch (This Weekend)

## 1.1 MVP Scope

Ship with:
- [x] `mu init` - Create .mubase
- [x] `mu build` - Populate graph from codebase
- [x] `mu query` - Basic MUQL (SELECT, SHOW, FIND)
- [x] `mu export --format mu` - Export to MU text
- [x] `mu status` - Graph stats

Defer to Phase 2:
- [ ] Vector embeddings (requires API key or local model)
- [ ] Temporal snapshots (requires git integration)
- [ ] Daemon mode

## 1.2 Launch Checklist

- [ ] PyPI package `mu-cli`
- [ ] GitHub repository
- [ ] README with examples
- [ ] Demo video
- [ ] Launch posts (Reddit, HN, Twitter)

---

# Phase 2: Power Features

## 2.1 Vector Layer

**Timeline**: Week 1-2 after launch

- [ ] OpenAI embeddings (text-embedding-3-small)
- [ ] Local embeddings fallback (sentence-transformers)
- [ ] `mu embed` command
- [ ] Semantic search in MUQL (`SIMILAR TO`)
- [ ] Smart context extraction

## 2.2 Temporal Layer

**Timeline**: Week 2-3

- [ ] Git integration
- [ ] Automatic snapshots on commit
- [ ] `mu history` / `mu blame`
- [ ] Temporal MUQL (`AT`, `BETWEEN`)
- [ ] `mu diff` (semantic diff)

## 2.3 Daemon Mode

**Timeline**: Week 3-4

- [ ] File watcher integration
- [ ] Incremental graph updates
- [ ] HTTP API server
- [ ] WebSocket live updates
- [ ] IDE integration endpoints

---

# Phase 3: Ecosystem

## 3.1 MU Contracts

Architecture verification using graph queries:

```yaml
# .mu-contracts.yml
contracts:
  - name: "No circular dependencies"
    query: "ANALYZE circular"
    expect: empty
    severity: error

  - name: "Controllers don't call repositories directly"
    query: |
      FIND functions 
      IN "src/controllers/**" 
      CALLING ANY IN "src/repositories/**"
    expect: empty
    severity: error

  - name: "All services have < 500 complexity"
    query: |
      SELECT * FROM functions 
      WHERE module LIKE 'src/services/%' 
      AND complexity > 500
    expect: empty
    severity: warning
```

## 3.2 MU Onboard

Interactive exploration powered by graph:

```
┌─────────────────────────────────────────────────────────────┐
│  MU Onboard - Exploring: AuthService                        │
│━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━│
│                                                             │
│  Dependencies (SHOW dependencies OF AuthService):           │
│  AuthService                                                │
│  ├── UserRepository (internal)                              │
│  │   └── Database (external: sqlalchemy)                    │
│  ├── TokenService (internal)                                │
│  │   └── jwt (external)                                     │
│  └── CacheService (internal)                                │
│       └── Redis (external)                                  │
│                                                             │
│  Used By (SHOW dependents OF AuthService):                  │
│  ├── AuthController                                         │
│  ├── WebSocketHandler                                       │
│  └── BackgroundWorker                                       │
│                                                             │
│  [d] Dive into dependency  [q] Query  [?] Ask AI           │
└─────────────────────────────────────────────────────────────┘
```

## 3.3 IDE Integration

VS Code extension with:
- MUbase explorer sidebar
- Inline complexity badges
- "Show dependencies" context menu
- MUQL query palette
- Smart context for Copilot/Claude

## 3.4 Visualization

Web UI for graph exploration:
- Cytoscape.js rendering
- Filter by type, complexity, module
- Path highlighting
- Time-travel slider
- Export to SVG/PNG

---

# Phase 4: Moonshot

## 4.1 MU Cloud

Hosted MUbase with:
- GitHub/GitLab sync
- Team collaboration
- Cross-repo search
- Historical analytics
- API access

## 4.2 MU Index

Public registry:
- Open source codebases indexed
- "How does X implement auth?"
- Learn from the ecosystem

## 4.3 Bidirectional MU

MU spec → Generated code:
- Write intent in MU-like spec
- Graph validates consistency
- LLM generates implementation
- Graph verifies result matches spec

---

# Technical Decisions

## Why DuckDB?

| Requirement | DuckDB | SQLite | PostgreSQL |
|-------------|--------|--------|------------|
| Embedded (single file) | ✅ | ✅ | ❌ |
| Zero dependencies | ✅ | ✅ | ❌ |
| Analytical queries | ✅✅ | ⚠️ | ✅ |
| Vector extensions | ✅ | ⚠️ | ✅ |
| Recursive CTEs | ✅ | ✅ | ✅ |
| JSON support | ✅✅ | ⚠️ | ✅ |
| Python native | ✅ | ✅ | ❌ |
| Performance at scale | ✅✅ | ⚠️ | ✅✅ |

**Winner: DuckDB** - Best of both worlds (embedded + analytical power)

## Why Not Neo4j?

Neo4j is excellent but:
- Requires running server
- Heavier deployment
- Overkill for single-codebase use case

**Future**: Optional Neo4j backend for MU Cloud (multi-repo, team features)

## Embedding Strategy

**Default**: OpenAI text-embedding-3-small
- 1536 dimensions
- $0.02 / 1M tokens
- Best quality/cost ratio

**Local fallback**: sentence-transformers/all-MiniLM-L6-v2
- 384 dimensions
- Free, runs locally
- Good enough for most use cases

**Configuration**:
```toml
# .murc.toml
[embeddings]
provider = "openai"  # or "local"
model = "text-embedding-3-small"
```

---

# Success Metrics

## Phase 0-1 (Launch)
- [ ] 1,000 GitHub stars
- [ ] 500 PyPI downloads/week
- [ ] 10 community issues/PRs
- [ ] 1 tech blog mention

## Phase 2 (Power)
- [ ] 5,000 stars
- [ ] 5,000 downloads/week
- [ ] 3 enterprise inquiries
- [ ] Integration with 1 AI coding tool

## Phase 3 (Ecosystem)
- [ ] 20,000 stars
- [ ] 50,000 downloads/week
- [ ] VS Code extension: 1,000 installs
- [ ] 100 projects in MU Index

## Phase 4 (Moonshot)
- [ ] Industry recognition as standard
- [ ] Acquisition interest OR $1M ARR
- [ ] Integration with major AI tools

---

# Appendix

## A. Full Schema SQL

```sql
-- See section 0.1-0.3 for complete schema
```

## B. API Reference

### HTTP API (Daemon Mode)

```
GET  /status                    # Graph stats
GET  /nodes/{id}                # Get node
GET  /nodes/{id}/neighbors      # Get neighbors
POST /query                     # Execute MUQL
POST /search                    # Semantic search
POST /context                   # Smart context extraction
GET  /export?format=mu          # Export graph
WS   /live                      # Real-time updates
```

### Python API

```python
from mu import MUbase

# Open/create database
db = MUbase(".mubase")

# Build from codebase
db.build("./src")

# Query
result = db.query("SELECT * FROM functions WHERE complexity > 500")

# Semantic search
similar = db.search("authentication logic")

# Smart context
context = db.get_context_for_question("How does auth work?")

# Export
mu_text = db.export_mu()
```

## C. Migration from v1 (Text-based)

```bash
# Old way (still works)
mu compress ./src --output system.mu

# New way (graph-first)
mu init
mu build ./src
mu export --format mu > system.mu

# The export is identical, but now you have queryable graph
```

---

*Document version: 3.0 DIVINE EDITION*
*Last updated: 2025-12-06*
*Author: Yavor Kangalov / MOESIA VCC*
