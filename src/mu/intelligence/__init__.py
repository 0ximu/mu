"""Intelligence Layer - Task-aware context and pattern recognition.

This module provides intelligent features that transform MU from a code analysis
tool into an AI coding assistant's companion:

- Pattern Library: Auto-detect and catalog recurring codebase patterns
- Code Templates: Generate boilerplate that matches codebase patterns
- NL to MUQL: Natural language to MUQL query translation
- Task Context: Curated context bundles for development tasks
- Change Validator: Pre-commit pattern validation
- Related Files: Suggest files that typically change together
- Proactive Warnings: Impact, staleness, security warnings

Usage:
    from mu.intelligence import PatternDetector, PatternCategory
    from mu.kernel import MUbase

    db = MUbase(".mubase")
    detector = PatternDetector(db)

    # Detect all patterns
    result = detector.detect()

    # Filter by category
    result = detector.detect(category=PatternCategory.ERROR_HANDLING)

    # Generate code templates
    from mu.intelligence import CodeGenerator, TemplateType

    generator = CodeGenerator(db)
    result = generator.generate(TemplateType.SERVICE, "UserManagement")

    # Natural language to MUQL translation
    from mu.intelligence import NL2MUQLTranslator, translate

    translator = NL2MUQLTranslator(db)
    result = translator.translate("What are the most complex functions?")
    print(result.muql)  # SELECT name, complexity FROM functions ORDER BY complexity DESC LIMIT 10
"""

from mu.intelligence.generator import CodeGenerator
from mu.intelligence.memory import MemoryManager
from mu.intelligence.models import (
    CodeExample,
    EntityType,
    FileContext,
    GeneratedFile,
    GenerateResult,
    MacroDefinition,
    MacroTier,
    Memory,
    MemoryCategory,
    Pattern,
    PatternCategory,
    PatternExample,
    PatternsResult,
    ProactiveWarning,
    RecallResult,
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
from mu.intelligence.nl2muql import NL2MUQLTranslator, TranslationResult, translate
from mu.intelligence.patterns import PatternDetector
from mu.intelligence.related import (
    ConventionPattern,
    RelatedFile,
    RelatedFilesDetector,
    RelatedFilesResult,
)
from mu.intelligence.synthesizer import MacroSynthesizer
from mu.intelligence.task_context import (
    TaskAnalyzer,
    TaskContextConfig,
    TaskContextExtractor,
)
from mu.intelligence.validator import (
    ChangedFile,
    ChangeValidator,
    ValidationResult,
    Violation,
    ViolationSeverity,
)
from mu.intelligence.warnings import ProactiveWarningGenerator, WarningConfig
from mu.intelligence.why import CommitInfo, WhyAnalyzer, WhyResult

__all__ = [
    "ChangeValidator",
    "ChangedFile",
    "CodeExample",
    "CodeGenerator",
    "CommitInfo",
    "ConventionPattern",
    "EntityType",
    "FileContext",
    "GeneratedFile",
    "GenerateResult",
    "MacroDefinition",
    "MacroSynthesizer",
    "MacroTier",
    "Memory",
    "MemoryCategory",
    "MemoryManager",
    "NL2MUQLTranslator",
    "Pattern",
    "PatternCategory",
    "PatternDetector",
    "PatternExample",
    "PatternsResult",
    "ProactiveWarning",
    "ProactiveWarningGenerator",
    "RecallResult",
    "RelatedFile",
    "RelatedFilesDetector",
    "RelatedFilesResult",
    "Suggestion",
    "SynthesisResult",
    "TaskAnalysis",
    "TaskAnalyzer",
    "TaskContextConfig",
    "TaskContextExtractor",
    "TaskContextResult",
    "TaskType",
    "TemplateType",
    "TranslationResult",
    "translate",
    "ValidationResult",
    "Violation",
    "ViolationSeverity",
    "Warning",
    "WarningCategory",
    "WarningConfig",
    "WarningsResult",
    "WhyAnalyzer",
    "WhyResult",
]
