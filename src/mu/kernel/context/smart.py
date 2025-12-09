"""Smart Context Extractor - orchestrates context extraction.

Combines entity extraction, scoring, budgeting, and export into
a cohesive API for intelligent context selection.

Now includes intent classification to select specialized extraction
strategies for different types of questions.
"""

from __future__ import annotations

import logging
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
from mu.kernel.schema import NodeType

if TYPE_CHECKING:
    from mu.kernel.models import Node
    from mu.kernel.mubase import MUbase

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

        # Fall through to default extraction pipeline
        stats: dict[str, Any] = {
            "question_length": len(question),
            "max_tokens": self.config.max_tokens,
            "intent": intent.value,
            "intent_confidence": confidence,
            "strategy_used": "default",
        }

        # Step 1: Extract entities from question
        entities = self.entity_extractor.extract(question)
        stats["entities_extracted"] = len(entities)
        stats["entities"] = [e.name for e in entities]

        # Step 2: Find seed nodes by name matching
        seed_nodes, seed_node_ids = self._find_seed_nodes(entities)
        stats["named_nodes_found"] = len(seed_nodes)

        # Step 3: Vector search for semantic matches (if embeddings available)
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

        # Handle empty results
        if not selected:
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


__all__ = ["SmartContextExtractor"]
