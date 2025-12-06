# Python API Reference

> **Note**: The Python API is internal and may change between minor versions. Use the CLI for stable interfaces.

## Overview

MU's Python API follows the pipeline architecture:

```
Scanner -> Parser -> Reducer -> Assembler -> Exporter
```

## Modules

### `mu.scanner`

Filesystem scanning and language detection.

```python
from mu.scanner import Scanner, ScanResult

# Scan a directory
scanner = Scanner(
    root="./src",
    ignore=["*.test.py", "__pycache__/"],
    max_file_size_kb=1000
)

for file_info in scanner.scan():
    print(f"{file_info.path}: {file_info.language}")
```

### `mu.parser`

AST extraction using Tree-sitter.

```python
from mu.parser import parse_file, parse_source
from mu.parser.models import ModuleDef

# Parse a file
module_def: ModuleDef = parse_file("src/auth.py")

# Parse source string
module_def = parse_source(
    source="def hello(): pass",
    language="python",
    path="example.py"
)

# Access parsed elements
for cls in module_def.classes:
    print(f"Class: {cls.name}")
    for method in cls.methods:
        print(f"  Method: {method.name}")

for func in module_def.functions:
    print(f"Function: {func.name} -> {func.return_type}")
```

#### `ModuleDef` Structure

```python
@dataclass
class ModuleDef:
    path: str
    language: str
    imports: list[ImportDef]
    classes: list[ClassDef]
    functions: list[FunctionDef]
    constants: list[ConstantDef]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]: ...
```

### `mu.reducer`

Transformation and compression rules.

```python
from mu.reducer import Reducer, ReducedModule

reducer = Reducer(
    complexity_threshold=20,
    strip_boilerplate=True
)

reduced: ReducedModule = reducer.reduce(module_def)

# Check if LLM summarization needed
for func in reduced.functions:
    if func.needs_llm:
        print(f"Complex function: {func.name}")
```

### `mu.assembler`

Dependency resolution and graph building.

```python
from mu.assembler import Assembler, ModuleGraph

assembler = Assembler()

# Build dependency graph
graph: ModuleGraph = assembler.build([reduced_module1, reduced_module2])

# Query dependencies
deps = graph.get_dependencies("auth_service")
dependents = graph.get_dependents("auth_service")

# Export
from mu.assembler.exporters import MUExporter, JSONExporter

exporter = MUExporter()
output = exporter.export(graph)
```

### `mu.llm`

LLM integration for function summarization.

```python
from mu.llm import LLMPool

async def summarize():
    pool = LLMPool(
        provider="anthropic",
        model="claude-3-haiku-20240307"
    )

    # Batch summarization
    items = [
        {"name": "complex_func", "source": "..."},
        {"name": "another_func", "source": "..."},
    ]

    summaries = await pool.summarize_batch(items)
```

### `mu.security`

Secret detection and redaction.

```python
from mu.security import SecretScanner

scanner = SecretScanner()

# Scan content for secrets
secrets = scanner.scan(content)
for secret in secrets:
    print(f"Found {secret.type} at line {secret.line}")

# Redact secrets
redacted = scanner.redact(content)
```

### `mu.diff`

Semantic diff between versions.

```python
from mu.diff import Differ, DiffResult

differ = Differ()

result: DiffResult = differ.diff(
    base_ref="main",
    head_ref="feature-branch"
)

for change in result.changes:
    print(f"{change.type}: {change.path}")
    for delta in change.deltas:
        print(f"  {delta.kind}: {delta.name}")
```

### `mu.kernel.context`

Smart context extraction for answering questions about code.

```python
from mu.kernel import MUbase, ContextResult, ExtractionConfig

# Open database
db = MUbase("./src/.mubase")

# Simple usage
result = db.get_context_for_question(
    "How does authentication work?",
    max_tokens=4000,
)

print(result.mu_text)           # MU format output
print(result.token_count)       # Actual token count
print(len(result.nodes))        # Number of nodes included
print(result.relevance_scores)  # node_id -> score mapping
print(result.extraction_stats)  # Debug statistics

# Advanced usage with custom config
from mu.kernel.context import SmartContextExtractor, ExtractionConfig

config = ExtractionConfig(
    max_tokens=8000,
    include_imports=True,
    include_parent=True,      # Include parent class for methods
    expand_depth=1,           # Graph expansion depth
    entity_weight=1.0,        # Weight for entity name match
    vector_weight=0.7,        # Weight for vector similarity
    proximity_weight=0.3,     # Weight for graph proximity
    min_relevance=0.1,        # Minimum score threshold
    exclude_tests=False,      # Filter test files
)

extractor = SmartContextExtractor(db, config)
result = extractor.extract("Where is Redis used?")

# Export as JSON
from mu.kernel.context import ContextExporter

exporter = ContextExporter(db, include_scores=True)
json_output = exporter.export_json(result)
```

