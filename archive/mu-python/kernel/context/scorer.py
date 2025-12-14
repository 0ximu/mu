"""Relevance scoring for context extraction.

Scores nodes based on multiple signals: entity match, vector similarity,
and graph proximity to seed nodes.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from mu.kernel.context.models import ExtractedEntity, ExtractionConfig, ScoredNode

if TYPE_CHECKING:
    from mu.kernel.models import Node
    from mu.kernel.mubase import MUbase


class RelevanceScorer:
    """Score nodes based on relevance to a question.

    Combines multiple scoring signals:
    - Entity match: How well node names match extracted entities
    - Vector similarity: Embedding similarity to the question
    - Proximity: Graph distance from high-relevance seed nodes
    """

    def __init__(self, config: ExtractionConfig, mubase: MUbase) -> None:
        """Initialize the relevance scorer.

        Args:
            config: Extraction configuration with weights.
            mubase: The MUbase database for graph queries.
        """
        self.config = config
        self.mubase = mubase

    def score_nodes(
        self,
        nodes: list[Node],
        question: str,
        entities: list[ExtractedEntity],
        seed_node_ids: set[str],
        vector_scores: dict[str, float] | None = None,
    ) -> list[ScoredNode]:
        """Score a list of nodes for relevance.

        Args:
            nodes: Candidate nodes to score.
            question: The original question (for future use).
            entities: Extracted entities from the question.
            seed_node_ids: IDs of high-confidence seed nodes.
            vector_scores: Optional pre-computed vector similarity scores.

        Returns:
            List of ScoredNode objects, sorted by score descending.
        """
        vector_scores = vector_scores or {}

        # Pre-compute distances from seed nodes
        distances = self._compute_distances(seed_node_ids, nodes)

        scored_nodes: list[ScoredNode] = []

        for node in nodes:
            # Calculate individual scores
            entity_score = self._score_entity_match(node, entities)
            vector_score = vector_scores.get(node.id, 0.0)
            proximity_score = self._score_proximity(node.id, distances)

            # Combine scores with weights
            combined_score = (
                self.config.entity_weight * entity_score
                + self.config.vector_weight * vector_score
                + self.config.proximity_weight * proximity_score
            )

            # Skip nodes below minimum relevance
            if combined_score < self.config.min_relevance:
                continue

            scored_nodes.append(
                ScoredNode(
                    node=node,
                    score=combined_score,
                    entity_score=entity_score,
                    vector_score=vector_score,
                    proximity_score=proximity_score,
                )
            )

        # Sort by score descending
        scored_nodes.sort(key=lambda sn: -sn.score)

        return scored_nodes

    def _score_entity_match(
        self,
        node: Node,
        entities: list[ExtractedEntity],
    ) -> float:
        """Score how well a node matches extracted entities.

        Scoring logic:
        - Exact name match: 1.0
        - Partial/suffix match: 0.5
        - Case-insensitive match: 0.3
        - Qualified name contains entity: 0.4
        """
        if not entities:
            return 0.0

        max_score = 0.0
        node_name = node.name
        node_name_lower = node_name.lower()
        qualified_name = node.qualified_name or ""
        qualified_lower = qualified_name.lower()

        for entity in entities:
            entity_name = entity.name
            entity_lower = entity_name.lower()
            entity_confidence = entity.confidence

            # Exact match
            if node_name == entity_name:
                score = 1.0 * entity_confidence
                max_score = max(max_score, score)
                continue

            # Case-insensitive exact match
            if node_name_lower == entity_lower:
                score = 0.8 * entity_confidence
                max_score = max(max_score, score)
                continue

            # Suffix match (e.g., entity "Service" matches "AuthService")
            if node_name.endswith(entity_name) or node_name_lower.endswith(entity_lower):
                score = 0.6 * entity_confidence
                max_score = max(max_score, score)
                continue

            # Prefix match (e.g., entity "Auth" matches "AuthService")
            if node_name.startswith(entity_name) or node_name_lower.startswith(entity_lower):
                score = 0.5 * entity_confidence
                max_score = max(max_score, score)
                continue

            # Qualified name contains entity
            if entity_lower in qualified_lower:
                score = 0.4 * entity_confidence
                max_score = max(max_score, score)
                continue

            # Substring match in name
            if entity_lower in node_name_lower:
                score = 0.3 * entity_confidence
                max_score = max(max_score, score)

        return max_score

    def _score_proximity(
        self,
        node_id: str,
        distances: dict[str, int],
    ) -> float:
        """Score based on graph distance from seed nodes.

        Score = 1 / (1 + distance)
        - Distance 0 (seed node): 1.0
        - Distance 1: 0.5
        - Distance 2: 0.33
        - etc.
        """
        distance = distances.get(node_id)
        if distance is None:
            return 0.0

        return 1.0 / (1.0 + distance)

    def _compute_distances(
        self,
        seed_node_ids: set[str],
        candidate_nodes: list[Node],
    ) -> dict[str, int]:
        """Compute shortest distances from seed nodes using BFS.

        Args:
            seed_node_ids: Starting nodes for BFS.
            candidate_nodes: Nodes we care about distances for.

        Returns:
            Mapping of node_id to shortest distance from any seed node.
        """
        if not seed_node_ids:
            return {}

        # Set of node IDs we want distances for
        target_ids = {n.id for n in candidate_nodes}

        # BFS from all seed nodes simultaneously
        distances: dict[str, int] = {}
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque()

        # Initialize with seed nodes at distance 0
        for seed_id in seed_node_ids:
            if seed_id not in visited:
                queue.append((seed_id, 0))
                visited.add(seed_id)
                if seed_id in target_ids:
                    distances[seed_id] = 0

        # BFS traversal
        max_depth = self.config.expand_depth + 1

        while queue:
            node_id, depth = queue.popleft()

            if depth >= max_depth:
                continue

            # Get neighbors (both directions)
            neighbors = self._get_neighbor_ids(node_id)

            for neighbor_id in neighbors:
                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    new_depth = depth + 1
                    queue.append((neighbor_id, new_depth))

                    if neighbor_id in target_ids:
                        distances[neighbor_id] = new_depth

        return distances

    def _get_neighbor_ids(self, node_id: str) -> list[str]:
        """Get IDs of neighboring nodes in the graph."""
        neighbor_ids: list[str] = []

        # Outgoing edges (dependencies)
        outgoing = self.mubase.get_edges(source_id=node_id)
        for edge in outgoing:
            neighbor_ids.append(edge.target_id)

        # Incoming edges (dependents)
        incoming = self.mubase.get_edges(target_id=node_id)
        for edge in incoming:
            neighbor_ids.append(edge.source_id)

        return neighbor_ids


__all__ = ["RelevanceScorer"]
