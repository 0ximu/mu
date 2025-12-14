# MU-SIGMA Task Breakdown

## Feature: Training Data Pipeline for Structure-Aware Embeddings

**PRD Reference:** `docs/prd.md`
**Branch:** `feature/mu-sigma`
**Date:** 2025-12-10

---

## Business Context

MU-SIGMA generates synthetic training data for embedding fine-tuning by leveraging MU's existing code graph infrastructure. The key insight: **the graph IS the training signal**.

- **Graph edges (contains, calls, imports, inherits)** become structural training pairs
- **LLM-generated Q&A pairs** bridge natural language to code nodes
- **Target:** 50,000+ training triplets from 100 GitHub repositories
- **Cost:** < $50 total LLM API spend

---

## Discovered Patterns (from MU codebase)

| Pattern | Source | Application |
|---------|--------|-------------|
| Dataclass + `to_dict()` | `parser/models.py` | All data models (Repo, QAPair, TrainingPair) |
| Async LLM pool with semaphore | `llm/pool.py` | Question/answer generation with rate limiting |
| Dual-layer caching | `cache/__init__.py` | Cache LLM responses, avoid re-processing repos |
| Error as data | `errors.py` | `ProcessingResult` with accumulated errors |
| Pydantic config | `config.py` | `SigmaConfig` with env overrides |
| Multi-pass processing | `kernel/builder.py` | Build mubase, then Q&A, then pairs |
| Click CLI | `commands/compress.py` | `mu sigma fetch`, `mu sigma run`, etc. |
| httpx client | `client.py` | GitHub API calls |
| Progress callbacks | `llm/pool.py` | Track processing progress |
| Stats accumulation | `llm/types.py` | `PipelineStats` tracking |

---

## Module Structure

```
src/mu/sigma/
├── __init__.py          # Module exports, version
├── config.py            # SigmaConfig (Pydantic settings)
├── models.py            # RepoInfo, QAPair, TrainingPair, etc.
├── repos.py             # GitHub repo fetching
├── clone.py             # Git clone + cleanup
├── build.py             # mu build wrapper
├── questions.py         # Haiku question generation
├── answers.py           # Sonnet answer generation
├── validate.py          # Haiku validation
├── pairs.py             # Training pair extraction
├── orchestrator.py      # Pipeline runner with checkpoints
└── cli.py               # Click commands
```

---

## Task Breakdown

### Task 1: Core Data Models (`models.py`)
**Priority:** P0 (blocking)
**Files:** `src/mu/sigma/models.py`

Create dataclasses for all pipeline data:

```python
@dataclass
class RepoInfo:
    name: str              # "owner/repo"
    url: str               # Clone URL
    stars: int
    language: str          # "python" | "typescript"
    size_kb: int

    def to_dict(self) -> dict[str, Any]: ...

@dataclass
class QAPair:
    question: str
    category: str          # architecture, dependencies, navigation, understanding
    answer: str | None = None
    relevant_nodes: list[str] = field(default_factory=list)
    confidence: float = 0.0
    validation_status: str = "pending"  # pending, accepted, corrected, rejected
    valid_nodes: list[str] = field(default_factory=list)
    invalid_nodes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]: ...

@dataclass
class TrainingPair:
    anchor: str
    positive: str
    negative: str
    pair_type: str         # contains, calls, imports, inherits, same_file, qa_relevance, co_relevant
    weight: float          # 0.7-1.0
    source_repo: str

    def to_dict(self) -> dict[str, Any]: ...

@dataclass
class ProcessingResult:
    repo_name: str
    success: bool
    mubase_path: str | None = None
    node_count: int = 0
    qa_pairs: list[QAPair] = field(default_factory=list)
    structural_pairs: int = 0
    qa_training_pairs: int = 0
    error: str | None = None
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]: ...

@dataclass
class PipelineStats:
    total_repos: int = 0
    processed_repos: int = 0
    failed_repos: int = 0
    total_nodes: int = 0
    total_qa_pairs: int = 0
    validated_qa_pairs: int = 0
    structural_pairs: int = 0
    qa_training_pairs: int = 0
    total_training_pairs: int = 0
    llm_tokens_used: int = 0
    estimated_cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]: ...
```