#### Entity Extraction

```python
from mu.kernel.context.extractor import EntityExtractor

# Create extractor with known codebase names
extractor = EntityExtractor(known_names={"AuthService", "UserModel"})

# Extract entities from question
entities = extractor.extract("How does AuthService validate the user login?")
# Returns: [ExtractedEntity(name="AuthService", confidence=1.0, source="known_name"), ...]
```

#### Token Budgeting

```python
from mu.kernel.context.budgeter import TokenBudgeter

budgeter = TokenBudgeter(max_tokens=8000)

# Count tokens in text
tokens = budgeter.get_actual_tokens("Some MU format text...")

# Fit nodes to budget
selected = budgeter.fit_to_budget(
    scored_nodes,
    mubase=db,
    include_parent=True,
)
```

### `mu.kernel.embeddings`

Vector embeddings for semantic code search.

```python
from mu.kernel import MUbase, EmbeddingService, NodeEmbedding

# Create embedding service
service = EmbeddingService(
    provider="openai",  # or "local"
    model="text-embedding-3-small"  # or "all-MiniLM-L6-v2" for local
)

# Get nodes from database
db = MUbase("./src/.mubase")
nodes = db.get_nodes()

# Generate embeddings
async def embed_codebase():
    def on_progress(current, total):
        print(f"Progress: {current}/{total}")

    embeddings = await service.embed_nodes(
        nodes,
        batch_size=100,
        on_progress=on_progress
    )

    # Store embeddings
    db.add_embeddings_batch(embeddings)

    return embeddings

# Run embedding generation
import asyncio
embeddings = asyncio.run(embed_codebase())

# Search by semantic similarity
results = db.vector_search(
    query_embedding=query_vector,
    embedding_type="code",  # code, docstring, name
    limit=10,
    node_type=NodeType.FUNCTION  # optional filter
)

for node, similarity in results:
    print(f"{node.name}: {similarity:.3f}")

# Convenience method: semantic search with text query
async def search():
    query_embedding = await service.embed_query("authentication logic")
    return db.vector_search(query_embedding, limit=5)

# Get embedding statistics
stats = db.embedding_stats()
print(f"Embedded: {stats['nodes_with_embeddings']}/{stats['total_nodes']}")
```

#### Embedding Providers

**OpenAI (default)**:
- Model: `text-embedding-3-small` (1536 dimensions)
- Requires: `OPENAI_API_KEY` environment variable
- Best for: Production, high quality

**Local (sentence-transformers)**:
- Model: `all-MiniLM-L6-v2` (384 dimensions)
- Requires: `pip install sentence-transformers`
- Best for: Offline use, privacy, cost savings

```python
# OpenAI provider
from mu.kernel.embeddings import OpenAIEmbeddingProvider

provider = OpenAIEmbeddingProvider(
    model="text-embedding-3-small",
    timeout=60.0,
    max_retries=3
)

# Local provider
from mu.kernel.embeddings import LocalEmbeddingProvider

provider = LocalEmbeddingProvider(
    model="all-MiniLM-L6-v2",
    device="auto"  # auto, cpu, cuda, mps
)
```

## Error Handling

MU uses error-as-data pattern instead of exceptions:

```python
# Good - check error field
result = parse_file("broken.py")
if result.error:
    print(f"Parse error: {result.error}")
else:
    process(result)

# Errors are also available in to_dict()
data = result.to_dict()
if data.get("error"):
    handle_error(data["error"])
```

## Type Hints

All public APIs are fully typed. Use mypy for static checking:

```bash
mypy your_script.py
```

## Examples

### Full Pipeline

```python
import asyncio
from pathlib import Path
from mu.scanner import Scanner
from mu.parser import parse_file
from mu.reducer import Reducer
from mu.assembler import Assembler
from mu.assembler.exporters import MUExporter
from mu.llm import LLMPool

async def compress_codebase(root: str, use_llm: bool = False):
    # Scan
    scanner = Scanner(root)
    files = list(scanner.scan())

    # Parse
    modules = [parse_file(f.path) for f in files]

    # Reduce
    reducer = Reducer()
    reduced = [reducer.reduce(m) for m in modules if not m.error]

    # LLM summarization (optional)
    if use_llm:
        pool = LLMPool()
        needs_summary = [
            {"name": f.name, "source": f.source}
            for r in reduced
            for f in r.functions
            if f.needs_llm
        ]
        summaries = await pool.summarize_batch(needs_summary)
        # Apply summaries...

    # Assemble
    assembler = Assembler()
    graph = assembler.build(reduced)

    # Export
    exporter = MUExporter()
    return exporter.export(graph)

# Run
output = asyncio.run(compress_codebase("./src", use_llm=True))
print(output)
```
