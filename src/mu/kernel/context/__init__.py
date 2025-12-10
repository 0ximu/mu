"""Smart Context extraction for MU Kernel.

This module provides intelligent context extraction from a MUbase graph database.
Given a natural language question, it identifies and extracts the most relevant
code entities to answer that question, fitting within a token budget.

Example:
    >>> from mu.kernel import MUbase
    >>> from mu.kernel.context import SmartContextExtractor, ExtractionConfig
    >>>
    >>> db = MUbase(".mubase")
    >>> config = ExtractionConfig(max_tokens=4000)
    >>> extractor = SmartContextExtractor(db, config)
    >>>
    >>> result = extractor.extract("How does authentication work?")
    >>> print(result.mu_text)
    >>> print(f"Selected {len(result.nodes)} nodes, {result.token_count} tokens")

The extraction pipeline:
    1. Entity extraction - find code identifiers in the question
    2. Node matching - find nodes by name and vector similarity
    3. Graph expansion - include related nodes
    4. Relevance scoring - rank all candidates
    5. Token budgeting - select top nodes within budget
    6. MU export - generate formatted output
"""

from mu.kernel.context.intent import (
    ClassifiedIntent,
    Intent,
    IntentClassifier,
)
from mu.kernel.context.models import (
    ContextResult,
    ExportConfig,
    ExtractedEntity,
    ExtractionConfig,
    ScoredNode,
)
from mu.kernel.context.omega import (
    OmegaConfig,
    OmegaContextExtractor,
    OmegaManifest,
    OmegaResult,
)
from mu.kernel.context.smart import (
    DomainBoundary,
    GraphExpansionConfig,
    SmartContextExtractor,
)
from mu.kernel.context.strategies import (
    DefaultStrategy,
    ExtractionStrategy,
    ImpactStrategy,
    ListStrategy,
    LocateStrategy,
    NavigateStrategy,
    get_strategy,
)

__all__ = [
    # Intent classification
    "ClassifiedIntent",
    "Intent",
    "IntentClassifier",
    # Extraction strategies
    "DefaultStrategy",
    "ExtractionStrategy",
    "ImpactStrategy",
    "ListStrategy",
    "LocateStrategy",
    "NavigateStrategy",
    "get_strategy",
    # Context extraction
    "ContextResult",
    "DomainBoundary",
    "ExportConfig",
    "ExtractionConfig",
    "ExtractedEntity",
    "GraphExpansionConfig",
    "OmegaConfig",
    "OmegaContextExtractor",
    "OmegaManifest",
    "OmegaResult",
    "ScoredNode",
    "SmartContextExtractor",
]
