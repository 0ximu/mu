"""Data models for MU-SIGMA pipeline.

All models use dataclasses with to_dict() for JSON serialization,
following MU's established patterns.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any


class QuestionCategory(str, Enum):
    """Categories for generated questions."""

    ARCHITECTURE = "architecture"
    DEPENDENCIES = "dependencies"
    NAVIGATION = "navigation"
    UNDERSTANDING = "understanding"


class ValidationStatus(str, Enum):
    """Status of Q&A validation."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class PairType(str, Enum):
    """Types of training pairs."""

    # Structural pairs (from graph edges)
    CONTAINS = "contains"  # class -> method
    CALLS = "calls"  # caller -> callee
    IMPORTS = "imports"  # module -> dependency
    INHERITS = "inherits"  # child -> parent
    SAME_FILE = "same_file"  # entities in same file

    # Q&A pairs
    QA_RELEVANCE = "qa_relevance"  # question -> relevant node
    CO_RELEVANT = "co_relevant"  # nodes answering same question


@dataclass
class RepoInfo:
    """Information about a GitHub repository."""

    name: str  # "owner/repo"
    url: str  # Clone URL
    stars: int
    language: str  # "python" | "typescript"
    size_kb: int
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "stars": self.stars,
            "language": self.language,
            "size_kb": self.size_kb,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepoInfo:
        return cls(
            name=data["name"],
            url=data["url"],
            stars=data["stars"],
            language=data["language"],
            size_kb=data["size_kb"],
            description=data.get("description"),
        )


@dataclass
class QAPair:
    """A question-answer pair about a codebase."""

    question: str
    category: QuestionCategory
    repo_name: str
    answer: str | None = None
    relevant_nodes: list[str] = field(default_factory=list)
    confidence: float = 0.0
    validation_status: ValidationStatus = ValidationStatus.PENDING
    valid_nodes: list[str] = field(default_factory=list)
    invalid_nodes: list[str] = field(default_factory=list)
    reasoning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "category": self.category.value,
            "repo_name": self.repo_name,
            "answer": self.answer,
            "relevant_nodes": self.relevant_nodes,
            "confidence": self.confidence,
            "validation_status": self.validation_status.value,
            "valid_nodes": self.valid_nodes,
            "invalid_nodes": self.invalid_nodes,
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QAPair:
        return cls(
            question=data["question"],
            category=QuestionCategory(data["category"]),
            repo_name=data["repo_name"],
            answer=data.get("answer"),
            relevant_nodes=data.get("relevant_nodes", []),
            confidence=data.get("confidence", 0.0),
            validation_status=ValidationStatus(data.get("validation_status", "pending")),
            valid_nodes=data.get("valid_nodes", []),
            invalid_nodes=data.get("invalid_nodes", []),
            reasoning=data.get("reasoning"),
        )

    @property
    def is_valid(self) -> bool:
        """Check if this Q&A pair passed validation."""
        return (
            self.validation_status in (ValidationStatus.ACCEPTED, ValidationStatus.CORRECTED)
            and len(self.valid_nodes) > 0
        )


@dataclass
class TrainingPair:
    """A training triplet for embedding fine-tuning."""

    anchor: str  # Question text or node representation
    positive: str  # Semantically related node
    negative: str  # Hard negative (same codebase, unrelated)
    pair_type: PairType
    weight: float  # 0.7-1.0
    source_repo: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor": self.anchor,
            "positive": self.positive,
            "negative": self.negative,
            "pair_type": self.pair_type.value,
            "weight": self.weight,
            "source_repo": self.source_repo,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrainingPair:
        return cls(
            anchor=data["anchor"],
            positive=data["positive"],
            negative=data["negative"],
            pair_type=PairType(data["pair_type"]),
            weight=data["weight"],
            source_repo=data["source_repo"],
        )

    def to_row(self) -> tuple[str, str, str, str, float, str]:
        """Convert to tuple for parquet/database insertion."""
        return (
            self.anchor,
            self.positive,
            self.negative,
            self.pair_type.value,
            self.weight,
            self.source_repo,
        )


