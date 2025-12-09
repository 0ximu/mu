"""MCP data models - re-exports all models for easy access."""

from mu.mcp.models.analysis import (
    DepsResult,
    ImpactResult,
    ReviewDiffOutput,
    SemanticDiffOutput,
    ViolationInfo,
)
from mu.mcp.models.common import (
    NodeInfo,
    QueryResult,
    ReadResult,
)
from mu.mcp.models.context import (
    ContextResult,
    OmegaContextOutput,
)
from mu.mcp.models.guidance import (
    PatternInfo,
    PatternsOutput,
    WarningInfo,
    WarningsOutput,
)
from mu.mcp.models.setup import (
    BootstrapResult,
)

__all__ = [
    # Common
    "NodeInfo",
    "QueryResult",
    "ReadResult",
    # Context
    "ContextResult",
    "OmegaContextOutput",
    # Analysis
    "DepsResult",
    "ImpactResult",
    "SemanticDiffOutput",
    "ViolationInfo",
    "ReviewDiffOutput",
    # Guidance
    "PatternInfo",
    "PatternsOutput",
    "WarningInfo",
    "WarningsOutput",
    # Setup
    "BootstrapResult",
]
