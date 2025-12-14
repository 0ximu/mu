"""Extraction strategies for different question intents.

Provides specialized extraction strategies that optimize context extraction
based on the classified intent of the user's question.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from mu.kernel.context.budgeter import TokenBudgeter
from mu.kernel.context.export import ContextExporter
from mu.kernel.context.intent import ClassifiedIntent, Intent
from mu.kernel.context.models import ContextResult, ExportConfig, ExtractionConfig, ScoredNode
from mu.kernel.schema import NodeType

if TYPE_CHECKING:
    from mu.kernel.models import Node
    from mu.kernel.mubase import MUbase

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------


def _create_export_config(config: ExtractionConfig) -> ExportConfig:
    """Create ExportConfig from ExtractionConfig.

    Args:
        config: The extraction configuration.

    Returns:
        ExportConfig with matching settings.
    """
    return ExportConfig(
        include_docstrings=config.include_docstrings,
        include_line_numbers=config.include_line_numbers,
        include_internal_imports=config.include_imports,
        min_complexity_to_show=config.min_complexity_to_show,
    )


# -----------------------------------------------------------------------------
# Protocol Definition
# -----------------------------------------------------------------------------


class ExtractionStrategy(Protocol):
    """Protocol for extraction strategies.

    Each strategy implements a specialized extraction approach based on
    the intent of the user's question.
    """

    def extract(
        self,
        intent: ClassifiedIntent,
        mubase: MUbase,
        config: ExtractionConfig,
    ) -> ContextResult:
        """Extract context based on the classified intent.

        Args:
            intent: The classified intent with entities and metadata.
            mubase: The MUbase graph database.
            config: Extraction configuration (token budget, etc.).

        Returns:
            ContextResult with MU format context and metadata.
        """
        ...


# -----------------------------------------------------------------------------
# Strategy Implementations
# -----------------------------------------------------------------------------


class LocateStrategy:
    """Strategy for 'where is X' questions.

    Finds exact match for entity and returns minimal context:
    - Single node (or top 3 if ambiguous)
    - File path and line numbers
    - Minimal expansion (just parent class/module)
    """

    def extract(
        self,
        intent: ClassifiedIntent,
        mubase: MUbase,
        config: ExtractionConfig,
    ) -> ContextResult:
        """Extract location information for entities."""
        stats: dict[str, Any] = {
            "strategy_used": "locate",
            "entities": intent.entities,
            "max_tokens": config.max_tokens,
        }

        # Find nodes matching the entities
        matched_nodes: list[Node] = []
        for entity in intent.entities:
            nodes = mubase.find_by_name(entity)
            if not nodes:
                # Try suffix match
                nodes = mubase.find_by_name(f"%{entity}")
            matched_nodes.extend(nodes)

        # Deduplicate
        seen_ids: set[str] = set()
        unique_nodes: list[Node] = []
        for node in matched_nodes:
            if node.id not in seen_ids:
                seen_ids.add(node.id)
                unique_nodes.append(node)

        stats["nodes_found"] = len(unique_nodes)

        # If no nodes found, return empty result
        if not unique_nodes:
            return ContextResult(
                mu_text=f":: No matches found for: {', '.join(intent.entities)}",
                nodes=[],
                token_count=10,
                relevance_scores={},
                extraction_stats=stats,
            )

        # Limit to top 3 if ambiguous
        if len(unique_nodes) > 3:
            unique_nodes = unique_nodes[:3]
            stats["limited_to"] = 3

        # Include parent context for each node
        nodes_with_parents: list[Node] = []
        for node in unique_nodes:
            nodes_with_parents.append(node)
            parent = mubase.get_parent(node.id)
            if parent and parent.id not in seen_ids:
                nodes_with_parents.append(parent)
                seen_ids.add(parent.id)

        # Convert to scored nodes (all score 1.0 for exact matches)
        scored_nodes = [
            ScoredNode(node=node, score=1.0, entity_score=1.0) for node in nodes_with_parents
        ]

        # Export as MU format
        exporter = ContextExporter(mubase, include_scores=False)
        mu_text = exporter.export_mu(scored_nodes)

        # Add location summary
        location_lines = [f":: Location Summary for: {', '.join(intent.entities)}"]
        for node in unique_nodes:
            location = f"  {node.name}: {node.file_path or 'unknown'}"
            if node.line_start:
                location += f":{node.line_start}"
                if node.line_end and node.line_end != node.line_start:
                    location += f"-{node.line_end}"
            location_lines.append(location)

        full_text = "\n".join(location_lines) + "\n\n" + mu_text

        export_config = _create_export_config(config)
        budgeter = TokenBudgeter(config.max_tokens, export_config=export_config)
        token_count = budgeter.count_tokens(full_text)

        return ContextResult(
            mu_text=full_text,
            nodes=[sn.node for sn in scored_nodes],
            token_count=token_count,
            relevance_scores={sn.node.id: sn.score for sn in scored_nodes},
            extraction_stats=stats,
        )


class ImpactStrategy:
    """Strategy for 'what would break' questions.

    Analyzes impact of changes by:
    - Finding the target node
    - Getting dependents (depth=3) to find what uses it
    - Categorizing by risk level (direct vs transitive)
    - Including test files that cover the target
    """

    def extract(
        self,
        intent: ClassifiedIntent,
        mubase: MUbase,
        config: ExtractionConfig,
    ) -> ContextResult:
        """Extract impact analysis context."""
        stats: dict[str, Any] = {
            "strategy_used": "impact",
            "entities": intent.entities,
            "max_tokens": config.max_tokens,
        }

        # Find target node
        target_nodes: list[Node] = []
        for entity in intent.entities:
            nodes = mubase.find_by_name(entity)
            if not nodes:
                nodes = mubase.find_by_name(f"%{entity}")
            target_nodes.extend(nodes)

        if not target_nodes:
            return ContextResult(
                mu_text=f":: No target found for impact analysis: {', '.join(intent.entities)}",
                nodes=[],
                token_count=15,
                relevance_scores={},
                extraction_stats=stats,
            )

        # Use the first matched target
        target = target_nodes[0]
        stats["target_node"] = target.id

        # Get direct dependents (depth=1) - high risk
        direct_dependents = mubase.get_dependents(target.id, depth=1)
        stats["direct_dependents"] = len(direct_dependents)

        # Get transitive dependents (depth=3) - medium/low risk
        all_dependents = mubase.get_dependents(target.id, depth=3)
        transitive_dependents = [
            d for d in all_dependents if d.id not in {n.id for n in direct_dependents}
        ]
        stats["transitive_dependents"] = len(transitive_dependents)

        # Find test files among dependents
        test_files: list[Node] = []
        non_test_dependents: list[Node] = []

        for dep in all_dependents:
            file_path = dep.file_path or ""
            name = dep.name.lower()
            is_test = any(
                pattern in file_path.lower()
                for pattern in ("test_", "_test.", "tests/", "test/", "spec/")
            ) or name.startswith("test")

            if is_test:
                test_files.append(dep)
            else:
                non_test_dependents.append(dep)

        stats["test_coverage"] = len(test_files)

        # Build scored nodes with risk levels
        scored_nodes: list[ScoredNode] = []

        # Target node with highest score
        scored_nodes.append(ScoredNode(node=target, score=1.0, entity_score=1.0))

        # Direct dependents - high risk (score 0.9)
        direct_ids = {n.id for n in direct_dependents}
        for node in direct_dependents:
            if node.id != target.id:
                scored_nodes.append(ScoredNode(node=node, score=0.9, proximity_score=0.9))

        # Transitive dependents - medium risk (score 0.5)
        for node in transitive_dependents[:20]:  # Limit transitive
            if node.id not in direct_ids:
                scored_nodes.append(ScoredNode(node=node, score=0.5, proximity_score=0.5))

        # Test files - include but lower score (0.3)
        for node in test_files[:10]:  # Limit tests
            if node.id not in {sn.node.id for sn in scored_nodes}:
                scored_nodes.append(ScoredNode(node=node, score=0.3, proximity_score=0.3))

        # Fit to budget
        export_config = _create_export_config(config)
        budgeter = TokenBudgeter(config.max_tokens, export_config=export_config)
        scored_nodes.sort(key=lambda x: x.score, reverse=True)
        selected = budgeter.fit_to_budget(scored_nodes, mubase, include_parent=True)

        # Export as MU format
        exporter = ContextExporter(mubase, include_scores=True)
        mu_text = exporter.export_mu(selected)

        # Add impact summary header
        impact_header = [
            f":: Impact Analysis for: {target.name}",
            f":: Direct dependents (high risk): {len(direct_dependents)}",
            f":: Transitive dependents: {len(transitive_dependents)}",
            f":: Test coverage: {len(test_files)} test(s)",
            "",
        ]
        full_text = "\n".join(impact_header) + mu_text

        token_count = budgeter.count_tokens(full_text)

        return ContextResult(
            mu_text=full_text,
            nodes=[sn.node for sn in selected],
            token_count=token_count,
            relevance_scores={sn.node.id: sn.score for sn in selected},
            extraction_stats=stats,
        )


class NavigateStrategy:
    """Strategy for 'what calls X' / 'dependencies of X' questions.

    Determines direction and runs graph query:
    - 'callers' -> get_dependents (who uses this)
    - 'callees' -> get_dependencies (what this uses)
    """

    def extract(
        self,
        intent: ClassifiedIntent,
        mubase: MUbase,
        config: ExtractionConfig,
    ) -> ContextResult:
        """Extract navigation context."""
        # Get direction from modifiers if available
        modifiers = getattr(intent, "modifiers", {}) or {}
        direction = modifiers.get("direction", "both")

        stats: dict[str, Any] = {
            "strategy_used": "navigate",
            "entities": intent.entities,
            "direction": direction,
            "max_tokens": config.max_tokens,
        }

        # Find target node
        target_nodes: list[Node] = []
        for entity in intent.entities:
            nodes = mubase.find_by_name(entity)
            if not nodes:
                nodes = mubase.find_by_name(f"%{entity}")
            target_nodes.extend(nodes)

        if not target_nodes:
            return ContextResult(
                mu_text=f":: No target found for navigation: {', '.join(intent.entities)}",
                nodes=[],
                token_count=15,
                relevance_scores={},
                extraction_stats=stats,
            )

        target = target_nodes[0]
        stats["target_node"] = target.id

        # Use determined direction
        related_nodes: list[Node] = []

        if direction in ("callers", "both"):
            dependents = mubase.get_dependents(target.id, depth=2)
            related_nodes.extend(dependents)
            stats["dependents_found"] = len(dependents)

        if direction in ("callees", "both"):
            dependencies = mubase.get_dependencies(target.id, depth=2)
            related_nodes.extend(dependencies)
            stats["dependencies_found"] = len(dependencies)

        # Deduplicate
        seen_ids: set[str] = set()
        unique_related: list[Node] = []
        for node in related_nodes:
            if node.id not in seen_ids and node.id != target.id:
                seen_ids.add(node.id)
                unique_related.append(node)

        stats["unique_related"] = len(unique_related)

        # Build scored nodes
        scored_nodes: list[ScoredNode] = []

        # Target node first
        scored_nodes.append(ScoredNode(node=target, score=1.0, entity_score=1.0))

        # Related nodes with decreasing scores
        for i, node in enumerate(unique_related):
            # Score based on proximity (depth 1 = 0.8, depth 2 = 0.5)
            score = 0.8 if i < 10 else 0.5
            scored_nodes.append(ScoredNode(node=node, score=score, proximity_score=score))

        # Fit to budget
        export_config = _create_export_config(config)
        budgeter = TokenBudgeter(config.max_tokens, export_config=export_config)
        scored_nodes.sort(key=lambda x: x.score, reverse=True)
        selected = budgeter.fit_to_budget(scored_nodes, mubase, include_parent=True)

        # Export as MU format
        exporter = ContextExporter(mubase, include_scores=False)
        mu_text = exporter.export_mu(selected)

        # Add navigation header
        direction_label = {
            "callers": "Callers of",
            "callees": "Callees of",
            "both": "Dependencies and dependents of",
        }.get(direction, "Related to")

        nav_header = [
            f":: {direction_label}: {target.name}",
            f":: Found {len(unique_related)} related nodes",
            "",
        ]
        full_text = "\n".join(nav_header) + mu_text

        token_count = budgeter.count_tokens(full_text)

        return ContextResult(
            mu_text=full_text,
            nodes=[sn.node for sn in selected],
            token_count=token_count,
            relevance_scores={sn.node.id: sn.score for sn in selected},
            extraction_stats=stats,
        )


class ListStrategy:
    """Strategy for 'show all X' questions.

    Lists all items of a specific type:
    - functions, classes, modules
    - filtered by optional criteria
    """

    def extract(
        self,
        intent: ClassifiedIntent,
        mubase: MUbase,
        config: ExtractionConfig,
    ) -> ContextResult:
        """Extract list of items by type."""
        # Get target_type from modifiers or infer from entities
        modifiers = getattr(intent, "modifiers", {}) or {}
        target_type = modifiers.get("target_type")

        # Try to infer target_type from entities if not in modifiers
        if not target_type and intent.entities:
            first_entity = intent.entities[0].lower()
            if first_entity in ("functions", "function", "methods", "method"):
                target_type = "functions"
            elif first_entity in ("classes", "class"):
                target_type = "classes"
            elif first_entity in ("modules", "module", "files", "file"):
                target_type = "modules"

        target_type = target_type or "functions"

        stats: dict[str, Any] = {
            "strategy_used": "list",
            "target_type": target_type,
            "max_tokens": config.max_tokens,
        }
        node_type_map = {
            "functions": NodeType.FUNCTION,
            "function": NodeType.FUNCTION,
            "methods": NodeType.FUNCTION,
            "classes": NodeType.CLASS,
            "class": NodeType.CLASS,
            "modules": NodeType.MODULE,
            "module": NodeType.MODULE,
            "files": NodeType.MODULE,
        }

        node_type = node_type_map.get(target_type.lower(), NodeType.FUNCTION)
        stats["node_type"] = node_type.value
        type_label = node_type.value.capitalize() + "s"

        # Get all nodes of this type
        all_nodes = mubase.get_nodes(node_type)
        stats["total_found"] = len(all_nodes)

        # Filter by entities if provided (e.g., "list all functions in auth")
        if intent.entities:
            filtered_nodes: list[Node] = []
            for node in all_nodes:
                # Check if any entity matches file path or name
                matches = any(
                    entity.lower() in (node.file_path or "").lower()
                    or entity.lower() in node.name.lower()
                    for entity in intent.entities
                )
                if matches:
                    filtered_nodes.append(node)

            # If no matches found, try semantic search fallback
            if not filtered_nodes and mubase.has_embeddings():
                stats["entity_filter_empty"] = True
                stats["fallback"] = "semantic_search"
                # Use entity terms as query
                query = " ".join(intent.entities)
                try:
                    import asyncio

                    from mu.extras.embeddings.service import create_embedding_service

                    service = create_embedding_service(provider="local")
                    query_embedding = asyncio.get_event_loop().run_until_complete(
                        service.embed_query(query)
                    )
                    if query_embedding:
                        # Search for similar nodes of this type
                        search_results = mubase.vector_search(
                            query_embedding,
                            limit=50,
                            node_type=node_type,
                        )
                        filtered_nodes = [r[0] for r in search_results]
                        stats["semantic_matches"] = len(filtered_nodes)
                except Exception as e:
                    stats["semantic_fallback_error"] = str(e)

            # If still no matches and no semantic fallback, return empty with message
            if not filtered_nodes:
                stats["filtered_to"] = 0
                stats["no_matches"] = True
                # Return helpful message for empty results
                list_header = [
                    f":: {type_label} matching '{', '.join(intent.entities)}'",
                    f":: Showing 0 of {stats['total_found']} total",
                    ":: No relevant context found",
                ]
                return ContextResult(
                    mu_text="\n".join(list_header),
                    nodes=[],
                    token_count=len("\n".join(list_header)) // 4,
                    relevance_scores={},
                    extraction_stats=stats,
                )

            all_nodes = filtered_nodes
            stats["filtered_to"] = len(all_nodes)

        # Sort by complexity (most complex first) for functions
        if node_type == NodeType.FUNCTION:
            all_nodes.sort(key=lambda n: n.complexity or 0, reverse=True)
        else:
            all_nodes.sort(key=lambda n: n.name)

        # Build scored nodes
        scored_nodes: list[ScoredNode] = []
        for i, node in enumerate(all_nodes):
            # Decreasing score by position
            score = max(0.1, 1.0 - (i * 0.01))
            scored_nodes.append(ScoredNode(node=node, score=score))

        # Fit to budget
        export_config = _create_export_config(config)
        budgeter = TokenBudgeter(config.max_tokens, export_config=export_config)
        selected = budgeter.fit_to_budget(scored_nodes, mubase, include_parent=False)

        # Export as MU format
        exporter = ContextExporter(mubase, include_scores=False)
        mu_text = exporter.export_mu(selected)

        # Add list header
        filter_info = f" matching '{', '.join(intent.entities)}'" if intent.entities else ""
        list_header = [
            f":: {type_label}{filter_info}",
            f":: Showing {len(selected)} of {stats['total_found']} total",
            "",
        ]
        full_text = "\n".join(list_header) + mu_text

        token_count = budgeter.count_tokens(full_text)

        return ContextResult(
            mu_text=full_text,
            nodes=[sn.node for sn in selected],
            token_count=token_count,
            relevance_scores={sn.node.id: sn.score for sn in selected},
            extraction_stats=stats,
        )


class DefaultStrategy:
    """Default fallback strategy using SmartContextExtractor.

    Used when intent is UNKNOWN or confidence is low.
    Falls back to the existing full extraction pipeline.
    """

    def extract(
        self,
        intent: ClassifiedIntent,
        mubase: MUbase,
        config: ExtractionConfig,
    ) -> ContextResult:
        """Extract context using default smart extraction."""
        from mu.kernel.context.smart import SmartContextExtractor

        # Get intent value as string for stats
        intent_str = intent.intent.value if hasattr(intent.intent, "value") else str(intent.intent)

        stats: dict[str, Any] = {
            "strategy_used": "default",
            "intent": intent_str,
            "confidence": intent.confidence,
            "reason": "fallback to SmartContextExtractor",
        }

        # Build question from entities if available
        # This is a heuristic - in practice, the original question should be passed
        question = " ".join(intent.entities) if intent.entities else "code structure"

        extractor = SmartContextExtractor(mubase, config)
        result = extractor.extract(question)

        # Merge stats
        result.extraction_stats.update(stats)
        result.extraction_stats["strategy_used"] = "default"

        return result


# -----------------------------------------------------------------------------
# Strategy Registry
# -----------------------------------------------------------------------------


# Registry maps intent values (strings) to strategy instances
_STRATEGIES_BY_VALUE: dict[str, ExtractionStrategy] = {
    "locate": LocateStrategy(),
    "impact": ImpactStrategy(),
    "navigate": NavigateStrategy(),
    "list": ListStrategy(),
    "unknown": DefaultStrategy(),
}

# Also provide access via Intent enum for convenience
STRATEGIES: dict[Any, ExtractionStrategy] = {
    Intent.LOCATE: _STRATEGIES_BY_VALUE["locate"],
    Intent.IMPACT: _STRATEGIES_BY_VALUE["impact"],
    Intent.NAVIGATE: _STRATEGIES_BY_VALUE["navigate"],
    Intent.LIST: _STRATEGIES_BY_VALUE["list"],
    Intent.UNKNOWN: _STRATEGIES_BY_VALUE["unknown"],
}


def get_strategy(intent: Any) -> ExtractionStrategy:
    """Get the appropriate strategy for an intent.

    Args:
        intent: The intent (can be Intent enum, string, or ClassifiedIntent).

    Returns:
        The corresponding ExtractionStrategy, or DefaultStrategy if not found.
    """
    # Handle ClassifiedIntent objects
    if hasattr(intent, "intent"):
        intent = intent.intent

    # Handle Intent enum values
    if hasattr(intent, "value"):
        intent = intent.value

    # Now intent should be a string
    return _STRATEGIES_BY_VALUE.get(intent, _STRATEGIES_BY_VALUE["unknown"])


__all__ = [
    "ClassifiedIntent",
    "DefaultStrategy",
    "ExtractionStrategy",
    "ImpactStrategy",
    "Intent",
    "ListStrategy",
    "LocateStrategy",
    "NavigateStrategy",
    "STRATEGIES",
    "get_strategy",
]
