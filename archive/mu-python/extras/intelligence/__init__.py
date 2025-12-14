"""Intelligence Layer - Pattern recognition and proactive guidance.

This module provides intelligent features for AI-assisted development:

- Pattern Library: Auto-detect and catalog recurring codebase patterns
- Related Files: Suggest files that typically change together
- Proactive Warnings: Impact, staleness, security warnings
- Macro Synthesis: Generate compression macros from patterns

Usage:
    from mu.extras.intelligence import PatternDetector, PatternCategory
    from mu.kernel import MUbase

    db = MUbase(".mubase")
    detector = PatternDetector(db)

    # Detect all patterns
    result = detector.detect()

    # Filter by category
    result = detector.detect(category=PatternCategory.ERROR_HANDLING)
"""

from mu.extras.intelligence.models import (
    CodeExample,
    EntityType,
    FileContext,
    GeneratedFile,
    GenerateResult,
    MacroDefinition,
    MacroTier,
    Pattern,
    PatternCategory,
    PatternExample,
    PatternsResult,
    ProactiveWarning,
    Suggestion,
    SynthesisResult,
    TaskAnalysis,
    TaskContextResult,
    TaskType,
    TemplateType,
    Warning,
    WarningCategory,
    WarningsResult,
)
from mu.extras.intelligence.patterns import PatternDetector
from mu.extras.intelligence.related import (
    ConventionPattern,
    RelatedFile,
    RelatedFilesDetector,
    RelatedFilesResult,
)
from mu.extras.intelligence.synthesizer import MacroSynthesizer
from mu.extras.intelligence.task_context import (
    TaskAnalyzer,
    TaskContextConfig,
    TaskContextExtractor,
)
from mu.extras.intelligence.warnings import ProactiveWarningGenerator, WarningConfig
from mu.extras.intelligence.why import CommitInfo, WhyAnalyzer, WhyResult

__all__ = [
    "CodeExample",
    "CommitInfo",
    "ConventionPattern",
    "EntityType",
    "FileContext",
    "GeneratedFile",
    "GenerateResult",
    "MacroDefinition",
    "MacroSynthesizer",
    "MacroTier",
    "Pattern",
    "PatternCategory",
    "PatternDetector",
    "PatternExample",
    "PatternsResult",
    "ProactiveWarning",
    "ProactiveWarningGenerator",
    "RelatedFile",
    "RelatedFilesDetector",
    "RelatedFilesResult",
    "Suggestion",
    "SynthesisResult",
    "TaskAnalyzer",
    "TaskContextConfig",
    "TaskContextExtractor",
    "TaskAnalysis",
    "TaskContextResult",
    "TaskType",
    "TemplateType",
    "Warning",
    "WarningCategory",
    "WarningConfig",
    "WarningsResult",
    "WhyAnalyzer",
    "WhyResult",
]
