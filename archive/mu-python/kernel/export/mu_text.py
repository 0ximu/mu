"""MU Text format exporter.

Exports the graph as MU format optimized for LLM consumption.
Uses sigils: ! (module), $ (class), # (function), @ (metadata), :: (annotation).
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from mu.kernel.context.models import ExportConfig
from mu.kernel.export.base import ExportOptions, ExportResult
from mu.kernel.models import Edge, Node
from mu.kernel.schema import EdgeType, NodeType

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase


class MUTextExporter:
    """Export graph as MU text format.

    Produces a token-efficient representation optimized for LLM comprehension.
    Output is grouped by module and uses MU sigil syntax.
    """

    # MU Sigils
    SIGIL_MODULE = "!"
    SIGIL_ENTITY = "$"
    SIGIL_FUNCTION = "#"
    SIGIL_METADATA = "@"
    SIGIL_ANNOTATION = "::"

    # Operators
    OP_FLOW = "->"
    OP_MUTATION = "=>"

    def __init__(self, export_config: ExportConfig | None = None) -> None:
        """Initialize MU text exporter.

        Args:
            export_config: Configuration for export enrichment.
        """
        self.export_config = export_config or ExportConfig()

    @property
    def format_name(self) -> str:
        """Return the format name identifier."""
        return "mu"

    @property
    def file_extension(self) -> str:
        """Return the default file extension for this format."""
        return ".mu"

    @property
    def description(self) -> str:
        """Return a short description of this format."""
        return "MU text format (LLM optimized)"

    def export(
        self,
        mubase: MUbase,
        options: ExportOptions | None = None,
    ) -> ExportResult:
        """Export graph to MU text format.

        Args:
            mubase: The MUbase database to export from.
            options: Export options for filtering and customization.

        Returns:
            ExportResult with MU format output.
        """
        options = options or ExportOptions()
        nodes = self._get_nodes(mubase, options)
        edges = self._get_edges(mubase, nodes, options) if options.include_edges else []

        if not nodes:
            return ExportResult(
                output=f"{self.SIGIL_ANNOTATION} No nodes to export",
                format=self.format_name,
                node_count=0,
                edge_count=0,
            )

        # Group by module
        by_module = self._group_by_module(nodes)

        lines: list[str] = []
        for module_path, module_nodes in sorted(by_module.items()):
            lines.extend(self._export_module(module_path, module_nodes, mubase))
            lines.append("")  # Blank line between modules

        output = "\n".join(lines).rstrip()

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

    def _group_by_module(self, nodes: list[Node]) -> dict[str, list[Node]]:
        """Group nodes by their module/file path.

        Args:
            nodes: List of nodes to group.

        Returns:
            Dictionary mapping module path to nodes.
        """
        by_module: dict[str, list[Node]] = defaultdict(list)

        for node in nodes:
            module_path = node.file_path or "unknown"

            # For module nodes, use their path directly
            if node.type == NodeType.MODULE:
                module_path = node.file_path or node.id

            by_module[module_path].append(node)

        return dict(by_module)

    def _export_module(
        self,
        path: str,
        nodes: list[Node],
        mubase: MUbase,
    ) -> list[str]:
        """Export a single module with its contents.

        Args:
            path: The module file path.
            nodes: Nodes in this module.
            mubase: The database for additional lookups.

        Returns:
            Lines of MU output for this module.
        """
        lines: list[str] = []

        # Module header
        module_name = self._path_to_module_name(path)
        lines.append(f"{self.SIGIL_MODULE}module {module_name}")

        # Language tag (optional, useful for multi-language codebases)
        if self.export_config.include_language:
            # Infer language from file extension
            lang = self._infer_language(path)
            if lang:
                lines.append(f"  {self.SIGIL_METADATA}lang {lang}")

        # Internal imports (IMPORTS edges)
        if self.export_config.include_internal_imports:
            internal_imports = self._get_internal_imports(path, mubase)
            if internal_imports:
                lines.append(f"  {self.SIGIL_METADATA}imports [{', '.join(internal_imports)}]")

        # Separate nodes by type
        classes: dict[str, Node] = {}
        functions: list[Node] = []
        methods_by_class: dict[str, list[Node]] = defaultdict(list)

        for node in nodes:
            if node.type == NodeType.MODULE:
                continue  # Skip module nodes, used for grouping
            elif node.type == NodeType.CLASS:
                classes[node.name] = node
            elif node.type == NodeType.FUNCTION:
                # Check if this is a method (has parent class)
                if node.properties.get("is_method"):
                    class_name = self._get_method_class_name(node, mubase)
                    methods_by_class[class_name].append(node)
                else:
                    functions.append(node)

        # Export classes with their methods
        for class_name, cls_node in sorted(classes.items()):
            lines.append("")
            lines.extend(self._export_class(cls_node, methods_by_class.get(class_name, [])))

        # Export orphan methods (class not selected)
        for class_name, methods in sorted(methods_by_class.items()):
            if class_name not in classes:
                lines.append("")
                lines.append(f"  {self.SIGIL_ENTITY}{class_name}")
                lines.append(f"    {self.SIGIL_ANNOTATION} (partial - selected methods only)")
                for method in sorted(methods, key=lambda m: m.name):
                    func_output = self._export_function(method, indent=4)
                    # Handle multi-line output (for docstrings)
                    if "\n" in func_output:
                        lines.extend(func_output.split("\n"))
                    else:
                        lines.append(func_output)

        # Export top-level functions
        if functions:
            lines.append("")
            for func in sorted(functions, key=lambda f: f.name):
                func_output = self._export_function(func, indent=2)
                # Handle multi-line output (for docstrings)
                if "\n" in func_output:
                    lines.extend(func_output.split("\n"))
                else:
                    lines.append(func_output)

        # Export external dependencies
        externals = [n for n in nodes if n.type == NodeType.EXTERNAL]
        if externals:
            lines.append("")
            ext_names = sorted(n.name for n in externals)
            lines.append(f"  {self.SIGIL_METADATA}ext [{', '.join(ext_names)}]")

        return lines

    def _export_class(
        self,
        cls: Node,
        methods: list[Node],
    ) -> list[str]:
        """Export a class with its methods.

        Args:
            cls: The class node.
            methods: Method nodes belonging to this class.

        Returns:
            Lines of MU output for this class.
        """
        lines: list[str] = []
        props = cls.properties

        # Class declaration
        parts = [f"  {self.SIGIL_ENTITY}"]

        # Decorators (filter visibility modifiers)
        decorators = props.get("decorators", [])
        visible_decorators = [
            d for d in decorators if d not in ("public", "private", "protected", "internal")
        ]
        if visible_decorators:
            parts.append(f"{self.SIGIL_METADATA}{', '.join(visible_decorators)} ")

        parts.append(cls.name)

        # Inheritance
        bases = props.get("bases", [])
        if bases:
            parts.append(f" < {', '.join(bases)}")

        # Line numbers (optional, useful for IDE integration)
        if self.export_config.include_line_numbers and cls.line_start:
            end_line = cls.line_end or cls.line_start
            parts.append(f" :L{cls.line_start}-{end_line}")

        lines.append("".join(parts))

        # Docstring (on next line after class declaration)
        if self.export_config.include_docstrings:
            docstring = self._get_docstring(cls)
            if docstring:
                lines.append(f'    "{docstring}"')

        # Complexity annotation
        if cls.complexity and cls.complexity >= 30:
            lines.append(f"    {self.SIGIL_ANNOTATION}complexity={cls.complexity}")

        # Attributes
        attrs = props.get("attributes", [])
        if attrs:
            max_attrs = self.export_config.max_attributes
            attrs_str = ", ".join(attrs[:max_attrs])
            if len(attrs) > max_attrs:
                attrs_str += f" (+{len(attrs) - max_attrs} more)"
            lines.append(f"    {self.SIGIL_METADATA}attrs [{attrs_str}]")

        # Methods
        for method in sorted(methods, key=lambda m: m.name):
            func_output = self._export_function(method, indent=4)
            # Handle multi-line output (for docstrings)
            if "\n" in func_output:
                lines.extend(func_output.split("\n"))
            else:
                lines.append(func_output)

        return lines

    def _export_function(self, func: Node, indent: int = 0) -> str:
        """Export a function or method.

        Args:
            func: The function node.
            indent: Number of spaces to indent.

        Returns:
            Single or multi-line MU output.
        """
        props = func.properties
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
        parts.append(func.name)

        # Parameters
        params = props.get("parameters", [])
        if params:
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

        # Line numbers (inline after signature)
        if self.export_config.include_line_numbers and func.line_start:
            end_line = func.line_end or func.line_start
            parts.append(f" :L{func.line_start}-{end_line}")

        # Decorators
        decorators = props.get("decorators", [])
        if decorators:
            parts.append(f" {self.SIGIL_ANNOTATION}{', '.join(decorators)}")

        # Complexity annotation for complex functions
        if func.complexity and func.complexity >= self.export_config.min_complexity_to_show:
            parts.append(f" {self.SIGIL_ANNOTATION}complexity={func.complexity}")

        signature_line = "".join(parts)

        # Docstring (on next line after signature)
        if self.export_config.include_docstrings:
            docstring = self._get_docstring(func)
            if docstring:
                # Return multi-line with docstring indented
                docstring_line = f'{prefix}  "{docstring}"'
                return f"{signature_line}\n{docstring_line}"

        return signature_line

    def _path_to_module_name(self, path: str) -> str:
        """Convert a file path to module name.

        Args:
            path: File path.

        Returns:
            Module name (e.g., 'mu.parser.models').
        """
        name = path

        # Remove common prefixes
        for prefix in ("src/", "lib/", "app/"):
            if name.startswith(prefix):
                name = name[len(prefix) :]
                break

        # Remove extension
        for ext in (".py", ".ts", ".js", ".go", ".java", ".rs", ".cs"):
            if name.endswith(ext):
                name = name[: -len(ext)]
                break

        # Convert path separators to dots
        name = name.replace("/", ".").replace("\\", ".")

        # Remove trailing __init__
        if name.endswith(".__init__"):
            name = name[:-9]

        return name

    def _get_method_class_name(self, node: Node, mubase: MUbase) -> str:
        """Get the class name for a method node.

        Args:
            node: The method node.
            mubase: The database for parent lookup.

        Returns:
            Class name or 'Unknown'.
        """
        # Try to extract from qualified name
        if node.qualified_name:
            parts = node.qualified_name.split(".")
            if len(parts) >= 2:
                return parts[-2]

        # Try to get from parent via CONTAINS edge
        parent = mubase.get_parent(node.id)
        if parent and parent.type == NodeType.CLASS:
            return parent.name

        return "Unknown"

    def _get_docstring(self, node: Node) -> str | None:
        """Extract and format docstring from node properties.

        Args:
            node: The node to extract docstring from.

        Returns:
            Formatted docstring or None if not available.
        """
        docstring = node.properties.get("docstring")
        if not docstring or not isinstance(docstring, str):
            return None

        # Clean and truncate
        lines = docstring.strip().split("\n")

        if (
            self.export_config.truncate_docstring
            and len(lines) > self.export_config.max_docstring_lines
        ):
            lines = lines[: self.export_config.max_docstring_lines]
            lines.append("...")

        # For single-line, return as-is
        if len(lines) == 1:
            return str(lines[0])

        # For multi-line, return first line (summary)
        return str(lines[0])

    def _get_internal_imports(self, module_path: str, mubase: MUbase) -> list[str]:
        """Get internal module imports via IMPORTS edges.

        Args:
            module_path: The module file path.
            mubase: The database for edge lookup.

        Returns:
            List of internal import module names.
        """
        # Build module node ID
        module_id = f"mod:{module_path}"

        # Get all edges from this module
        edges = mubase.get_edges()
        import_edges = [e for e in edges if e.source_id == module_id and e.type == EdgeType.IMPORTS]

        # Get target module names
        imports = []
        for edge in import_edges:
            target = mubase.get_node(edge.target_id)
            if target:
                # Convert file path to module name
                imports.append(self._path_to_module_name(target.file_path or target.id))

        return sorted(imports)

    def _infer_language(self, path: str) -> str | None:
        """Infer programming language from file extension.

        Args:
            path: File path.

        Returns:
            Language name or None.
        """
        ext_to_lang = {
            ".py": "python",
            ".ts": "typescript",
            ".js": "javascript",
            ".go": "go",
            ".java": "java",
            ".rs": "rust",
            ".cs": "csharp",
        }

        for ext, lang in ext_to_lang.items():
            if path.endswith(ext):
                return lang

        return None


__all__ = ["MUTextExporter"]