@dataclass
class CloneResult:
    """Result of cloning a repository."""

    repo_name: str
    local_path: Path | None
    success: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_name": self.repo_name,
            "local_path": str(self.local_path) if self.local_path else None,
            "success": self.success,
            "error": self.error,
        }


@dataclass
class BuildResult:
    """Result of building a .mubase graph."""

    repo_name: str
    mubase_path: Path | None
    node_count: int = 0
    edge_count: int = 0
    classes: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    success: bool = False
    error: str | None = None
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_name": self.repo_name,
            "mubase_path": str(self.mubase_path) if self.mubase_path else None,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "classes": self.classes,
            "functions": self.functions,
            "modules": self.modules,
            "success": self.success,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BuildResult:
        return cls(
            repo_name=data["repo_name"],
            mubase_path=Path(data["mubase_path"]) if data.get("mubase_path") else None,
            node_count=data.get("node_count", 0),
            edge_count=data.get("edge_count", 0),
            classes=data.get("classes", []),
            functions=data.get("functions", []),
            modules=data.get("modules", []),
            success=data.get("success", False),
            error=data.get("error"),
            duration_seconds=data.get("duration_seconds", 0.0),
        )


@dataclass
class ProcessingResult:
    """Result of processing a single repository."""

    repo_name: str
    success: bool
    mubase_path: Path | None = None
    node_count: int = 0
    edge_count: int = 0
    questions_generated: int = 0
    answers_generated: int = 0
    qa_pairs_validated: int = 0
    qa_pairs_accepted: int = 0
    structural_pairs: int = 0
    qa_training_pairs: int = 0
    error: str | None = None
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_name": self.repo_name,
            "success": self.success,
            "mubase_path": str(self.mubase_path) if self.mubase_path else None,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "questions_generated": self.questions_generated,
            "answers_generated": self.answers_generated,
            "qa_pairs_validated": self.qa_pairs_validated,
            "qa_pairs_accepted": self.qa_pairs_accepted,
            "structural_pairs": self.structural_pairs,
            "qa_training_pairs": self.qa_training_pairs,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProcessingResult:
        return cls(
            repo_name=data["repo_name"],
            success=data["success"],
            mubase_path=Path(data["mubase_path"]) if data.get("mubase_path") else None,
            node_count=data.get("node_count", 0),
            edge_count=data.get("edge_count", 0),
            questions_generated=data.get("questions_generated", 0),
            answers_generated=data.get("answers_generated", 0),
            qa_pairs_validated=data.get("qa_pairs_validated", 0),
            qa_pairs_accepted=data.get("qa_pairs_accepted", 0),
            structural_pairs=data.get("structural_pairs", 0),
            qa_training_pairs=data.get("qa_training_pairs", 0),
            error=data.get("error"),
            duration_seconds=data.get("duration_seconds", 0.0),
        )

    @property
    def total_training_pairs(self) -> int:
        """Total training pairs generated for this repo."""
        return self.structural_pairs + self.qa_training_pairs


