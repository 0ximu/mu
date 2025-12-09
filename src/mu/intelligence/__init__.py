"""Intelligence Layer - Pattern recognition and proactive guidance.

This module provides intelligent features for AI-assisted development:

- Pattern Library: Auto-detect and catalog recurring codebase patterns
- Related Files: Suggest files that typically change together
- Proactive Warnings: Impact, staleness, security warnings
- Macro Synthesis: Generate compression macros from patterns

Usage:
    from mu.intelligence import PatternDetector, PatternCategory
    from mu.kernel import MUbase

    db = MUbase(".mubase")
    detector = PatternDetector(db)

    # Detect all patterns
    result = detector.detect()

    # Filter by category
    result = detector.detect(category=PatternCategory.ERROR_HANDLING)
"""

from mu.intelligence.models import (
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
from mu.intelligence.patterns import PatternDetector
from mu.intelligence.related import (
    ConventionPattern,
    RelatedFile,
    RelatedFilesDetector,
    RelatedFilesResult,
)
from mu.intelligence.synthesizer import MacroSynthesizer
from mu.intelligence.warnings import ProactiveWarningGenerator, WarningConfig
from mu.intelligence.why import CommitInfo, WhyAnalyzer, WhyResult

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
