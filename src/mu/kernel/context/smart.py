"""Smart Context Extractor - orchestrates context extraction.

Combines entity extraction, scoring, budgeting, and export into
a cohesive API for intelligent context selection.

Now includes intent classification to select specialized extraction
strategies for different types of questions.

When embeddings are unavailable, uses graph-based extraction that
leverages code structure (imports, calls, inheritance) for better
domain-aware results.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mu.kernel.context.budgeter import TokenBudgeter
from mu.kernel.context.export import ContextExporter
from mu.kernel.context.extractor import EntityExtractor
from mu.kernel.context.intent import Intent, IntentClassifier
from mu.kernel.context.models import (
    ContextResult,
    ExportConfig,
    ExtractedEntity,
    ExtractionConfig,
    ScoredNode,
)
from mu.kernel.context.scorer import RelevanceScorer
from mu.kernel.context.strategies import get_strategy
from mu.kernel.schema import EdgeType, NodeType

if TYPE_CHECKING:
    from mu.kernel.models import Edge, Node
    from mu.kernel.mubase import MUbase


# =============================================================================
# Graph Expansion Configuration
# =============================================================================


@dataclass
class GraphExpansionConfig:
    """Configuration for graph-based context expansion.

    Controls how nodes are expanded via graph relationships when
    embeddings are not available.
    """

    max_depth: int = 2
    """Maximum depth for BFS expansion."""

    max_nodes_per_depth: int = 15
    """Maximum nodes to expand at each depth level."""

    weights: dict[str, float] = field(
        default_factory=lambda: {
            "CONTAINS": 0.95,  # Same module/class is very relevant
            "CALLS": 0.9,  # Called functions are very relevant
            "INHERITS": 0.85,  # Parent/child classes are relevant
            "IMPORTS": 0.7,  # Imported modules are relevant
        }
    )
    """Relationship weights - how much to preserve score for each edge type."""

    depth_decay: float = 0.7
    """Decay factor per depth level (depth 1 = 0.7x, depth 2 = 0.49x)."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "max_depth": self.max_depth,
            "max_nodes_per_depth": self.max_nodes_per_depth,
            "weights": self.weights,
            "depth_decay": self.depth_decay,
        }


