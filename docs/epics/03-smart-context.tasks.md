# Smart Context - Task Breakdown

## Business Context

**Problem**: Developers and AI coding assistants need the optimal slice of code to answer a specific question. Currently, providing context to LLMs requires manual selection or including entire files, wasting tokens on irrelevant code.

**Outcome**: Extract semantically relevant code from MUbase for any natural language question, fitting within token budgets. This is the "killer feature" that enables AI assistants to receive perfect context for any coding task.

**Users**:
- AI coding assistants needing targeted context for code generation
- Developers asking questions about unfamiliar codebases
- Code review tools needing relevant context for change analysis
- Documentation generators needing code examples

---

## Discovered Patterns

| Pattern | File | Relevance |
|---------|------|-----------|
| Dataclass with `to_dict()` | `/Users/imu/Dev/work/mu/src/mu/kernel/models.py:16-86` | Context models should follow this pattern |
| EmbeddingService batch async | `/Users/imu/Dev/work/mu/src/mu/kernel/embeddings/service.py:135-293` | SmartContextExtractor can use similar async patterns |
| MUbase query methods | `/Users/imu/Dev/work/mu/src/mu/kernel/mubase.py:133-459` | Extractor uses existing graph traversal methods |
| MUbase vector_search | `/Users/imu/Dev/work/mu/src/mu/kernel/mubase.py:593-666` | Vector similarity for relevance scoring |
| MU format generator | `/Users/imu/Dev/work/mu/src/mu/reducer/generator.py:219-231` | MUGenerator for context export |
| Assembler exporters | `/Users/imu/Dev/work/mu/src/mu/assembler/exporters.py:219-231` | export_mu pattern for selective export |
| CLI kernel commands | `/Users/imu/Dev/work/mu/src/mu/cli.py:843-1499` | `@kernel.command` pattern for `mu context` |
| Test class organization | `/Users/imu/Dev/work/mu/tests/unit/test_kernel.py:14-100` | Test structure for context module |
| Progress callbacks | `/Users/imu/Dev/work/mu/src/mu/kernel/embeddings/service.py:247-292` | on_progress pattern for CLI feedback |

---

## Prerequisites

1. **Vector Layer (Epic 1)**: Must be complete - Smart Context uses embeddings for semantic search
2. **MUbase with embeddings**: Database must have embeddings populated via `mu kernel embed`
3. **tiktoken dependency**: Add `tiktoken>=0.5.0` to `pyproject.toml` for accurate token counting

---

## Task Breakdown

### Task 1: Create Data Models

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/context/__init__.py` (create)
- `/Users/imu/Dev/work/mu/src/mu/kernel/context/models.py` (create)

**Dependencies**: None (first task)

**Pattern**: Follow `/Users/imu/Dev/work/mu/src/mu/kernel/models.py:16-86` dataclass pattern

**Description**:
Create the context module directory and define all data models for smart context extraction. Models should follow existing dataclass conventions with `to_dict()` methods.

**Details**:
- [ ] Create `ContextResult` dataclass:
  ```python
  @dataclass
  class ContextResult:
      mu_text: str                      # Generated MU format context
      nodes: list[Node]                 # Selected nodes
      token_count: int                  # Actual token count
      relevance_scores: dict[str, float]  # node_id -> score
      extraction_stats: dict[str, Any]    # Debug/metrics info
  ```
- [ ] Create `ExtractionConfig` dataclass:
  ```python
  @dataclass
  class ExtractionConfig:
      max_tokens: int = 8000
      include_imports: bool = True
      include_parent: bool = True       # Include class for methods
      expand_depth: int = 1             # Neighbor expansion
      entity_weight: float = 1.0        # Named entity match weight
      vector_weight: float = 0.7        # Embedding similarity weight
      proximity_weight: float = 0.3     # Graph distance weight
      min_relevance: float = 0.1        # Minimum score threshold
      exclude_tests: bool = False       # Filter test files
  ```
- [ ] Create `ScoredNode` dataclass:
  ```python
  @dataclass
  class ScoredNode:
      node: Node
      score: float
      entity_score: float = 0.0
      vector_score: float = 0.0
      proximity_score: float = 0.0
  ```
- [ ] Create `ExtractedEntity` dataclass for entity extraction results
- [ ] Implement `to_dict()` methods for all dataclasses
- [ ] Create `__init__.py` with public API exports

**Acceptance**:
- [ ] All dataclasses serialize correctly via `to_dict()`
- [ ] Type hints are complete and pass mypy
- [ ] Docstrings explain each field's purpose

---

### Task 2: Implement Entity Extraction

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/context/extractor.py` (create)

