"""MU format export for context extraction.

Generates MU format output from selected nodes, grouping by module
and preserving structural relationships.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from mu.kernel.context.models import ContextResult, ExportConfig, ScoredNode
from mu.kernel.schema import EdgeType, NodeType

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase


class ContextExporter:
    """Export selected context nodes as MU format.

    Groups nodes by module path and generates coherent MU output
    preserving the hierarchical structure (modules -> classes -> methods).
    """

    # MU Sigils (matching MUGenerator)
    SIGIL_MODULE = "!"
    SIGIL_ENTITY = "$"
    SIGIL_FUNCTION = "#"
    SIGIL_METADATA = "@"
    SIGIL_ANNOTATION = "::"

    # Operators
    OP_FLOW = "->"
    OP_MUTATION = "=>"

    def __init__(
        self,
        mubase: MUbase,
        include_scores: bool = False,
        export_config: ExportConfig | None = None,
    ) -> None:
        """Initialize the context exporter.

        Args:
            mubase: MUbase for looking up additional context.
            include_scores: Whether to include relevance score annotations.
            export_config: Configuration for export enrichment (docstrings, line numbers, etc.).
        """
        self.mubase = mubase
        self.include_scores = include_scores
        self.export_config = export_config or ExportConfig()
        # Get root_path for converting absolute paths to relative
        stats = mubase.stats()
        self._root_path = stats.get("root_path", "")

    def export_mu(self, scored_nodes: list[ScoredNode]) -> str:
        """Export scored nodes as MU format.

        Args:
            scored_nodes: Nodes with scores to export.

        Returns:
            MU format string.
        """
        if not scored_nodes:
            return f"{self.SIGIL_ANNOTATION} No relevant context found"

        lines: list[str] = []

        # Header
        lines.append(f"{self.SIGIL_FUNCTION} Context Extract")
        lines.append(f"{self.SIGIL_FUNCTION} nodes: {len(scored_nodes)}")
        lines.append("")

        # Group nodes by module
        by_module = self._group_by_module(scored_nodes)

        # Generate output for each module
        for module_path, module_nodes in sorted(by_module.items()):
            lines.extend(self._export_module_context(module_path, module_nodes))
            lines.append("")

        return "\n".join(lines).rstrip()

    def export_json(self, result: ContextResult) -> str:
        """Export context result as JSON.

        Args:
            result: The full context result.

        Returns:
            JSON string.
        """
        data: dict[str, Any] = {
            "node_count": len(result.nodes),
            "token_count": result.token_count,
            "nodes": [
                {
                    "id": n.id,
                    "type": n.type.value,
                    "name": n.name,
                    "qualified_name": n.qualified_name,
                    "file_path": n.file_path,
                    "score": round(result.relevance_scores.get(n.id, 0), 4),
                }
                for n in result.nodes
            ],
            "extraction_stats": result.extraction_stats,
            "mu_text": result.mu_text,
        }

        return json.dumps(data, indent=2)

    def _group_by_module(
        self,
        scored_nodes: list[ScoredNode],
    ) -> dict[str, list[ScoredNode]]:
        """Group nodes by their module path.

        Args:
            scored_nodes: Nodes to group.

        Returns:
            Dictionary mapping module path to nodes in that module.
        """
        by_module: dict[str, list[ScoredNode]] = defaultdict(list)

        for scored_node in scored_nodes:
            node = scored_node.node
            module_path = node.file_path or "unknown"

            # For module nodes, use their path directly
            if node.type == NodeType.MODULE:
                module_path = node.file_path or node.id

            by_module[module_path].append(scored_node)

        return dict(by_module)

    def _export_module_context(
        self,
        module_path: str,
        scored_nodes: list[ScoredNode],
    ) -> list[str]:
        """Export context for a single module.

        Args:
            module_path: Path to the module.
            scored_nodes: Nodes in this module.

        Returns:
            Lines of MU output for this module.
        """
        lines: list[str] = []

        # Module header
        module_name = self._path_to_module_name(module_path)
        lines.append(f"{self.SIGIL_MODULE}module {module_name}")

        # Internal imports section
        internal_imports = self._get_internal_imports(module_path)
        if internal_imports:
            imports_str = ", ".join(internal_imports)
            lines.append(f"{self.SIGIL_METADATA}imports [{imports_str}]")

        # Separate nodes by type
        classes: dict[str, ScoredNode] = {}
        functions: list[ScoredNode] = []
        methods_by_class: dict[str, list[ScoredNode]] = defaultdict(list)

        for scored_node in scored_nodes:
            node = scored_node.node

            if node.type == NodeType.MODULE:
                # Skip module nodes themselves, we use them for grouping
                continue
            elif node.type == NodeType.CLASS:
                classes[node.name] = scored_node
            elif node.type == NodeType.FUNCTION:
                props = node.properties or {}
                if props.get("is_method"):
                    # Find the class this method belongs to
                    class_name = self._get_method_class_name(node)
                    methods_by_class[class_name].append(scored_node)
                else:
                    functions.append(scored_node)

        # Export classes with their methods
        for class_name, class_scored in sorted(classes.items()):
            lines.append("")
            lines.extend(
                self._export_class(
                    class_scored,
                    methods_by_class.get(class_name, []),
                )
            )

        # Export orphan methods (class not selected)
        for class_name, methods in sorted(methods_by_class.items()):
            if class_name not in classes:
                lines.append("")
                lines.append(f"{self.SIGIL_ENTITY}{class_name}")
                lines.append(f"  {self.SIGIL_ANNOTATION} (partial - selected methods only)")
                for method_scored in sorted(methods, key=lambda m: m.node.name):
                    lines.append(self._export_function(method_scored, indent=2))

        # Export top-level functions
        if functions:
            lines.append("")
            for func_scored in sorted(functions, key=lambda f: f.node.name):
                lines.append(self._export_function(func_scored, indent=0))

        return lines

    def _export_class(
        self,
        class_scored: ScoredNode,
        method_nodes: list[ScoredNode],
    ) -> list[str]:
        """Export a class with its methods.

        Args:
            class_scored: The class node with score.
            method_nodes: Methods to include.

        Returns:
            Lines of MU output for this class.
        """
        lines: list[str] = []
        node = class_scored.node
        props = node.properties or {}

        # Class declaration
        parts = [self.SIGIL_ENTITY]

        # Decorators
        decorators = props.get("decorators", [])
        visible_decorators = [
            d for d in decorators if d not in ("public", "private", "protected", "internal")
        ]
        if visible_decorators:
            parts.append(f"{self.SIGIL_METADATA}{', '.join(visible_decorators)} ")

        parts.append(node.name)

        # Inheritance
        bases = props.get("bases", [])
        if bases:
            parts.append(f" < {', '.join(bases)}")

        # Line numbers
        if (
            self.export_config.include_line_numbers
            and props.get("line_start")
            and props.get("line_end")
        ):
            parts.append(f":L{props['line_start']}-{props['line_end']}")

        lines.append("".join(parts))

        # Docstring
        docstring = self._get_docstring(node)
        if docstring:
            lines.append(f'  """{docstring}"""')

        # Score annotation
        if self.include_scores:
            lines.append(f"  {self.SIGIL_ANNOTATION} relevance={class_scored.score:.2f}")

        # Attributes
        attrs = props.get("attributes", [])
        if attrs:
            max_attrs = self.export_config.max_attributes
            attrs_str = ", ".join(attrs[:max_attrs])
            if len(attrs) > max_attrs:
                attrs_str += f" (+{len(attrs) - max_attrs} more)"
            lines.append(f"  {self.SIGIL_METADATA}attrs [{attrs_str}]")

        # Methods
        for method_scored in sorted(method_nodes, key=lambda m: m.node.name):
            lines.append(self._export_function(method_scored, indent=2))

        return lines

    def _export_function(
        self,
        func_scored: ScoredNode,
        indent: int = 0,
    ) -> str:
        """Export a function or method.

        Args:
            func_scored: The function node with score.
            indent: Indentation level.

        Returns:
            Single line MU output (or multiple lines if docstring included).
        """
        node = func_scored.node
        props = node.properties or {}
        prefix = " " * indent

        parts = [prefix, self.SIGIL_FUNCTION]

        # Modifiers
        if props.get("is_async"):
            parts.append("async ")
        if props.get("is_static"):
            parts.append("static ")
        if props.get("is_classmethod"):
            parts.append("classmethod ")

        # Name
        parts.append(node.name)

        # Parameters
        params = props.get("parameters", [])
        if params:
            # Format parameters
            param_strs = []
            for p in params:
                if isinstance(p, dict):
                    name = p.get("name", "?")
                    ptype = p.get("type_annotation", "")
                    if ptype:
                        param_strs.append(f"{name}: {ptype}")
                    else:
                        param_strs.append(name)
                else:
                    param_strs.append(str(p))
            parts.append(f"({', '.join(param_strs)})")
        else:
            parts.append("()")

        # Return type
        return_type = props.get("return_type")
        if return_type:
            parts.append(f" {self.OP_FLOW} {return_type}")

        # Line numbers
        if (
            self.export_config.include_line_numbers
            and props.get("line_start")
            and props.get("line_end")
        ):
            parts.append(f":L{props['line_start']}-{props['line_end']}")

        # Complexity annotation
        complexity = node.complexity
        if complexity >= self.export_config.min_complexity_to_show:
            parts.append(f" {self.SIGIL_ANNOTATION} complexity:{complexity}")

        # Score annotation
        if self.include_scores:
            parts.append(f" {self.SIGIL_ANNOTATION} relevance={func_scored.score:.2f}")

        result = "".join(parts)

        # Add docstring on next line if available
        docstring = self._get_docstring(node)
        if docstring:
            result += f'\n{prefix}  """{docstring}"""'

        return result

    def _path_to_module_name(self, path: str) -> str:
        """Convert a file path to module name.

        Args:
            path: File path (absolute or relative).

        Returns:
            Module name (e.g., "mu/parser/models.py" or "mu.parser.models").
        """
        name = path

        # Strip root_path prefix if absolute path
        if self._root_path and name.startswith(self._root_path):
            name = name[len(self._root_path) :]
            # Remove leading slash
            if name.startswith("/") or name.startswith("\\"):
                name = name[1:]

        # Return as relative path (cleaner for display)
        # Just remove leading src/ etc for common project layouts
        for prefix in ("src/", "lib/", "app/"):
            if name.startswith(prefix):
                name = name[len(prefix) :]
                break

        return name

    def _get_method_class_name(self, node: Any) -> str:
        """Get the class name for a method node.

        Args:
            node: The method node.

        Returns:
            Class name or "Unknown".
        """
        # Try to extract from qualified name
        if node.qualified_name:
            parts = node.qualified_name.split(".")
            if len(parts) >= 2:
                return str(parts[-2])

        # Try to get from parent
        parent = self.mubase.get_parent(node.id)
        if parent and parent.type == NodeType.CLASS:
            return parent.name

        return "Unknown"

    def _get_docstring(self, node: Any) -> str | None:
        """Extract and format docstring from node properties.

        Args:
            node: The node to extract docstring from.

        Returns:
            Formatted docstring or None if not present.
        """
        if not self.export_config.include_docstrings:
            return None

        props = node.properties if hasattr(node, "properties") else {}
        docstring = props.get("docstring")
        if not docstring or not isinstance(docstring, str):
            return None

        lines = docstring.strip().split("\n")

        if (
            self.export_config.truncate_docstring
            and len(lines) > self.export_config.max_docstring_lines
        ):
            lines = lines[: self.export_config.max_docstring_lines]
            lines.append("...")

        if len(lines) == 1:
            return str(lines[0])

        # Return summary line for multi-line docstrings
        return str(lines[0])

    def _get_internal_imports(self, module_path: str) -> list[str]:
        """Get internal module imports (IMPORTS edges) for a module.

        Args:
            module_path: Path to the module.

        Returns:
            List of imported module names.
        """
        if not self.export_config.include_internal_imports:
            return []

        # Query IMPORTS edges from this module
        module_id = f"mod:{module_path}"
        try:
            # Get edges where this module is the source
            edges = self.mubase.get_edges(source_id=module_id, edge_type=EdgeType.IMPORTS)

            # Extract target module names
            imports = []
            for edge in edges:
                target_node = self.mubase.get_node(edge.target_id)
                if target_node and target_node.type == NodeType.MODULE:
                    # Convert path to module name
                    import_name = self._path_to_module_name(
                        target_node.file_path or target_node.name
                    )
                    imports.append(import_name)

            return sorted(imports)
        except Exception:
            # If query fails, return empty list
            return []


__all__ = ["ContextExporter"]