**Acceptance Criteria:**
- [ ] All dataclasses have `to_dict()` methods
- [ ] All dataclasses use `field(default_factory=...)` for mutable defaults
- [ ] Type hints complete (mypy passes)
- [ ] Enums for pair_type and validation_status

---

### Task 2: Configuration (`config.py`)
**Priority:** P0 (blocking)
**Files:** `src/mu/sigma/config.py`

Pydantic-based configuration following MU's pattern:

```python
class SigmaConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MU_SIGMA_",
        env_nested_delimiter="_",
    )

    # Repository settings
    languages: list[str] = ["python", "typescript"]
    repos_per_language: int = 50
    min_stars: int = 500
    max_size_kb: int = 100_000  # 100MB

    # LLM settings
    question_model: str = "claude-3-haiku-20240307"
    answer_model: str = "claude-3-5-sonnet-20241022"
    validation_model: str = "claude-3-haiku-20240307"
    questions_per_repo: int = 30
    llm_timeout: int = 60
    llm_max_retries: int = 2
    llm_concurrency: int = 3

    # Pipeline settings
    checkpoint_interval: int = 10  # Save every N repos
    data_dir: Path = Path("data/sigma")
    cleanup_clones: bool = True

    @classmethod
    def load(cls, path: Path | None = None) -> SigmaConfig:
        """Load from .sigmarc.toml or environment."""
        ...
```

**Acceptance Criteria:**
- [ ] Environment variable overrides work (`MU_SIGMA_*`)
- [ ] Config file loading (`.sigmarc.toml`)
- [ ] Sensible defaults that stay within budget

---

### Task 3: GitHub Repository Fetching (`repos.py`)
**Priority:** P0 (blocking)
**Files:** `src/mu/sigma/repos.py`

Fetch top repos using GitHub Search API:

```python
async def fetch_top_repos(
    config: SigmaConfig,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[RepoInfo]:
    """Fetch top repos by stars for configured languages."""
    ...

def save_repos(repos: list[RepoInfo], path: Path) -> None:
    """Save repos to JSON file."""
    ...

def load_repos(path: Path) -> list[RepoInfo]:
    """Load repos from JSON file."""
    ...
```

**Implementation Notes:**
- Use `httpx` async client
- Handle rate limiting (403 response)
- Support GitHub token via `GITHUB_TOKEN` env var
- Cache results to `data/sigma/repos.json`

**Acceptance Criteria:**
- [ ] Fetches repos sorted by stars
- [ ] Excludes repos > max_size_kb
- [ ] Handles rate limits gracefully
- [ ] Saves to repos.json

---

### Task 4: Repository Cloning (`clone.py`)
**Priority:** P0 (blocking)
**Files:** `src/mu/sigma/clone.py`

Clone and cleanup repos:

```python
@dataclass
class CloneResult:
    repo_name: str
    local_path: Path | None
    success: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]: ...

def clone_repo(repo: RepoInfo, target_dir: Path) -> CloneResult:
    """Shallow clone a repository."""
    # git clone --depth 1 --single-branch
    ...

def cleanup_clone(clone_result: CloneResult) -> None:
    """Remove cloned repository."""
    ...

@contextmanager
def cloned_repo(repo: RepoInfo, target_dir: Path) -> Iterator[Path]:
    """Context manager that clones and auto-cleans."""
    ...
```