**Dependencies**: Task 1

**Pattern**: Regex-based extraction similar to pattern matching in code analysis tools

**Description**:
Create `EntityExtractor` class that identifies code entity names from natural language questions. Uses multiple strategies: regex patterns, quoted strings, and known node name matching.

**Details**:
- [ ] Implement `EntityExtractor` class:
  ```python
  class EntityExtractor:
      def __init__(self, known_names: set[str] | None = None):
          self.known_names = known_names or set()

      def extract(self, text: str) -> list[ExtractedEntity]: ...
  ```
- [ ] Pattern extraction strategies:
  - [ ] CamelCase: `r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b'` (e.g., AuthService)
  - [ ] snake_case: `r'\b[a-z]+(?:_[a-z]+)+\b'` (e.g., get_user)
  - [ ] CONSTANTS: `r'\b[A-Z][A-Z_]+\b'` (e.g., MAX_RETRIES)
  - [ ] Qualified names: `r'\b\w+(?:\.\w+)+\b'` (e.g., auth.service.login)
  - [ ] Quoted strings: `r'["\']([^"\']+)["\']'`
- [ ] Known name matching (exact and suffix match)
- [ ] Confidence scoring based on extraction method
- [ ] Deduplication of extracted entities

**Acceptance**:
- [ ] `extract("How does AuthService handle login?")` returns `["AuthService", "login"]`
- [ ] `extract("What's in 'config.py'?")` returns `["config.py"]`
- [ ] `extract("user_validation logic")` returns `["user_validation"]`
- [ ] Known names get higher confidence scores

---

### Task 3: Implement Relevance Scoring

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/context/scorer.py` (create)

**Dependencies**: Task 1, Task 2

**Pattern**: Weighted scoring similar to search ranking algorithms

**Description**:
Create `RelevanceScorer` class that scores nodes based on multiple signals: entity match, vector similarity, and graph proximity to seed nodes.

**Details**:
- [ ] Implement `RelevanceScorer` class:
  ```python
  class RelevanceScorer:
      def __init__(self, config: ExtractionConfig, mubase: MUbase):
          self.config = config
          self.mubase = mubase

      def score_nodes(
          self,
          nodes: list[Node],
          question: str,
          entities: list[ExtractedEntity],
          seed_node_ids: set[str],
      ) -> list[ScoredNode]: ...
  ```
- [ ] Entity match scoring:
  - Exact name match: 1.0
  - Partial/suffix match: 0.5
  - Case-insensitive match: 0.3
- [ ] Vector similarity scoring (if embeddings available):
  - Get question embedding via EmbeddingService
  - Compute cosine similarity with node embeddings
  - Normalize to [0, 1] range
- [ ] Proximity scoring:
  - Distance from seed nodes in graph
  - Score = 1 / (1 + distance)
  - Use BFS to calculate shortest distance
- [ ] Combine scores with configurable weights:
  ```
  score = entity_weight * entity_score
        + vector_weight * vector_score
        + proximity_weight * proximity_score
  ```
- [ ] Filter nodes below `min_relevance` threshold

**Acceptance**:
- [ ] Exact entity matches get highest scores
- [ ] Vector similarity boosts semantically related nodes
- [ ] Proximity scoring favors structurally close nodes
- [ ] Scores are normalized and comparable

---

### Task 4: Implement Token Budgeting

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/context/budgeter.py` (create)
- `/Users/imu/Dev/work/mu/pyproject.toml` (modify - add tiktoken)

