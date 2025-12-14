"""Cytoscape.js JSON exporter.

Exports the graph as Cytoscape.js compatible JSON for interactive visualization.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from mu.kernel.export.base import ExportOptions, ExportResult
from mu.kernel.models import Edge, Node
from mu.kernel.schema import NodeType

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase


class CytoscapeExporter:
    """Export graph as Cytoscape.js JSON.

    Generates JSON compatible with Cytoscape.js for interactive
    graph visualization in web applications.
    """

    # Default colors by node type
    NODE_COLORS = {
        NodeType.MODULE: "#4A90D9",  # Blue
        NodeType.CLASS: "#7B68EE",  # Purple
        NodeType.FUNCTION: "#3CB371",  # Green
        NodeType.EXTERNAL: "#FFB347",  # Orange
    }

    @property
    def format_name(self) -> str:
        """Return the format name identifier."""
        return "cytoscape"

    @property
    def file_extension(self) -> str:
        """Return the default file extension for this format."""
        return ".cyjs"

    @property
    def description(self) -> str:
        """Return a short description of this format."""
        return "Cytoscape.js JSON"

    def export(
        self,
        mubase: MUbase,
        options: ExportOptions | None = None,
    ) -> ExportResult:
        """Export graph to Cytoscape.js JSON format.

        Args:
            mubase: The MUbase database to export from.
            options: Export options for filtering and customization.
                Extra options:
                - include_styles: True/False (default: True)
                - include_layout: True/False (default: True)

        Returns:
            ExportResult with Cytoscape.js JSON.
        """
        options = options or ExportOptions()

        # Get format-specific options
        include_styles = options.extra.get("include_styles", True)
        include_layout = options.extra.get("include_layout", True)

        nodes = self._get_nodes(mubase, options)
        edges = self._get_edges(mubase, nodes, options) if options.include_edges else []

        # Build Cytoscape.js data structure
        data: dict[str, Any] = {
            "elements": {
                "nodes": [self._node_element(n) for n in nodes],
                "edges": [self._edge_element(e, i) for i, e in enumerate(edges)],
            },
        }

        if include_styles:
            data["style"] = self._default_styles()

        if include_layout:
            data["layout"] = self._default_layout()

        output = json.dumps(data, indent=2)

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

    def _node_element(self, node: Node) -> dict[str, Any]:
        """Convert a node to Cytoscape.js element format.

        Args:
            node: The node to convert.

        Returns:
            Cytoscape.js node element.
        """
        # Build data object with all relevant properties
        data: dict[str, Any] = {
            "id": node.id,
            "label": node.name,
            "type": node.type.value,
            "complexity": node.complexity or 0,
        }

        # Add optional properties
        if node.qualified_name:
            data["qualified_name"] = node.qualified_name
        if node.file_path:
            data["file_path"] = node.file_path
        if node.line_start:
            data["line_start"] = node.line_start
        if node.line_end:
            data["line_end"] = node.line_end

        # Add select properties from node.properties (avoid large fields)
        safe_props = ["bases", "decorators", "is_async", "is_static", "return_type"]
        for prop in safe_props:
            if prop in node.properties:
                data[prop] = node.properties[prop]

        return {"data": data}

    def _edge_element(self, edge: Edge, index: int) -> dict[str, Any]:
        """Convert an edge to Cytoscape.js element format.

        Args:
            edge: The edge to convert.
            index: Edge index for generating unique IDs if needed.

        Returns:
            Cytoscape.js edge element.
        """
        return {
            "data": {
                "id": edge.id or f"e{index}",
                "source": edge.source_id,
                "target": edge.target_id,
                "type": edge.type.value,
            }
        }

    def _default_styles(self) -> list[dict[str, Any]]:
        """Generate default Cytoscape.js styles.

        Returns:
            List of style objects for Cytoscape.js.
        """
        return [
            # Base node style
            {
                "selector": "node",
                "style": {
                    "label": "data(label)",
                    "background-color": "#666",
                    "text-valign": "center",
                    "text-halign": "center",
                    "font-size": "10px",
                    "width": "label",
                    "height": "label",
                    "padding": "10px",
                    "shape": "round-rectangle",
                },
            },
            # Module nodes
            {
                "selector": "node[type='module']",
                "style": {
                    "background-color": self.NODE_COLORS[NodeType.MODULE],
                    "shape": "rectangle",
                },
            },
            # Class nodes
            {
                "selector": "node[type='class']",
                "style": {
                    "background-color": self.NODE_COLORS[NodeType.CLASS],
                    "shape": "round-rectangle",
                },
            },
            # Function nodes
            {
                "selector": "node[type='function']",
                "style": {
                    "background-color": self.NODE_COLORS[NodeType.FUNCTION],
                    "shape": "ellipse",
                },
            },
            # External nodes
            {
                "selector": "node[type='external']",
                "style": {
                    "background-color": self.NODE_COLORS[NodeType.EXTERNAL],
                    "shape": "diamond",
                },
            },
            # High complexity nodes (red tint)
            {
                "selector": "node[complexity >= 30]",
                "style": {
                    "border-width": "3px",
                    "border-color": "#FF6B6B",
                },
            },
            # Base edge style
            {
                "selector": "edge",
                "style": {
                    "width": 2,
                    "line-color": "#999",
                    "target-arrow-color": "#999",
                    "target-arrow-shape": "triangle",
                    "curve-style": "bezier",
                    "label": "data(type)",
                    "font-size": "8px",
                    "text-rotation": "autorotate",
                },
            },
            # Contains edges (structural)
            {
                "selector": "edge[type='contains']",
                "style": {
                    "line-color": "#AAA",
                    "target-arrow-color": "#AAA",
                    "line-style": "solid",
                },
            },
            # Imports edges
            {
                "selector": "edge[type='imports']",
                "style": {
                    "line-color": "#4A90D9",
                    "target-arrow-color": "#4A90D9",
                    "line-style": "dashed",
                },
            },
            # Inherits edges
            {
                "selector": "edge[type='inherits']",
                "style": {
                    "line-color": "#7B68EE",
                    "target-arrow-color": "#7B68EE",
                    "target-arrow-shape": "triangle-backcurve",
                    "line-style": "solid",
                    "width": 3,
                },
            },
        ]

    def _default_layout(self) -> dict[str, Any]:
        """Generate default layout configuration.

        Returns:
            Layout configuration for Cytoscape.js.
        """
        return {
            "name": "cose",
            "animate": False,
            "nodeDimensionsIncludeLabels": True,
            "nodeRepulsion": 8000,
            "idealEdgeLength": 100,
            "edgeElasticity": 100,
            "nestingFactor": 5,
            "gravity": 80,
            "numIter": 1000,
            "initialTemp": 200,
            "coolingFactor": 0.95,
            "minTemp": 1.0,
        }


__all__ = ["CytoscapeExporter"]