**Implementation Notes:**
- Use `subprocess` for git commands (like MU's approach)
- Shallow clone only (`--depth 1`)
- Clean up on exit (context manager)
- Handle clone failures gracefully

**Acceptance Criteria:**
- [ ] Shallow clones to minimize disk usage
- [ ] Context manager auto-cleanup
- [ ] Error handling (not all repos clone successfully)

---

### Task 5: MU Build Integration (`build.py`)
**Priority:** P0 (blocking)
**Files:** `src/mu/sigma/build.py`

Build `.mubase` for each repo:

```python
@dataclass
class BuildResult:
    repo_name: str
    mubase_path: Path | None
    node_count: int
    edge_count: int
    success: bool
    error: str | None = None
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]: ...

def build_mubase(
    repo_path: Path,
    output_dir: Path,
    repo_name: str,
) -> BuildResult:
    """Build .mubase for a repository."""
    ...

def get_graph_summary(mubase_path: Path) -> dict[str, Any]:
    """Get node/edge counts and sample nodes for LLM context."""
    ...
```

**Implementation Notes:**
- Use MU's existing `mu bootstrap` command via subprocess
- OR import `mu.kernel.builder` directly
- Save .mubase files to `data/sigma/mubases/{repo_name}.mubase`
- Extract graph summary for LLM prompts

**Acceptance Criteria:**
- [ ] Builds .mubase using MU's infrastructure
- [ ] Extracts node/edge counts
- [ ] >80% repo success rate expected

---

### Task 6: Question Generation (`questions.py`)
**Priority:** P0 (blocking)
**Files:** `src/mu/sigma/questions.py`

Generate diverse questions using Haiku:

```python
QUESTION_PROMPT = """You are analyzing a codebase. Given this summary, generate {count} diverse questions.

Codebase: {repo_name}
Language: {language}

Available entities:
- Classes: {classes}
- Functions: {functions}
- Modules: {modules}

Generate questions across these categories:
1. Architecture (5): How is X structured? What pattern does Y use?
2. Dependencies (5): What does X depend on? What uses Y?
3. Navigation (10): Where is X implemented? What handles Y?
4. Understanding (10): How does X work? What is the purpose of Y?

Output JSON array:
[{{"question": "...", "category": "architecture|dependencies|navigation|understanding"}}]
"""

async def generate_questions(
    mubase_path: Path,
    repo_name: str,
    config: SigmaConfig,
) -> list[QAPair]:
    """Generate questions about a codebase."""
    ...
```

**Implementation Notes:**
- Use Anthropic SDK directly (or LiteLLM)
- Include actual node names in prompt
- Parse JSON response
- Retry on parse failures

**Acceptance Criteria:**
- [ ] Generates 30 questions per repo
- [ ] Questions reference actual node names
- [ ] Categories distributed as specified

---

### Task 7: Answer Generation (`answers.py`)
**Priority:** P0 (blocking)
**Files:** `src/mu/sigma/answers.py`

Generate answers using Sonnet:

```python
ANSWER_PROMPT = """You are answering questions about a codebase.

Codebase: {repo_name}
Question: {question}
Category: {category}

Available nodes (answer MUST reference these):
{nodes}

Provide:
1. A concise answer (2-3 sentences)
2. List of relevant_nodes (MUST exist in available nodes)
3. Confidence score (0.0-1.0)

Output JSON:
{{"answer": "...", "relevant_nodes": ["NodeA", "NodeB"], "confidence": 0.95}}
"""

async def generate_answer(
    qa_pair: QAPair,
    mubase_path: Path,
    config: SigmaConfig,
) -> QAPair:
    """Generate answer for a question."""
    ...

async def generate_answers_batch(
    qa_pairs: list[QAPair],
    mubase_path: Path,
    config: SigmaConfig,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[QAPair]:
    """Generate answers for multiple questions with concurrency."""
    ...
```

**Implementation Notes:**
- Sonnet for higher quality answers
- Include full node list in prompt
- Validate referenced nodes exist
- Async batch processing with semaphore

**Acceptance Criteria:**
- [ ] Answers reference valid node names
- [ ] Confidence scores provided
- [ ] Batch processing with concurrency limit

---

### Task 8: Answer Validation (`validate.py`)
**Priority:** P0 (blocking)
**Files:** `src/mu/sigma/validate.py`

Validate answers using Haiku:

```python
VALIDATION_PROMPT = """Validate this Q&A pair against the codebase.

Question: {question}
Answer: {answer}
Referenced nodes: {nodes}

Validation checks:
1. Do referenced nodes exist? (check against: {available_nodes})
2. Is the answer semantically correct for the question?
3. Are the referenced nodes relevant to the question?

Output JSON:
{{
  "status": "accepted|corrected|rejected",
  "valid_nodes": ["NodeA"],
  "invalid_nodes": ["NodeC"],
  "reasoning": "..."
}}
"""

async def validate_answer(
    qa_pair: QAPair,
    mubase_path: Path,
    config: SigmaConfig,
) -> QAPair:
    """Validate a Q&A pair."""
    ...

async def validate_answers_batch(
    qa_pairs: list[QAPair],
    mubase_path: Path,
    config: SigmaConfig,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[QAPair]:
    """Validate multiple Q&A pairs."""
    ...
```

**Implementation Notes:**
- Haiku for cost efficiency
- Check node existence programmatically first
- LLM validates semantic correctness
- Filter out invalid nodes

**Acceptance Criteria:**
- [ ] >85% validation pass rate
- [ ] Invalid nodes filtered from pairs
- [ ] Rejected pairs excluded from training

---

### Task 9: Training Pair Extraction (`pairs.py`)
**Priority:** P0 (blocking)
**Files:** `src/mu/sigma/pairs.py`

Extract training triplets:

```python
def extract_structural_pairs(
    mubase_path: Path,
    repo_name: str,
) -> list[TrainingPair]:
    """Extract pairs from graph edges."""
    # For each edge type:
    # - contains: class -> method (weight 1.0)
    # - calls: caller -> callee (weight 0.9)
    # - imports: module -> dependency (weight 0.8)
    # - inherits: child -> parent (weight 0.9)
    #
    # Hard negatives: same file but unrelated nodes
    ...

def extract_qa_pairs(
    qa_pairs: list[QAPair],
    repo_name: str,
) -> list[TrainingPair]:
    """Convert validated Q&A to training pairs."""
    # Anchor: question text
    # Positive: each relevant node
    # Negative: nodes from same repo not in relevant_nodes
    ...

def get_hard_negative(
    mubase_path: Path,
    positive_node: str,
    exclude_nodes: set[str],
) -> str | None:
    """Get hard negative from same codebase."""
    ...
```

**Implementation Notes:**
- Query .mubase for edges by type
- Hard negatives from same file (harder to distinguish)
- Different weights by edge type
- Co-relevance pairs from Q&A (nodes answering same question)

**Acceptance Criteria:**
- [ ] Extracts pairs from all edge types
- [ ] Hard negatives from same codebase
- [ ] Appropriate weights assigned

---

### Task 10: Pipeline Orchestrator (`orchestrator.py`)
**Priority:** P0 (blocking)
**Files:** `src/mu/sigma/orchestrator.py`

Main pipeline runner:

```python
@dataclass
class Checkpoint:
    processed_repos: list[str]
    results: list[ProcessingResult]
    stats: PipelineStats
    timestamp: str

    def to_dict(self) -> dict[str, Any]: ...

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint: ...

class SigmaPipeline:
    def __init__(self, config: SigmaConfig):
        self.config = config
        self.stats = PipelineStats()

    async def run(
        self,
        repos: list[RepoInfo],
        resume_from: Checkpoint | None = None,
    ) -> PipelineStats:
        """Run full pipeline on repos."""
        ...

    async def process_repo(self, repo: RepoInfo) -> ProcessingResult:
        """Process a single repository."""
        ...

    def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        """Save checkpoint to disk."""
        ...

    def load_checkpoint(self) -> Checkpoint | None:
        """Load checkpoint if exists."""
        ...

    def export_training_pairs(self, pairs: list[TrainingPair]) -> Path:
        """Export to parquet format."""
        ...
```

**Implementation Notes:**
- Process repos sequentially (disk space management)
- Checkpoint every N repos
- Resume from checkpoint on failure
- Export final parquet with all pairs

**Acceptance Criteria:**
- [ ] Processes 100 repos in <8 hours
- [ ] Checkpoint saves every 10 repos
- [ ] Resume works correctly
- [ ] Exports parquet file

---

### Task 11: CLI Commands (`cli.py`)
**Priority:** P1 (important)
**Files:** `src/mu/sigma/cli.py`, `src/mu/cli.py` (register)

Add CLI commands:

```python
@click.group()
def sigma():
    """MU-SIGMA training data pipeline."""
    pass

@sigma.command()
@click.option("--languages", "-l", multiple=True, default=["python", "typescript"])
@click.option("--count", "-n", default=50, help="Repos per language")
@click.option("--min-stars", default=500)
@click.option("--output", "-o", type=click.Path(path_type=Path))
def fetch(languages, count, min_stars, output):
    """Fetch top GitHub repositories."""
    ...

@sigma.command()
@click.option("--resume", is_flag=True, help="Resume from checkpoint")
@click.option("--repo", help="Process single repo (for testing)")
@click.option("--dry-run", is_flag=True, help="Show what would be processed")
def run(resume, repo, dry_run):
    """Run training data pipeline."""
    ...

@sigma.command()
def stats():
    """Show pipeline statistics."""
    ...

@sigma.command()
@click.argument("parquet_path", type=click.Path(exists=True, path_type=Path))
@click.option("--sample", "-n", default=10, help="Number of samples to show")
def inspect(parquet_path, sample):
    """Inspect training data."""
    ...
```

**Acceptance Criteria:**
- [ ] `mu sigma fetch` fetches repos
- [ ] `mu sigma run` runs pipeline
- [ ] `mu sigma run --resume` resumes from checkpoint
- [ ] `mu sigma stats` shows statistics
- [ ] `mu sigma inspect` samples training data

---

### Task 12: Module Integration (`__init__.py`)
**Priority:** P1 (important)
**Files:** `src/mu/sigma/__init__.py`, `src/mu/cli.py`

Wire up the module:

```python
# src/mu/sigma/__init__.py
"""MU-SIGMA: Training Data Pipeline for Structure-Aware Embeddings."""

from mu.sigma.config import SigmaConfig
from mu.sigma.models import (
    QAPair,
    RepoInfo,
    TrainingPair,
    ProcessingResult,
    PipelineStats,
)
from mu.sigma.orchestrator import SigmaPipeline

__all__ = [
    "SigmaConfig",
    "SigmaPipeline",
    "QAPair",
    "RepoInfo",
    "TrainingPair",
    "ProcessingResult",
    "PipelineStats",
]
```

**Acceptance Criteria:**
- [ ] Module imports work
- [ ] CLI registered in main `mu` command
- [ ] No circular imports

---

## Implementation Order

1. **Task 1: Data Models** - Foundation for everything else
2. **Task 2: Configuration** - Needed before any processing
3. **Task 3: GitHub Fetching** - Get the repos list
4. **Task 4: Cloning** - Get code locally
5. **Task 5: MU Build** - Generate .mubase graphs
6. **Task 6: Questions** - Generate questions (depends on .mubase)
7. **Task 7: Answers** - Generate answers (depends on questions)
8. **Task 8: Validation** - Validate answers
9. **Task 9: Pair Extraction** - Extract training pairs
10. **Task 10: Orchestrator** - Tie it all together
11. **Task 11: CLI** - User interface
12. **Task 12: Integration** - Wire up module

---

## Quality Checklist

Before marking complete:

- [ ] `ruff check src/mu/sigma/` passes
- [ ] `ruff format src/mu/sigma/` applied
- [ ] `mypy src/mu/sigma/` passes
- [ ] All dataclasses have `to_dict()`
- [ ] Async LLM calls use semaphore concurrency
- [ ] Error handling returns data (not exceptions)
- [ ] Progress callbacks implemented
- [ ] Checkpointing works
- [ ] Budget stays under $50

---

## Testing Strategy

| Layer | Coverage Target | Focus |
|-------|-----------------|-------|
| Models | 95% | Serialization, validation |
| Config | 90% | Loading, env overrides |
| LLM modules | 80% | Mock responses, error handling |
| Orchestrator | 85% | Checkpoint save/load, resume |
| CLI | 70% | Happy paths |

---

## Risk Mitigations

| Risk | Mitigation |
|------|------------|
| LLM costs exceed budget | Use Haiku where possible, monitor `estimated_cost_usd` |
| GitHub rate limiting | Support token auth, cache repos.json |
| MU build failures | Skip failed repos, target 80% success |
| Invalid node references | Validation step filters bad data |
| Pipeline crashes | Checkpoint every 10 repos, resume support |
