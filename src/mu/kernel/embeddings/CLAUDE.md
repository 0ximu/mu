# Embeddings Module - Vector Embeddings for Semantic Search

The embeddings module provides vector embedding generation and semantic search for code nodes in MUbase.

## Architecture

```
Node → EmbeddingService → Provider → Vector → MUbase Storage → Vector Search
        (async batch)     (OpenAI/   (float[])   (DuckDB)      (cosine sim)
                          Local)
```

### Files

| File | Purpose |
|------|---------|
| `models.py` | `NodeEmbedding`, `EmbeddingStats` dataclasses |
| `service.py` | `EmbeddingService` - batch embedding orchestration |
| `providers/base.py` | `EmbeddingProvider` protocol, result types |
| `providers/openai.py` | OpenAI API provider (text-embedding-3-small) |
| `providers/local.py` | sentence-transformers provider (all-MiniLM-L6-v2) |
| `__init__.py` | Public API exports |

## Key Classes

### `EmbeddingService`

Orchestrates embedding generation for code nodes.

```python
service = EmbeddingService(provider="openai")

# Single node
embedding = await service.embed_node(node)

# Batch with progress
embeddings = await service.embed_nodes(
    nodes,
    batch_size=100,
    on_progress=lambda cur, total: print(f"{cur}/{total}")
)

# Query embedding
query_vec = await service.embed_query("authentication logic")
```

### `EmbeddingProvider` Protocol

All providers implement:

```python
class EmbeddingProvider(Protocol):
    @property
    def dimensions(self) -> int: ...
    @property
    def model_name(self) -> str: ...
    async def embed(self, text: str) -> EmbeddingResult: ...
    async def embed_batch(self, texts: list[str]) -> BatchEmbeddingResult: ...
```

### `NodeEmbedding`

Stores embeddings for a node:

```python
@dataclass
class NodeEmbedding:
    node_id: str
    code_embedding: list[float] | None      # From code/signature
    docstring_embedding: list[float] | None # From docstring
    name_embedding: list[float] | None      # From qualified name
    model_name: str
    model_version: str
    dimensions: int
    created_at: datetime
```

## Provider Details

### OpenAI Provider

- Model: `text-embedding-3-small` (1536 dimensions)
- Max batch: 2048 texts per request
- Rate limiting: Exponential backoff on 429
- Requires: `OPENAI_API_KEY` environment variable

### Local Provider

- Model: `all-MiniLM-L6-v2` (384 dimensions)
- Lazy model loading (first use)
- GPU detection: CUDA > MPS > CPU
- Requires: `pip install sentence-transformers`

## Text Generation Strategies

Different node types generate different text for embedding:

| Node Type | Text Strategy |
|-----------|---------------|
| Function | signature + docstring + first 500 chars of body |
| Class | name + docstring + method signatures |
| Module | docstring + export names |
| External | qualified name only |

## Usage Patterns

### Embedding a Codebase

```python
from mu.kernel import MUbase, EmbeddingService

async def embed_codebase(path: Path):
    db = MUbase(path / ".mubase")
    service = EmbeddingService(provider="openai")

    nodes = db.get_nodes()
    embeddings = await service.embed_nodes(nodes)
    db.add_embeddings_batch(embeddings)

    await service.close()
    db.close()
```

### Semantic Search

```python
async def search(db: MUbase, query: str):
    service = EmbeddingService(provider="openai")
    query_vec = await service.embed_query(query)

    results = db.vector_search(
        query_embedding=query_vec,
        embedding_type="code",
        limit=10
    )

    for node, similarity in results:
        print(f"{node.name}: {similarity:.3f}")
```

## Anti-Patterns

1. **Never** call embedding APIs synchronously - always use async
2. **Never** embed empty or whitespace-only text - providers reject it
3. **Never** mix embeddings from different models in search - dimensions differ
4. **Never** hardcode API keys - use environment variables

## Configuration

```toml
# .murc.toml
[embeddings]
provider = "openai"  # or "local"
model = "text-embedding-3-small"
batch_size = 100

[embeddings.openai]
api_key_env = "OPENAI_API_KEY"

[embeddings.local]
model = "all-MiniLM-L6-v2"
device = "auto"
```

## Testing

```bash
pytest tests/unit/test_embeddings.py -v
```

Tests mock all external API calls - no real OpenAI requests made.

## Related

- [ADR-0004: Vector Embeddings](/docs/adr/0004-vector-embeddings-for-semantic-search.md)
- [Epic 01: Vector Layer](/docs/epics/01-vector-layer.md)
- [Kernel Module](/src/mu/kernel/CLAUDE.md)