@dataclass
class DomainBoundary:
    """Represents a code domain boundary in a monorepo.

    Domains are detected by directory structure and language,
    helping to filter cross-domain noise in context extraction.
    """

    root_path: str
    """Root directory path for this domain."""

    language: str
    """Primary language of this domain (e.g., 'csharp', 'python')."""

    name: str
    """Human-readable domain name (e.g., 'payment-services')."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "root_path": self.root_path,
            "language": self.language,
            "name": self.name,
        }


logger = logging.getLogger(__name__)

# Intents that have specialized strategies
_STRATEGY_INTENTS = {Intent.LOCATE, Intent.IMPACT, Intent.NAVIGATE, Intent.LIST}

# Minimum confidence to use a specialized strategy
_MIN_STRATEGY_CONFIDENCE = 0.7


class SmartContextExtractor:
    """Extract optimal context for answering questions about code.

    Orchestrates the full extraction pipeline:
    1. Intent classification (NEW) - determines extraction strategy
    2. Entity extraction from the question
    3. Node matching by name and vector similarity
    4. Graph expansion to include related nodes
    5. Relevance scoring of all candidates
    6. Token budgeting to fit output size
    7. MU format export

    For certain intents (LOCATE, IMPACT, NAVIGATE, LIST), specialized
    strategies are used to provide more targeted context extraction.
    """

    def __init__(
        self,
        mubase: MUbase,
        config: ExtractionConfig | None = None,
        *,
        use_intent_classification: bool = True,
    ) -> None:
        """Initialize the smart context extractor.

        Args:
            mubase: The MUbase graph database.
            config: Extraction configuration (uses defaults if not provided).
            use_intent_classification: Whether to use intent classification
                to select specialized strategies. Default True.
        """
        self.mubase = mubase
        self.config = config or ExtractionConfig()
        self.use_intent_classification = use_intent_classification

        # Create export config based on extraction config
        self.export_config = ExportConfig(
            include_docstrings=self.config.include_docstrings,
            include_line_numbers=self.config.include_line_numbers,
            include_internal_imports=self.config.include_imports,
            min_complexity_to_show=self.config.min_complexity_to_show,
        )

        # Get all node names for entity extraction
        known_names = self._get_known_names()

        # Initialize components
        self.entity_extractor = EntityExtractor(known_names)
        self.scorer = RelevanceScorer(self.config, mubase)
        self.budgeter = TokenBudgeter(self.config.max_tokens, export_config=self.export_config)
        self.exporter = ContextExporter(
            mubase, include_scores=False, export_config=self.export_config
        )
        self.intent_classifier = IntentClassifier()

    def extract(self, question: str) -> ContextResult:
        """Extract optimal context for answering a question.

        Args:
            question: Natural language question about the code.

        Returns:
            ContextResult with MU format context and metadata.

        Note:
            This method is synchronous and uses asyncio.run() internally
            for embedding operations. Do not call from an async context.
            If you need async extraction, the vector search will be
            skipped and only entity/graph matching will be used.
        """
        # Step 0: Classify intent (NEW)
        classified_intent = self.intent_classifier.classify(question)
        intent = classified_intent.intent
        confidence = classified_intent.confidence

        # Check if we should use a specialized strategy
        use_specialized = (
            self.use_intent_classification
            and intent in _STRATEGY_INTENTS
            and confidence >= _MIN_STRATEGY_CONFIDENCE
        )

        if use_specialized:
            # Use specialized strategy for this intent
            logger.debug(f"Using {intent.value} strategy (confidence: {confidence:.2f})")
            strategy = get_strategy(intent)
            result = strategy.extract(classified_intent, self.mubase, self.config)

            # Add intent info to result
            result.intent = intent.value
            result.intent_confidence = confidence
            result.strategy_used = result.extraction_stats.get("strategy_used", intent.value)

            return result

        # Step 1: Extract entities from question
        entities = self.entity_extractor.extract(question)

        # Step 2: Check if embeddings are available
        # If not, use graph-based extraction which leverages code structure
        has_embeddings = self._check_embeddings_available()

        if not has_embeddings:
            # Use graph-based extraction when embeddings unavailable
            logger.debug("Using graph-based extraction (no embeddings)")
            result = self._extract_with_graph(question, entities)

            # Add intent info to result
            result.intent = intent.value
            result.intent_confidence = confidence
            result.strategy_used = "graph"

            return result

        # Fall through to embeddings-based extraction pipeline
        stats: dict[str, Any] = {
            "question_length": len(question),
            "max_tokens": self.config.max_tokens,
            "intent": intent.value,
            "intent_confidence": confidence,
            "strategy_used": "default",
            "method": "embeddings",
        }

        stats["entities_extracted"] = len(entities)
        stats["entities"] = [e.name for e in entities]

        # Step 3: Find seed nodes by name matching
        seed_nodes, seed_node_ids = self._find_seed_nodes(entities)
        stats["named_nodes_found"] = len(seed_nodes)

        # Step 4: Vector search for semantic matches
        vector_nodes, vector_scores, vector_skip_reason = self._vector_search(question)
        stats["vector_matches"] = len(vector_nodes)
        stats["vector_search_used"] = vector_skip_reason is None
        if vector_skip_reason:
            stats["vector_search_skipped"] = vector_skip_reason

        # Merge seed nodes with vector results
        all_candidates = self._merge_candidates(seed_nodes, vector_nodes)
        seed_node_ids.update(n.id for n in vector_nodes[:5])  # Top 5 vector as seeds
        stats["candidates_before_expansion"] = len(all_candidates)

        # Step 4: Expand with graph neighbors
        expanded = self._expand_graph(all_candidates)
        stats["candidates_after_expansion"] = len(expanded)

        # Step 5: Score all candidates
        scored_nodes = self.scorer.score_nodes(
            nodes=list(expanded.values()),
            question=question,
            entities=entities,
            seed_node_ids=seed_node_ids,
            vector_scores=vector_scores,
        )
        stats["scored_nodes"] = len(scored_nodes)

        # Step 6: Filter by test exclusion if configured
        if self.config.exclude_tests:
            scored_nodes = self._exclude_tests(scored_nodes)
            stats["after_test_filter"] = len(scored_nodes)

        # Step 7: Fit to token budget
        selected = self.budgeter.fit_to_budget(
            scored_nodes,
            mubase=self.mubase,
            include_parent=self.config.include_parent,
        )
        stats["selected_nodes"] = len(selected)

        # Handle empty results - try semantic search fallback if embeddings available
        if not selected:
            fallback_result = self._try_semantic_search_fallback(question, stats)
            if fallback_result is not None:
                fallback_result.intent = intent.value
                fallback_result.intent_confidence = confidence
                return fallback_result

            # No results even after fallback
            fallback_msg = f":: No relevant context found for: {question}"
            # Estimate tokens: ~4 chars per token for English text
            estimated_tokens = len(fallback_msg) // 4
            return ContextResult(
                mu_text=fallback_msg,
                nodes=[],
                token_count=estimated_tokens,
                relevance_scores={},
                extraction_stats=stats,
                intent=intent.value,
                intent_confidence=confidence,
                strategy_used="default",
                extraction_method="embeddings",
            )

        # Step 8: Export as MU format
        mu_text = self.exporter.export_mu(selected)
        token_count = self.budgeter.get_actual_tokens(mu_text)
        stats["actual_tokens"] = token_count
        stats["budget_utilization"] = round(token_count / self.config.max_tokens * 100, 1)

        # Build relevance scores map
        relevance_scores = {sn.node.id: sn.score for sn in selected}

        return ContextResult(
            mu_text=mu_text,
            nodes=[sn.node for sn in selected],
            token_count=token_count,
            relevance_scores=relevance_scores,
            extraction_stats=stats,
            intent=intent.value,
            intent_confidence=confidence,
            strategy_used="default",
            extraction_method="embeddings",
        )

    def _get_known_names(self) -> set[str]:
        """Get all node names from the database."""
        names: set[str] = set()

        for node_type in [NodeType.MODULE, NodeType.CLASS, NodeType.FUNCTION]:
            nodes = self.mubase.get_nodes(node_type)
            for node in nodes:
                names.add(node.name)
                if node.qualified_name:
                    names.add(node.qualified_name)

        return names

    def _find_seed_nodes(
        self,
        entities: list[ExtractedEntity],
    ) -> tuple[list[Node], set[str]]:
        """Find nodes matching extracted entities.

        Args:
            entities: Extracted entities to search for.

        Returns:
            Tuple of (matching nodes, set of node IDs).
        """
        nodes: list[Node] = []
        node_ids: set[str] = set()

        for entity in entities:
            # Try exact name match
            matches = self.mubase.find_by_name(entity.name)

            # Also try suffix match for qualified names
            if not matches:
                matches = self._find_by_suffix(entity.name)

            # For lowercase words without matches, try pattern match in file_path
            # This helps find "zustand" -> files containing "zustand" in path/name
            if not matches and entity.extraction_method == "lowercase_word":
                matches = self._search_by_path_pattern(entity.name)

            for node in matches:
                if node.id not in node_ids:
                    nodes.append(node)
                    node_ids.add(node.id)

        return nodes, node_ids

    def _search_by_path_pattern(self, pattern: str) -> list[Node]:
        """Search for nodes by pattern in file_path or node name.

        Useful for finding files/modules related to a library name.
        """
        try:
            # Search in file_path (e.g., "zustand" matches "hooks/useZustandStore.ts")
            result = self.mubase.execute(
                """
                SELECT * FROM nodes
                WHERE (file_path LIKE ? OR name LIKE ? OR qualified_name LIKE ?)
                AND type IN ('module', 'class', 'function')
                LIMIT 20
                """,
                [f"%{pattern}%", f"%{pattern}%", f"%{pattern}%"],
            )
            if result:
                # Convert rows to Node objects
                nodes = []
                for row in result:
                    node = self.mubase.get_node(row[0])  # First column is id
                    if node:
                        nodes.append(node)
                return nodes
        except Exception:
            pass
        return []

    def _find_by_suffix(self, suffix: str) -> list[Node]:
        """Find nodes whose name ends with the given suffix."""
        # Use pattern match with wildcard
        return self.mubase.find_by_name(f"%{suffix}")

    def _vector_search(
        self,
        question: str,
    ) -> tuple[list[Node], dict[str, float], str | None]:
        """Search for semantically similar nodes.

        Args:
            question: The question to search for.

        Returns:
            Tuple of (matching nodes, node_id -> similarity score, skip_reason or None).
            skip_reason is set when vector search was skipped (e.g., no embeddings, no API key).
        """
        # Check if embeddings are available
        try:
            embed_stats = self.mubase.embedding_stats()
            if embed_stats.get("nodes_with_embeddings", 0) == 0:
                logger.debug("Vector search skipped: no embeddings in database")
                return [], {}, "no_embeddings"
        except Exception as e:
            logger.debug(f"Vector search skipped: failed to check embeddings: {e}")
            return [], {}, "embeddings_check_failed"

        # Import embedding service lazily to avoid circular imports
        try:
            from mu.kernel.embeddings import EmbeddingService
        except ImportError:
            logger.debug("Vector search skipped: embeddings module not available")
            return [], {}, "embeddings_module_unavailable"

        # Create embedding service for query
        try:
            import asyncio
            import os

            from mu.config import MUConfig

            config = MUConfig()

            # Check for API key if using OpenAI provider
            if config.embeddings.provider == "openai":
                api_key_env = config.embeddings.openai.api_key_env
                if not os.environ.get(api_key_env):
                    logger.debug(
                        f"Vector search skipped: {api_key_env} not set. "
                        "Set the environment variable or use local embeddings."
                    )
                    return [], {}, "no_api_key"

            service = EmbeddingService(config=config.embeddings)

            # Get query embedding
            async def get_embedding() -> list[float] | None:
                return await service.embed_query(question)

            query_embedding = asyncio.run(get_embedding())

            if not query_embedding:
                asyncio.run(service.close())
                logger.debug("Vector search skipped: failed to generate query embedding")
                return [], {}, "query_embedding_failed"

            # Perform vector search
            results = self.mubase.vector_search(
                query_embedding=query_embedding,
                embedding_type="code",
                limit=self.config.vector_search_limit,
            )

            asyncio.run(service.close())

            nodes = [node for node, _ in results]
            scores = {node.id: score for node, score in results}

            logger.debug(f"Vector search found {len(nodes)} results")
            return nodes, scores, None

        except Exception as e:
            # Vector search failed, continue without it
            logger.debug(f"Vector search skipped: {e}")
            return [], {}, f"error: {e}"

    def _merge_candidates(
        self,
        seed_nodes: list[Node],
        vector_nodes: list[Node],
    ) -> dict[str, Node]:
        """Merge seed nodes with vector search results, deduplicating.

        Args:
            seed_nodes: Nodes from entity matching.
            vector_nodes: Nodes from vector search.

        Returns:
            Dictionary of unique node_id -> node.
        """
        candidates: dict[str, Node] = {}

        for node in seed_nodes:
            candidates[node.id] = node

        for node in vector_nodes:
            if node.id not in candidates:
                candidates[node.id] = node

        return candidates

    def _expand_graph(
        self,
        candidates: dict[str, Node],
    ) -> dict[str, Node]:
        """Expand candidates with graph neighbors.

        Args:
            candidates: Initial candidate nodes.

        Returns:
            Expanded set of candidates.
        """
        if self.config.expand_depth <= 0:
            return candidates

        expanded = dict(candidates)
        current_ids = set(candidates.keys())

        for _ in range(self.config.expand_depth):
            new_ids: set[str] = set()

            for node_id in current_ids:
                if len(expanded) >= self.config.max_expansion_nodes:
                    break

                # Get neighbors
                deps = self.mubase.get_dependencies(node_id, depth=1)
                dependents = self.mubase.get_dependents(node_id, depth=1)
                children = self.mubase.get_children(node_id)
                parent = self.mubase.get_parent(node_id)

                for node in deps + dependents + children:
                    if node.id not in expanded:
                        expanded[node.id] = node
                        new_ids.add(node.id)

                if parent and parent.id not in expanded:
                    expanded[parent.id] = parent
                    new_ids.add(parent.id)

            if not new_ids:
                break

            current_ids = new_ids

        return expanded

    def _exclude_tests(
        self,
        scored_nodes: list[ScoredNode],
    ) -> list[ScoredNode]:
        """Filter out test files from results.

        Args:
            scored_nodes: Nodes to filter.

        Returns:
            Filtered list without test files.
        """
        filtered: list[ScoredNode] = []

        for scored_node in scored_nodes:
            node = scored_node.node
            file_path = node.file_path or ""

            # Skip test files
            if any(
                pattern in file_path.lower()
                for pattern in ("test_", "_test.", "tests/", "test/", "spec/")
            ):
                continue

            # Skip test functions/classes
            name = node.name.lower()
            if name.startswith("test_") or name.startswith("test"):
                continue

            filtered.append(scored_node)

        return filtered

    def _try_semantic_search_fallback(
        self,
        question: str,
        stats: dict[str, Any],
    ) -> ContextResult | None:
        """Try semantic search as fallback when entity extraction finds nothing.

        This is useful for queries like "idempotency" where the word doesn't
        match any entity extraction patterns but embeddings can find relevant
        nodes semantically.

        Args:
            question: The original question.
            stats: Extraction stats dict to update.

        Returns:
            ContextResult with search results, or None if no results.
        """
        # Check if embeddings are available
        try:
            embed_stats = self.mubase.embedding_stats()
            if embed_stats.get("nodes_with_embeddings", 0) == 0:
                logger.debug("Semantic fallback skipped: no embeddings")
                stats["semantic_fallback"] = "no_embeddings"
                return None
        except Exception as e:
            logger.debug(f"Semantic fallback skipped: {e}")
            stats["semantic_fallback"] = f"error: {e}"
            return None

        try:
            import asyncio

            from mu.config import MUConfig
            from mu.kernel.embeddings import EmbeddingService

            try:
                config = MUConfig.load()
            except Exception:
                config = MUConfig()

            # Use local embeddings for fallback (faster, no API key needed)
            service = EmbeddingService(config=config.embeddings, provider="local")

            async def get_query_embedding() -> list[float] | None:
                return await service.embed_query(question)

            query_embedding = asyncio.run(get_query_embedding())

            if not query_embedding:
                asyncio.run(service.close())
                stats["semantic_fallback"] = "embedding_failed"
                return None

            # Search with reasonable limit
            search_results = self.mubase.vector_search(
                query_embedding=query_embedding,
                embedding_type="code",
                limit=20,
            )

            asyncio.run(service.close())

            if not search_results:
                stats["semantic_fallback"] = "no_results"
                return None

            # Convert to ScoredNode and export
            scored_nodes = [
                ScoredNode(node=node, score=score)
                for node, score in search_results
            ]

            # Fit to budget
            selected = self.budgeter.fit_to_budget(
                scored_nodes,
                mubase=self.mubase,
                include_parent=self.config.include_parent,
            )

            if not selected:
                stats["semantic_fallback"] = "budget_exhausted"
                return None

            # Export as MU format
            mu_text = self.exporter.export_mu(selected)
            token_count = self.budgeter.get_actual_tokens(mu_text)

            stats["semantic_fallback"] = "success"
            stats["fallback_results"] = len(search_results)
            stats["selected_nodes"] = len(selected)
            stats["actual_tokens"] = token_count

            return ContextResult(
                mu_text=mu_text,
                nodes=[sn.node for sn in selected],
                token_count=token_count,
                relevance_scores={sn.node.id: sn.score for sn in selected},
                extraction_stats=stats,
                strategy_used="semantic_search_fallback",
            )

        except Exception as e:
            logger.debug(f"Semantic fallback failed: {e}")
            stats["semantic_fallback"] = f"error: {e}"
            return None

    # =========================================================================
    # Graph-Based Extraction Methods (used when embeddings unavailable)
    # =========================================================================

    def _check_embeddings_available(self) -> bool:
        """Check if embeddings are available in the database.

        Returns:
            True if embeddings exist, False otherwise.
        """
        try:
            embed_stats = self.mubase.embedding_stats()
            count = embed_stats.get("nodes_with_embeddings", 0)
            return bool(count and count > 0)
        except Exception as e:
            logger.debug(f"Failed to check embeddings: {e}")
            return False

    def _detect_query_language(
        self,
        question: str,
        entities: list[ExtractedEntity],
    ) -> str | None:
        """Detect the likely target programming language from the query.

        Looks for:
        - Explicit language mentions: "C#", "Python", ".NET"
        - File extension mentions: ".cs", ".py"
        - Framework mentions: "ASP.NET", "Django", "React"

        Args:
            question: The user's natural language question.
            entities: Extracted entities from the question.

        Returns:
            Language identifier (e.g., "csharp", "python") or None if not detected.
        """
        question_lower = question.lower()

        # Language indicators mapped to canonical language names
        language_indicators: dict[str, list[str]] = {
            "csharp": ["c#", ".net", "asp.net", ".cs", "csharp", "c sharp"],
            "python": ["python", "django", "flask", ".py", "fastapi", "pytest"],
            "typescript": ["typescript", "react", "angular", ".ts", ".tsx", "nextjs", "next.js"],
            "javascript": ["javascript", "node", "express", ".js", ".jsx", "nodejs"],
            "java": ["java", "spring", "maven", ".java", "gradle", "kotlin"],
            "go": ["golang", " go ", ".go", "goroutine"],
            "rust": ["rust", "cargo", ".rs", "rustc"],
        }

        for lang, indicators in language_indicators.items():
            if any(ind in question_lower for ind in indicators):
                return lang

        # Check entity file extensions
        for entity in entities:
            if "." in entity.name:
                ext = entity.name.split(".")[-1].lower()
                ext_to_lang = {
                    "cs": "csharp",
                    "py": "python",
                    "ts": "typescript",
                    "tsx": "typescript",
                    "js": "javascript",
                    "jsx": "javascript",
                    "java": "java",
                    "go": "go",
                    "rs": "rust",
                }
                if ext in ext_to_lang:
                    return ext_to_lang[ext]

        return None

    def _get_node_language(self, node: Node) -> str | None:
        """Determine a node's programming language from its file extension.

        Args:
            node: The node to check.

        Returns:
            Language identifier or None if not determinable.
        """
        if not node.file_path:
            return None

        ext_to_lang = {
            ".cs": "csharp",
            ".py": "python",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".java": "java",
            ".go": "go",
            ".rs": "rust",
        }

        for ext, lang in ext_to_lang.items():
            if node.file_path.endswith(ext):
                return lang

        return None

    def _lang_to_extensions(self, language: str) -> list[str]:
        """Convert language name to file extensions.

        Args:
            language: Language identifier (e.g., "csharp", "python").

        Returns:
            List of file extensions for that language.
        """
        lang_extensions = {
            "csharp": [".cs"],
            "python": [".py"],
            "typescript": [".ts", ".tsx"],
            "javascript": [".js", ".jsx"],
            "java": [".java"],
            "go": [".go"],
            "rust": [".rs"],
        }
        return lang_extensions.get(language, [])

    def _find_seed_nodes_graph_aware(
        self,
        entities: list[ExtractedEntity],
        question: str,
    ) -> tuple[list[Node], set[str], dict[str, float]]:
        """Find seed nodes using graph-aware matching with language filtering.

        This method improves upon basic keyword matching by:
        1. Prioritizing exact name matches (score: 1.0)
        2. Falling back to qualified name matches (score: 0.95)
        3. Using file path matching (score: 0.8)
        4. Using suffix/prefix matching within same language (score: 0.7)
        5. Filtering cross-language results when language is detected

        Args:
            entities: Extracted entities to search for.
            question: Original question for language detection.

        Returns:
            Tuple of (seed nodes, seed node IDs, node_id -> match_score).
        """
        seed_nodes: list[Node] = []
        seed_ids: set[str] = set()
        scores: dict[str, float] = {}

        # Detect primary language from question context
        primary_language = self._detect_query_language(question, entities)
        logger.debug(f"Detected primary language: {primary_language}")

        for entity in entities:
            name = entity.name

            # Strategy 1: Exact name match (highest priority)
            exact_matches = self.mubase.find_by_name(name)
            for node in exact_matches:
                if node.id not in seed_ids:
                    # Apply language filter if detected
                    node_lang = self._get_node_language(node)
                    if primary_language and node_lang and node_lang != primary_language:
                        # Different language - skip for exact matches
                        continue

                    seed_nodes.append(node)
                    seed_ids.add(node.id)
                    scores[node.id] = 1.0

            if exact_matches:
                continue  # Found exact matches, skip fuzzy for this entity

            # Strategy 2: Qualified name suffix match
            qualified_matches = self.mubase.find_by_name(f"%{name}")
            for node in qualified_matches:
                if node.id not in seed_ids:
                    node_lang = self._get_node_language(node)
                    if primary_language and node_lang and node_lang != primary_language:
                        continue

                    seed_nodes.append(node)
                    seed_ids.add(node.id)
                    scores[node.id] = 0.95

            if qualified_matches:
                continue

            # Strategy 3: File path contains entity name
            path_matches = self._search_by_path_pattern(name)
            for node in path_matches:
                if node.id not in seed_ids:
                    node_lang = self._get_node_language(node)
                    if primary_language and node_lang and node_lang != primary_language:
                        continue

                    seed_nodes.append(node)
                    seed_ids.add(node.id)
                    scores[node.id] = 0.8

            # Strategy 4: Suffix/prefix match (same language only)
            if primary_language:
                extensions = self._lang_to_extensions(primary_language)
                for ext in extensions:
                    try:
                        result = self.mubase.execute(
                            """
                            SELECT * FROM nodes
                            WHERE (name LIKE ? OR name LIKE ?)
                            AND file_path LIKE ?
                            AND type IN ('module', 'class', 'function')
                            LIMIT 10
                            """,
                            [f"%{name}", f"{name}%", f"%{ext}"],
                        )
                        for row in result:
                            found_node = self.mubase.get_node(row[0])
                            if found_node is not None and found_node.id not in seed_ids:
                                seed_nodes.append(found_node)
                                seed_ids.add(found_node.id)
                                scores[found_node.id] = 0.7
                    except Exception:
                        pass

        return seed_nodes, seed_ids, scores

    def _get_edges_for_node(self, node_id: str) -> list[Edge]:
        """Get all edges connected to a node (both directions).

        Args:
            node_id: The node ID to get edges for.

        Returns:
            List of edges where node is either source or target.
        """
        outgoing = self.mubase.get_edges(source_id=node_id)
        incoming = self.mubase.get_edges(target_id=node_id)
        return outgoing + incoming

    def _expand_graph_scored(
        self,
        seed_nodes: list[Node],
        seed_scores: dict[str, float],
        config: GraphExpansionConfig | None = None,
    ) -> dict[str, tuple[Node, float]]:
        """Expand seed nodes via graph relationships with scored results.

        Uses BFS with relationship-type scoring and depth decay to find
        related nodes while maintaining relevance scores.

        Args:
            seed_nodes: Initial nodes to expand from.
            seed_scores: Scores for seed nodes from matching.
            config: Expansion configuration (uses defaults if not provided).

        Returns:
            Dict of node_id -> (Node, score) for all discovered nodes.
        """
        if config is None:
            config = GraphExpansionConfig()

        results: dict[str, tuple[Node, float]] = {}

        # Add seeds with their scores
        for node in seed_nodes:
            score = seed_scores.get(node.id, 1.0)
            results[node.id] = (node, score)

        # BFS expansion with score decay
        # Format: (node_id, current_score, depth)
        frontier: list[tuple[str, float, int]] = [
            (node.id, seed_scores.get(node.id, 1.0), 0) for node in seed_nodes
        ]
        visited = set(results.keys())

        while frontier:
            current_id, current_score, depth = frontier.pop(0)

            if depth >= config.max_depth:
                continue

            # Get all edges from current node
            edges = self._get_edges_for_node(current_id)

            # Limit edges per node to prevent explosion
            edges = edges[: config.max_nodes_per_depth]

            for edge in edges:
                # Determine neighbor
                if edge.source_id == current_id:
                    neighbor_id = edge.target_id
                else:
                    neighbor_id = edge.source_id

                if neighbor_id in visited:
                    # If already visited, check if we have a better score
                    if neighbor_id in results:
                        existing_score = results[neighbor_id][1]
                        edge_weight = config.weights.get(edge.type.value.upper(), 0.5)
                        depth_factor = config.depth_decay ** (depth + 1)
                        new_score = current_score * edge_weight * depth_factor
                        if new_score > existing_score:
                            # Update with better score
                            node = results[neighbor_id][0]
                            results[neighbor_id] = (node, new_score)
                    continue

                # Calculate score for neighbor
                edge_weight = config.weights.get(edge.type.value.upper(), 0.5)
                depth_factor = config.depth_decay ** (depth + 1)
                neighbor_score = current_score * edge_weight * depth_factor

                # Skip if score too low
                if neighbor_score < 0.1:
                    continue

                # Get neighbor node
                neighbor = self.mubase.get_node(neighbor_id)
                if neighbor is None:
                    continue

                # Add to results
                results[neighbor_id] = (neighbor, neighbor_score)
                visited.add(neighbor_id)

                # Add to frontier for further expansion
                if depth + 1 < config.max_depth:
                    frontier.append((neighbor_id, neighbor_score, depth + 1))

        return results

    def _detect_domains(self) -> list[DomainBoundary]:
        """Detect domain boundaries in the codebase.

        Domains are detected by analyzing directory structure and language
        distribution. This helps prevent context from crossing domain
        boundaries in monorepos.

        Returns:
            List of detected domain boundaries.
        """
        domains: list[DomainBoundary] = []

        try:
            # Query for distinct root directories and their languages
            result = self.mubase.execute(
                """
                SELECT
                    CASE
                        WHEN POSITION('/' IN file_path) > 0
                        THEN SPLIT_PART(file_path, '/', 1)
                        ELSE file_path
                    END as root_dir,
                    CASE
                        WHEN file_path LIKE '%.cs' THEN 'csharp'
                        WHEN file_path LIKE '%.py' THEN 'python'
                        WHEN file_path LIKE '%.ts' OR file_path LIKE '%.tsx' THEN 'typescript'
                        WHEN file_path LIKE '%.js' OR file_path LIKE '%.jsx' THEN 'javascript'
                        WHEN file_path LIKE '%.java' THEN 'java'
                        WHEN file_path LIKE '%.go' THEN 'go'
                        WHEN file_path LIKE '%.rs' THEN 'rust'
                        ELSE 'other'
                    END as language,
                    COUNT(*) as node_count
                FROM nodes
                WHERE file_path IS NOT NULL
                GROUP BY root_dir, language
                HAVING COUNT(*) > 3
                ORDER BY node_count DESC
                """,
                [],
            )

            for row in result:
                root_dir, language, _count = row
                if root_dir and language != "other":
                    domains.append(
                        DomainBoundary(
                            root_path=root_dir,
                            language=language,
                            name=f"{root_dir}-{language}",
                        )
                    )
        except Exception as e:
            logger.debug(f"Failed to detect domains: {e}")

        return domains

    def _get_node_domain(
        self,
        node: Node,
        domains: list[DomainBoundary],
    ) -> DomainBoundary | None:
        """Determine which domain a node belongs to.

        Args:
            node: The node to check.
            domains: List of detected domain boundaries.

        Returns:
            The matching domain or None if not in any domain.
        """
        if not node.file_path:
            return None

        node_lang = self._get_node_language(node)

        for domain in domains:
            # Check if file path starts with domain root
            if node.file_path.startswith(domain.root_path):
                # Verify language matches
                if node_lang == domain.language:
                    return domain

        return None

    def _filter_by_domain(
        self,
        candidates: dict[str, tuple[Node, float]],
        seed_domains: set[str],
    ) -> dict[str, tuple[Node, float]]:
        """Filter candidates to prefer nodes in the same domain as seeds.

        Cross-domain nodes are penalized but not excluded entirely,
        allowing some cross-domain references to appear with lower scores.

        Args:
            candidates: Dict of node_id -> (Node, score).
            seed_domains: Set of domain names from seed nodes.

        Returns:
            Filtered dict with adjusted scores.
        """
        domains = self._detect_domains()
        filtered: dict[str, tuple[Node, float]] = {}

        for node_id, (node, score) in candidates.items():
            node_domain = self._get_node_domain(node, domains)

            if node_domain is None:
                # Unknown domain - keep with slight penalty
                filtered[node_id] = (node, score * 0.8)
            elif node_domain.name in seed_domains:
                # Same domain - keep full score
                filtered[node_id] = (node, score)
            else:
                # Different domain - significant penalty but not excluded
                filtered[node_id] = (node, score * 0.3)

        return filtered

    def _include_call_sites(
        self,
        candidates: dict[str, tuple[Node, float]],
    ) -> dict[str, tuple[Node, float]]:
        """Include call sites for function nodes.

        For each function in candidates, also include nodes that call it
        (with reduced score) to show how the function is used.

        Args:
            candidates: Dict of node_id -> (Node, score).

        Returns:
            Expanded dict including callers of functions.
        """
        result = dict(candidates)

        for node_id, (node, score) in candidates.items():
            if node.type != NodeType.FUNCTION:
                continue

            # Get callers (incoming CALLS edges)
            caller_edges = self.mubase.get_edges(
                target_id=node_id,
                edge_type=EdgeType.CALLS,
            )

            # Limit to top 3 callers
            for edge in caller_edges[:3]:
                caller_id = edge.source_id
                if caller_id in result:
                    continue

                caller = self.mubase.get_node(caller_id)
                if caller:
                    # Callers get 0.7x score
                    result[caller_id] = (caller, score * 0.7)

        return result

    def _generate_extraction_warnings(
        self,
        seed_nodes: list[Node],
        final_nodes: list[ScoredNode],
        primary_language: str | None,
    ) -> list[str]:
        """Generate warnings about potential context quality issues.

        Args:
            seed_nodes: Initial seed nodes from matching.
            final_nodes: Final selected nodes after budgeting.
            primary_language: Detected primary language (if any).

        Returns:
            List of warning messages.
        """
        warnings: list[str] = []

        # Check if we lost too many seeds
        seed_ids = {n.id for n in seed_nodes}
        final_ids = {sn.node.id for sn in final_nodes}
        lost_seeds = seed_ids - final_ids

        if len(lost_seeds) > len(seed_ids) * 0.5 and len(seed_ids) > 0:
            warnings.append(
                f"{len(lost_seeds)} seed nodes excluded due to budget. Results may be incomplete."
            )

        # Check for multi-language results
        languages: set[str] = set()
        for sn in final_nodes:
            lang = self._get_node_language(sn.node)
            if lang:
                languages.add(lang)

        if len(languages) > 1:
            lang_list = ", ".join(sorted(languages))
            warnings.append(
                f"Results span multiple languages ({lang_list}). "
                "Consider specifying the target language in your query."
            )

        return warnings

    def _extract_with_graph(
        self,
        question: str,
        entities: list[ExtractedEntity],
    ) -> ContextResult:
        """Extract context using graph relationships instead of embeddings.

        This is the fallback strategy when embeddings are not available.
        It leverages the code structure (imports, calls, inheritance) to
        find relevant code with domain boundary awareness.

        Strategy:
        1. Find seed nodes with graph-aware matching
        2. Detect seed domains for filtering
        3. Expand via graph relationships with scored traversal
        4. Apply domain filtering to reduce cross-language noise
        5. Include call sites for function nodes
        6. Score and rank results
        7. Apply budget and export to MU format

        Args:
            question: Natural language question about the code.
            entities: Extracted entities from the question.

        Returns:
            ContextResult with MU format context and metadata.
        """
        stats: dict[str, Any] = {
            "method": "graph",
            "question_length": len(question),
            "max_tokens": self.config.max_tokens,
        }

        # Detect primary language for filtering
        primary_language = self._detect_query_language(question, entities)
        stats["detected_language"] = primary_language

        # Step 1: Find seed nodes
        seed_nodes, seed_ids, seed_scores = self._find_seed_nodes_graph_aware(entities, question)
        stats["seeds"] = len(seed_nodes)
        stats["entities"] = [e.name for e in entities]

        if not seed_nodes:
            return ContextResult(
                mu_text="# No relevant nodes found\n\n"
                "Try using more specific terms or check that the code has been indexed.",
                nodes=[],
                token_count=0,
                relevance_scores={},
                extraction_stats=stats,
                extraction_method="graph",
            )

        # Detect seed domains for filtering
        domains = self._detect_domains()
        seed_domains: set[str] = set()
        for node in seed_nodes:
            domain = self._get_node_domain(node, domains)
            if domain:
                seed_domains.add(domain.name)
        stats["seed_domains"] = list(seed_domains)

        # Step 2: Expand via graph
        expansion_config = GraphExpansionConfig(
            max_depth=2,
            max_nodes_per_depth=15,
        )
        expanded = self._expand_graph_scored(seed_nodes, seed_scores, expansion_config)
        stats["expanded"] = len(expanded)

        # Step 3: Apply domain filtering
        filtered = self._filter_by_domain(expanded, seed_domains)
        stats["after_domain_filter"] = len(filtered)

        # Step 4: Include call sites for functions
        with_call_sites = self._include_call_sites(filtered)
        stats["with_call_sites"] = len(with_call_sites)

        # Step 5: Create scored nodes for ranking
        scored_nodes: list[ScoredNode] = []
        for node_id, (node, score) in with_call_sites.items():
            scored_nodes.append(
                ScoredNode(
                    node=node,
                    score=score,
                    entity_score=seed_scores.get(node_id, 0.0),
                    vector_score=0.0,  # No vector search in graph mode
                    proximity_score=score if node_id not in seed_ids else 0.0,
                )
            )

        # Sort by score descending
        scored_nodes.sort(key=lambda x: x.score, reverse=True)
        stats["scored_nodes"] = len(scored_nodes)

        # Step 6: Filter by test exclusion if configured
        if self.config.exclude_tests:
            scored_nodes = self._exclude_tests(scored_nodes)
            stats["after_test_filter"] = len(scored_nodes)

        # Step 7: Fit to token budget
        selected = self.budgeter.fit_to_budget(
            scored_nodes,
            mubase=self.mubase,
            include_parent=self.config.include_parent,
        )
        stats["selected_nodes"] = len(selected)

        # Handle empty results
        if not selected:
            stats["warnings"] = ["No nodes fit within the token budget."]
            return ContextResult(
                mu_text=f":: No relevant context found for: {question}",
                nodes=[],
                token_count=0,
                relevance_scores={},
                extraction_stats=stats,
                extraction_method="graph",
            )

        # Step 8: Export as MU format
        mu_text = self.exporter.export_mu(selected)
        token_count = self.budgeter.get_actual_tokens(mu_text)
        stats["actual_tokens"] = token_count
        stats["budget_utilization"] = round(token_count / self.config.max_tokens * 100, 1)

        # Build relevance scores map
        relevance_scores = {sn.node.id: sn.score for sn in selected}

        # Generate and store warnings in stats
        extraction_warnings = self._generate_extraction_warnings(
            seed_nodes, selected, primary_language
        )
        if extraction_warnings:
            stats["warnings"] = extraction_warnings

        return ContextResult(
            mu_text=mu_text,
            nodes=[sn.node for sn in selected],
            token_count=token_count,
            relevance_scores=relevance_scores,
            extraction_stats=stats,
            extraction_method="graph",
        )


__all__ = ["SmartContextExtractor", "GraphExpansionConfig", "DomainBoundary"]