**Dependencies**: Task 1, Task 3

**Pattern**: Greedy knapsack-style selection

**Description**:
Create `TokenBudgeter` class that selects nodes to fit within a token budget. Uses tiktoken for accurate counting and greedy selection by relevance score.

**Details**:
- [ ] Add `tiktoken>=0.5.0` to `pyproject.toml` dependencies
- [ ] Implement `TokenBudgeter` class:
  ```python
  class TokenBudgeter:
      def __init__(self, max_tokens: int, encoding: str = "cl100k_base"):
          self.max_tokens = max_tokens
          self.tokenizer = tiktoken.get_encoding(encoding)

      def fit_to_budget(self, scored_nodes: list[ScoredNode]) -> list[ScoredNode]: ...
      def estimate_node_tokens(self, node: Node) -> int: ...
      def count_tokens(self, text: str) -> int: ...
  ```
- [ ] Token estimation per node type:
  - Function: signature + params + return type (~20-50 tokens)
  - Class: name + bases + method signatures
  - Module: header + exports list
- [ ] Greedy selection algorithm:
  - Sort by score descending
  - Add nodes while budget allows
  - Include mandatory context (parent class for methods)
- [ ] Handle essential context:
  - If method selected, include parent class
  - If class selected, consider including key imports
- [ ] Track actual vs estimated tokens

**Acceptance**:
- [ ] `fit_to_budget()` respects `max_tokens` limit
- [ ] Higher-scored nodes are prioritized
- [ ] Parent context is included when needed
- [ ] Token count is accurate (within 5% of tiktoken)

---

### Task 5: Implement MU Context Export

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/context/export.py` (create)

**Dependencies**: Task 1, Task 4

**Pattern**: Follow `/Users/imu/Dev/work/mu/src/mu/assembler/exporters.py:219-231`

**Description**:
Create context exporter that generates MU format output from selected nodes. Groups by module for coherent output and optionally includes relevance annotations.

**Details**:
- [ ] Implement `ContextExporter` class:
  ```python
  class ContextExporter:
      def __init__(self, mubase: MUbase, include_scores: bool = False):
          self.mubase = mubase
          self.include_scores = include_scores

      def export_mu(self, scored_nodes: list[ScoredNode]) -> str: ...
      def export_json(self, result: ContextResult) -> str: ...
  ```
- [ ] Group selected nodes by module path
- [ ] Generate MU format using existing sigils:
  - `!` Module header
  - `$` Class with `<` for inheritance
  - `#` Function/method
  - `@` Dependencies
  - `::` Annotations (optional relevance scores)
- [ ] Preserve structural relationships:
  - Classes contain their methods
  - Modules contain their classes/functions
- [ ] Include import context when `include_imports=True`
- [ ] Optional: Add relevance score annotations `:: relevance=0.85`

**Acceptance**:
- [ ] Output is valid MU format
- [ ] Modules are logically grouped
- [ ] Class methods appear under their class
- [ ] Relevance annotations work when enabled

---

