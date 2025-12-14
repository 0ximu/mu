"""Lisp S-expression format exporter.

Exports the graph as Lisp S-expressions optimized for LLM consumption.
Part of Project OMEGA: S-Expression Semantic Compression.

Core forms: module, class, defn, data, const
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mu.kernel.export.base import ExportOptions, ExportResult
from mu.kernel.models import Node
from mu.kernel.schema import NodeType

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase


@dataclass
class LispExportOptions(ExportOptions):
    """Extended options for Lisp export."""

    include_header: bool = True
    """Include MU-Lisp standard library header."""

    macros: list[str] = field(default_factory=list)
    """Names of macros to enable (empty = core only)."""

    pretty_print: bool = True
    """Format with indentation for readability."""

    max_depth: int = 10
    """Maximum nesting depth before truncation."""


class LispExporter:
    """Export graph as Lisp S-expressions.

    Produces a token-efficient representation using nested lists
    that LLMs can parse natively without custom syntax.

    Example output:
        (mu-lisp :version "1.0"
          (module auth
            :deps [fastapi pydantic]
            (class AuthService
              :bases [BaseService]
              (defn authenticate [username:str password:str] -> User))
            (defn hash_password [raw:str] -> str)))
    """

    # Format metadata
    format_name: str = "lisp"
    file_extension: str = ".mulisp"
    description: str = "Lisp S-expression format (OMEGA compression)"

    # Core forms (always available)
    CORE_FORMS = {
        "module": "(module name :deps [deps...] body...)",
        "class": "(class name :bases [bases...] :attrs [attrs...] methods...)",
        "defn": "(defn name [params...] -> return-type :decorators [...])",
        "data": "(data name [fields...])",
        "const": "(const name value)",
    }

    def __init__(self) -> None:
        """Initialize the Lisp exporter."""
        self._indent_size = 2

    def export(
        self,
        mubase: MUbase,
        options: LispExportOptions | ExportOptions | None = None,
    ) -> ExportResult:
        """Export graph to Lisp S-expression format.

        Args:
            mubase: The MUbase database to export from.
            options: Export options for filtering and customization.

        Returns:
            ExportResult with Lisp format output.
        """
        options = options or LispExportOptions()

        # Extract LispExportOptions fields or use defaults
        include_header = getattr(options, "include_header", True)
        pretty_print = getattr(options, "pretty_print", True)
        max_depth = getattr(options, "max_depth", 10)

        nodes = self._get_nodes(mubase, options)
        edges = self._get_edges(mubase, nodes, options) if options.include_edges else []

        if not nodes:
            return ExportResult(
                output=";; No nodes to export",
                format=self.format_name,
                node_count=0,
                edge_count=0,
            )

        lines: list[str] = []

        # Emit header if requested
        if include_header:
            lines.append(self._emit_header())
            lines.append("")

        # Group nodes by module
        by_module = self._group_by_module(nodes)

        # Build the mu-lisp wrapper
        lines.append('(mu-lisp :version "1.0"')

        for module_path, module_nodes in sorted(by_module.items()):
            module_sexpr = self._module_to_sexpr(
                module_path, module_nodes, mubase, pretty_print, max_depth
            )
            if pretty_print:
                # Indent module content
                indented = self._indent_block(module_sexpr, 2)
                lines.append(indented)
            else:
                lines.append(f"  {module_sexpr}")

        lines.append(")")

        output = "\n".join(lines) if pretty_print else " ".join(lines)

        return ExportResult(
            output=output,
            format=self.format_name,
            node_count=len(nodes),
            edge_count=len(edges),
        )

    def _emit_header(self, version: str = "1.0") -> str:
        """Emit the MU-Lisp header with version and core forms.

        Args:
            version: MU-Lisp version string.

        Returns:
            Header comment string.
        """
        lines = [
            f";; MU-Lisp v{version} - Machine Understanding Semantic Format",
            ";; Core forms: module, class, defn, data, const",
        ]
        return "\n".join(lines)

    def _module_to_sexpr(
        self,
        module_path: str,
        nodes: list[Node],
        mubase: MUbase,
        pretty_print: bool = True,
        max_depth: int = 10,
    ) -> str:
        """Convert a module and its contents to S-expression.

        Args:
            module_path: The module file path.
            nodes: Nodes belonging to this module.
            mubase: Database for additional lookups.
            pretty_print: Whether to format with indentation.
            max_depth: Maximum nesting depth.

        Returns:
            S-expression string for the module.
        """
        module_name = self._path_to_module_name(module_path)
        parts: list[str] = [f"(module {module_name}"]

        # Collect dependencies (external nodes)
        externals = [n for n in nodes if n.type == NodeType.EXTERNAL]
        if externals:
            ext_names = sorted(n.name for n in externals)
            parts.append(f":deps [{' '.join(ext_names)}]")

        # Add file path
        parts.append(f':file "{module_path}"')

        # Separate nodes by type
        classes: dict[str, Node] = {}
        functions: list[Node] = []
        methods_by_class: dict[str, list[Node]] = defaultdict(list)

        for node in nodes:
            if node.type == NodeType.MODULE:
                continue
            elif node.type == NodeType.CLASS:
                classes[node.name] = node
            elif node.type == NodeType.FUNCTION:
                if node.properties.get("is_method"):
                    class_name = self._get_method_class_name(node, mubase)
                    methods_by_class[class_name].append(node)
                else:
                    functions.append(node)

        # Build class S-expressions
        class_sexprs: list[str] = []
        for class_name, cls_node in sorted(classes.items()):
            methods = methods_by_class.get(class_name, [])
            class_sexpr = self._class_to_sexpr(cls_node, methods, max_depth - 1)
            class_sexprs.append(class_sexpr)

        # Build orphan method S-expressions (class not in selection)
        for class_name, methods in sorted(methods_by_class.items()):
            if class_name not in classes and class_name != "Unknown":
                # Create a partial class representation
                partial_sexpr = f"(class {class_name} :partial"
                method_sexprs = [
                    self._function_to_sexpr(m, max_depth - 2)
                    for m in sorted(methods, key=lambda m: m.name)
                ]
                if method_sexprs:
                    partial_sexpr += " " + " ".join(method_sexprs)
                partial_sexpr += ")"
                class_sexprs.append(partial_sexpr)

        # Build top-level function S-expressions
        func_sexprs: list[str] = []
        for func in sorted(functions, key=lambda f: f.name):
            func_sexprs.append(self._function_to_sexpr(func, max_depth - 1))

        # Combine all parts
        if pretty_print:
            result_parts = [parts[0]]
            if len(parts) > 1:
                result_parts.append(" " + " ".join(parts[1:]))

            # Add classes on new lines
            for cls_sexpr in class_sexprs:
                result_parts.append("\n    " + cls_sexpr)

            # Add functions on new lines
            for func_sexpr in func_sexprs:
                result_parts.append("\n    " + func_sexpr)

            result_parts.append(")")
            return "".join(result_parts)
        else:
            all_content = class_sexprs + func_sexprs
            if all_content:
                return " ".join(parts) + " " + " ".join(all_content) + ")"
            return " ".join(parts) + ")"

    def _class_to_sexpr(
        self,
        cls: Node,
        methods: list[Node],
        max_depth: int = 10,
    ) -> str:
        """Convert a class to S-expression.

        Args:
            cls: The class node.
            methods: Method nodes belonging to this class.
            max_depth: Maximum nesting depth.

        Returns:
            S-expression string for the class.
        """
        props = cls.properties
        parts: list[str] = [f"(class {cls.name}"]

        # Check if it's a dataclass/data type
        decorators = props.get("decorators", [])
        is_dataclass = "dataclass" in decorators

        # Inheritance
        bases = props.get("bases", [])
        if bases:
            parts.append(f":bases [{' '.join(bases)}]")

        # Attributes
        attrs = props.get("attributes", [])
        if attrs:
            # Limit to first 10 for readability
            attr_list = attrs[:10]
            if len(attrs) > 10:
                attr_list.append(f"+{len(attrs) - 10}")
            parts.append(f":attrs [{' '.join(attr_list)}]")

        # Complexity annotation for complex classes
        if cls.complexity and cls.complexity >= 30:
            parts.append(f":complexity {cls.complexity}")

        # For dataclasses, use the (data ...) shorthand if no methods
        if is_dataclass and not methods and attrs:
            fields = [self._format_field(a) for a in attrs[:10]]
            return f"(data {cls.name} [{' '.join(fields)}])"

        # Add methods
        if max_depth > 0:
            method_sexprs = [
                self._function_to_sexpr(m, max_depth - 1)
                for m in sorted(methods, key=lambda m: m.name)
            ]
            if method_sexprs:
                parts.extend(method_sexprs)

        parts.append(")")
        return " ".join(parts)

    def _function_to_sexpr(self, func: Node, max_depth: int = 10) -> str:
        """Convert a function/method to S-expression.

        Args:
            func: The function node.
            max_depth: Maximum nesting depth.

        Returns:
            S-expression string for the function.
        """
        props = func.properties

        # Determine the form name based on modifiers
        form = "defn"
        if props.get("is_async"):
            form = "defn-async"
        elif props.get("is_static"):
            form = "defn-static"
        elif props.get("is_classmethod"):
            form = "defn-classmethod"

        parts: list[str] = [f"({form} {func.name}"]

        # Parameters
        params = props.get("parameters", [])
        param_strs: list[str] = []
        for p in params:
            if isinstance(p, dict):
                name = p.get("name", "?")
                ptype = p.get("type_annotation", "")
                if name == "self" or name == "cls":
                    continue  # Skip self/cls in S-expr
                if ptype:
                    param_strs.append(f"{name}:{ptype}")
                else:
                    param_strs.append(name)
            else:
                if str(p) not in ("self", "cls"):
                    param_strs.append(str(p))

        parts.append(f"[{' '.join(param_strs)}]")

        # Return type
        return_type = props.get("return_type")
        if return_type:
            parts.append(f"-> {return_type}")

        # Decorators (excluding common ones)
        decorators = props.get("decorators", [])
        visible_decorators = [
            d
            for d in decorators
            if d
            not in (
                "public",
                "private",
                "protected",
                "internal",
                "staticmethod",
                "classmethod",
                "async",
            )
        ]
        if visible_decorators:
            parts.append(f":decorators [{' '.join(visible_decorators)}]")

        # Complexity annotation for complex functions
        if func.complexity and func.complexity >= 20:
            parts.append(f":complexity {func.complexity}")

        parts.append(")")
        return " ".join(parts)

    def _escape_string(self, s: str) -> str:
        """Escape special characters in strings.

        Args:
            s: String to escape.

        Returns:
            Escaped string safe for S-expression.
        """
        # Escape backslashes first, then quotes
        s = s.replace("\\", "\\\\")
        s = s.replace('"', '\\"')
        # Escape parentheses in identifiers
        s = s.replace("(", "_")
        s = s.replace(")", "_")
        s = s.replace("[", "_")
        s = s.replace("]", "_")
        return s

    def _format_sexpr(self, sexpr: str, indent: int = 0) -> str:
        """Pretty-print an S-expression with proper indentation.

        Args:
            sexpr: The S-expression string.
            indent: Current indentation level.

        Returns:
            Formatted S-expression.
        """
        # Simple implementation - more sophisticated formatting could be added
        return " " * indent + sexpr

    def _indent_block(self, text: str, spaces: int) -> str:
        """Indent a block of text.

        Args:
            text: Text to indent.
            spaces: Number of spaces.

        Returns:
            Indented text.
        """
        prefix = " " * spaces
        lines = text.split("\n")
        return "\n".join(prefix + line if line.strip() else line for line in lines)

    def _format_field(self, attr: str) -> str:
        """Format an attribute as a field specification.

        Args:
            attr: Attribute name, possibly with type.

        Returns:
            Field string in name:type format.
        """
        # If attr already has type info, return as-is
        if ":" in attr:
            return attr
        return attr

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
    ) -> list[Any]:
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

            if node.type == NodeType.MODULE:
                module_path = node.file_path or node.id

            by_module[module_path].append(node)

        return dict(by_module)

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


__all__ = ["LispExporter", "LispExportOptions"]
