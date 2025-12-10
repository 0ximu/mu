# Vector Layer - Task Breakdown

## Business Context

**Problem**: Developers need to find code by meaning, not just by name or structure. Currently, MU provides excellent structural analysis but lacks semantic search capabilities.

**Outcome**: Enable semantic code search via embeddings, allowing queries like "find functions that handle authentication" to return relevant code even if it does not contain the word "authentication."

**Users**:
- Developers exploring unfamiliar codebases
- AI agents needing relevant context for code generation
- Code reviewers looking for similar implementations

---

## Discovered Patterns

### Pattern 1: Kernel Module Structure
- **Location**: `/Users/imu/Dev/work/mu/src/mu/kernel/`
- **Description**: The kernel module follows a clean separation pattern:
  - `schema.py` - Enums and SQL DDL definitions
  - `models.py` - Dataclasses with `to_dict()`, `to_tuple()`, `from_row()` methods
  - `mubase.py` - Main database class with DuckDB connection management
  - `builder.py` - Transformation logic from parser output to graph structures
  - `__init__.py` - Public API exports
- **Relevance**: Embeddings submodule should mirror this structure within `src/mu/kernel/embeddings/`

### Pattern 2: Dataclass Model with Serialization
- **Location**: `/Users/imu/Dev/work/mu/src/mu/kernel/models.py:16-83`
- **Description**: Models use `@dataclass` with explicit methods:
  ```python
  @dataclass
  class Node:
      id: str
      type: NodeType
      name: str
      # ...

      def to_tuple(self) -> tuple[...]:
          """Convert to tuple for DuckDB insertion."""

      def to_dict(self) -> dict[str, Any]:
          """Convert to dictionary for JSON serialization."""

      @classmethod
      def from_row(cls, row: tuple[Any, ...]) -> Node:
          """Create from DuckDB row."""
  ```
- **Relevance**: `NodeEmbedding` dataclass should follow this exact pattern

### Pattern 3: DuckDB Schema Definition
- **Location**: `/Users/imu/Dev/work/mu/src/mu/kernel/schema.py:32-76`
- **Description**: Schema uses raw SQL string with:
  - `CREATE TABLE IF NOT EXISTS` for idempotency
  - Appropriate indexes for common queries
  - VARCHAR for enum types (DuckDB pattern)
  - JSON type for flexible properties
- **Relevance**: Embeddings table schema should use DuckDB array types for vectors

### Pattern 4: MUbase Database Wrapper
- **Location**: `/Users/imu/Dev/work/mu/src/mu/kernel/mubase.py:22-530`
- **Description**: Database wrapper pattern:
  - `VERSION` class attribute for schema versioning
  - `__init__` connects and initializes schema
  - `_init_schema()` checks version, migrates if needed
  - `_create_schema()` executes DDL
  - `close()` and context manager support
  - Query methods return typed dataclass instances
- **Relevance**: MUbase will be extended with embedding methods following existing query patterns

### Pattern 5: Async Pool Pattern (LLM Module)
- **Location**: `/Users/imu/Dev/work/mu/src/mu/llm/pool.py:36-318`
- **Description**: LLMPool provides async batch processing with:
  - Semaphore for concurrency control
  - Progress callback support
  - Two-tier caching (persistent + memory)
  - Retry logic with exponential backoff
  - Stats tracking via `LLMStats` dataclass
- **Relevance**: `EmbeddingService` should follow identical async batch pattern

### Pattern 6: Provider Protocol Pattern
- **Location**: `/Users/imu/Dev/work/mu/src/mu/llm/types.py:9-16`
- **Description**: Providers defined as string enum:
  ```python
  class LLMProvider(str, Enum):
      ANTHROPIC = "anthropic"
      OPENAI = "openai"
      OLLAMA = "ollama"
  ```
- **Relevance**: `EmbeddingProvider` enum should follow same pattern; actual providers implement async interface

### Pattern 7: Request/Result Dataclasses
- **Location**: `/Users/imu/Dev/work/mu/src/mu/llm/types.py:18-44`
- **Description**: Request/Result pairs with:
  - Request: input data needed for operation
  - Result: output with success property, optional error field
  ```python
  @dataclass
  class SummarizationResult:
      function_name: str
      summary: list[str]
      tokens_used: int
      model: str
      cached: bool = False
      error: str | None = None

      @property
      def success(self) -> bool:
          return self.error is None and len(self.summary) > 0
  ```
