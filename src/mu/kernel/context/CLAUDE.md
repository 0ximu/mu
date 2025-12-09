# Context Module - Smart Context Extraction

The context module provides intelligent context extraction from MUbase for answering natural language questions about code.

## Architecture

```
Question → Intent Classification → Strategy Selection
                  ↓
           Entity Extraction → Seed Nodes
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
| `intent.py` | `IntentClassifier`, `Intent`, `ClassifiedIntent` - question intent classification |
| `strategies.py` | `ExtractionStrategy`, `LocateStrategy`, `ImpactStrategy`, etc. - specialized extractors |
| `models.py` | `ContextResult`, `ExtractionConfig`, `ExportConfig`, `ScoredNode`, `ExtractedEntity` |
| `extractor.py` | `EntityExtractor` - regex-based entity extraction from questions |
| `scorer.py` | `RelevanceScorer` - multi-signal relevance scoring |
| `budgeter.py` | `TokenBudgeter` - tiktoken-based budget fitting |
| `export.py` | `ContextExporter` - MU format generation |
| `smart.py` | `SmartContextExtractor` - orchestration facade |
| `omega.py` | `OmegaContextExtractor`, `OmegaConfig`, `OmegaResult`, `OmegaManifest` |
| `__init__.py` | Public API exports |

## Intent Classification

Questions are classified into intents which select specialized extraction strategies.

### Intent Types

| Intent | Trigger Patterns | Extraction Strategy |
|--------|------------------|---------------------|
| `EXPLAIN` | "how does", "explain", "walk me through" | Default pipeline with docstrings |
| `IMPACT` | "what would break", "who uses", "depends on" | `ImpactStrategy` - get_dependents(depth=3) |
| `LOCATE` | "where is", "find", "locate" | `LocateStrategy` - minimal, targeted results |
| `LIST` | "list all", "show all", "what are the" | `ListStrategy` - query by node type |
| `NAVIGATE` | "what calls", "dependencies of", "callers of" | `NavigateStrategy` - graph traversal |
| `TEMPORAL` | "changed", "history", "who modified" | Query snapshots, node history |
| `DEBUG` | "why is failing", "bug in", "error" | Include tests, error handlers |
| `COMPARE` | "difference between", "compare", "vs" | Fetch both, side-by-side |
| `UNKNOWN` | Fallback | Default `SmartContextExtractor` pipeline |

### Confidence Levels

- **HIGH (>0.8)**: Use specialized strategy
- **MEDIUM (0.5-0.8)**: Use strategy with fallback
- **LOW (<0.5)**: Use default pipeline

### Example

```python
from mu.kernel.context import IntentClassifier, Intent

classifier = IntentClassifier()

# Classify a question
result = classifier.classify("What would break if I deleted UserService?")
print(result.intent)       # Intent.IMPACT
print(result.confidence)   # 0.95
print(result.entities)     # ["UserService"]

# Result includes intent info
extractor = SmartContextExtractor(db)
ctx = extractor.extract("Where is validate_email defined?")
print(ctx.intent)            # "locate"
print(ctx.intent_confidence) # 0.92
print(ctx.strategy_used)     # "locate"
```

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

### `OmegaContextExtractor`

OMEGA-enhanced context extraction with S-expression output for improved LLM parseability.

**Important:** OMEGA Schema v2.0 prioritizes **LLM parseability** over token savings. S-expressions
are more verbose than sigils, so `compression_ratio` may be < 1.0 (expansion). The value is in:
- Structured, parseable format for LLMs
- Stable seed (schema) enabling prompt cache optimization
- Explicit syntax (parentheses vs sigils) for precise extraction

```python
from mu.kernel.context.omega import OmegaContextExtractor, OmegaConfig
from mu.kernel import MUbase

db = MUbase(".mubase")

config = OmegaConfig(
    max_tokens=8000,
    header_budget_ratio=0.15,      # Max 15% for macro definitions
    include_synthesized=True,       # Include codebase-specific macros
    max_synthesized_macros=5,       # Limit synthesized macros
    enable_prompt_cache_optimization=True,  # Order macros for cache
)

extractor = OmegaContextExtractor(db, config)
result = extractor.extract("How does authentication work?")

print(result.full_output)           # Complete OMEGA context
print(f"Compression ratio: {result.compression_ratio:.2f}")  # May be < 1.0
```

**OMEGA Output Structure:**

```lisp
;; MU-Lisp Macro Definitions (seed - stable, cacheable)
(defmacro api [method path handler] "API endpoint definition")
(defmacro service [name entity] "Service class pattern")

;; Codebase Context (body - compressed content)
(mu-lisp :version "1.0" :codebase "mu" :commit "abc123"
  :core [module class defn data]
  :standard [api service])

(module "src/auth.py"
  (class AuthService :bases [BaseService]
    (defn authenticate [username:str password:str] -> User)))
```

**Key Properties:**

| Property | Description |
|----------|-------------|
| `seed` | Macro definitions header (stable for caching) |
| `body` | S-expression content |
| `full_output` | Combined seed + body for LLM consumption |
| `compression_ratio` | Ratio vs sigil format (may be < 1.0) |
| `manifest` | `OmegaManifest` with macro metadata |

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

# OMEGA format (S-expression for LLM parseability)
mu kernel context "auth service" --format omega

# OMEGA with verbose stats
mu kernel context "database" --format omega --verbose

# Exclude test files
mu kernel context "error handling" --exclude-tests

# Include relevance scores
mu kernel context "API endpoints" --scores

# Copy to clipboard
mu kernel context "parser logic" --copy

# With enrichment options (docstrings, line numbers, imports)
mu kernel context "auth service" --docstrings --line-numbers
mu kernel context "user model" --no-docstrings  # Disable docstrings
mu kernel context "API" --imports  # Include internal module imports
```

## Configuration Options

### ExtractionConfig

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
| `include_docstrings` | True | Include docstrings in output |
| `include_line_numbers` | False | Include line numbers for IDE integration |
| `min_complexity_to_show` | 0 | Minimum complexity to show (0 = all) |

### ExportConfig

Controls MU text export enrichment:

| Option | Default | Description |
|--------|---------|-------------|
| `include_docstrings` | True | Include docstrings in output |
| `max_docstring_lines` | 5 | Max lines for multi-line docstrings |
| `truncate_docstring` | True | Add '...' if truncated |
| `min_complexity_to_show` | 0 | Min complexity for annotation (0 = all) |
| `include_line_numbers` | False | Add `:L{start}-{end}` suffixes |
| `include_internal_imports` | True | Show internal module imports |
| `include_import_aliases` | False | Show import aliases |
| `max_attributes` | 15 | Max class attributes to show |
| `include_language` | False | Add `@lang` tag for language |
| `include_qualified_names` | False | Show fully qualified names |

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
