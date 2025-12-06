"""Smart Context Extractor - orchestrates context extraction.

Combines entity extraction, scoring, budgeting, and export into
a cohesive API for intelligent context selection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mu.kernel.context.budgeter import TokenBudgeter
from mu.kernel.context.export import ContextExporter
from mu.kernel.context.extractor import EntityExtractor
from mu.kernel.context.models import (
    ContextResult,
    ExtractedEntity,
    ExtractionConfig,
    ScoredNode,
)
from mu.kernel.context.scorer import RelevanceScorer
from mu.kernel.schema import NodeType

if TYPE_CHECKING:
    from mu.kernel.models import Node
    from mu.kernel.mubase import MUbase


class SmartContextExtractor:
    """Extract optimal context for answering questions about code.

    Orchestrates the full extraction pipeline:
    1. Entity extraction from the question
    2. Node matching by name and vector similarity
    3. Graph expansion to include related nodes
    4. Relevance scoring of all candidates
    5. Token budgeting to fit output size
    6. MU format export
    """

    def __init__(
        self,
        mubase: MUbase,
        config: ExtractionConfig | None = None,
    ) -> None:
        """Initialize the smart context extractor.

        Args:
            mubase: The MUbase graph database.
            config: Extraction configuration (uses defaults if not provided).
        """
        self.mubase = mubase
        self.config = config or ExtractionConfig()

        # Get all node names for entity extraction
        known_names = self._get_known_names()

        # Initialize components
        self.entity_extractor = EntityExtractor(known_names)
        self.scorer = RelevanceScorer(self.config, mubase)
        self.budgeter = TokenBudgeter(self.config.max_tokens)
        self.exporter = ContextExporter(mubase, include_scores=False)

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
        stats: dict[str, Any] = {
            "question_length": len(question),
            "max_tokens": self.config.max_tokens,
        }

        # Step 1: Extract entities from question
        entities = self.entity_extractor.extract(question)
        stats["entities_extracted"] = len(entities)
        stats["entities"] = [e.name for e in entities]

        # Step 2: Find seed nodes by name matching
        seed_nodes, seed_node_ids = self._find_seed_nodes(entities)
        stats["named_nodes_found"] = len(seed_nodes)

        # Step 3: Vector search for semantic matches (if embeddings available)
        vector_nodes, vector_scores = self._vector_search(question)
        stats["vector_matches"] = len(vector_nodes)

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
            return ContextResult(
                mu_text=f":: No relevant context found for: {question}",
                nodes=[],
                token_count=0,
                relevance_scores={},
                extraction_stats=stats,
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

            for node in matches:
                if node.id not in node_ids:
                    nodes.append(node)
                    node_ids.add(node.id)

        return nodes, node_ids

    def _find_by_suffix(self, suffix: str) -> list[Node]:
        """Find nodes whose name ends with the given suffix."""
        # Use pattern match with wildcard
        return self.mubase.find_by_name(f"%{suffix}")

    def _vector_search(
        self,
        question: str,
    ) -> tuple[list[Node], dict[str, float]]:
        """Search for semantically similar nodes.

        Args:
            question: The question to search for.

        Returns:
            Tuple of (matching nodes, node_id -> similarity score).
        """
        # Check if embeddings are available
        try:
            embed_stats = self.mubase.embedding_stats()
            if embed_stats.get("nodes_with_embeddings", 0) == 0:
                return [], {}
        except Exception:
            return [], {}

        # Import embedding service lazily to avoid circular imports
        try:
            from mu.kernel.embeddings import EmbeddingService
        except ImportError:
            return [], {}

        # Create embedding service for query
        try:
            import asyncio

            from mu.config import MUConfig

            config = MUConfig()
            service = EmbeddingService(config=config.embeddings)

            # Get query embedding
            async def get_embedding() -> list[float] | None:
                return await service.embed_query(question)

            query_embedding = asyncio.run(get_embedding())

            if not query_embedding:
                asyncio.run(service.close())
                return [], {}

            # Perform vector search
            results = self.mubase.vector_search(
                query_embedding=query_embedding,
                embedding_type="code",
                limit=self.config.vector_search_limit,
            )

            asyncio.run(service.close())

            nodes = [node for node, _ in results]
            scores = {node.id: score for node, score in results}

            return nodes, scores

        except Exception:
            # Vector search failed, continue without it
            return [], {}

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