### Task 6: Implement Smart Context Extractor

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/context/smart.py` (create)

**Dependencies**: Tasks 1-5

**Pattern**: Facade pattern integrating all components

**Description**:
Create `SmartContextExtractor` class that orchestrates entity extraction, scoring, budgeting, and export into a single cohesive API.

**Details**:
- [ ] Implement `SmartContextExtractor` class:
  ```python
  class SmartContextExtractor:
      def __init__(self, mubase: MUbase, config: ExtractionConfig | None = None):
          self.mubase = mubase
          self.config = config or ExtractionConfig()
          self.entity_extractor = EntityExtractor(self._get_known_names())
          self.scorer = RelevanceScorer(self.config, mubase)
          self.budgeter = TokenBudgeter(self.config.max_tokens)
          self.exporter = ContextExporter(mubase)

      def extract(self, question: str) -> ContextResult: ...
      async def extract_async(self, question: str) -> ContextResult: ...
  ```
- [ ] Extraction pipeline:
  1. Extract entities from question
  2. Find nodes by name (exact + fuzzy)
  3. Vector search for semantic matches (if embeddings available)
  4. Merge seed nodes with deduplication
  5. Expand with graph neighbors (up to `expand_depth`)
  6. Score all candidate nodes
  7. Fit to token budget
  8. Export as MU format
- [ ] Stats collection:
  - Entities extracted
  - Named nodes found
  - Vector similar nodes
  - Nodes after expansion
  - Nodes after scoring
  - Final selected count
  - Token count vs budget
- [ ] Handle edge cases:
  - No embeddings: Entity + structure only
  - No matches: Return empty result with helpful message
  - Large expansion: Cap at reasonable limit

**Acceptance**:
- [ ] `extract("How does authentication work?")` returns relevant auth code
- [ ] Works without embeddings (degraded mode)
- [ ] Respects token budget
- [ ] Stats provide debugging insight

---

### Task 7: Extend MUbase with Context Method

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/mubase.py` (modify)

**Dependencies**: Task 6

**Pattern**: Follow existing MUbase method patterns

**Description**:
Add `get_context_for_question()` method to MUbase class as the primary API for smart context extraction.

**Details**:
- [ ] Add method to MUbase class:
  ```python
  def get_context_for_question(
      self,
      question: str,
      max_tokens: int = 8000,
      **kwargs,
  ) -> ContextResult:
      """Extract optimal context for answering a question.

      Args:
          question: Natural language question about the code
          max_tokens: Maximum tokens in output (default: 8000)
          **kwargs: Additional ExtractionConfig options

      Returns:
          ContextResult with MU format context
      """
      from mu.kernel.context import SmartContextExtractor, ExtractionConfig

      config = ExtractionConfig(max_tokens=max_tokens, **kwargs)
      extractor = SmartContextExtractor(self, config)
      return extractor.extract(question)
  ```
- [ ] Add helper methods:
  - `has_embeddings() -> bool`: Check if embeddings exist
  - `find_nodes_by_suffix(suffix: str) -> list[Node]`: Fuzzy name matching
  - `get_neighbors(node_id: str, direction: str = "both") -> list[Node]`
- [ ] Add type hints and docstrings
- [ ] Update `__all__` exports

**Acceptance**:
- [ ] `db.get_context_for_question("...")` works from Python API
- [ ] Keyword arguments pass through to config
- [ ] Works as sync method (async internally if needed)

---

### Task 8: Add CLI Command

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/cli.py` (modify)

**Dependencies**: Task 7

**Pattern**: Follow `/Users/imu/Dev/work/mu/src/mu/cli.py:1454-1499` `kernel_search` pattern

**Description**:
Add `mu kernel context` command for CLI access to smart context extraction.

**Details**:
- [ ] Add `mu kernel context` command:
  ```python
  @kernel.command("context")
  @click.argument("question", type=str)
  @click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
  @click.option("--max-tokens", "-t", type=int, default=8000, help="Maximum tokens")
  @click.option("--format", "-f", type=click.Choice(["mu", "json"]), default="mu")
  @click.option("--verbose", "-v", is_flag=True, help="Show extraction stats")
  @click.option("--no-imports", is_flag=True, help="Exclude import context")
  @click.option("--depth", type=int, default=1, help="Graph expansion depth")
  @pass_context
  def kernel_context(
      ctx: MUContext,
      question: str,
      path: Path,
      max_tokens: int,
      format: str,
      verbose: bool,
      no_imports: bool,
      depth: int,
  ) -> None:
      """Extract optimal context for a question."""
  ```
- [ ] Display extraction stats in verbose mode:
  - Entities found
  - Nodes matched
  - Token usage
- [ ] Support output formats:
  - `mu`: MU sigil format (default)
  - `json`: Structured JSON with scores
- [ ] Handle missing .mubase gracefully
- [ ] Handle missing embeddings with warning
- [ ] Copy to clipboard option (follow existing pattern)

**Acceptance**:
- [ ] `mu kernel context "How does auth work?"` returns MU output
- [ ] `--max-tokens 2000` limits output size
- [ ] `--verbose` shows extraction statistics
- [ ] `--format json` outputs structured data

---

### Task 9: Update Public API Exports

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/context/__init__.py` (update)
- `/Users/imu/Dev/work/mu/src/mu/kernel/__init__.py` (modify)

