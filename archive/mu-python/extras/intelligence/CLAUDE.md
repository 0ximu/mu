# Intelligence Module - Pattern Detection, Code Generation, Task Context, and NL2MUQL

The Intelligence Layer transforms MU from a code analysis tool into an AI coding assistant's essential companion by providing task-aware context, pattern recognition, change validation, pattern-aware code generation, and natural language query translation.

## Architecture

```
MUbase Graph → Pattern Detection → Pattern Library
                    ↓                    ↓
              Pattern Storage    Code Generator
                    ↓                    ↓
              MCP: mu_patterns() MCP: mu_generate()
              CLI: mu patterns   CLI: mu generate

Task Description → TaskAnalyzer → TaskContextExtractor → Curated Context
                        ↓                ↓
                 Task Analysis    File Context + Patterns + Warnings
                        ↓                ↓
                 MCP: mu_task_context()
                 CLI: mu context --task

Natural Language → NL2MUQLTranslator → MUQL Query → MUbase
                          ↓
                   MCP: mu_ask()
```

### Files

| File | Purpose |
|------|---------|
| `models.py` | `Pattern`, `PatternCategory`, `TemplateType`, `TaskType`, `EntityType`, `TaskContextResult` |
| `patterns.py` | `PatternDetector` - Multi-strategy pattern detection |
| `generator.py` | `CodeGenerator` - Pattern-aware boilerplate generation |
| `task_context.py` | `TaskContextExtractor` - Task-aware context extraction |
| `nl2muql.py` | `NL2MUQLTranslator` - Natural language to MUQL translation |
| `__init__.py` | Public API exports |

## Pattern Categories

| Category | Description | Example Patterns |
|----------|-------------|------------------|
| `error_handling` | Error creation, throwing, catching | Custom error classes, try/catch style |
| `state_management` | State management approach | Zustand slices, React Query |
| `api` | API conventions | Response envelope, middleware |
| `naming` | Naming conventions | File naming, casing styles |
| `testing` | Test patterns | File location, mocking approach |
| `components` | Component patterns | Props interface, composition |
| `imports` | Import organization | Grouping, aliases, barrel files |
| `architecture` | Architectural patterns | Services, repositories |
| `async` | Async patterns | async/await, promises |
| `logging` | Logging patterns | Levels, formats |

## Usage

### Basic Detection

```python
from mu.extras.intelligence import PatternDetector, PatternCategory
from mu.kernel import MUbase

db = MUbase(".mubase")
detector = PatternDetector(db)

# Detect all patterns
result = detector.detect()

# Filter by category
result = detector.detect(category=PatternCategory.ERROR_HANDLING)

# Force re-analysis (bypass cache)
result = detector.detect(refresh=True)
```

### Accessing Results

```python
# Get patterns
for pattern in result.patterns:
    print(f"{pattern.name}: {pattern.frequency} occurrences")
    print(f"  {pattern.description}")
    for example in pattern.examples[:2]:
        print(f"  - {example.file_path}:{example.line_start}")

# Filter by category
error_patterns = result.get_by_category(PatternCategory.ERROR_HANDLING)

# Get top patterns
top_10 = result.get_top_patterns(10)
```

### CLI Usage

```bash
# List all detected patterns
mu patterns

# Filter by category
mu patterns --category error_handling

# Show examples
mu patterns --examples

# JSON output
mu patterns --json

# Force refresh (re-analyze)
mu patterns --refresh
```

### MCP Tool

```python
# Via MCP server
result = mu_patterns()  # All patterns
result = mu_patterns("error_handling")  # By category
result = mu_patterns(refresh=True)  # Force re-analysis
```

## Pattern Detection Strategies

### 1. Structural Clustering

Groups similar AST structures:
- Functions with same decorator patterns
- Classes with same base classes
- Files with similar suffix naming (*.test.ts, *.stories.tsx)

### 2. Naming Convention Extraction

Analyzes naming patterns:
- File naming (PascalCase components, kebab-case utils)
- Function naming (camelCase, snake_case)
- Class naming (suffixes like Service, Controller, Handler)
- Constant naming (UPPER_SNAKE_CASE)

### 3. Import Pattern Analysis

Detects import organization:
- Common import groupings (external → internal → relative)
- Path aliases (@/, ~/, src/)
- Barrel file patterns (index.ts re-exports)

### 4. Code Shape Analysis

Identifies structural patterns:
- Error handling (try/catch, Result types, error callbacks)
- Async patterns (async/await prevalence, .then() chains)
- Component structure (functional vs class, hooks usage)

## Pattern Storage

Patterns are stored in the `.mubase` database:

```sql
CREATE TABLE IF NOT EXISTS patterns (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    frequency INTEGER,
    confidence REAL,
    examples JSON,
    anti_patterns JSON,
    related_patterns JSON,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_patterns_category ON patterns(category);
CREATE INDEX IF NOT EXISTS idx_patterns_name ON patterns(name);
```

## Configuration

