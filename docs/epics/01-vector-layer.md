# Epic 1: Vector Layer

**Priority**: P1 - Critical for semantic search and smart context
**Dependencies**: Kernel (complete)
**Estimated Complexity**: Medium
**PRD Reference**: Section 0.2

---

## Overview

Add vector embeddings to MUbase for semantic code search. This enables finding code by meaning rather than just structure, and is foundational for the Smart Context feature.

## Goals

1. Generate embeddings for all code nodes (functions, classes, modules)
2. Store embeddings efficiently in DuckDB with vector indexing
3. Enable semantic similarity search via API and CLI
4. Support both OpenAI and local embedding models

---

## User Stories

### Story 1.1: Embedding Schema
**As a** developer
**I want** embeddings stored alongside graph nodes
**So that** I can query by semantic similarity

**Acceptance Criteria**:
- [ ] `embeddings` table added to MUbase schema
- [ ] Support for multiple embedding types (code, docstring, name)
- [ ] Efficient storage using DuckDB array types
- [ ] Migration path for existing .mubase files

### Story 1.2: Embedding Service
**As a** developer
**I want** automatic embedding generation
**So that** my codebase is searchable without manual setup

**Acceptance Criteria**:
- [ ] `EmbeddingService` class with async batch processing
- [ ] OpenAI provider (text-embedding-3-small)
- [ ] Local provider fallback (sentence-transformers)
- [ ] Configuration via `.murc.toml`
- [ ] Rate limiting and retry logic for API calls

### Story 1.3: Vector Search API
**As a** developer
**I want** to search code semantically
**So that** I can find relevant code by description

**Acceptance Criteria**:
- [ ] `MUbase.vector_search(embedding, limit, node_type)` method
- [ ] `MUbase.semantic_search(query_text, limit)` convenience method
- [ ] Cosine similarity scoring
- [ ] Filter by node type (function, class, module)

### Story 1.4: CLI Integration
**As a** developer
**I want** CLI commands for embedding and search
**So that** I can use semantic features from terminal

**Acceptance Criteria**:
- [ ] `mu kernel embed [path]` - Generate embeddings for codebase
- [ ] `mu kernel search "<query>"` - Semantic search
- [ ] `--local` flag to force local embeddings
- [ ] Progress indicator for embedding generation

---

## Technical Design

### Schema Addition

```sql
-- Add to existing schema in schema.py
CREATE TABLE embeddings (
    node_id VARCHAR PRIMARY KEY REFERENCES nodes(id),
    code_embedding FLOAT[],        -- Variable size based on model
    docstring_embedding FLOAT[],
    name_embedding FLOAT[],
    model_name VARCHAR,
    model_version VARCHAR,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_embeddings_node ON embeddings(node_id);
```

### File Structure

```
src/mu/kernel/
├── embeddings/
│   ├── __init__.py          # Public API
│   ├── service.py           # EmbeddingService class
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py          # EmbeddingProvider protocol
│   │   ├── openai.py        # OpenAI provider
│   │   └── local.py         # Sentence-transformers provider
│   └── models.py            # Embedding dataclasses
```

### EmbeddingService Interface

```python
from dataclasses import dataclass
from typing import Protocol

class EmbeddingProvider(Protocol):
    """Protocol for embedding providers."""

    @property
    def dimensions(self) -> int: ...

    async def embed(self, text: str) -> list[float]: ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class NodeEmbeddings:
    """Embeddings for a single node."""
    node_id: str
    code_embedding: list[float] | None
    docstring_embedding: list[float] | None
    name_embedding: list[float] | None
    model_name: str
    model_version: str


class EmbeddingService:
    """Generate and manage embeddings for code nodes."""

    def __init__(
        self,
        provider: str = "openai",  # or "local"
        model: str | None = None,
    ):
        self.provider = self._create_provider(provider, model)

    async def embed_node(self, node: Node) -> NodeEmbeddings:
        """Generate all embeddings for a node."""
        ...

    async def embed_nodes(
        self,
        nodes: list[Node],
        batch_size: int = 100,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[NodeEmbeddings]:
        """Batch embed multiple nodes with progress callback."""
        ...

    def _create_text_for_embedding(self, node: Node) -> str:
        """Create embedding-optimized text representation."""
        ...
```

### MUbase Extensions

