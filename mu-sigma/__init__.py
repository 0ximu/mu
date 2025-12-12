"""MU-SIGMA: Training Data Pipeline for Structure-Aware Embeddings.

Self-bootstrapping training data generation by leveraging MU's code graph
infrastructure to automatically create embedding training pairs.

The key insight: the graph IS the training signal.
- Graph edges (contains, calls, imports, inherits) become structural pairs
- LLM-generated Q&A pairs bridge natural language to code nodes
"""

from mu.sigma.config import SigmaConfig
from mu.sigma.models import (
    BuildResult,
    Checkpoint,
    CloneResult,
    PairType,
    PipelineStats,
    ProcessingResult,
    QAPair,
    QuestionCategory,
    RepoInfo,
    TrainingPair,
    ValidationStatus,
)

__all__ = [
    # Config
    "SigmaConfig",
    # Models
    "BuildResult",
    "Checkpoint",
    "CloneResult",
    "PairType",
    "PipelineStats",
    "ProcessingResult",
    "QAPair",
    "QuestionCategory",
    "RepoInfo",
    "TrainingPair",
    "ValidationStatus",
]

__version__ = "0.1.0"
