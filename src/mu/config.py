"""Configuration models for MU CLI."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ScannerConfig(BaseModel):
    """Scanner configuration."""

    ignore: list[str] = Field(
        default=[
            "node_modules/",
            ".git/",
            "__pycache__/",
            "*.pyc",
            ".venv/",
            "venv/",
            "dist/",
            "build/",
            "*.min.js",
            "*.bundle.js",
            "*.lock",
            ".mu-cache/",
        ],
        description="Glob patterns to ignore during scanning",
    )
    include_hidden: bool = Field(
        default=False,
        description="Include hidden files and directories",
    )
    max_file_size_kb: int = Field(
        default=1000,
        description="Maximum file size to process in KB",
    )


class ParserConfig(BaseModel):
    """Parser configuration."""

    languages: list[str] | Literal["auto"] = Field(
        default="auto",
        description="Languages to process ('auto' detects from extensions)",
    )


class ReducerConfig(BaseModel):
    """Reducer configuration."""

    strip_comments: bool = Field(
        default=True,
        description="Strip comments from output",
    )
    strip_docstrings: bool = Field(
        default=False,
        description="Strip docstrings (keep for semantic value by default)",
    )
    complexity_threshold: int = Field(
        default=20,
        description="AST node count before triggering LLM summarization",
    )


class OllamaConfig(BaseModel):
    """Ollama-specific LLM configuration."""

    base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama server URL",
    )
    model: str = Field(
        default="codellama",
        description="Default Ollama model",
    )


class LLMConfig(BaseModel):
    """LLM configuration."""

    enabled: bool = Field(
        default=False,
        description="Enable LLM-enhanced summarization",
    )
    provider: Literal["anthropic", "openai", "ollama", "openrouter"] = Field(
        default="anthropic",
        description="LLM provider to use",
    )
    model: str = Field(
        default="claude-3-haiku-20240307",
        description="Model to use for summarization",
    )
    timeout_seconds: int = Field(
        default=30,
        description="Timeout for LLM API calls",
    )
    max_retries: int = Field(
        default=2,
        description="Maximum retry attempts for failed LLM calls",
    )
    ollama: OllamaConfig = Field(
        default_factory=OllamaConfig,
        description="Ollama-specific settings",
    )


class SecurityConfig(BaseModel):
    """Security configuration."""

    redact_secrets: bool = Field(
        default=True,
        description="Automatically redact detected secrets",
    )
    secret_patterns: str = Field(
        default="default",
        description="Secret patterns to use ('default' or path to custom file)",
    )


class OutputConfig(BaseModel):
    """Output configuration."""

    format: Literal["mu", "json", "markdown"] = Field(
        default="mu",
        description="Output format",
    )
    include_line_numbers: bool = Field(
        default=False,
        description="Include source line numbers in output",
    )
    include_file_hashes: bool = Field(
        default=True,
        description="Include file content hashes in output",
    )
    shell_safe: bool = Field(
        default=False,
        description="Escape sigils for shell piping",
    )


class CacheConfig(BaseModel):
    """Cache configuration."""

    enabled: bool = Field(
        default=True,
        description="Enable file and LLM response caching",
    )
    directory: str = Field(
        default=".mu-cache",
        description="Cache directory path",
    )
    ttl_hours: int = Field(
        default=168,
        description="Cache time-to-live in hours (default: 1 week)",
    )


class MUConfig(BaseSettings):
    """Main MU configuration."""

    model_config = SettingsConfigDict(
        env_prefix="MU_",
        env_nested_delimiter="_",
        extra="ignore",
    )

    version: str = Field(default="1.0", description="Config version")
    scanner: ScannerConfig = Field(default_factory=ScannerConfig)
    parser: ParserConfig = Field(default_factory=ParserConfig)
    reducer: ReducerConfig = Field(default_factory=ReducerConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)

    @classmethod
    def load(cls, config_path: Path | None = None) -> MUConfig:
        """Load configuration from file and environment.

        Resolution order (highest to lowest priority):
        1. Environment variables
        2. Provided config file path
        3. .murc.toml in current directory
        4. .murc.toml in home directory
        5. Built-in defaults
        """
        config_data: dict = {}

        # Check config file locations
        locations = []
        if config_path:
            locations.append(config_path)
        locations.extend([
            Path.cwd() / ".murc.toml",
            Path.home() / ".murc.toml",
        ])

        for loc in locations:
            if loc.exists():
                with open(loc, "rb") as f:
                    config_data = tomllib.load(f)
                break

        return cls(**config_data)


def get_default_config_toml() -> str:
    """Generate default .murc.toml content."""
    return '''# MU Configuration
# https://github.com/dominaite/mu

[mu]
version = "1.0"

[scanner]
ignore = [
    "node_modules/",
    ".git/",
    "__pycache__/",
    "*.pyc",
    ".venv/",
    "venv/",
    "dist/",
    "build/",
    "*.min.js",
    "*.bundle.js",
    "*.lock",
    ".mu-cache/",
]
include_hidden = false
max_file_size_kb = 1000

[parser]
# "auto" = detect from file extensions
# Or specify: ["python", "typescript", "csharp"]
languages = "auto"

[reducer]
strip_comments = true
strip_docstrings = false  # Keep for semantic value
complexity_threshold = 20  # AST nodes before LLM summarization

[llm]
enabled = false  # Set to true to enable LLM summarization
provider = "anthropic"  # anthropic | openai | ollama | openrouter
model = "claude-3-haiku-20240307"
timeout_seconds = 30
max_retries = 2

[llm.ollama]
base_url = "http://localhost:11434"
model = "codellama"

[security]
redact_secrets = true
secret_patterns = "default"  # Or path to custom patterns file

[output]
format = "mu"  # mu | json | markdown
include_line_numbers = false
include_file_hashes = true
shell_safe = false

[cache]
enabled = true
directory = ".mu-cache"
ttl_hours = 168  # 1 week
'''