- **Relevance**: Use same pattern for `EmbeddingRequest` and `EmbeddingResult`

### Pattern 8: CLI Command Group Pattern
- **Location**: `/Users/imu/Dev/work/mu/src/mu/cli.py:822-828`
- **Description**: Subcommands via Click groups:
  ```python
  @cli.group()
  def kernel() -> None:
      """MU Kernel commands (graph database)."""
      pass

  @kernel.command("build")
  @click.argument("path", ...)
  def kernel_build(ctx: MUContext, path: Path, ...) -> None:
      ...
  ```
- **Relevance**: Add `kernel_embed` and `kernel_search` commands following this pattern

### Pattern 9: Configuration via Pydantic
- **Location**: `/Users/imu/Dev/work/mu/src/mu/config.py:82-108`
- **Description**: Config sections as Pydantic models with defaults:
  ```python
  class LLMConfig(BaseModel):
      enabled: bool = Field(default=False, description="...")
      provider: Literal["anthropic", "openai", "ollama"] = Field(...)
      model: str = Field(default="claude-3-haiku-20240307", ...)
  ```
- **Relevance**: Add `EmbeddingsConfig` following same pattern

### Pattern 10: Test Structure
- **Location**: `/Users/imu/Dev/work/mu/tests/unit/test_kernel.py`
- **Description**: Tests organized by class:
  - `TestSchema` - enum definitions
  - `TestNodeModel` - dataclass serialization
  - `TestGraphBuilder` - transformation logic
  - `TestMUbase` - database operations with fixtures
  - `TestBuildIntegration` - end-to-end workflows
- **Relevance**: Embedding tests should follow: `TestEmbeddingModels`, `TestEmbeddingService`, `TestEmbeddingProviders`, `TestMUbaseEmbeddings`

---

## Task Breakdown

### Task 1: Add Embeddings Schema and Model
**Status**: COMPLETE

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/embeddings/__init__.py` (create)
- `/Users/imu/Dev/work/mu/src/mu/kernel/embeddings/models.py` (create)
- `/Users/imu/Dev/work/mu/src/mu/kernel/schema.py` (modify)

**Dependencies**: None

**Pattern to Follow**:
- Dataclass pattern from `/Users/imu/Dev/work/mu/src/mu/kernel/models.py:16-83`
- Schema pattern from `/Users/imu/Dev/work/mu/src/mu/kernel/schema.py:32-76`

**Details**:
- [x] Create `NodeEmbedding` dataclass with fields:
  - `node_id: str` (FK to nodes table)
  - `code_embedding: list[float] | None`
  - `docstring_embedding: list[float] | None`
  - `name_embedding: list[float] | None`
  - `model_name: str`
  - `model_version: str`
  - `dimensions: int`
  - `created_at: datetime`
- [x] Implement `to_tuple()`, `to_dict()`, `from_row()` methods
- [x] Add SQL DDL for embeddings table to `SCHEMA_SQL` or new `EMBEDDINGS_SCHEMA_SQL`
- [x] Use `FLOAT[]` array type for DuckDB vector storage
- [x] Add index on `node_id` for efficient joins

**Acceptance Criteria**:
- [x] `NodeEmbedding` dataclass serializes to/from DuckDB correctly
- [x] Schema creates `embeddings` table with proper foreign key relationship
- [x] Array columns store vectors of variable dimensions

---

### Task 2: Create Embedding Provider Interface
**Status**: COMPLETE

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/embeddings/providers/__init__.py` (create)
- `/Users/imu/Dev/work/mu/src/mu/kernel/embeddings/providers/base.py` (create)
- `/Users/imu/Dev/work/mu/src/mu/kernel/embeddings/providers/openai.py` (create)
- `/Users/imu/Dev/work/mu/src/mu/kernel/embeddings/providers/local.py` (create)

**Dependencies**: None (can run in parallel with Task 1)