@dataclass
class PipelineStats:
    """Aggregate statistics for the pipeline run."""

    total_repos: int = 0
    processed_repos: int = 0
    successful_repos: int = 0
    failed_repos: int = 0
    skipped_repos: int = 0
    total_nodes: int = 0
    total_edges: int = 0
    questions_generated: int = 0
    answers_generated: int = 0
    qa_pairs_validated: int = 0
    qa_pairs_accepted: int = 0
    structural_pairs: int = 0
    qa_training_pairs: int = 0
    llm_tokens_used: int = 0
    estimated_cost_usd: float = 0.0
    total_duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_repos": self.total_repos,
            "processed_repos": self.processed_repos,
            "successful_repos": self.successful_repos,
            "failed_repos": self.failed_repos,
            "skipped_repos": self.skipped_repos,
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "questions_generated": self.questions_generated,
            "answers_generated": self.answers_generated,
            "qa_pairs_validated": self.qa_pairs_validated,
            "qa_pairs_accepted": self.qa_pairs_accepted,
            "structural_pairs": self.structural_pairs,
            "qa_training_pairs": self.qa_training_pairs,
            "total_training_pairs": self.total_training_pairs,
            "llm_tokens_used": self.llm_tokens_used,
            "estimated_cost_usd": self.estimated_cost_usd,
            "total_duration_seconds": self.total_duration_seconds,
            "success_rate": self.success_rate,
            "validation_rate": self.validation_rate,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelineStats:
        return cls(
            total_repos=data.get("total_repos", 0),
            processed_repos=data.get("processed_repos", 0),
            successful_repos=data.get("successful_repos", 0),
            failed_repos=data.get("failed_repos", 0),
            skipped_repos=data.get("skipped_repos", 0),
            total_nodes=data.get("total_nodes", 0),
            total_edges=data.get("total_edges", 0),
            questions_generated=data.get("questions_generated", 0),
            answers_generated=data.get("answers_generated", 0),
            qa_pairs_validated=data.get("qa_pairs_validated", 0),
            qa_pairs_accepted=data.get("qa_pairs_accepted", 0),
            structural_pairs=data.get("structural_pairs", 0),
            qa_training_pairs=data.get("qa_training_pairs", 0),
            llm_tokens_used=data.get("llm_tokens_used", 0),
            estimated_cost_usd=data.get("estimated_cost_usd", 0.0),
            total_duration_seconds=data.get("total_duration_seconds", 0.0),
        )

    @property
    def total_training_pairs(self) -> int:
        """Total training pairs generated."""
        return self.structural_pairs + self.qa_training_pairs

    @property
    def success_rate(self) -> float:
        """Percentage of repos successfully processed."""
        if self.processed_repos == 0:
            return 0.0
        return (self.successful_repos / self.processed_repos) * 100

    @property
    def validation_rate(self) -> float:
        """Percentage of Q&A pairs that passed validation."""
        if self.qa_pairs_validated == 0:
            return 0.0
        return (self.qa_pairs_accepted / self.qa_pairs_validated) * 100

    def add_result(self, result: ProcessingResult) -> None:
        """Update stats with a processing result."""
        self.processed_repos += 1
        if result.success:
            self.successful_repos += 1
            self.total_nodes += result.node_count
            self.total_edges += result.edge_count
            self.questions_generated += result.questions_generated
            self.answers_generated += result.answers_generated
            self.qa_pairs_validated += result.qa_pairs_validated
            self.qa_pairs_accepted += result.qa_pairs_accepted
            self.structural_pairs += result.structural_pairs
            self.qa_training_pairs += result.qa_training_pairs
        else:
            self.failed_repos += 1
        self.total_duration_seconds += result.duration_seconds


@dataclass
class Checkpoint:
    """Pipeline checkpoint for resume support."""

    processed_repos: list[str]
    results: list[ProcessingResult]
    all_training_pairs: list[TrainingPair]
    stats: PipelineStats
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "processed_repos": self.processed_repos,
            "results": [r.to_dict() for r in self.results],
            "all_training_pairs": [p.to_dict() for p in self.all_training_pairs],
            "stats": self.stats.to_dict(),
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        return cls(
            processed_repos=data["processed_repos"],
            results=[ProcessingResult.from_dict(r) for r in data["results"]],
            all_training_pairs=[
                TrainingPair.from_dict(p) for p in data.get("all_training_pairs", [])
            ],
            stats=PipelineStats.from_dict(data["stats"]),
            timestamp=data["timestamp"],
        )

    def save(self, path: Path) -> None:
        """Save checkpoint to file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> Checkpoint | None:
        """Load checkpoint from file."""
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