**Dependencies**: Tasks 1-7

**Pattern**: Follow `/Users/imu/Dev/work/mu/src/mu/kernel/__init__.py` export pattern

**Description**:
Export public API classes from context module and re-export from kernel for convenience.

**Details**:
- [ ] Export from `kernel/context/__init__.py`:
  ```python
  from mu.kernel.context.models import (
      ContextResult,
      ExtractionConfig,
      ScoredNode,
      ExtractedEntity,
  )
  from mu.kernel.context.smart import SmartContextExtractor

  __all__ = [
      "ContextResult",
      "ExtractionConfig",
      "ScoredNode",
      "ExtractedEntity",
      "SmartContextExtractor",
  ]
  ```
- [ ] Add to `kernel/__init__.py`:
  ```python
  from mu.kernel.context import (
      ContextResult,
      ExtractionConfig,
      SmartContextExtractor,
  )
  ```
- [ ] Add to `__all__` in kernel module

**Acceptance**:
- [ ] `from mu.kernel.context import SmartContextExtractor` works
- [ ] `from mu.kernel import ContextResult` works as convenience

---

### Task 10: Add Unit Tests

**Files**:
- `/Users/imu/Dev/work/mu/tests/unit/test_context.py` (create)

**Dependencies**: Tasks 1-7

**Pattern**: Follow `/Users/imu/Dev/work/mu/tests/unit/test_kernel.py` organization

**Description**:
Comprehensive unit tests for all smart context components.

**Details**:
- [ ] `TestContextModels`:
  - Test `ContextResult` creation and `to_dict()`
  - Test `ExtractionConfig` defaults and custom values
  - Test `ScoredNode` with all score components
- [ ] `TestEntityExtractor`:
  - Test CamelCase extraction
  - Test snake_case extraction
  - Test quoted string extraction
  - Test qualified name extraction
  - Test with known names (exact and suffix match)
  - Test deduplication
- [ ] `TestRelevanceScorer`:
  - Test entity match scoring
  - Test proximity scoring
  - Test score combination with weights
  - Test minimum relevance filtering
  - Mock vector scoring (without real embeddings)
- [ ] `TestTokenBudgeter`:
  - Test token estimation per node type
  - Test budget fitting
  - Test parent context inclusion
  - Test actual token counting
- [ ] `TestContextExporter`:
  - Test MU format generation
  - Test module grouping
  - Test relevance annotations
- [ ] `TestSmartContextExtractor`:
  - Integration test with mock MUbase
  - Test entity-only extraction (no embeddings)
  - Test full pipeline with fixtures

**Acceptance**:
- [ ] All tests pass with `pytest tests/unit/test_context.py`
- [ ] No real embedding API calls (mocked)
- [ ] Edge cases covered (empty results, no matches)

---

### Task 11: Add Integration Tests

**Files**:
- `/Users/imu/Dev/work/mu/tests/integration/test_context_integration.py` (create)

**Dependencies**: Tasks 1-8

**Pattern**: Follow `/Users/imu/Dev/work/mu/tests/integration/test_muql_integration.py`

**Description**:
Integration tests running smart context extraction against real MUbase with sample codebase.

**Details**:
- [ ] Fixture: Build MUbase from test codebase (can reuse existing fixtures)
- [ ] Test extraction quality:
  - Auth-related question returns auth code
  - Database question returns DB code
  - Generic question returns core modules