**Pattern to Follow**:
- Provider enum from `/Users/imu/Dev/work/mu/src/mu/llm/types.py:9-16`
- Model config from `/Users/imu/Dev/work/mu/src/mu/llm/providers.py:11-22`

**Details**:
- [x] Create `EmbeddingProviderType` enum: `OPENAI = "openai"`, `LOCAL = "local"`
- [x] Define `EmbeddingProvider` Protocol:
  ```python
  class EmbeddingProvider(Protocol):
      @property
      def dimensions(self) -> int: ...
      @property
      def model_name(self) -> str: ...
      async def embed(self, text: str) -> list[float]: ...
      async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
  ```
- [x] Implement `OpenAIEmbeddingProvider`:
  - Use `httpx` for async HTTP calls
  - Model: `text-embedding-3-small` (1536 dimensions)
  - Batch size: up to 2048 texts per request
  - Rate limiting with exponential backoff
- [x] Implement `LocalEmbeddingProvider`:
  - Lazy load sentence-transformers
  - Default model: `all-MiniLM-L6-v2` (384 dimensions)
  - GPU detection with CPU fallback

**Acceptance Criteria**:
- [x] Both providers implement the Protocol correctly
- [x] OpenAI provider handles rate limits gracefully
- [x] Local provider works without GPU
- [x] Dimensions property returns correct values

---

### Task 3: Create Embedding Service
**Status**: COMPLETE

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/embeddings/service.py` (create)

**Dependencies**: Task 1, Task 2

**Pattern to Follow**:
- Async pool pattern from `/Users/imu/Dev/work/mu/src/mu/llm/pool.py:36-280`
- Stats tracking from `/Users/imu/Dev/work/mu/src/mu/llm/types.py:73-94`

**Details**:
- [x] Create `EmbeddingService` class:
  ```python
  class EmbeddingService:
      def __init__(self, provider: str = "openai", model: str | None = None):
          self.provider = self._create_provider(provider, model)

      async def embed_node(self, node: Node) -> NodeEmbedding: ...
      async def embed_nodes(
          self,
          nodes: list[Node],
          batch_size: int = 100,
          on_progress: Callable[[int, int], None] | None = None
      ) -> list[NodeEmbedding]: ...
  ```
- [x] Implement text generation strategies per node type:
  - Functions: signature + docstring + first 500 chars of body
  - Classes: name + docstring + method signatures
  - Modules: docstring + exports
- [x] Add semaphore for concurrency control
- [x] Create `EmbeddingStats` dataclass for tracking
- [x] Implement caching to avoid re-embedding unchanged nodes

**Acceptance Criteria**:
- [x] Batch processing respects concurrency limits
- [x] Progress callback is invoked correctly
- [x] Different node types generate appropriate text for embedding
- [x] Stats track successful/failed/cached counts

---

### Task 4: Extend MUbase with Embedding Methods
**Status**: COMPLETE

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/mubase.py` (modify)

**Dependencies**: Task 1

**Pattern to Follow**:
- Query methods from `/Users/imu/Dev/work/mu/src/mu/kernel/mubase.py:134-410`
- Add/get pattern from `/Users/imu/Dev/work/mu/src/mu/kernel/mubase.py:109-132`

**Details**:
- [x] Add schema migration logic for embeddings table
- [x] Implement `add_embedding(self, embedding: NodeEmbedding) -> None`
- [x] Implement `get_embedding(self, node_id: str) -> NodeEmbedding | None`
- [x] Implement `add_embeddings_batch(self, embeddings: list[NodeEmbedding]) -> None`
- [x] Implement `vector_search(...)`:
  ```python
  def vector_search(
      self,
      query_embedding: list[float],
      embedding_type: str = "code",  # code, docstring, name
      limit: int = 10,
      node_type: NodeType | None = None,
  ) -> list[tuple[Node, float]]:
      """Find similar nodes by cosine similarity."""
  ```
- [ ] Implement `semantic_search(...)` (moved to CLI layer, not in MUbase):
  ```python
  def semantic_search(
      self,
      query: str,
      limit: int = 10,
      node_type: NodeType | None = None,
  ) -> list[tuple[Node, float]]:
      """Search by text query (embeds query then searches)."""
  ```
