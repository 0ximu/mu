# Context Module - Smart Context Extraction

The context module provides intelligent context extraction from MUbase for answering natural language questions about code.

## Architecture

```
Question → Entity Extraction → Seed Nodes
                  ↓
           Vector Search → Candidate Nodes
                  ↓
           Graph Expansion → Extended Nodes
                  ↓
           Relevance Scoring → Sorted Nodes
                  ↓
           Token Budgeting → Selected Nodes
                  ↓
           MU Export → Context String
```

### Files

| File | Purpose |
|------|---------|
| `models.py` | `ContextResult`, `ExtractionConfig`, `ScoredNode`, `ExtractedEntity` |
| `extractor.py` | `EntityExtractor` - regex-based entity extraction from questions |
| `scorer.py` | `RelevanceScorer` - multi-signal relevance scoring |
| `budgeter.py` | `TokenBudgeter` - tiktoken-based budget fitting |
| `export.py` | `ContextExporter` - MU format generation |
| `smart.py` | `SmartContextExtractor` - orchestration facade |
| `__init__.py` | Public API exports |

## Key Classes

### `SmartContextExtractor`

Main orchestrator that combines all extraction components.

```python
from mu.kernel.context import SmartContextExtractor, ExtractionConfig
from mu.kernel import MUbase

db = MUbase(".mubase")

config = ExtractionConfig(
    max_tokens=8000,
    include_imports=True,
    include_parent=True,
    expand_depth=1,
    entity_weight=1.0,
    vector_weight=0.7,
    proximity_weight=0.3,
    exclude_tests=False,
)

extractor = SmartContextExtractor(db, config)
result = extractor.extract("How does authentication work?")

print(result.mu_text)
print(f"Tokens: {result.token_count}")
print(f"Nodes: {len(result.nodes)}")
```

### `EntityExtractor`

Extracts code identifiers from natural language questions.

```python
from mu.kernel.context.extractor import EntityExtractor

extractor = EntityExtractor(known_names={"AuthService", "UserModel"})
entities = extractor.extract("How does AuthService handle login?")

# Returns: [ExtractedEntity(name="AuthService", ...), ExtractedEntity(name="login", ...)]
```

**Extraction Strategies:**
- CamelCase: `AuthService`, `UserModel`
- snake_case: `get_user`, `validate_token`
- CONSTANTS: `MAX_RETRIES`, `API_KEY`
- Quoted strings: `"config.py"`, `'service'`
- File paths: `src/auth/service.py`

### `RelevanceScorer`

Scores nodes by combining multiple signals.

```python
from mu.kernel.context.scorer import RelevanceScorer

scorer = RelevanceScorer(config, mubase)
scored_nodes = scorer.score_nodes(
    nodes=candidates,
    question="authentication",
    entities=extracted_entities,
    seed_node_ids={"node1", "node2"},
    vector_scores={"node1": 0.85},  # Optional
)
```

**Scoring Formula:**
```
score = entity_weight * entity_score
      + vector_weight * vector_score
      + proximity_weight * proximity_score
```

### `TokenBudgeter`

Fits nodes within token budget using tiktoken.

```python
from mu.kernel.context.budgeter import TokenBudgeter

budgeter = TokenBudgeter(max_tokens=8000)
selected = budgeter.fit_to_budget(
    scored_nodes,
    mubase=db,
    include_parent=True,  # Include parent class for methods
)
```

### `ContextExporter`

Exports selected nodes as MU format.

```python
from mu.kernel.context.export import ContextExporter

exporter = ContextExporter(mubase, include_scores=False)
mu_text = exporter.export_mu(selected_nodes)
json_output = exporter.export_json(context_result)
```

## MUbase Integration

The `get_context_for_question()` method provides a convenient API:

```python
from mu.kernel import MUbase

db = MUbase(".mubase")

result = db.get_context_for_question(
    "How does authentication work?",
    max_tokens=4000,
    exclude_tests=True,
)

print(result.mu_text)
```

## CLI Usage

```bash
# Basic usage
mu kernel context "How does authentication work?"

# With options
mu kernel context "database queries" --max-tokens 4000 --verbose

# JSON output
mu kernel context "user validation" --format json

# Exclude test files
mu kernel context "error handling" --exclude-tests

# Include relevance scores
mu kernel context "API endpoints" --scores

# Copy to clipboard
mu kernel context "parser logic" --copy
```

## Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `max_tokens` | 8000 | Maximum tokens in output |
| `include_imports` | True | Include import context |
| `include_parent` | True | Include parent class for methods |
| `expand_depth` | 1 | Graph expansion depth |
| `entity_weight` | 1.0 | Weight for entity match score |
| `vector_weight` | 0.7 | Weight for vector similarity |
| `proximity_weight` | 0.3 | Weight for graph proximity |
| `min_relevance` | 0.1 | Minimum score threshold |
| `exclude_tests` | False | Filter out test files |
| `vector_search_limit` | 20 | Max nodes from vector search |
| `max_expansion_nodes` | 100 | Cap on graph expansion |

## Anti-Patterns

1. **Never** call `extract()` from an async context - it uses `asyncio.run()` internally
2. **Never** modify `ScoredNode` objects - they may be mutated during budgeting
3. **Never** assume embeddings exist - check `has_embeddings()` or handle degraded mode
4. **Never** set `expand_depth` too high - exponential growth can be slow

## Testing

```bash
pytest tests/unit/test_context.py -v
pytest tests/integration/test_context_integration.py -v
```

## Related

- [Embeddings Module](/src/mu/kernel/embeddings/CLAUDE.md)
- [Kernel Module](/src/mu/kernel/CLAUDE.md)
- [Epic 03: Smart Context](/docs/epics/03-smart-context.md)