Pattern detection can be configured via `.murc.toml`:

```toml
[intelligence]
# Minimum confidence to include a pattern (0.0 - 1.0)
min_confidence = 0.5

# Maximum examples to store per pattern
max_examples = 5

# Categories to analyze (empty = all)
categories = []

# Exclude patterns from these paths
exclude_paths = ["node_modules", "vendor", ".git"]
```

## Anti-Patterns

1. **Never** run pattern detection on very large codebases without limiting categories
2. **Never** trust patterns with confidence < 0.5 without manual review
3. **Never** assume all files follow detected patterns (always check frequency)

---

## Code Generation

The `CodeGenerator` creates boilerplate code that matches detected codebase patterns.

### Template Types

| Type | Description | Generated Files |
|------|-------------|-----------------|
| `hook` | React-style hook | Hook file, test file |
| `component` | UI Component | Component file, test file |
| `service` | Service class | Service file, test file |
| `repository` | Data access layer | Repository file |
| `api_route` | API route handler | Route handler file |
| `test` | Test file | Test file |
| `model` | Data model/entity | Model file |
| `controller` | Controller/Handler | Controller file |

### Usage

#### Python API

```python
from mu.extras.intelligence import CodeGenerator, TemplateType
from mu.kernel import MUbase

db = MUbase(".mubase")
generator = CodeGenerator(db)

# Generate a service
result = generator.generate(TemplateType.SERVICE, "User")
print(result.name)  # "UserService"
for file in result.files:
    print(f"{file.path}: {file.description}")

# Generate a hook
result = generator.generate(TemplateType.HOOK, "Auth")
print(result.name)  # "useAuth" (auto-prefixed)

# Generate a model with fields
result = generator.generate(
    TemplateType.MODEL,
    "Product",
    {"fields": [{"name": "price", "type": "float"}]}
)
```

#### CLI Usage

```bash
# Generate a service
mu generate service User

# Generate a hook
mu generate hook useAuth

# Generate a model with fields
mu generate model Product -f price:float -f name:str

# Preview without creating files
mu generate component UserProfile --dry-run

# JSON output
mu generate service Payment --json

# Generate test for existing module
mu generate test auth -t src/auth.py
```

#### MCP Tool

```python
# Via MCP server
result = mu_generate("hook", "useAuth")
result = mu_generate("service", "User", {"entity": "User"})
result = mu_generate("model", "Product", {"fields": [{"name": "price", "type": "float"}]})
```

### Language Detection

The generator automatically detects the primary language from:
1. File extension patterns (`file_extension_py`, `file_extension_ts`)
2. Defaults to Python if no patterns detected

### Pattern Integration

Generated code adapts to detected patterns:
- **Naming conventions**: Uses detected snake_case/camelCase
- **File organization**: Places files in detected directories
- **Test patterns**: Follows detected test file naming
- **Import patterns**: Adds barrel file suggestions

### Output Structure

```python
@dataclass
class GenerateResult:
    template_type: TemplateType  # What was generated
    name: str                    # Final name (with normalization)
    files: list[GeneratedFile]   # Generated files
    patterns_used: list[str]     # Patterns that influenced generation
    suggestions: list[str]       # Additional suggestions

@dataclass
class GeneratedFile:
    path: str         # Relative path for the file
    content: str      # Generated file content
    description: str  # What this file does
    is_primary: bool  # Main file vs supporting files
```

---

## Natural Language to MUQL Translation

The `NL2MUQLTranslator` converts natural language questions into executable MUQL queries using an LLM with few-shot prompting.

### Usage

#### Python API

```python
from mu.extras.intelligence import NL2MUQLTranslator, translate
from mu.kernel import MUbase

db = MUbase(".mubase")
translator = NL2MUQLTranslator(db)

# Translate and execute
result = translator.translate("What are the most complex functions?")
print(result.muql)  # SELECT name, complexity FROM functions ORDER BY complexity DESC LIMIT 10
print(result.rows)  # Query results

# Translation only (no execution)
result = translator.translate("How many modules?", execute=False)
print(result.muql)  # SELECT COUNT(*) FROM modules

# Convenience function
result = translate("Show me all service classes", db=db)
```

#### MCP Tool

```python
# Via MCP server
result = mu_ask("What are the most complex functions?")
# AskResult(
#   question="What are the most complex functions?",
#   muql="SELECT name, complexity FROM functions ORDER BY complexity DESC LIMIT 10",
#   confidence=0.9,
#   executed=True,
#   rows=[...],
#   row_count=10
# )

# Translation only
result = mu_ask("How many modules?", execute=False)
print(result.muql)
```

### Supported Question Types

