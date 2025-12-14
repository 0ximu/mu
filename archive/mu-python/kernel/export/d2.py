"""D2 diagram exporter.

Exports the graph as D2 diagram syntax for professional diagram generation.
D2 is a modern diagram scripting language (https://d2lang.com/).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from mu.kernel.export.base import ExportOptions, ExportResult
from mu.kernel.models import Edge, Node
from mu.kernel.schema import EdgeType, NodeType

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase


class D2Exporter:
    """Export graph as D2 diagram.

    Generates valid D2 syntax for rendering with the D2 compiler
    or in the D2 playground.
    """

    # Node shapes by type
    SHAPES = {
        NodeType.MODULE: "package",
        NodeType.CLASS: "class",
        NodeType.FUNCTION: "rectangle",
        NodeType.EXTERNAL: "cloud",
    }

    # Node icons/prefixes for labels
    ICONS = {
        NodeType.MODULE: "M",
        NodeType.CLASS: "C",
        NodeType.FUNCTION: "f",
        NodeType.EXTERNAL: "ext",
    }

    # Edge styles by type
    EDGE_STYLES = {
        EdgeType.INHERITS: "stroke-dash: 5",
        EdgeType.IMPORTS: "opacity: 0.6",
        EdgeType.CONTAINS: "",
    }

    # Default max nodes
    DEFAULT_MAX_NODES = 100

    @property
    def format_name(self) -> str:
        """Return the format name identifier."""
        return "d2"

    @property
    def file_extension(self) -> str:
        """Return the default file extension for this format."""
        return ".d2"

    @property
    def description(self) -> str:
        """Return a short description of this format."""
        return "D2 diagram language"

    def export(
        self,
        mubase: MUbase,
        options: ExportOptions | None = None,
    ) -> ExportResult:
        """Export graph to D2 diagram format.

        Args:
            mubase: The MUbase database to export from.
            options: Export options for filtering and customization.
                Extra options:
                - direction: 'right' (default), 'down', 'left', 'up'
                - include_styles: True/False (default: True)

        Returns:
            ExportResult with D2 syntax.
        """
        options = options or ExportOptions()

        # Get format-specific options
        direction = options.extra.get("direction", "right")
        include_styles = options.extra.get("include_styles", True)

        # Apply default max_nodes if not set
        if options.max_nodes is None:
            options.max_nodes = self.DEFAULT_MAX_NODES

        nodes = self._get_nodes(mubase, options)
        edges = self._get_edges(mubase, nodes, options) if options.include_edges else []

        if not nodes:
            return ExportResult(
                output="empty: No nodes to export",
                format=self.format_name,
                node_count=0,
                edge_count=0,
            )

        lines: list[str] = []

        # Direction setting
        lines.append(f"direction: {direction}")
        lines.append("")

        # Node definitions
        for node in nodes:
            lines.extend(self._export_node(node, include_styles))

        lines.append("")

        # Edge definitions
        for edge in edges:
            lines.append(self._export_edge(edge, include_styles))

        output = "\n".join(lines)

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

    def _export_node(self, node: Node, include_styles: bool) -> list[str]:
        """Export a single node.

        Args:
            node: The node to export.
            include_styles: Whether to include styling.

        Returns:
            List of D2 lines for this node.
        """
        lines: list[str] = []

        node_id = self._escape_id(node.id)
        label = self._node_label(node)

        # Node declaration with label
        lines.append(f"{node_id}: {label}")

        # Add styling if requested
        if include_styles:
            shape = self.SHAPES.get(node.type, "rectangle")
            lines.append(f"{node_id}.shape: {shape}")

            # Add tooltip with qualified name
            if node.qualified_name:
                lines.append(f"{node_id}.tooltip: {node.qualified_name}")

        return lines

    def _export_edge(self, edge: Edge, include_styles: bool) -> str:
        """Export a single edge.

        Args:
            edge: The edge to export.
            include_styles: Whether to include styling.

        Returns:
            D2 line for this edge.
        """
        source = self._escape_id(edge.source_id)
        target = self._escape_id(edge.target_id)
        label = edge.type.value

        edge_def = f"{source} -> {target}: {label}"

        # Add style if available
        if include_styles:
            style = self.EDGE_STYLES.get(edge.type, "")
            if style:
                edge_def += f" {{ style.{style} }}"

        return edge_def

    def _node_label(self, node: Node) -> str:
        """Create a node label with icon prefix.

        Args:
            node: The node.

        Returns:
            Label string.
        """
        icon = self.ICONS.get(node.type, "")
        name = self._escape_label(node.name)

        if icon:
            return f"{icon} {name}"
        return name

    def _escape_id(self, node_id: str) -> str:
        """Escape a node ID for D2.

        D2 IDs can contain most characters but some need quoting.

        Args:
            node_id: The original node ID.

        Returns:
            Escaped ID safe for D2.
        """
        # Replace characters that break D2 syntax
        escaped = re.sub(r"[^a-zA-Z0-9_]", "_", node_id)
        # Ensure it starts with a letter
        if escaped and escaped[0].isdigit():
            escaped = "n" + escaped
        return escaped

    def _escape_label(self, text: str) -> str:
        """Escape text for D2 labels.

        Args:
            text: The original text.

        Returns:
            Escaped text safe for D2.
        """
        # D2 labels are generally safe, but escape newlines and quotes
        text = text.replace("\n", " ")
        text = text.replace('"', "'")
        return text


__all__ = ["D2Exporter"]
