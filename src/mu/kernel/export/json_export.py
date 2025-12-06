"""JSON format exporter.

Exports the graph as structured JSON for tool integration.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from mu.kernel.export.base import ExportOptions, ExportResult
from mu.kernel.models import Edge, Node

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase


class JSONExporter:
    """Export graph as JSON.

    Produces structured JSON output including nodes, edges, and metadata.
    Suitable for integration with other tools and data processing.
    """

    @property
    def format_name(self) -> str:
        """Return the format name identifier."""
        return "json"

    @property
    def file_extension(self) -> str:
        """Return the default file extension for this format."""
        return ".json"

    @property
    def description(self) -> str:
        """Return a short description of this format."""
        return "Structured JSON"

    def export(
        self,
        mubase: MUbase,
        options: ExportOptions | None = None,
    ) -> ExportResult:
        """Export graph to JSON format.

        Args:
            mubase: The MUbase database to export from.
            options: Export options for filtering and customization.

        Returns:
            ExportResult with JSON output.
        """
        options = options or ExportOptions()
        pretty = options.extra.get("pretty", True)

        nodes = self._get_nodes(mubase, options)
        edges = self._get_edges(mubase, nodes, options) if options.include_edges else []

        # Get database stats
        db_stats = mubase.stats()

        data: dict[str, Any] = {
            "version": "1.0",
            "format": "mubase-json",
            "generated_at": datetime.now(UTC).isoformat(),
            "stats": {
                "node_count": len(nodes),
                "edge_count": len(edges),
                "nodes_by_type": self._count_by_type(nodes),
                "edges_by_type": self._count_edges_by_type(edges),
            },
            "database": {
                "path": str(mubase.path),
                "version": db_stats.get("version", "unknown"),
                "built_at": db_stats.get("built_at"),
                "root_path": db_stats.get("root_path"),
            },
            "nodes": [self._node_to_dict(n) for n in nodes],
            "edges": [self._edge_to_dict(e) for e in edges],
        }

        indent = 2 if pretty else None
        output = json.dumps(data, indent=indent, default=str)

        return ExportResult(
            output=output,
            format=self.format_name,
            node_count=len(nodes),
            edge_count=len(edges),
        )

    def _get_nodes(
        self,
        mubase: MUbase,
        options: ExportOptions,
    ) -> list[Node]:
        """Get nodes based on filter options.

        Args:
            mubase: The MUbase database.
            options: Export options with filters.

        Returns:
            List of filtered nodes.
        """
        # If specific node IDs requested
        if options.node_ids:
            nodes = []
            for node_id in options.node_ids:
                node = mubase.get_node(node_id)
                if node:
                    nodes.append(node)
            return nodes

        # Get all nodes of requested types
        if options.node_types:
            nodes = []
            for node_type in options.node_types:
                nodes.extend(mubase.get_nodes(node_type))
        else:
            nodes = mubase.get_nodes()

        # Apply max_nodes limit
        if options.max_nodes and len(nodes) > options.max_nodes:
            nodes = nodes[: options.max_nodes]

        return nodes

    def _get_edges(
        self,
        mubase: MUbase,
        nodes: list[Node],
        options: ExportOptions,
    ) -> list[Edge]:
        """Get edges relevant to the selected nodes.

        Args:
            mubase: The MUbase database.
            nodes: The selected nodes.
            options: Export options.

        Returns:
            List of relevant edges.
        """
        node_ids = {n.id for n in nodes}
        all_edges = mubase.get_edges()

        # Only include edges where both source and target are in our node set
        return [e for e in all_edges if e.source_id in node_ids and e.target_id in node_ids]

    def _node_to_dict(self, node: Node) -> dict[str, Any]:
        """Convert node to dictionary, using its to_dict method.

        Args:
            node: The node to convert.

        Returns:
            Dictionary representation.
        """
        return node.to_dict()

    def _edge_to_dict(self, edge: Edge) -> dict[str, Any]:
        """Convert edge to dictionary, using its to_dict method.

        Args:
            edge: The edge to convert.

        Returns:
            Dictionary representation.
        """
        return edge.to_dict()

    def _count_by_type(self, nodes: list[Node]) -> dict[str, int]:
        """Count nodes by type.

        Args:
            nodes: List of nodes.

        Returns:
            Dictionary of type -> count.
        """
        counts: dict[str, int] = {}
        for node in nodes:
            type_name = node.type.value
            counts[type_name] = counts.get(type_name, 0) + 1
        return counts

    def _count_edges_by_type(self, edges: list[Edge]) -> dict[str, int]:
        """Count edges by type.

        Args:
            edges: List of edges.

        Returns:
            Dictionary of type -> count.
        """
        counts: dict[str, int] = {}
        for edge in edges:
            type_name = edge.type.value
            counts[type_name] = counts.get(type_name, 0) + 1
        return counts


__all__ = ["JSONExporter"]