| Question Pattern | Generated MUQL |
|------------------|----------------|
| "What are the most complex functions?" | `SELECT name, complexity FROM functions ORDER BY complexity DESC LIMIT 10` |
| "Show me all service classes" | `SELECT * FROM classes WHERE name LIKE '%Service%'` |
| "What depends on AuthService?" | `SHOW dependents OF AuthService DEPTH 2` |
| "Are there circular dependencies?" | `FIND CYCLES` |
| "Find functions with @cache decorator" | `FIND functions WITH DECORATOR "cache"` |
| "How do I get from API to database?" | `PATH FROM api TO database MAX DEPTH 5` |
| "What modules import requests?" | `FIND modules IMPORTING requests` |
| "How many modules are there?" | `SELECT COUNT(*) FROM modules` |

### Configuration

The translator uses LiteLLM for LLM calls. Configure via environment variables:

```bash
# Required: API key for the LLM provider
export ANTHROPIC_API_KEY=sk-ant-...

# Optional: Override the default model
export MU_ASK_MODEL=claude-3-haiku-20240307
```

### Output Structure

```python
@dataclass
class TranslationResult:
    question: str       # Original question
    muql: str           # Generated MUQL query
    explanation: str    # Optional explanation from LLM
    confidence: float   # Confidence score (0.0 - 1.0)
    executed: bool      # Whether query was executed
    result: dict | None # Query results if executed
    error: str | None   # Error message if failed
```

### Cost Estimation

- Default model: `claude-3-haiku-20240307`
- Cost: ~$0.001 per query (input + output tokens)
- Latency: ~500ms per translation

---

## Task-Aware Context Extraction (F1)

The `TaskContextExtractor` provides curated context bundles for development tasks, reducing exploration time from 30-60 seconds to 5-10 seconds.

### Usage

#### Python API

```python
from mu.extras.intelligence import TaskContextExtractor, TaskContextConfig
from mu.kernel import MUbase

db = MUbase(".mubase")
config = TaskContextConfig(max_tokens=8000)
extractor = TaskContextExtractor(db, config)

# Extract context for a task
result = extractor.extract("Add rate limiting to API endpoints")

# Access results
print(result.task_analysis.task_type)  # TaskType.CREATE
print(result.entry_points)  # ["src/api/routes.py", "src/middleware/"]
for fc in result.relevant_files[:5]:
    print(f"{fc.path}: {fc.relevance:.0%}")
for w in result.warnings:
    print(f"Warning: {w.message}")
```

#### CLI Usage

```bash
# Task-aware context
mu context --task "Add rate limiting to API endpoints"

# Standard question context
mu context "How does authentication work?"

# JSON output
mu context --task "Fix login bug" --json
```

#### MCP Tool

```python
# Via MCP server
result = mu_task_context("Add rate limiting to API endpoints")
# TaskContextOutput(
#   relevant_files=[...],
#   entry_points=["src/api/", ...],
#   patterns=[...],
#   warnings=[...],
#   suggestions=[...],
#   mu_text="...",
#   token_count=2500,
#   confidence=0.85
# )
```

### Task Types

| Type | Description | Keywords |
|------|-------------|----------|
| `create` | Creating new code | add, create, implement, build |
| `modify` | Modifying existing code | update, change, edit |
| `delete` | Removing code | remove, delete, drop |
| `refactor` | Restructuring without behavior change | refactor, restructure, extract |
| `debug` | Finding and fixing bugs | fix, bug, debug, error |
| `test` | Writing or updating tests | test, spec, coverage |
| `document` | Adding documentation | document, docs, readme |
| `review` | Reviewing code for issues | review, audit, check |

### Entity Types

| Type | Description | Keywords |
|------|-------------|----------|
| `api_endpoint` | REST/GraphQL endpoints | api, endpoint, route |
| `hook` | React-style hooks | hook, use* |
| `component` | UI components | component, view, page |
| `service` | Business logic classes | service, manager |
| `repository` | Data access layer | repository, repo, store |
| `model` | Data models/entities | model, entity, schema |
| `middleware` | Middleware/interceptors | middleware, guard, filter |
| `config` | Configuration files | config, settings, env |
| `test` | Test files | test, spec |

### Output Structure

```python
@dataclass
class TaskContextResult:
    relevant_files: list[FileContext]  # Files to read/modify
    entry_points: list[str]            # Where to start
    patterns: list[Pattern]            # Patterns to follow
    examples: list[CodeExample]        # Similar code
    warnings: list[Warning]            # High-impact warnings
    suggestions: list[Suggestion]      # Related changes
    task_analysis: TaskAnalysis        # Analysis details
    mu_text: str                       # MU format context
    token_count: int                   # Token budget used
    confidence: float                  # Context relevance
```

### Token Budget Allocation

- 60% for core relevant files
- 20% for patterns and examples
- 10% for dependencies
- 10% for warnings and metadata

---

## Related

- [MCP Server](/src/mu/mcp/CLAUDE.md) - `mu_patterns`, `mu_generate`, `mu_ask`, `mu_task_context` tools
- [Kernel Module](/src/mu/kernel/CLAUDE.md) - MUbase storage
- [PRD: Intelligence Layer](/docs/prd/MU_INTELLIGENCE_LAYER.md) - Full specification
