# ADR-0004: Vector Embeddings for Semantic Search

## Status

Accepted

## Date

2025-12-06

## Context

MU provides structural code analysis through the kernel module (graph database), but users need to find code by meaning, not just by name or structure. For example, finding "functions that handle authentication" even if they don't contain the word "authentication" in their names.

The Smart Context feature (Epic 03) depends on semantic search capabilities to provide relevant code context to LLMs. This requires vector embeddings of code nodes.

Key requirements:
1. Generate embeddings for all code nodes (functions, classes, modules)
2. Store embeddings efficiently alongside the existing graph database
3. Support both cloud (OpenAI) and local (sentence-transformers) embedding models
4. Enable semantic similarity search via API and CLI

## Decision

Implement a vector embedding layer within the kernel module with the following architecture:

### Storage

Store embeddings in the existing DuckDB `.mubase` file using `FLOAT[]` array columns:

```sql
CREATE TABLE embeddings (
    node_id VARCHAR PRIMARY KEY REFERENCES nodes(id),
    code_embedding FLOAT[],
    docstring_embedding FLOAT[],
    name_embedding FLOAT[],
    model_name VARCHAR,
    model_version VARCHAR,
    dimensions INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);
```

This approach:
- Keeps embeddings co-located with graph data (single file)
- Uses DuckDB's native array types for efficient vector operations
- Supports multiple embedding types per node for different search strategies

### Provider Architecture

Use a Protocol-based provider system:

```python
class EmbeddingProvider(Protocol):
    @property
    def dimensions(self) -> int: ...
    @property
    def model_name(self) -> str: ...
    async def embed(self, text: str) -> EmbeddingResult: ...
    async def embed_batch(self, texts: list[str]) -> BatchEmbeddingResult: ...
```

Two implementations:
1. **OpenAIEmbeddingProvider**: Uses `text-embedding-3-small` via httpx (async HTTP)
2. **LocalEmbeddingProvider**: Uses sentence-transformers with lazy loading

### Similarity Search

Use DuckDB's `list_cosine_similarity()` function for vector search:

```python
def vector_search(
    self,
    query_embedding: list[float],
    embedding_type: str = "code",
    limit: int = 10,
    node_type: NodeType | None = None,
) -> list[tuple[Node, float]]:
```

This leverages DuckDB's columnar storage and vectorized execution for efficient similarity computation.

## Consequences

### Positive

- **Single-file deployment**: Embeddings stored in `.mubase` file, no separate vector database needed
- **Provider flexibility**: Easy to add new embedding providers (Cohere, local models)
- **Async-first**: All API calls are async, matching existing LLM patterns
- **Cost control**: Local embeddings available for offline/cost-sensitive use cases
- **Incremental**: Can embed nodes incrementally as code changes

### Negative

- **File size**: Embeddings add ~6KB per node (1536 floats x 4 bytes), so a 10K node codebase adds ~60MB
- **Model lock-in**: Changing embedding models requires re-embedding (dimensions may differ)
- **No HNSW index**: DuckDB doesn't support approximate nearest neighbor indices; linear scan for now

### Neutral

- **External dependency**: OpenAI provider requires API key; local requires sentence-transformers install
- **GPU optional**: Local provider works on CPU but benefits from GPU acceleration

## Alternatives Considered

### Alternative 1: Separate Vector Database (Qdrant/Pinecone)

**Pros:**
- Purpose-built for vector search
- Scalable to millions of vectors
- HNSW/ANNS support

**Cons:**
- Additional deployment complexity
- Network latency for searches
- Cost for managed services

**Why rejected:** MU targets individual codebases (typically <100K nodes), where DuckDB's linear scan is sufficient (<100ms). Adding a separate database increases deployment friction.

### Alternative 2: SQLite with sqlite-vss

**Pros:**
- Lightweight, embedded
- VSS extension adds vector support

**Cons:**
- Less mature than DuckDB
- Requires compiling native extension
- No async support

**Why rejected:** DuckDB already used for graph storage; native array support is simpler than adding another database.

### Alternative 3: In-Memory Only (NumPy/FAISS)

**Pros:**
- Fast FAISS index for large datasets
- No persistence overhead

**Cons:**
- Must regenerate embeddings on every load
- No incremental updates

**Why rejected:** Persistence is essential for large codebases where embedding takes minutes.

## References

- [Epic 01: Vector Layer](/docs/epics/01-vector-layer.md)
- [PRD Section 0.2: Semantic Search](/docs/INITIAL%20+%20PRD/mu-prd-v3-divine.md)
- [OpenAI Embeddings API](https://platform.openai.com/docs/guides/embeddings)
- [Sentence-Transformers](https://www.sbert.net/)
- [DuckDB Array Functions](https://duckdb.org/docs/sql/functions/nested.html)
