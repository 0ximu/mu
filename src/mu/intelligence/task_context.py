"""Task-Aware Context Extraction.

Provides curated context bundles for development tasks by analyzing the task
description and extracting relevant code patterns, files, and examples.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mu.intelligence.models import (
    CodeExample,
    EntityType,
    FileContext,
    Pattern,
    Suggestion,
    TaskAnalysis,
    TaskContextResult,
    TaskType,
    Warning,
)
from mu.kernel.schema import NodeType

if TYPE_CHECKING:
    from mu.intelligence.patterns import PatternDetector
    from mu.kernel import MUbase
    from mu.kernel.models import Node


@dataclass
class TaskContextConfig:
    """Configuration for task context extraction."""

    max_tokens: int = 8000
    """Maximum tokens in output."""

    include_tests: bool = True
    """Include relevant test patterns."""

    include_patterns: bool = True
    """Include codebase patterns."""

    max_files: int = 20
    """Maximum number of files to include."""

    max_examples: int = 5
    """Maximum number of code examples."""

    max_patterns: int = 5
    """Maximum number of patterns to include."""

    # Token budget allocation (percentages)
    core_files_budget: float = 0.60
    """60% for core files."""

    patterns_budget: float = 0.20
    """20% for patterns."""

    deps_budget: float = 0.10
    """10% for dependencies."""

    warnings_budget: float = 0.10
    """10% for warnings."""


class TaskAnalyzer:
    """Analyzes natural language task descriptions.

    Uses pattern matching and heuristics to extract:
    - Task type (create, modify, refactor, etc.)
    - Entity types (API, hook, service, etc.)
    - Keywords for search
    - Domain hints (auth, payment, user, etc.)
    """

    # Task type indicators
    TASK_PATTERNS: dict[TaskType, list[str]] = {
        TaskType.CREATE: [
            r"\badd\b", r"\bcreate\b", r"\bimplement\b", r"\bbuild\b",
            r"\bnew\b", r"\bintroduce\b", r"\bset up\b", r"\bsetup\b",
        ],
        TaskType.MODIFY: [
            r"\bmodify\b", r"\bchange\b", r"\bupdate\b", r"\bedit\b",
            r"\balter\b", r"\badjust\b", r"\btweak\b", r"\benhance\b",
        ],
        TaskType.DELETE: [
            r"\bremove\b", r"\bdelete\b", r"\bdrop\b", r"\bclean up\b",
            r"\bdeprecate\b",
        ],
        TaskType.REFACTOR: [
            r"\brefactor\b", r"\brestructure\b", r"\breorganize\b",
            r"\bextract\b", r"\bmove\b", r"\brename\b", r"\bsplit\b",
        ],
        TaskType.DEBUG: [
            r"\bfix\b", r"\bbug\b", r"\bdebug\b", r"\bissue\b",
            r"\berror\b", r"\bcrash\b", r"\bbroken\b", r"\bfailing\b",
        ],
        TaskType.TEST: [
            r"\btest\b", r"\btests\b", r"\btesting\b", r"\bspec\b",
            r"\bcoverage\b", r"\bunit test\b",
        ],
        TaskType.DOCUMENT: [
            r"\bdocument\b", r"\bdocs\b", r"\breadme\b", r"\bcomment\b",
            r"\bjsdoc\b", r"\bdocstring\b",
        ],
        TaskType.REVIEW: [
            r"\breview\b", r"\baudit\b", r"\bcheck\b", r"\banalyze\b",
            r"\binspect\b",
        ],
    }

    # Entity type indicators
    ENTITY_PATTERNS: dict[EntityType, list[str]] = {
        EntityType.API_ENDPOINT: [
            r"\bapi\b", r"\bendpoint\b", r"\broute\b", r"\brest\b",
            r"\bgraphql\b", r"\bget\b", r"\bpost\b", r"\bput\b", r"\bdelete\b",
        ],
        EntityType.HOOK: [
            r"\bhook\b", r"\buse[A-Z]", r"\bcustom hook\b",
        ],
        EntityType.COMPONENT: [
            r"\bcomponent\b", r"\bwidget\b", r"\bui\b", r"\bview\b",
            r"\bscreen\b", r"\bpage\b",
        ],
        EntityType.SERVICE: [
            r"\bservice\b", r"\bbusiness logic\b", r"\bmanager\b",
        ],
        EntityType.REPOSITORY: [
            r"\brepository\b", r"\brepo\b", r"\bstore\b", r"\bdao\b",
            r"\bdata access\b",
        ],
        EntityType.MODEL: [
            r"\bmodel\b", r"\bentity\b", r"\bschema\b", r"\bdto\b",
            r"\btype\b", r"\binterface\b",
        ],
        EntityType.MIDDLEWARE: [
            r"\bmiddleware\b", r"\binterceptor\b", r"\bguard\b", r"\bfilter\b",
        ],
        EntityType.CONFIG: [
            r"\bconfig\b", r"\bconfiguration\b", r"\bsettings\b", r"\benv\b",
        ],
        EntityType.TEST: [
            r"\btest\b", r"\bspec\b", r"\bunit\b", r"\bintegration\b",
        ],
    }

    # Domain indicators
    DOMAIN_PATTERNS: dict[str, list[str]] = {
        "auth": [r"\bauth", r"\blogin", r"\blogout", r"\bsession", r"\btoken", r"\bjwt"],
        "payment": [r"\bpay", r"\bbilling", r"\bcharge", r"\bsubscription", r"\binvoice"],
        "user": [r"\buser", r"\bprofile", r"\baccount", r"\bregistration"],
        "notification": [r"\bnotif", r"\bemail", r"\bsms", r"\balert", r"\bpush"],
        "search": [r"\bsearch", r"\bfilter", r"\bquery", r"\bindex"],
        "cache": [r"\bcache", r"\bredis", r"\bmemcache"],
        "database": [r"\bdatabase", r"\bdb\b", r"\bsql", r"\bquery", r"\btransaction"],
        "api": [r"\bapi\b", r"\bendpoint", r"\brest", r"\bgraphql"],
        "security": [r"\bsecur", r"\bencrypt", r"\bhash", r"\bvalidat"],
        "logging": [r"\blog", r"\btrace", r"\bmonitor", r"\bmetric"],
    }

    def analyze(self, task: str) -> TaskAnalysis:
        """Analyze a task description.

        Args:
            task: Natural language task description.

        Returns:
            TaskAnalysis with extracted information.
        """
        task_lower = task.lower()

        # Detect task type
        task_type = self._detect_task_type(task_lower)

        # Detect entity types
        entity_types = self._detect_entity_types(task_lower)

        # Extract keywords
        keywords = self._extract_keywords(task)

        # Detect domain hints
        domain_hints = self._detect_domains(task_lower)

        # Calculate confidence
        confidence = self._calculate_confidence(
            task_type, entity_types, keywords, domain_hints
        )

        return TaskAnalysis(
            original_task=task,
            task_type=task_type,
            entity_types=entity_types,
            keywords=keywords,
            domain_hints=domain_hints,
            confidence=confidence,
        )

    def _detect_task_type(self, task_lower: str) -> TaskType:
        """Detect the primary task type."""
        scores: dict[TaskType, int] = {}

        for task_type, patterns in self.TASK_PATTERNS.items():
            score = sum(1 for p in patterns if re.search(p, task_lower))
            if score > 0:
                scores[task_type] = score

        if not scores:
            return TaskType.MODIFY  # Default

        return max(scores, key=lambda k: scores[k])

    def _detect_entity_types(self, task_lower: str) -> list[EntityType]:
        """Detect entity types mentioned in the task."""
        detected: list[EntityType] = []

        for entity_type, patterns in self.ENTITY_PATTERNS.items():
            if any(re.search(p, task_lower) for p in patterns):
                detected.append(entity_type)

        return detected if detected else [EntityType.UNKNOWN]

    def _extract_keywords(self, task: str) -> list[str]:
        """Extract searchable keywords from task description."""
        keywords: list[str] = []

        # Extract CamelCase words
        camel_case = re.findall(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", task)
        keywords.extend(camel_case)

        # Extract snake_case words
        snake_case = re.findall(r"\b[a-z]+_[a-z_]+\b", task)
        keywords.extend(snake_case)

        # Extract quoted strings
        quoted = re.findall(r'["\']([^"\']+)["\']', task)
        keywords.extend(quoted)

        # Extract meaningful words (4+ chars, not common words)
        stop_words = {
            "that", "this", "with", "from", "have", "been", "will", "should",
            "would", "could", "must", "need", "want", "like", "make", "sure",
            "when", "where", "what", "which", "while", "there", "their", "then",
            "than", "other", "some", "more", "into", "also", "just", "only",
        }
        words = re.findall(r"\b[a-z]{4,}\b", task.lower())
        meaningful = [w for w in words if w not in stop_words]
        keywords.extend(meaningful[:10])  # Limit to avoid noise

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower not in seen:
                seen.add(kw_lower)
                unique.append(kw)

        return unique

    def _detect_domains(self, task_lower: str) -> list[str]:
        """Detect domain-specific hints in the task."""
        domains: list[str] = []

        for domain, patterns in self.DOMAIN_PATTERNS.items():
            if any(re.search(p, task_lower) for p in patterns):
                domains.append(domain)

        return domains

    def _calculate_confidence(
        self,
        task_type: TaskType,
        entity_types: list[EntityType],
        keywords: list[str],
        domain_hints: list[str],
    ) -> float:
        """Calculate confidence score for the analysis."""
        confidence = 0.5  # Base confidence

        # Boost for specific task type detection
        if task_type != TaskType.MODIFY:
            confidence += 0.1

        # Boost for entity type detection
        if entity_types and EntityType.UNKNOWN not in entity_types:
            confidence += 0.1 * min(len(entity_types), 3)

        # Boost for keywords
        if len(keywords) >= 3:
            confidence += 0.1

        # Boost for domain hints
        if domain_hints:
            confidence += 0.1

        return min(confidence, 1.0)


class TaskContextExtractor:
    """Extracts curated context bundles for development tasks.

    Combines task analysis, pattern detection, semantic search, and
    structural analysis to provide comprehensive context for AI assistants.
    """

    def __init__(
        self,
        mubase: MUbase,
        config: TaskContextConfig | None = None,
    ) -> None:
        """Initialize the task context extractor.

        Args:
            mubase: The MUbase graph database.
            config: Extraction configuration.
        """
        self.mubase = mubase
        self.config = config or TaskContextConfig()
        self.analyzer = TaskAnalyzer()
        self._pattern_detector: PatternDetector | None = None

    def extract(
        self,
        task: str,
        max_tokens: int | None = None,
        include_tests: bool | None = None,
        include_patterns: bool | None = None,
    ) -> TaskContextResult:
        """Extract comprehensive context for a development task.

        Args:
            task: Natural language task description.
            max_tokens: Override max tokens (optional).
            include_tests: Override include_tests setting (optional).
            include_patterns: Override include_patterns setting (optional).

        Returns:
            TaskContextResult with files, patterns, warnings, suggestions.
        """
        start_time = time.time()
        stats: dict[str, Any] = {"task_length": len(task)}

        # Override config if provided
        effective_max_tokens = max_tokens or self.config.max_tokens
        # Note: include_tests is used for filtering later (planned feature)
        _ = include_tests if include_tests is not None else self.config.include_tests
        effective_include_patterns = (
            include_patterns
            if include_patterns is not None
            else self.config.include_patterns
        )

        # Step 1: Analyze task
        analysis = self.analyzer.analyze(task)
        stats["task_type"] = analysis.task_type.value
        stats["entity_types"] = [et.value for et in analysis.entity_types]
        stats["keywords"] = analysis.keywords
        stats["domain_hints"] = analysis.domain_hints

        # Step 2: Multi-signal retrieval
        relevant_nodes = self._retrieve_nodes(analysis)
        stats["nodes_retrieved"] = len(relevant_nodes)

        # Step 3: Build file contexts
        file_contexts = self._build_file_contexts(relevant_nodes, analysis)
        stats["files_found"] = len(file_contexts)

        # Step 4: Identify entry points
        entry_points = self._identify_entry_points(file_contexts, analysis)

        # Step 5: Get relevant patterns
        patterns: list[Pattern] = []
        if effective_include_patterns:
            patterns = self._get_relevant_patterns(analysis)
            stats["patterns_found"] = len(patterns)

        # Step 6: Find code examples
        examples = self._find_examples(relevant_nodes, analysis)
        stats["examples_found"] = len(examples)

        # Step 7: Generate warnings
        warnings = self._generate_warnings(relevant_nodes, analysis)

        # Step 8: Generate suggestions
        suggestions = self._generate_suggestions(analysis, file_contexts, patterns)

        # Step 9: Build MU text with token budgeting
        mu_text, token_count = self._build_mu_text(
            file_contexts,
            patterns,
            relevant_nodes,
            effective_max_tokens,
        )
        stats["token_count"] = token_count

        # Calculate overall confidence
        confidence = self._calculate_confidence(analysis, file_contexts, patterns)

        stats["extraction_time_ms"] = (time.time() - start_time) * 1000

        return TaskContextResult(
            relevant_files=file_contexts[: self.config.max_files],
            entry_points=entry_points,
            patterns=patterns[: self.config.max_patterns],
            examples=examples[: self.config.max_examples],
            warnings=warnings,
            suggestions=suggestions,
            task_analysis=analysis,
            mu_text=mu_text,
            token_count=token_count,
            confidence=confidence,
            extraction_stats=stats,
        )

    def _retrieve_nodes(self, analysis: TaskAnalysis) -> list[Node]:
        """Retrieve relevant nodes using multiple signals.

        Uses:
        1. Keyword matching on node names
        2. Semantic search (if embeddings available)
        3. Entity type filtering
        """
        all_nodes: dict[str, Node] = {}

        # 1. Keyword-based retrieval
        for keyword in analysis.keywords[:10]:  # Limit keywords
            matches = self.mubase.find_by_name(f"%{keyword}%")
            for node in matches:
                if node.id not in all_nodes:
                    all_nodes[node.id] = node

        # 2. Semantic search (if embeddings available)
        try:
            embed_stats = self.mubase.embedding_stats()
            if embed_stats.get("nodes_with_embeddings", 0) > 0:
                semantic_matches = self._semantic_search(analysis.original_task)
                for node in semantic_matches:
                    if node.id not in all_nodes:
                        all_nodes[node.id] = node
        except Exception:
            pass  # Continue without semantic search

        # 3. Entity type-based filtering
        type_matches = self._filter_by_entity_types(list(all_nodes.values()), analysis)

        return type_matches

    def _semantic_search(self, task: str, limit: int = 20) -> list[Node]:
        """Perform semantic search for task-related nodes."""
        try:
            import asyncio

            from mu.config import MUConfig
            from mu.kernel.embeddings import EmbeddingService

            config = MUConfig()
            embed_stats = self.mubase.embedding_stats()
            stored_dims = embed_stats.get("dimensions", [])

            if stored_dims:
                dim = stored_dims[0] if isinstance(stored_dims, list) else stored_dims
                provider = "local" if dim == 384 else config.embeddings.provider
            else:
                provider = config.embeddings.provider

            service = EmbeddingService(config=config.embeddings, provider=provider)

            async def get_embedding() -> list[float] | None:
                return await service.embed_query(task)

            query_embedding = asyncio.run(get_embedding())

            if not query_embedding:
                asyncio.run(service.close())
                return []

            results = self.mubase.vector_search(
                query_embedding=query_embedding,
                embedding_type="code",
                limit=limit,
            )

            asyncio.run(service.close())

            return [node for node, _ in results]

        except Exception:
            return []

    def _filter_by_entity_types(
        self,
        nodes: list[Node],
        analysis: TaskAnalysis,
    ) -> list[Node]:
        """Filter and score nodes by entity type relevance."""
        if EntityType.UNKNOWN in analysis.entity_types:
            return nodes

        scored: list[tuple[Node, float]] = []

        for node in nodes:
            score = 1.0
            name_lower = node.name.lower()
            file_path = (node.file_path or "").lower()

            # Boost for entity type matches
            for entity_type in analysis.entity_types:
                if entity_type == EntityType.SERVICE and "service" in name_lower:
                    score += 0.3
                elif entity_type == EntityType.REPOSITORY and any(
                    kw in name_lower for kw in ["repository", "repo", "store"]
                ):
                    score += 0.3
                elif entity_type == EntityType.HOOK and name_lower.startswith("use"):
                    score += 0.3
                elif entity_type == EntityType.COMPONENT and any(
                    kw in name_lower for kw in ["component", "view", "page"]
                ):
                    score += 0.3
                elif entity_type == EntityType.API_ENDPOINT and any(
                    kw in file_path for kw in ["route", "api", "endpoint"]
                ):
                    score += 0.3
                elif entity_type == EntityType.MIDDLEWARE and "middleware" in file_path:
                    score += 0.3
                elif entity_type == EntityType.MODEL and any(
                    kw in name_lower for kw in ["model", "entity", "schema"]
                ):
                    score += 0.3
                elif entity_type == EntityType.TEST and "test" in file_path:
                    score += 0.2  # Lower boost for tests

            # Boost for domain hints
            for domain in analysis.domain_hints:
                if domain in name_lower or domain in file_path:
                    score += 0.2

            scored.append((node, score))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)

        return [node for node, _ in scored]

    def _build_file_contexts(
        self,
        nodes: list[Node],
        analysis: TaskAnalysis,
    ) -> list[FileContext]:
        """Build FileContext objects from nodes."""
        # Group nodes by file
        files: dict[str, list[Node]] = {}
        for node in nodes:
            if node.file_path:
                if node.file_path not in files:
                    files[node.file_path] = []
                files[node.file_path].append(node)

        file_contexts: list[FileContext] = []

        for file_path, file_nodes in files.items():
            # Calculate relevance based on node count and types
            relevance = min(len(file_nodes) * 0.15, 0.9)

            # Boost for matching entity types
            for node in file_nodes:
                if node.type == NodeType.CLASS:
                    relevance += 0.1
                elif node.type == NodeType.FUNCTION:
                    relevance += 0.05

            relevance = min(relevance, 1.0)

            # Generate reason
            node_types = {n.type.value for n in file_nodes}
            reason = f"Contains {', '.join(node_types)} matching search criteria"

            # Determine suggested action
            if analysis.task_type == TaskType.CREATE:
                suggested_action = "reference"
            elif analysis.task_type == TaskType.DELETE:
                suggested_action = "modify"
            else:
                suggested_action = "modify"

            file_contexts.append(
                FileContext(
                    path=file_path,
                    relevance=relevance,
                    reason=reason,
                    is_entry_point=False,
                    suggested_action=suggested_action,
                )
            )

        # Sort by relevance
        file_contexts.sort(key=lambda f: f.relevance, reverse=True)

        return file_contexts

    def _identify_entry_points(
        self,
        file_contexts: list[FileContext],
        analysis: TaskAnalysis,
    ) -> list[str]:
        """Identify suggested entry points for the task."""
        entry_points: list[str] = []

        # Mark top files as entry points
        for fc in file_contexts[:3]:
            fc.is_entry_point = True
            entry_points.append(fc.path)

        # Also suggest directories based on entity types
        for entity_type in analysis.entity_types:
            if entity_type == EntityType.API_ENDPOINT:
                entry_points.append("src/api/")
                entry_points.append("routes/")
            elif entity_type == EntityType.HOOK:
                entry_points.append("src/hooks/")
            elif entity_type == EntityType.COMPONENT:
                entry_points.append("src/components/")
            elif entity_type == EntityType.SERVICE:
                entry_points.append("src/services/")
            elif entity_type == EntityType.MIDDLEWARE:
                entry_points.append("src/middleware/")

        # Deduplicate
        seen: set[str] = set()
        unique: list[str] = []
        for ep in entry_points:
            if ep not in seen:
                seen.add(ep)
                unique.append(ep)

        return unique[:5]

    def _get_relevant_patterns(self, analysis: TaskAnalysis) -> list[Pattern]:
        """Get patterns relevant to the task."""
        from mu.intelligence import PatternCategory, PatternDetector

        if self._pattern_detector is None:
            self._pattern_detector = PatternDetector(self.mubase)

        # Map entity types to pattern categories
        categories: list[PatternCategory] = []

        for entity_type in analysis.entity_types:
            if entity_type == EntityType.API_ENDPOINT:
                categories.append(PatternCategory.API)
            elif entity_type == EntityType.HOOK:
                categories.append(PatternCategory.STATE_MANAGEMENT)
            elif entity_type == EntityType.COMPONENT:
                categories.append(PatternCategory.COMPONENTS)
            elif entity_type in (EntityType.SERVICE, EntityType.REPOSITORY):
                categories.append(PatternCategory.ARCHITECTURE)
            elif entity_type == EntityType.TEST:
                categories.append(PatternCategory.TESTING)

        # Always include naming and error handling
        categories.append(PatternCategory.NAMING)
        categories.append(PatternCategory.ERROR_HANDLING)

        # Get patterns for relevant categories
        all_patterns: list[Pattern] = []

        for category in set(categories):
            result = self._pattern_detector.detect(category=category)
            all_patterns.extend(result.patterns)

        # Sort by frequency and return top patterns
        all_patterns.sort(key=lambda p: p.frequency, reverse=True)

        return all_patterns[: self.config.max_patterns]

    def _find_examples(
        self,
        nodes: list[Node],
        analysis: TaskAnalysis,
    ) -> list[CodeExample]:
        """Find code examples similar to what's being requested."""
        examples: list[CodeExample] = []

        # Look for nodes that match entity types and have good examples
        for node in nodes[: self.config.max_examples * 2]:
            if not node.file_path or not node.line_start or not node.line_end:
                continue

            # Skip test files for examples unless task is about tests
            if "test" in (node.file_path or "").lower():
                if TaskType.TEST not in [analysis.task_type]:
                    continue

            # Create example
            description = f"{node.type.value.title()}: {node.name}"

            examples.append(
                CodeExample(
                    description=description,
                    file_path=node.file_path,
                    line_start=node.line_start,
                    line_end=node.line_end,
                )
            )

            if len(examples) >= self.config.max_examples:
                break

        return examples

    def _generate_warnings(
        self,
        nodes: list[Node],
        analysis: TaskAnalysis,
    ) -> list[Warning]:
        """Generate warnings about potential issues."""
        warnings: list[Warning] = []

        # Collect file paths
        files = {n.file_path for n in nodes if n.file_path}

        # Warning: High impact files
        for file_path in list(files)[:5]:  # Check top files
            if not file_path:
                continue

            # Find module node
            mod_nodes = [
                n
                for n in nodes
                if n.file_path == file_path and n.type == NodeType.MODULE
            ]
            if not mod_nodes:
                continue

            mod_node = mod_nodes[0]
            try:
                dependents = self.mubase.get_dependents(mod_node.id, depth=1)
                if len(dependents) > 10:
                    warnings.append(
                        Warning(
                            level="warn",
                            message=f"{len(dependents)} files depend on {file_path}",
                            related_file=file_path,
                        )
                    )
            except Exception:
                pass

        # Warning: New pattern introduction
        if analysis.task_type == TaskType.CREATE:
            entity_str = ", ".join(et.value for et in analysis.entity_types[:2])
            warnings.append(
                Warning(
                    level="info",
                    message=f"Creating new {entity_str} - follow existing patterns",
                )
            )

        # Warning: No matches found
        if not nodes:
            warnings.append(
                Warning(
                    level="warn",
                    message="No matching code found - task may require new files",
                )
            )

        return warnings

    def _generate_suggestions(
        self,
        analysis: TaskAnalysis,
        file_contexts: list[FileContext],
        patterns: list[Pattern],
    ) -> list[Suggestion]:
        """Generate suggestions for the task."""
        suggestions: list[Suggestion] = []

        # Suggest tests for create/modify tasks
        if analysis.task_type in (TaskType.CREATE, TaskType.MODIFY):
            suggestions.append(
                Suggestion(
                    suggestion_type="test",
                    message="Consider adding or updating tests for changed functionality",
                )
            )

        # Suggest pattern adherence
        if patterns:
            pattern_names = [p.name for p in patterns[:2]]
            suggestions.append(
                Suggestion(
                    suggestion_type="pattern",
                    message=f"Follow detected patterns: {', '.join(pattern_names)}",
                )
            )

        # Suggest related changes based on file conventions
        if file_contexts:
            top_file = file_contexts[0].path
            if ".ts" in top_file or ".tsx" in top_file:
                suggestions.append(
                    Suggestion(
                        suggestion_type="related_change",
                        message="Check if exports need updating in index.ts",
                    )
                )
            elif ".py" in top_file:
                suggestions.append(
                    Suggestion(
                        suggestion_type="related_change",
                        message="Check if __init__.py exports need updating",
                    )
                )

        return suggestions

    def _build_mu_text(
        self,
        file_contexts: list[FileContext],
        patterns: list[Pattern],
        nodes: list[Node],
        max_tokens: int,
    ) -> tuple[str, int]:
        """Build MU format text with token budgeting.

        Returns:
            Tuple of (mu_text, token_count).
        """
        from mu.kernel.context.budgeter import TokenBudgeter
        from mu.kernel.context.export import ContextExporter
        from mu.kernel.context.models import ScoredNode

        budgeter = TokenBudgeter(max_tokens)
        exporter = ContextExporter(self.mubase, include_scores=False)

        # Convert nodes to scored nodes for the budgeter
        scored_nodes: list[ScoredNode] = []
        for i, node in enumerate(nodes):
            # Simple relevance scoring based on order
            score = 1.0 - (i * 0.02)  # Decay by position
            score = max(score, 0.1)

            scored_nodes.append(
                ScoredNode(
                    node=node,
                    score=score,
                    entity_score=score,
                    vector_score=0.0,
                    proximity_score=0.0,
                    estimated_tokens=0,
                )
            )

        # Fit to budget
        selected = budgeter.fit_to_budget(
            scored_nodes,
            mubase=self.mubase,
            include_parent=True,
        )

        if not selected:
            return ":: No relevant context found", 0

        # Export as MU format
        mu_text = exporter.export_mu(selected)
        token_count = budgeter.get_actual_tokens(mu_text)

        return mu_text, token_count

    def _calculate_confidence(
        self,
        analysis: TaskAnalysis,
        file_contexts: list[FileContext],
        patterns: list[Pattern],
    ) -> float:
        """Calculate overall confidence in the context."""
        confidence = analysis.confidence

        # Boost for file matches
        if file_contexts:
            confidence += 0.1 * min(len(file_contexts) / 5, 1.0)

        # Boost for pattern matches
        if patterns:
            confidence += 0.05 * min(len(patterns), 3)

        return min(confidence, 1.0)


__all__ = ["TaskAnalyzer", "TaskContextConfig", "TaskContextExtractor"]