```python
# Add to mubase.py

def add_embedding(self, embedding: NodeEmbeddings) -> None:
    """Store embedding for a node."""
    ...

def get_embedding(self, node_id: str) -> NodeEmbeddings | None:
    """Retrieve embedding for a node."""
    ...

def vector_search(
    self,
    query_embedding: list[float],
    embedding_type: str = "code",
    limit: int = 10,
    node_type: NodeType | None = None,
) -> list[tuple[Node, float]]:
    """Find similar nodes by vector similarity."""
    ...

def semantic_search(
    self,
    query: str,
    limit: int = 10,
    node_type: NodeType | None = None,
) -> list[tuple[Node, float]]:
    """Search nodes by natural language query."""
    ...

def embedding_stats(self) -> dict:
    """Get embedding coverage statistics."""
    ...
```

---

## Implementation Plan

### Phase 1: Schema & Storage (Day 1)
1. Add `embeddings` table to `schema.py`
2. Update `MUbase._create_schema()` for new table
3. Add migration logic for existing databases
4. Create `NodeEmbeddings` dataclass in `models.py`
5. Implement `add_embedding()` and `get_embedding()` in `mubase.py`

### Phase 2: Providers (Day 1-2)
1. Create `EmbeddingProvider` protocol
2. Implement `OpenAIProvider` with:
   - Async HTTP calls via `httpx`
   - Batch processing (up to 2048 texts per call)
   - Rate limiting (3000 RPM for tier 1)
   - Retry with exponential backoff
3. Implement `LocalProvider` with:
   - Lazy loading of sentence-transformers
   - GPU detection and fallback to CPU
   - Batch processing

### Phase 3: Service Layer (Day 2)
1. Create `EmbeddingService` class
2. Implement node text generation strategies:
   - Functions: signature + docstring + body summary
   - Classes: name + docstring + method signatures
   - Modules: docstring + exports
3. Implement batch processing with progress callbacks
4. Add caching to avoid re-embedding unchanged nodes

### Phase 4: Search (Day 2-3)
1. Implement `vector_search()` using DuckDB array functions
2. Add `semantic_search()` convenience wrapper
3. Implement result ranking and filtering
4. Add vector index creation (optional, for large codebases)

### Phase 5: CLI (Day 3)
1. Add `mu kernel embed` command
2. Add `mu kernel search` command
3. Add configuration options to `.murc.toml`
4. Add `--provider` and `--model` flags

### Phase 6: Testing (Day 3)
1. Unit tests for providers (with mocking)
2. Integration tests for embedding storage
3. Search quality tests with known-similar functions
4. Performance benchmarks for batch embedding

---

## Configuration

```toml
# .murc.toml
[embeddings]
provider = "openai"              # or "local"
model = "text-embedding-3-small" # or "all-MiniLM-L6-v2"
batch_size = 100
cache_embeddings = true

[embeddings.openai]
api_key_env = "OPENAI_API_KEY"   # Environment variable name
dimensions = 1536                 # Can reduce for cost savings

[embeddings.local]
model = "sentence-transformers/all-MiniLM-L6-v2"
device = "auto"                   # auto, cpu, cuda, mps
```

---

## Testing Strategy

### Unit Tests
```python
def test_openai_provider_batch():
    """Test OpenAI batch embedding."""
    ...

def test_local_provider_dimensions():
    """Test local model produces correct dimensions."""
    ...

def test_embedding_storage_roundtrip():
    """Test store and retrieve embeddings."""
    ...
```

### Integration Tests
```python
def test_embed_codebase():
    """Test embedding a full codebase."""
    ...

def test_semantic_search_finds_similar():
    """Test that similar functions are found."""
    # Create two auth functions, verify they're similar
    ...
```

---

## Success Criteria

- [ ] Embeddings generated for 100% of code nodes
- [ ] Search returns relevant results (manual verification)
- [ ] OpenAI embedding cost < $1 for typical codebase (10k nodes)
- [ ] Local embedding time < 5 minutes for 10k nodes
- [ ] All existing tests continue to pass

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| OpenAI API rate limits | Medium | Implement proper rate limiting, use batch API |
| Local model quality | Low | Sentence-transformers is proven; fallback only |
| Large codebases | Medium | Add incremental embedding, skip unchanged |
| DuckDB vector perf | Low | DuckDB handles arrays well; add HNSW if needed |

---

## Open Questions

1. Should we embed function bodies or just signatures?
   - **Recommendation**: Signature + docstring + first 500 chars of body

2. How to handle embedding dimension mismatch when switching models?
   - **Recommendation**: Store model info, re-embed on model change

3. Should embeddings be in separate file for portability?
   - **Recommendation**: Keep in .mubase for simplicity; reconsider if file size is issue
