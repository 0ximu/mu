# MU-SIGMA Module - Self-Bootstrapping Training Data Pipeline

MU-SIGMA generates synthetic training data for embedding model fine-tuning by transforming code graphs into training triplets.

## Architecture

```
GitHub Repos -> Clone -> Build .mubase -> Generate Q&A -> Extract Pairs -> Export
     |            |           |              |                |              |
  repos.py    clone.py    build.py    questions.py      pairs.py      parquet/json
                                      answers.py
                                      validate.py
```

## Files

| File | Purpose |
|------|---------|
| `models.py` | Data models: RepoInfo, QAPair, TrainingPair, ProcessingResult, PipelineStats |
| `config.py` | Pydantic configuration with env var overrides (MU_SIGMA_* prefix) |
| `repos.py` | GitHub API client for fetching top repositories |
| `clone.py` | Git shallow clone with URL validation |
| `build.py` | MU graph building integration |
| `questions.py` | Question generation using Claude Haiku |
| `answers.py` | Answer generation using Claude Sonnet |
| `validate.py` | Q&A validation using Claude Haiku |
| `pairs.py` | Training pair extraction (structural + Q&A) |
| `orchestrator.py` | Pipeline coordination with checkpointing |
| `cli.py` | Click commands (sigma subcommand) |
| `llm_client.py` | Shared Anthropic client singleton |

## CLI Commands

```bash
# Initialize config
uv run mu sigma init

# Fetch top repos from GitHub
uv run mu sigma fetch

# Run full pipeline
uv run mu sigma run [--repos N] [--questions N]

# Show pipeline statistics
uv run mu sigma stats

# Inspect training data
uv run mu sigma inspect [--sample N] [--type TYPE]

# Clean up (remove clones, mubases, checkpoints)
uv run mu sigma clean [--all]
```

## Configuration

Config loaded from `sigma.toml` or environment variables:

```toml
[llm]
question_model = "claude-3-haiku-20240307"
answer_model = "claude-sonnet-4-20250514"
validation_model = "claude-3-haiku-20240307"
concurrency = 5
max_retries = 3

[repos]
languages = ["python", "typescript"]
repos_per_language = 50
min_stars = 500
max_size_kb = 100000

[pipeline]
questions_per_repo = 30
checkpoint_interval = 5
skip_existing_mubase = true
cleanup_clones = true
```

## Training Pair Types

| Type | Source | Weight | Description |
|------|--------|--------|-------------|
| `contains` | Graph | 1.0 | Module contains class/function |
| `calls` | Graph | 0.9 | Function calls another function |
| `imports` | Graph | 0.8 | Module imports another module |
| `inherits` | Graph | 0.85 | Class inherits from another |
| `same_file` | Graph | 0.7 | Entities in same file |
| `qa_relevance` | LLM | 1.0 | Question to relevant code node |
| `co_relevant` | LLM | 0.9 | Multiple nodes answering same question |

## Key Patterns

### Error Handling as Data
Functions return result objects with error field, not exceptions:
```python
result = clone_repo(repo, target_dir)
if not result.success:
    logger.error(f"Clone failed: {result.error}")
    return
```

### Checkpoint/Resume
Pipeline saves progress every N repos:
```python
checkpoint = Checkpoint.load(checkpoint_file)
if checkpoint:
    processed_set = set(checkpoint.processed_repos)
    repos = [r for r in repos if r.name not in processed_set]
```

### Shared LLM Client
Single Anthropic client reused across calls:
```python
from mu.sigma.llm_client import get_anthropic_client
client = get_anthropic_client()  # Singleton
```

### URL Validation
Clone URLs validated before subprocess:
```python
if not validate_clone_url(repo.url):
    return CloneResult(success=False, error="Invalid URL")
```

## Data Flow

1. **Fetch Repos**: Query GitHub API for top repos by stars
2. **Clone**: Shallow clone each repo (depth=1)
3. **Build**: Create .mubase graph database
4. **Generate Questions**: Haiku generates diverse questions
5. **Generate Answers**: Sonnet identifies relevant code nodes
6. **Validate**: Haiku validates Q&A quality
7. **Extract Pairs**: Combine structural edges + Q&A pairs
8. **Export**: Write parquet file with triplets

## Output Format

Training triplets (anchor, positive, negative):
```python
{
    "anchor": "How does authentication work?",
    "positive": "AuthService",  # Relevant node
    "negative": "DatabasePool",  # Hard negative from same codebase
    "pair_type": "qa_relevance",
    "weight": 1.0,
    "source_repo": "owner/repo"
}
```

## Testing

```bash
# Run sigma unit tests
uv run pytest tests/unit/test_sigma.py -v

# With coverage
uv run pytest tests/unit/test_sigma.py --cov=src/mu/sigma
```

## Anti-Patterns

1. **Never** create Anthropic client per-call - use `get_anthropic_client()`
2. **Never** clone without URL validation - use `validate_clone_url()`
3. **Never** skip checkpointing - pipeline may be interrupted
4. **Never** hardcode model names - use config.llm settings
5. **Never** use bare `open()` - always specify `encoding="utf-8"`
