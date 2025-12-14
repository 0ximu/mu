"""Task-aware context extraction for AI-assisted development.

Provides curated context bundles for development tasks, combining:
- Smart context extraction (relevant code)
- Pattern matching (codebase conventions)
- Proactive warnings (high-impact, security, staleness)
- Entry point suggestions

Usage:
    from mu.extras.intelligence import TaskContextExtractor, TaskContextConfig
    from mu.kernel import MUbase

    db = MUbase(".mubase")
    extractor = TaskContextExtractor(db)

    result = extractor.extract("Add rate limiting to API endpoints")
    print(result.entry_points)
    print(result.patterns)
    for w in result.warnings:
        print(f"Warning: {w.message}")
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from mu.extras.intelligence.models import (
    CodeExample,
    EntityType,
    FileContext,
    Pattern,
    PatternCategory,
    Suggestion,
    TaskAnalysis,
    TaskContextResult,
    TaskType,
    Warning,
)

if TYPE_CHECKING:
    from mu.kernel import MUbase
    from mu.kernel.models import Node

logger = logging.getLogger(__name__)

# Keywords for task type classification
TASK_TYPE_KEYWORDS: dict[TaskType, list[str]] = {
    TaskType.CREATE: [
        "add",
        "create",
        "implement",
        "build",
        "new",
        "introduce",
        "make",
        "write",
        "develop",
    ],
    TaskType.MODIFY: [
        "update",
        "change",
        "edit",
        "modify",
        "alter",
        "adjust",
        "tweak",
        "extend",
    ],
    TaskType.DELETE: ["remove", "delete", "drop", "eliminate", "deprecate"],
    TaskType.REFACTOR: [
        "refactor",
        "restructure",
        "extract",
        "reorganize",
        "clean",
        "simplify",
    ],
    TaskType.DEBUG: ["fix", "bug", "debug", "error", "issue", "crash", "broken", "failing"],
    TaskType.TEST: ["test", "spec", "coverage", "unit test", "integration test"],
    TaskType.DOCUMENT: ["document", "docs", "readme", "comment", "docstring"],
    TaskType.REVIEW: ["review", "audit", "check", "inspect", "analyze"],
}

# Keywords for entity type classification
ENTITY_TYPE_KEYWORDS: dict[EntityType, list[str]] = {
    EntityType.API_ENDPOINT: [
        "api",
        "endpoint",
        "route",
        "rest",
        "graphql",
        "handler",
        "controller",
    ],
    EntityType.HOOK: ["hook", "use"],
    EntityType.COMPONENT: ["component", "view", "page", "screen", "widget", "ui"],
    EntityType.SERVICE: ["service", "manager", "provider", "processor"],
    EntityType.REPOSITORY: ["repository", "repo", "store", "dao", "data access"],
    EntityType.MODEL: ["model", "entity", "schema", "dto", "dataclass"],
    EntityType.MIDDLEWARE: ["middleware", "guard", "filter", "interceptor", "decorator"],
    EntityType.CONFIG: ["config", "settings", "env", "environment"],
    EntityType.TEST: ["test", "spec", "fixture"],
}

# Domain keywords for context hints
DOMAIN_KEYWORDS = {
    "auth": ["auth", "authenticate", "authorization", "login", "logout", "session", "token"],
    "payment": ["payment", "pay", "charge", "billing", "invoice", "subscription", "stripe"],
    "user": ["user", "account", "profile", "member", "customer"],
    "database": ["database", "db", "query", "sql", "migration", "schema", "orm"],
    "api": ["api", "endpoint", "rest", "graphql", "request", "response"],
    "security": ["security", "encrypt", "decrypt", "hash", "secret", "permission", "rbac"],
    "cache": ["cache", "redis", "memcache", "memoize"],
    "queue": ["queue", "job", "worker", "celery", "rq", "async"],
    "email": ["email", "mail", "smtp", "notification"],
}


@dataclass
class TaskContextConfig:
    """Configuration for task context extraction."""

    # Token budget allocation
    max_tokens: int = 8000
    """Maximum tokens in the output."""

    context_token_ratio: float = 0.6
    """Ratio of tokens for core relevant files."""

    pattern_token_ratio: float = 0.2
    """Ratio of tokens for patterns and examples."""

    dependency_token_ratio: float = 0.1
    """Ratio of tokens for dependencies."""

    metadata_token_ratio: float = 0.1
    """Ratio of tokens for warnings and metadata."""

    # Feature flags
    include_patterns: bool = True
    """Include relevant codebase patterns."""

    include_warnings: bool = True
    """Include proactive warnings."""

    include_examples: bool = True
    """Include similar code examples."""

    include_suggestions: bool = True
    """Include suggestions for related changes."""

    # Search settings
    max_files: int = 15
    """Maximum relevant files to include."""

    max_patterns: int = 5
    """Maximum patterns to include."""

    max_examples: int = 3
    """Maximum code examples to include."""

    max_warnings: int = 10
    """Maximum warnings to include."""

    # Relevance thresholds
    min_relevance: float = 0.3
    """Minimum relevance score for file inclusion."""


class TaskAnalyzer:
    """Analyzes natural language task descriptions."""

    def analyze(self, task: str) -> TaskAnalysis:
        """Analyze a task description.

        Args:
            task: Natural language task description.

        Returns:
            TaskAnalysis with inferred type, entities, and keywords.
        """
        task_lower = task.lower()

        # Classify task type
        task_type = self._classify_task_type(task_lower)

        # Extract entity types
        entity_types = self._extract_entity_types(task_lower)

        # Extract keywords for search
        keywords = self._extract_keywords(task)

        # Extract domain hints
        domain_hints = self._extract_domain_hints(task_lower)

        # Calculate confidence
        confidence = self._calculate_confidence(task_type, entity_types, keywords)

        return TaskAnalysis(
            original_task=task,
            task_type=task_type,
            entity_types=entity_types,
            keywords=keywords,
            domain_hints=domain_hints,
            confidence=confidence,
        )

    def _classify_task_type(self, task_lower: str) -> TaskType:
        """Classify the task type based on keywords."""
        scores: dict[TaskType, int] = {}

        for task_type, keywords in TASK_TYPE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in task_lower)
            if score > 0:
                scores[task_type] = score

        if scores:
            return max(scores, key=lambda t: scores[t])
        return TaskType.MODIFY  # Default

    def _extract_entity_types(self, task_lower: str) -> list[EntityType]:
        """Extract likely entity types from the task."""
        types = []

        for entity_type, keywords in ENTITY_TYPE_KEYWORDS.items():
            if any(kw in task_lower for kw in keywords):
                types.append(entity_type)

        return types or [EntityType.UNKNOWN]

    def _extract_keywords(self, task: str) -> list[str]:
        """Extract searchable keywords from the task.

        Extracts:
        - CamelCase identifiers
        - snake_case identifiers
        - Quoted strings
        - File paths
        """
        keywords = []

        # CamelCase: AuthService, UserModel
        keywords.extend(re.findall(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", task))

        # snake_case: get_user, validate_token
        keywords.extend(re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", task))

        # Quoted strings
        keywords.extend(re.findall(r'["\']([^"\']+)["\']', task))

        # File paths
        keywords.extend(re.findall(r"[\w/]+\.\w{1,4}\b", task))

        # Domain-specific words (filter common words)
        common_words = {
            "the",
            "to",
            "a",
            "an",
            "is",
            "in",
            "for",
            "and",
            "or",
            "with",
            "this",
            "that",
            "how",
            "what",
            "why",
            "when",
            "where",
            "which",
        }
        words = re.findall(r"\b[a-z]{4,}\b", task.lower())
        keywords.extend([w for w in words if w not in common_words])

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for kw in keywords:
            if kw.lower() not in seen:
                seen.add(kw.lower())
                unique.append(kw)

        return unique[:20]  # Limit to 20 keywords

    def _extract_domain_hints(self, task_lower: str) -> list[str]:
        """Extract domain hints from the task."""
        hints = []
        for domain, keywords in DOMAIN_KEYWORDS.items():
            if any(kw in task_lower for kw in keywords):
                hints.append(domain)
        return hints

    def _calculate_confidence(
        self,
        task_type: TaskType,
        entity_types: list[EntityType],
        keywords: list[str],
    ) -> float:
        """Calculate confidence in the analysis."""
        confidence = 0.5  # Base confidence

        # Boost for explicit task type match
        if task_type != TaskType.MODIFY:  # Non-default match
            confidence += 0.2

        # Boost for entity types
        if EntityType.UNKNOWN not in entity_types:
            confidence += 0.15

        # Boost for keywords found
        if len(keywords) >= 3:
            confidence += 0.15

        return min(1.0, confidence)


class TaskContextExtractor:
    """Extracts task-aware context bundles for development tasks.

    Combines multiple intelligence sources to provide curated context:
    - Smart context extraction for relevant code
    - Pattern detection for codebase conventions
    - Proactive warnings for high-impact changes
    - Entry point suggestions for task navigation
    """

    def __init__(
        self,
        db: MUbase,
        config: TaskContextConfig | None = None,
        root_path: Path | None = None,
    ) -> None:
        """Initialize the task context extractor.

        Args:
            db: MUbase database instance.
            config: Optional extraction configuration.
            root_path: Optional root path for file operations.
        """
        self.db = db
        self.config = config or TaskContextConfig()

        # Infer root path from database metadata if not provided
        if root_path:
            self.root_path = root_path
        else:
            stats = db.stats()
            root_path_str = stats.get("root_path")
            self.root_path = Path(root_path_str) if root_path_str else Path.cwd()

        self.analyzer = TaskAnalyzer()

    def extract(self, task: str) -> TaskContextResult:
        """Extract context for a development task.

        Args:
            task: Natural language task description.

        Returns:
            TaskContextResult with curated context bundle.
        """
        start_time = time.time()

        # Step 1: Analyze the task
        analysis = self.analyzer.analyze(task)

        # Step 2: Find relevant files using smart context
        relevant_files, mu_text, token_count = self._extract_relevant_files(task, analysis)

        # Step 3: Identify entry points
        entry_points = self._identify_entry_points(relevant_files, analysis)

        # Step 4: Get relevant patterns
        patterns = self._get_relevant_patterns(analysis) if self.config.include_patterns else []

        # Step 5: Find similar examples
        examples = self._find_examples(analysis) if self.config.include_examples else []

        # Step 6: Generate proactive warnings
        warnings = self._generate_warnings(relevant_files) if self.config.include_warnings else []

        # Step 7: Generate suggestions
        suggestions = (
            self._generate_suggestions(analysis, relevant_files, patterns)
            if self.config.include_suggestions
            else []
        )

        # Calculate overall confidence
        confidence = self._calculate_confidence(analysis, relevant_files, patterns)

        elapsed_ms = (time.time() - start_time) * 1000

        return TaskContextResult(
            relevant_files=relevant_files,
            entry_points=entry_points,
            patterns=patterns,
            examples=examples,
            warnings=warnings,
            suggestions=suggestions,
            task_analysis=analysis,
            mu_text=mu_text,
            token_count=token_count,
            confidence=confidence,
            extraction_stats={
                "extraction_time_ms": elapsed_ms,
                "files_found": len(relevant_files),
                "patterns_found": len(patterns),
                "warnings_found": len(warnings),
                "keywords_used": len(analysis.keywords),
            },
        )

    def _extract_relevant_files(
        self, task: str, analysis: TaskAnalysis
    ) -> tuple[list[FileContext], str, int]:
        """Extract relevant files using smart context extraction.

        Returns:
            Tuple of (file contexts, MU text, token count)
        """
        from mu.kernel.context import ExtractionConfig, SmartContextExtractor

        # Configure context extraction
        config = ExtractionConfig(
            max_tokens=int(self.config.max_tokens * self.config.context_token_ratio),
            include_imports=True,
            include_parent=True,
            expand_depth=1,
            exclude_tests=analysis.task_type
            not in (TaskType.TEST, TaskType.DEBUG),  # Include tests for test/debug tasks
        )

        extractor = SmartContextExtractor(self.db, config)
        result = extractor.extract(task)

        # Convert to FileContext list
        file_contexts: list[FileContext] = []
        seen_files: set[str] = set()

        for node in result.nodes:
            if not node.file_path:
                continue

            # Deduplicate by file
            if node.file_path in seen_files:
                continue
            seen_files.add(node.file_path)

            # Get score from relevance_scores dict using node.id
            # Clamp to 0-1 range
            score = min(1.0, max(0.0, result.relevance_scores.get(node.id, 0.5)))

            # Determine relevance reason
            reason = self._determine_relevance_reason(node, analysis)

            # Determine suggested action based on task type
            action = self._determine_action(analysis.task_type, node)

            file_contexts.append(
                FileContext(
                    path=node.file_path,
                    relevance=score,
                    reason=reason,
                    is_entry_point=False,  # Will be set later
                    suggested_action=action,
                )
            )

        # Sort by relevance and limit to max files
        file_contexts.sort(key=lambda fc: fc.relevance, reverse=True)
        file_contexts = file_contexts[: self.config.max_files]

        return file_contexts, result.mu_text, result.token_count

    def _determine_relevance_reason(self, node: Node, analysis: TaskAnalysis) -> str:
        """Determine why a node is relevant to the task."""
        name = node.name or ""
        name_lower = name.lower()

        # Check keyword matches
        for kw in analysis.keywords:
            if kw.lower() in name_lower:
                return f"Name contains '{kw}'"

        # Check domain match
        for domain in analysis.domain_hints:
            domain_keywords = DOMAIN_KEYWORDS.get(domain, [])
            if any(dk in name_lower for dk in domain_keywords):
                return f"Related to {domain} domain"

        # Check entity type match
        for entity_type in analysis.entity_types:
            entity_keywords = ENTITY_TYPE_KEYWORDS.get(entity_type, [])
            if any(ek in name_lower for ek in entity_keywords):
                return f"Matches {entity_type.value} entity type"

        return "Semantically related to task"

    def _determine_action(self, task_type: TaskType, node: Node) -> str:
        """Determine suggested action for a file based on task type."""
        actions = {
            TaskType.CREATE: "reference",
            TaskType.MODIFY: "modify",
            TaskType.DELETE: "review",
            TaskType.REFACTOR: "refactor",
            TaskType.DEBUG: "investigate",
            TaskType.TEST: "test",
            TaskType.DOCUMENT: "document",
            TaskType.REVIEW: "review",
        }
        return actions.get(task_type, "read")

    def _identify_entry_points(
        self, files: list[FileContext], analysis: TaskAnalysis
    ) -> list[str]:
        """Identify suggested entry points for the task."""
        entry_points: list[str] = []

        if not files:
            return entry_points

        # Helper to make path relative if possible
        def relative_path(path: str) -> str:
            try:
                p = Path(path)
                if p.is_absolute() and self.root_path:
                    return str(p.relative_to(self.root_path))
            except ValueError:
                pass
            return path

        # Top files by relevance are entry points
        for fc in files[:3]:
            if fc.relevance >= self.config.min_relevance:
                fc.is_entry_point = True
                entry_points.append(relative_path(fc.path))

        # Add directory-level entry points for certain task types
        if analysis.task_type == TaskType.CREATE:
            # For new code, suggest directories not specific files
            dirs = set()
            for fc in files[:5]:
                parent = str(Path(relative_path(fc.path)).parent)
                if parent and parent != ".":
                    dirs.add(parent)
            # Add unique directories
            for d in list(dirs)[:2]:
                if d not in entry_points:
                    entry_points.append(d)

        return entry_points

    def _get_relevant_patterns(self, analysis: TaskAnalysis) -> list[Pattern]:
        """Get patterns relevant to the task."""
        from mu.extras.intelligence.patterns import PatternDetector

        detector = PatternDetector(self.db)
        all_patterns = detector.detect()

        # Filter patterns by relevance to task
        relevant: list[Pattern] = []

        # Map task types to pattern categories
        type_to_categories: dict[TaskType, list[PatternCategory]] = {
            TaskType.CREATE: [
                PatternCategory.NAMING,
                PatternCategory.ARCHITECTURE,
                PatternCategory.IMPORTS,
            ],
            TaskType.MODIFY: [PatternCategory.ARCHITECTURE, PatternCategory.ERROR_HANDLING],
            TaskType.TEST: [PatternCategory.TESTING],
            TaskType.DEBUG: [PatternCategory.ERROR_HANDLING, PatternCategory.LOGGING],
            TaskType.REFACTOR: [PatternCategory.ARCHITECTURE, PatternCategory.NAMING],
        }

        # Map entity types to pattern categories
        entity_to_categories: dict[EntityType, list[PatternCategory]] = {
            EntityType.API_ENDPOINT: [PatternCategory.API],
            EntityType.COMPONENT: [PatternCategory.COMPONENTS, PatternCategory.STATE_MANAGEMENT],
            EntityType.SERVICE: [PatternCategory.ARCHITECTURE],
            EntityType.TEST: [PatternCategory.TESTING],
        }

        # Get target categories
        target_categories: set[PatternCategory] = set()
        for cat_list in type_to_categories.get(analysis.task_type, []):
            target_categories.add(cat_list)
        for entity_type in analysis.entity_types:
            for cat in entity_to_categories.get(entity_type, []):
                target_categories.add(cat)

        # Always include naming patterns
        target_categories.add(PatternCategory.NAMING)

        # Filter patterns
        for pattern in all_patterns.patterns:
            if pattern.category in target_categories:
                relevant.append(pattern)

        # Sort by frequency and limit
        relevant.sort(key=lambda p: p.frequency, reverse=True)
        return relevant[: self.config.max_patterns]

    def _find_examples(self, analysis: TaskAnalysis) -> list[CodeExample]:
        """Find similar code examples in the codebase."""
        examples: list[CodeExample] = []

        # Use entity types to find similar implementations
        for entity_type in analysis.entity_types:
            if entity_type == EntityType.UNKNOWN:
                continue

            # Search for nodes of the relevant type
            node_examples = self._find_entity_examples(entity_type, analysis.keywords)
            examples.extend(node_examples)

        return examples[: self.config.max_examples]

    def _find_entity_examples(
        self, entity_type: EntityType, keywords: list[str]
    ) -> list[CodeExample]:
        """Find example nodes for an entity type."""
        from mu.kernel.schema import NodeType

        examples: list[CodeExample] = []

        # Map entity types to node types and name patterns
        type_config = {
            EntityType.SERVICE: (NodeType.CLASS, "Service"),
            EntityType.REPOSITORY: (NodeType.CLASS, "Repository"),
            EntityType.MODEL: (NodeType.CLASS, "Model"),
            EntityType.API_ENDPOINT: (NodeType.FUNCTION, ""),  # Look at routes
            EntityType.HOOK: (NodeType.FUNCTION, "use"),
        }

        config = type_config.get(entity_type)
        if not config:
            return examples

        node_type, suffix = config
        nodes = self.db.get_nodes(node_type)

        # Filter by suffix or keywords
        matching = []
        for node in nodes:
            if not node.name:
                continue
            if suffix and node.name.endswith(suffix):
                matching.append(node)
            elif any(kw.lower() in node.name.lower() for kw in keywords[:5]):
                matching.append(node)

        # Convert to examples
        for node in matching[:3]:
            if node.file_path and node.line_start and node.line_end:
                examples.append(
                    CodeExample(
                        description=f"Example {entity_type.value}: {node.name}",
                        file_path=node.file_path,
                        line_start=node.line_start,
                        line_end=node.line_end,
                    )
                )

        return examples

    def _generate_warnings(self, files: list[FileContext]) -> list[Warning]:
        """Generate proactive warnings for relevant files."""
        from mu.extras.intelligence.warnings import ProactiveWarningGenerator, WarningConfig

        warnings: list[Warning] = []

        if not files:
            return warnings

        config = WarningConfig(
            check_impact=True,
            check_staleness=True,
            check_security=True,
            check_tests=True,
            check_complexity=True,
            check_deprecated=True,
        )

        generator = ProactiveWarningGenerator(self.db, config, self.root_path)

        # Check top files for warnings
        for fc in files[: min(5, len(files))]:
            try:
                result = generator.analyze(fc.path)
                for w in result.warnings:
                    warnings.append(
                        Warning(
                            level=w.level,
                            message=w.message,
                            related_file=fc.path,
                        )
                    )
            except Exception as e:
                logger.debug(f"Warning generation failed for {fc.path}: {e}")

        return warnings[: self.config.max_warnings]

    def _generate_suggestions(
        self,
        analysis: TaskAnalysis,
        files: list[FileContext],
        patterns: list[Pattern],
    ) -> list[Suggestion]:
        """Generate suggestions for the task."""
        suggestions: list[Suggestion] = []

        # Suggest following patterns
        if patterns:
            top_pattern = patterns[0]
            suggestions.append(
                Suggestion(
                    suggestion_type="pattern",
                    message=f"Follow {top_pattern.name} pattern ({top_pattern.frequency} occurrences in codebase)",
                )
            )

        # Task-type specific suggestions
        if analysis.task_type == TaskType.CREATE:
            suggestions.append(
                Suggestion(
                    suggestion_type="related_change",
                    message="Consider adding tests for new code",
                )
            )
            if EntityType.API_ENDPOINT in analysis.entity_types:
                suggestions.append(
                    Suggestion(
                        suggestion_type="related_change",
                        message="Update API documentation after adding endpoint",
                    )
                )

        elif analysis.task_type == TaskType.MODIFY:
            if files:
                suggestions.append(
                    Suggestion(
                        suggestion_type="test",
                        message=f"Ensure tests cover changes to {files[0].path}",
                    )
                )

        elif analysis.task_type == TaskType.DELETE:
            suggestions.append(
                Suggestion(
                    suggestion_type="related_change",
                    message="Check for other files that import the deleted code",
                )
            )

        elif analysis.task_type == TaskType.REFACTOR:
            suggestions.append(
                Suggestion(
                    suggestion_type="alternative",
                    message="Run tests before and after refactoring to ensure behavior is preserved",
                )
            )

        return suggestions[:5]

    def _calculate_confidence(
        self,
        analysis: TaskAnalysis,
        files: list[FileContext],
        patterns: list[Pattern],
    ) -> float:
        """Calculate overall confidence in the extracted context."""
        confidence = analysis.confidence

        # Boost for finding relevant files
        if files:
            avg_relevance = sum(fc.relevance for fc in files) / len(files)
            confidence = confidence * 0.7 + avg_relevance * 0.3

        # Slight boost for finding patterns
        if patterns:
            confidence = min(1.0, confidence + 0.05)

        return confidence


__all__ = [
    "TaskAnalyzer",
    "TaskContextConfig",
    "TaskContextExtractor",
]
