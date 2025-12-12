"""Configuration for MU-SIGMA pipeline.

Uses Pydantic BaseSettings for environment variable support,
following MU's established config patterns.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseModel):
    """LLM-specific settings."""

    question_model: str = Field(
        default="claude-3-haiku-20240307",
        description="Model for question generation (cost-efficient)",
    )
    answer_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Model for answer generation (higher quality)",
    )
    validation_model: str = Field(
        default="claude-3-haiku-20240307",
        description="Model for answer validation (cost-efficient)",
    )
    timeout_seconds: int = Field(
        default=60,
        description="Timeout for LLM API calls",
    )
    max_retries: int = Field(
        default=2,
        description="Maximum retry attempts for failed LLM calls",
    )
    concurrency: int = Field(
        default=3,
        description="Maximum concurrent LLM requests",
    )


class RepoSettings(BaseModel):
    """Repository fetching settings."""

    languages: list[str] = Field(
        default=["python", "typescript"],
        description="Languages to fetch repos for",
    )
    repos_per_language: int = Field(
        default=50,
        description="Number of repos to fetch per language",
    )
    min_stars: int = Field(
        default=500,
        description="Minimum stars for repo selection",
    )
    max_size_kb: int = Field(
        default=100_000,
        description="Maximum repo size in KB (100MB default)",
    )


class PipelineSettings(BaseModel):
    """Pipeline execution settings."""

    questions_per_repo: int = Field(
        default=30,
        description="Number of questions to generate per repo",
    )
    checkpoint_interval: int = Field(
        default=10,
        description="Save checkpoint every N repos",
    )
    cleanup_clones: bool = Field(
        default=True,
        description="Remove cloned repos after processing",
    )
    skip_existing_mubase: bool = Field(
        default=True,
        description="Skip building mubase if already exists",
    )


class PathSettings(BaseModel):
    """Path configuration."""

    data_dir: Path = Field(
        default=Path("data/sigma"),
        description="Base directory for pipeline data",
    )

    @property
    def repos_file(self) -> Path:
        """Path to repos.json."""
        return self.data_dir / "repos.json"

    @property
    def mubases_dir(self) -> Path:
        """Directory for .mubase files."""
        return self.data_dir / "mubases"

    @property
    def qa_pairs_dir(self) -> Path:
        """Directory for Q&A pair JSONs."""
        return self.data_dir / "qa_pairs"

    @property
    def training_dir(self) -> Path:
        """Directory for training output."""
        return self.data_dir / "training"

    @property
    def clones_dir(self) -> Path:
        """Directory for temporary clones."""
        return self.data_dir / "clones"

    @property
    def checkpoint_file(self) -> Path:
        """Path to checkpoint file."""
        return self.data_dir / "checkpoint.json"


class CostSettings(BaseModel):
    """Cost tracking settings."""

    # Prices per 1M tokens (as of Dec 2024)
    haiku_input_price: float = Field(
        default=0.25,
        description="Haiku input price per 1M tokens",
    )
    haiku_output_price: float = Field(
        default=1.25,
        description="Haiku output price per 1M tokens",
    )
    sonnet_input_price: float = Field(
        default=3.0,
        description="Sonnet input price per 1M tokens",
    )
    sonnet_output_price: float = Field(
        default=15.0,
        description="Sonnet output price per 1M tokens",
    )
    budget_limit_usd: float = Field(
        default=50.0,
        description="Maximum budget for pipeline run",
    )


class SigmaConfig(BaseSettings):
    """Main MU-SIGMA configuration.

    Configuration resolution order (highest to lowest priority):
    1. Environment variables (MU_SIGMA_* prefix)
    2. Provided config file path
    3. .sigmarc.toml in current directory
    4. Built-in defaults
    """

    model_config = SettingsConfigDict(
        env_prefix="MU_SIGMA_",
        env_nested_delimiter="_",
        extra="ignore",
    )

    version: str = Field(default="0.1.0", description="Config version")
    llm: LLMSettings = Field(default_factory=LLMSettings)
    repos: RepoSettings = Field(default_factory=RepoSettings)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    paths: PathSettings = Field(default_factory=PathSettings)
    costs: CostSettings = Field(default_factory=CostSettings)

    def with_data_dir(self, data_dir: Path) -> SigmaConfig:
        """Return a copy of this config with a different data directory.

        This enables parallel pipeline runs with isolated paths.

        Args:
            data_dir: New base directory for all pipeline data

        Returns:
            New SigmaConfig with updated paths
        """
        return SigmaConfig(
            version=self.version,
            llm=self.llm,
            repos=self.repos,
            pipeline=self.pipeline,
            paths=PathSettings(data_dir=data_dir),
            costs=self.costs,
        )

    @classmethod
    def load(cls, config_path: Path | None = None) -> SigmaConfig:
        """Load configuration from file and environment.

        Resolution order (highest to lowest priority):
        1. Environment variables (MU_SIGMA_* prefix)
        2. Provided config file path
        3. .sigmarc.toml in current directory
        4. Built-in defaults
        """
        config_data: dict[str, Any] = {}

        locations: list[Path] = []
        if config_path:
            locations.append(config_path)
        locations.append(Path.cwd() / ".sigmarc.toml")

        for loc in locations:
            if loc.exists():
                with open(loc, "rb") as f:
                    config_data = tomllib.load(f)
                break

        return cls(**config_data)

    def ensure_directories(self) -> None:
        """Create all required directories."""
        self.paths.data_dir.mkdir(parents=True, exist_ok=True)
        self.paths.mubases_dir.mkdir(parents=True, exist_ok=True)
        self.paths.qa_pairs_dir.mkdir(parents=True, exist_ok=True)
        self.paths.training_dir.mkdir(parents=True, exist_ok=True)
        self.paths.clones_dir.mkdir(parents=True, exist_ok=True)

    def estimate_cost(
        self,
        num_repos: int,
        questions_per_repo: int | None = None,
    ) -> dict[str, float]:
        """Estimate LLM costs for a pipeline run.

        Returns estimated costs broken down by model.
        """
        qpr = questions_per_repo or self.pipeline.questions_per_repo

        # Rough token estimates per operation
        question_gen_tokens = 2000  # Input + output for batch
        answer_gen_tokens = 1500  # Per question
        validation_tokens = 1000  # Per Q&A pair

        total_questions = num_repos * qpr

        # Haiku costs (questions + validation)
        haiku_tokens = (
            num_repos * question_gen_tokens  # Question generation
            + total_questions * validation_tokens  # Validation
        )
        haiku_cost = (
            (haiku_tokens / 1_000_000)
            * (self.costs.haiku_input_price + self.costs.haiku_output_price)
            / 2
        )  # Rough split

        # Sonnet costs (answers only)
        sonnet_tokens = total_questions * answer_gen_tokens
        sonnet_cost = (
            (sonnet_tokens / 1_000_000)
            * (self.costs.sonnet_input_price + self.costs.sonnet_output_price)
            / 2
        )

        return {
            "haiku_tokens": haiku_tokens,
            "haiku_cost_usd": round(haiku_cost, 2),
            "sonnet_tokens": sonnet_tokens,
            "sonnet_cost_usd": round(sonnet_cost, 2),
            "total_cost_usd": round(haiku_cost + sonnet_cost, 2),
            "within_budget": (haiku_cost + sonnet_cost) <= self.costs.budget_limit_usd,
        }


def get_default_config_toml() -> str:
    """Return default configuration as TOML string."""
    return """# MU-SIGMA Configuration
# Environment variables override with MU_SIGMA_ prefix

[llm]
question_model = "claude-3-haiku-20240307"
answer_model = "claude-sonnet-4-20250514"
validation_model = "claude-3-haiku-20240307"
timeout_seconds = 60
max_retries = 2
concurrency = 3

[repos]
languages = ["python", "typescript"]
repos_per_language = 50
min_stars = 500
max_size_kb = 100000  # 100MB

[pipeline]
questions_per_repo = 30
checkpoint_interval = 10
cleanup_clones = true
skip_existing_mubase = true

[paths]
data_dir = "data/sigma"

[costs]
haiku_input_price = 0.25
haiku_output_price = 1.25
sonnet_input_price = 3.0
sonnet_output_price = 15.0
budget_limit_usd = 50.0
"""
