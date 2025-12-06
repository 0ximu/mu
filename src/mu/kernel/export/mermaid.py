"""Mermaid diagram exporter.

Exports the graph as Mermaid diagram syntax for visualization in markdown.
Supports flowchart and classDiagram diagram types.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from mu.kernel.export.base import ExportOptions, ExportResult
from mu.kernel.models import Edge, Node
from mu.kernel.schema import EdgeType, NodeType

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase


class MermaidExporter:
    """Export graph as Mermaid diagram.

    Generates valid Mermaid syntax for rendering in markdown viewers,
    GitHub, or the Mermaid Live Editor.
    """

    # Node shapes by type for flowchart
    SHAPES = {
        NodeType.MODULE: ("([", "])"),  # Stadium shape
        NodeType.CLASS: ("[", "]"),  # Rectangle
        NodeType.FUNCTION: ("(", ")"),  # Rounded
        NodeType.EXTERNAL: ("{{", "}}"),  # Hexagon
    }

    # Edge arrows by type
    ARROWS = {
        EdgeType.CONTAINS: "-->",
        EdgeType.IMPORTS: "-.->",
        EdgeType.INHERITS: "==>",
    }

    # Default max nodes to prevent oversized diagrams
    DEFAULT_MAX_NODES = 50

    @property
    def format_name(self) -> str:
        """Return the format name identifier."""
        return "mermaid"

    @property
    def file_extension(self) -> str:
        """Return the default file extension for this format."""
        return ".mmd"

    @property
    def description(self) -> str:
        """Return a short description of this format."""
        return "Mermaid diagram"

    def export(
        self,
        mubase: MUbase,
        options: ExportOptions | None = None,
    ) -> ExportResult:
        """Export graph to Mermaid diagram format.

        Args:
            mubase: The MUbase database to export from.
            options: Export options for filtering and customization.
                Extra options:
                - diagram_type: 'flowchart' (default) or 'classDiagram'
                - direction: 'TB' (top-bottom), 'LR' (left-right), etc.

        Returns:
            ExportResult with Mermaid syntax.
        """
        options = options or ExportOptions()

        # Get format-specific options
        diagram_type = options.extra.get("diagram_type", "flowchart")
        direction = options.extra.get("direction", "TB")

        # Apply default max_nodes if not set
        if options.max_nodes is None:
            options.max_nodes = self.DEFAULT_MAX_NODES

        nodes = self._get_nodes(mubase, options)
        edges = self._get_edges(mubase, nodes, options) if options.include_edges else []

        if not nodes:
            return ExportResult(
                output=f"flowchart {direction}\n    empty[No nodes to export]",
                format=self.format_name,
                node_count=0,
                edge_count=0,
            )

        # Generate diagram based on type
        if diagram_type == "classDiagram":
            output = self._export_class_diagram(nodes, edges)
        else:
            output = self._export_flowchart(nodes, edges, direction)

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

    def _export_flowchart(
        self,
        nodes: list[Node],
        edges: list[Edge],
        direction: str,
    ) -> str:
        """Export as Mermaid flowchart.

        Args:
            nodes: Nodes to include.
            edges: Edges to include.
            direction: Layout direction (TB, LR, etc.).

        Returns:
            Mermaid flowchart syntax.
        """
        lines = [f"flowchart {direction}"]

        # Node definitions
        for node in nodes:
            node_id = self._escape_id(node.id)
            label = self._escape_label(node.name)
            left, right = self.SHAPES.get(node.type, ("[", "]"))
            lines.append(f"    {node_id}{left}{label}{right}")

        lines.append("")

        # Edge definitions
        for edge in edges:
            source = self._escape_id(edge.source_id)
            target = self._escape_id(edge.target_id)
            arrow = self.ARROWS.get(edge.type, "-->")

            # Add edge label for non-CONTAINS edges
            if edge.type != EdgeType.CONTAINS:
                label = edge.type.value
                lines.append(f"    {source} {arrow}|{label}| {target}")
            else:
                lines.append(f"    {source} {arrow} {target}")

        return "\n".join(lines)

    def _export_class_diagram(
        self,
        nodes: list[Node],
        edges: list[Edge],
    ) -> str:
        """Export as Mermaid class diagram.

        Args:
            nodes: Nodes to include.
            edges: Edges to include.

        Returns:
            Mermaid classDiagram syntax.
        """
        lines = ["classDiagram"]

        # Group nodes by type
        classes = [n for n in nodes if n.type == NodeType.CLASS]
        functions = [n for n in nodes if n.type == NodeType.FUNCTION]

        # Build class -> methods mapping
        methods_by_class: dict[str, list[Node]] = {}
        for func in functions:
            if func.properties.get("is_method"):
                class_id = func.properties.get("parent_class", "")
                if class_id:
                    if class_id not in methods_by_class:
                        methods_by_class[class_id] = []
                    methods_by_class[class_id].append(func)

        # Class definitions
        for cls in classes:
            class_name = self._escape_class_name(cls.name)
            lines.append(f"    class {class_name} {{")

            # Attributes
            attrs = cls.properties.get("attributes", [])
            for attr in attrs[:10]:  # Limit attributes
                lines.append(f"        +{attr}")

            # Methods
            methods = methods_by_class.get(cls.id, [])
            for method in methods[:10]:  # Limit methods
                params = self._format_method_params(method)
                return_type = method.properties.get("return_type", "")
                visibility = "+" if not method.name.startswith("_") else "-"
                if return_type:
                    lines.append(f"        {visibility}{method.name}({params}) {return_type}")
                else:
                    lines.append(f"        {visibility}{method.name}({params})")

            lines.append("    }")

        lines.append("")

        # Inheritance edges
        for edge in edges:
            if edge.type == EdgeType.INHERITS:
                parent = self._find_node_name(edge.target_id, nodes)
                child = self._find_node_name(edge.source_id, nodes)
                if parent and child:
                    lines.append(
                        f"    {self._escape_class_name(parent)} <|-- {self._escape_class_name(child)}"
                    )

        return "\n".join(lines)

    def _escape_id(self, node_id: str) -> str:
        """Escape a node ID for Mermaid.

        Mermaid IDs must be alphanumeric with underscores.

        Args:
            node_id: The original node ID.

        Returns:
            Escaped ID safe for Mermaid.
        """
        # Replace special characters
        escaped = re.sub(r"[^a-zA-Z0-9_]", "_", node_id)
        # Ensure it starts with a letter
        if escaped and escaped[0].isdigit():
            escaped = "n" + escaped
        return escaped

    def _escape_label(self, text: str) -> str:
        """Escape text for Mermaid labels.

        Args:
            text: The original text.

        Returns:
            Escaped text safe for Mermaid labels.
        """
        # Replace quotes and brackets that could break Mermaid syntax
        text = text.replace('"', "'")
        text = text.replace("[", "(")
        text = text.replace("]", ")")
        text = text.replace("{", "(")
        text = text.replace("}", ")")
        text = text.replace("<", "(")
        text = text.replace(">", ")")
        return text

    def _escape_class_name(self, name: str) -> str:
        """Escape a class name for Mermaid classDiagram.

        Args:
            name: The class name.

        Returns:
            Escaped class name.
        """
        # Remove special characters, keep alphanumeric and underscore
        return re.sub(r"[^a-zA-Z0-9_]", "_", name)

    def _format_method_params(self, method: Node) -> str:
        """Format method parameters for class diagram.

        Args:
            method: The method node.

        Returns:
            Parameter string.
        """
        params = method.properties.get("parameters", [])
        param_strs = []
        for p in params[:5]:  # Limit params displayed
            if isinstance(p, dict):
                name = p.get("name", "?")
                ptype = p.get("type_annotation", "")
                if ptype:
                    param_strs.append(f"{name}: {ptype}")
                else:
                    param_strs.append(name)
            else:
                param_strs.append(str(p))
        return ", ".join(param_strs)

    def _find_node_name(self, node_id: str, nodes: list[Node]) -> str | None:
        """Find node name by ID.

        Args:
            node_id: The node ID to find.
            nodes: List of nodes to search.

        Returns:
            Node name if found, None otherwise.
        """
        for node in nodes:
            if node.id == node_id:
                return node.name
        return None


__all__ = ["MermaidExporter"]