- [x] Implement `embedding_stats(self) -> dict`:
  - Total nodes with embeddings
  - Nodes without embeddings
  - Model distribution
  - Embedding dimensions

**Acceptance Criteria**:
- [x] Embeddings can be stored and retrieved correctly
- [x] `vector_search` returns nodes sorted by similarity descending
- [x] `semantic_search` handled in CLI via `kernel search` command
- [x] Stats show accurate embedding coverage

---

### Task 5: Add CLI Commands
**Status**: COMPLETE

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/cli.py` (modify)

**Dependencies**: Task 3, Task 4

**Pattern to Follow**:
- Kernel command group from `/Users/imu/Dev/work/mu/src/mu/cli.py:822-1094`
- Progress reporting from `/Users/imu/Dev/work/mu/src/mu/cli.py:285-298`

**Details**:
- [x] Add `mu kernel embed` command:
  ```python
  @kernel.command("embed")
  @click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
  @click.option("--provider", type=click.Choice(["openai", "local"]), default="openai")
  @click.option("--model", type=str, help="Embedding model to use")
  @click.option("--batch-size", type=int, default=100)
  @click.option("--local", is_flag=True, help="Force local embeddings")
  def kernel_embed(path: Path, provider: str, model: str, batch_size: int, local: bool):
      """Generate embeddings for codebase nodes."""
  ```
- [x] Add progress indicator using `create_progress()`
- [x] Add `mu kernel search` command:
  ```python
  @kernel.command("search")
  @click.argument("query", type=str)
  @click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
  @click.option("--limit", "-l", type=int, default=10)
  @click.option("--type", "-t", "node_type", type=click.Choice(["function", "class", "module"]))
  @click.option("--json", "as_json", is_flag=True)
  def kernel_search(query: str, path: Path, limit: int, node_type: str, as_json: bool):
      """Semantic search for code nodes."""
  ```
- [x] Display results in table format with similarity scores

**Acceptance Criteria**:
- [x] `mu kernel embed .` generates embeddings with progress bar
- [x] `mu kernel search "authentication logic"` returns relevant results
- [x] `--local` flag forces sentence-transformers
- [x] `--json` outputs structured results

---

### Task 6: Add Configuration Support
**Status**: COMPLETE

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/config.py` (modify)

**Dependencies**: None (can run in parallel)

**Pattern to Follow**:
- Config class from `/Users/imu/Dev/work/mu/src/mu/config.py:82-108`
- Default config TOML from `/Users/imu/Dev/work/mu/src/mu/config.py:211-272`

**Details**:
- [x] Create `EmbeddingsConfig` class:
  ```python
  class EmbeddingsConfig(BaseModel):
      provider: Literal["openai", "local"] = Field(default="openai")
      model: str = Field(default="text-embedding-3-small")
      batch_size: int = Field(default=100)
      cache_embeddings: bool = Field(default=True)

  class OpenAIEmbeddingsConfig(BaseModel):
      api_key_env: str = Field(default="OPENAI_API_KEY")
      dimensions: int = Field(default=1536)

  class LocalEmbeddingsConfig(BaseModel):
      model: str = Field(default="sentence-transformers/all-MiniLM-L6-v2")
      device: Literal["auto", "cpu", "cuda", "mps"] = Field(default="auto")
  ```
- [x] Add `embeddings: EmbeddingsConfig` to `MUConfig`
- [x] Update `get_default_config_toml()` with embeddings section

**Acceptance Criteria**:
- [x] Configuration loads from `.murc.toml`
- [x] Environment variable override works
- [x] Defaults are sensible

---

### Task 7: Add Unit Tests
**Files**:
- `/Users/imu/Dev/work/mu/tests/unit/test_embeddings.py` (create)

**Dependencies**: Tasks 1-4

**Pattern to Follow**:
- Test structure from `/Users/imu/Dev/work/mu/tests/unit/test_kernel.py`
- Mock patterns from `/Users/imu/Dev/work/mu/tests/unit/test_llm.py:315-402`

**Details**:
- [ ] `TestEmbeddingModels`:
  - Test `NodeEmbedding` creation, serialization, deserialization
  - Test `to_tuple()`, `to_dict()`, `from_row()`