- [ ] Test token budget adherence
- [ ] Test CLI command execution
- [ ] Performance test: Extraction completes < 500ms

**Acceptance**:
- [ ] Tests run against real (test) MUbase
- [ ] Quality assertions verify relevant code included
- [ ] Performance within expected bounds

---

### Task 12: Create CLAUDE.md Documentation

**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/context/CLAUDE.md` (create)

**Dependencies**: Tasks 1-7

**Pattern**: Follow `/Users/imu/Dev/work/mu/src/mu/kernel/embeddings/CLAUDE.md`

**Description**:
Create module documentation for Claude Code with architecture overview, usage examples, and anti-patterns.

**Details**:
- [ ] Architecture diagram showing extraction pipeline
- [ ] File/class descriptions
- [ ] Usage examples:
  - Python API usage
  - CLI usage
  - Configuration options
- [ ] Scoring algorithm explanation
- [ ] Anti-patterns section
- [ ] Testing instructions

**Acceptance**:
- [ ] Documentation covers all public APIs
- [ ] Examples are runnable
- [ ] Architecture is clearly explained

---

## Dependencies Graph

```
Task 1 (Models) ─────┬──────────────────────────────────────────┐
                     │                                          │
Task 2 (Extractor) ──┼─→ Task 3 (Scorer) ──┐                   │
                     │                      │                   │
                     └──────────────────────┼─→ Task 6 (Smart) ─┼─→ Task 7 (MUbase)
                                            │                   │         │
Task 4 (Budgeter) ──────────────────────────┤                   │         │
                                            │                   │         v
Task 5 (Exporter) ──────────────────────────┘                   │   Task 8 (CLI)
                                                                │         │
                                                                v         │
                                                          Task 9 (API)    │
                                                                │         │
                                                                v         v
                                                          Task 10 (Unit Tests)
                                                                │
                                                                v
                                                          Task 11 (Integration)
                                                                │
                                                                v
                                                          Task 12 (Docs)
```

Parallelizable:
- Tasks 2, 4, 5 can run in parallel after Task 1
- Task 12 can start after Task 6

---

## Edge Cases

1. **No embeddings**: System should work in degraded mode using entity extraction + graph structure only
2. **No entity matches**: Return helpful message suggesting alternative queries or showing top vector matches
3. **Token budget too small**: Return partial result with warning that budget was constraining
4. **Very long questions**: Truncate question for embedding, but use full text for entity extraction
5. **Circular graph references**: Prevent infinite loops in graph expansion
6. **Unicode in names**: Support non-ASCII identifiers in extraction patterns
7. **Ambiguous names**: When multiple nodes match, include highest-scored or ask for clarification
8. **Test files**: Support `exclude_tests` option to filter test code from results

---

## Security Considerations

1. **Input sanitization**: Entity extraction uses regex - ensure patterns don't cause ReDoS
2. **Token limits**: Enforce maximum `max_tokens` to prevent resource exhaustion
3. **No code execution**: Extracted patterns are matched as strings only, never evaluated
4. **Embedding queries**: Question text sent to embedding service - document for users

---

## Performance Considerations

1. **Caching entity lookups**: Cache name -> node mappings for repeated queries
2. **Batch vector operations**: Batch similarity computations when possible
3. **Lazy embedding loading**: Don't load embedding service until vector search needed
4. **Graph traversal limits**: Cap expansion depth and neighbor count to prevent explosion
5. **Token estimation cache**: Cache node token estimates (they don't change)
6. **Target latency**: < 500ms for typical extraction

---

## Out of Scope (Future Work)

1. **Query understanding via LLM**: Use LLM to better interpret question intent
2. **Conversation context**: Include previous Q&A in context selection
3. **Code snippets**: Include relevant lines, not just signatures
4. **Cross-repo search**: Search across multiple .mubase files
5. **Learning from feedback**: Adjust weights based on user feedback
6. **Streaming output**: Stream context as it's generated