- [ ] `TestEmbeddingProviders`:
  - Test `OpenAIEmbeddingProvider` with mocked HTTP responses
  - Test `LocalEmbeddingProvider` with mocked sentence-transformers
  - Test rate limiting behavior
  - Test batch processing
- [ ] `TestEmbeddingService`:
  - Test node text generation per type
  - Test batch processing with progress callbacks
  - Test caching behavior
- [ ] `TestMUbaseEmbeddings`:
  - Test `add_embedding()` and `get_embedding()`
  - Test `vector_search()` returns correct order
  - Test `semantic_search()` integration
  - Test `embedding_stats()`
- [ ] Integration tests:
  - End-to-end embed + search workflow

**Acceptance Criteria**:
- [ ] All tests pass with `pytest`
- [ ] Provider tests use mocks (no real API calls)
- [ ] Coverage for happy path + error cases

---

### Task 8: Update Public API Exports
**Status**: COMPLETE

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/__init__.py` (modify)
- `/Users/imu/Dev/work/mu/src/mu/kernel/embeddings/__init__.py` (modify)

**Dependencies**: Tasks 1-4

**Pattern to Follow**:
- Export pattern from `/Users/imu/Dev/work/mu/src/mu/kernel/__init__.py:22-40`
- LLM exports from `/Users/imu/Dev/work/mu/src/mu/llm/__init__.py`

**Details**:
- [x] Export from `kernel/embeddings/__init__.py`:
  - `EmbeddingService`
  - `EmbeddingProvider` (Protocol)
  - `EmbeddingProviderType`
  - `NodeEmbedding`
  - `OpenAIEmbeddingProvider`
  - `LocalEmbeddingProvider`
- [x] Add embeddings to `kernel/__init__.py`:
  - Re-export key classes for convenience

**Acceptance Criteria**:
- [x] `from mu.kernel.embeddings import EmbeddingService` works
- [x] `from mu.kernel import EmbeddingService` works as convenience

---

## Implementation Order

1. **Task 1: Schema & Model** - Foundation for all other tasks
2. **Task 2: Provider Interface** - Can run in parallel with Task 1
3. **Task 6: Configuration** - Can run in parallel with Tasks 1-2
4. **Task 3: Embedding Service** - Requires Tasks 1, 2
5. **Task 4: MUbase Extensions** - Requires Task 1
6. **Task 5: CLI Commands** - Requires Tasks 3, 4
7. **Task 8: Public Exports** - Requires Tasks 1-4
8. **Task 7: Tests** - Can start early but complete after Tasks 1-4

```
    Task 1 (Schema) ----+
                        |---> Task 3 (Service) --+
    Task 2 (Providers) -+                        |
                                                 +---> Task 5 (CLI) ---> Task 7 (Tests)
    Task 6 (Config) ----+---> Task 4 (MUbase) ---+
                        |
                        +---> Task 8 (Exports)
```

---

## Edge Cases

1. **Empty embeddings**: Node with no code/docstring should skip or use name-only embedding
2. **Very long text**: Truncate to model's context limit (8191 tokens for OpenAI)
3. **Unicode edge cases**: Ensure proper encoding for all languages
4. **Missing API key**: Clear error message, suggest `--local` flag
5. **GPU OOM**: LocalProvider should catch and fall back to CPU
6. **Dimension mismatch**: Store model info, flag when querying with different dimensions
7. **Concurrent writes**: DuckDB handles single-writer correctly

---

## Security Considerations

1. **API Key Handling**: Use environment variables only, never store in config files
2. **Code Content**: Embedding vectors could potentially leak code patterns - document this
3. **Local Model Security**: Sentence-transformers downloads models - verify sources
4. **Rate Limiting**: Implement proper backoff to avoid API bans

---

## Performance Considerations

1. **Batch Size**: Default 100, configurable. OpenAI allows up to 2048.
2. **Concurrency**: Semaphore limit of 5 for API calls to respect rate limits
3. **Caching**: Store embeddings by content hash to skip unchanged code
4. **Vector Search**: DuckDB handles array operations efficiently; add HNSW index for >100k nodes
5. **Local Model**: GPU detection with MPS support for Apple Silicon
