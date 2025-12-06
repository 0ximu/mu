"""Graph builder for converting parsed modules to graph nodes and edges.

Converts the existing ModuleDef structure from the parser into
Node and Edge objects for storage in the MUbase graph database.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from mu.kernel.models import Edge, Node
from mu.kernel.schema import EdgeType, NodeType

if TYPE_CHECKING:
    from mu.parser.models import ClassDef, FunctionDef, ModuleDef


class GraphBuilder:
    """Builds graph nodes and edges from parsed module definitions.

    This is the bridge between the existing parser infrastructure
    and the new graph storage layer.
    """

    def __init__(self, root_path: Path) -> None:
        """Initialize builder.

        Args:
            root_path: Root path of the codebase (for relative path calculation)
        """
        self.root_path = root_path.resolve()
        self._nodes: list[Node] = []
        self._edges: list[Edge] = []
        self._module_id_map: dict[str, str] = {}  # path -> node_id

    def build(self, modules: list[ModuleDef]) -> tuple[list[Node], list[Edge]]:
        """Convert parsed modules to graph nodes and edges.

        Args:
            modules: List of parsed ModuleDef objects

        Returns:
            Tuple of (nodes, edges) for the graph
        """
        self._nodes = []
        self._edges = []
        self._module_id_map = {}

        # First pass: create all module nodes (needed for IMPORTS edges)
        for module in modules:
            self._create_module_node(module)

        # Second pass: create class/function nodes and edges
        for module in modules:
            self._process_module_contents(module)

        return self._nodes, self._edges

    def _create_module_node(self, module: ModuleDef) -> Node:
        """Create a MODULE node from a ModuleDef."""
        node_id = f"mod:{module.path}"
        self._module_id_map[module.path] = node_id

        node = Node(
            id=node_id,
            type=NodeType.MODULE,
            name=module.name,
            qualified_name=module.name,
            file_path=module.path,
            properties={
                "language": module.language,
                "total_lines": module.total_lines,
            },
        )

        if module.module_docstring:
            node.properties["docstring"] = module.module_docstring

        self._nodes.append(node)
        return node

    def _process_module_contents(self, module: ModuleDef) -> None:
        """Process classes, functions, and imports in a module."""
        module_node_id = self._module_id_map[module.path]

        # Process classes
        for cls in module.classes:
            self._process_class(cls, module, module_node_id)

        # Process module-level functions
        for func in module.functions:
            self._process_function(func, module, module_node_id, class_name=None)

        # Process imports (create IMPORTS edges)
        self._process_imports(module, module_node_id)

    def _process_class(
        self,
        cls: ClassDef,
        module: ModuleDef,
        module_node_id: str,
    ) -> None:
        """Create CLASS node and related edges."""
        class_node_id = f"cls:{module.path}:{cls.name}"

        class_node = Node(
            id=class_node_id,
            type=NodeType.CLASS,
            name=cls.name,
            qualified_name=f"{module.name}.{cls.name}",
            file_path=module.path,
            line_start=cls.start_line,
            line_end=cls.end_line,
            properties={
                "bases": cls.bases,
                "decorators": cls.decorators,
                "attributes": cls.attributes,
            },
        )

        if cls.docstring:
            class_node.properties["docstring"] = cls.docstring

        self._nodes.append(class_node)

        # Module CONTAINS Class
        self._edges.append(Edge(
            id=f"edge:{module_node_id}:contains:{class_node_id}",
            source_id=module_node_id,
            target_id=class_node_id,
            type=EdgeType.CONTAINS,
        ))

        # INHERITS edges for base classes
        for base in cls.bases:
            # Create edge to base class
            # Target ID is a placeholder - we try to resolve it but may not find it
            base_target_id = self._resolve_base_class(base, module)
            self._edges.append(Edge(
                id=f"edge:{class_node_id}:inherits:{base}",
                source_id=class_node_id,
                target_id=base_target_id,
                type=EdgeType.INHERITS,
                properties={"base_name": base},
            ))

        # Process methods
        for method in cls.methods:
            self._process_function(method, module, class_node_id, class_name=cls.name)

    def _process_function(
        self,
        func: FunctionDef,
        module: ModuleDef,
        parent_node_id: str,
        class_name: str | None,
    ) -> None:
        """Create FUNCTION node and CONTAINS edge."""
        if class_name:
            func_node_id = f"fn:{module.path}:{class_name}.{func.name}"
            qualified_name = f"{module.name}.{class_name}.{func.name}"
        else:
            func_node_id = f"fn:{module.path}:{func.name}"
            qualified_name = f"{module.name}.{func.name}"

        func_node = Node(
            id=func_node_id,
            type=NodeType.FUNCTION,
            name=func.name,
            qualified_name=qualified_name,
            file_path=module.path,
            line_start=func.start_line,
            line_end=func.end_line,
            complexity=func.body_complexity,
            properties={
                "is_async": func.is_async,
                "is_method": func.is_method,
                "is_static": func.is_static,
                "is_classmethod": func.is_classmethod,
                "is_property": func.is_property,
                "decorators": func.decorators,
                "return_type": func.return_type,
                "parameters": [p.to_dict() for p in func.parameters],
            },
        )

        if func.docstring:
            func_node.properties["docstring"] = func.docstring

        self._nodes.append(func_node)

        # Parent CONTAINS Function
        self._edges.append(Edge(
            id=f"edge:{parent_node_id}:contains:{func_node_id}",
            source_id=parent_node_id,
            target_id=func_node_id,
            type=EdgeType.CONTAINS,
        ))

    def _process_imports(self, module: ModuleDef, module_node_id: str) -> None:
        """Create IMPORTS edges for internal module dependencies.

        Only creates edges for imports that resolve to modules in the codebase.
        External/stdlib imports are tracked in module properties.
        """
        external_deps: list[str] = []

        for imp in module.imports:
            # Skip dynamic imports for now
            if imp.is_dynamic:
                continue

            # Try to find target module in our codebase
            target_node_id = self._resolve_import(imp.module, module)

            if target_node_id:
                # Internal import - create IMPORTS edge
                edge_id = f"edge:{module_node_id}:imports:{target_node_id}"
                # Avoid duplicate edges
                if not any(e.id == edge_id for e in self._edges):
                    self._edges.append(Edge(
                        id=edge_id,
                        source_id=module_node_id,
                        target_id=target_node_id,
                        type=EdgeType.IMPORTS,
                        properties={
                            "names": imp.names,
                            "alias": imp.alias,
                        },
                    ))
            else:
                # External import - track in properties
                package = imp.module.split(".")[0].split("/")[0]
                if package and package not in external_deps:
                    external_deps.append(package)

        # Update module node with external deps
        if external_deps:
            for node in self._nodes:
                if node.id == module_node_id:
                    node.properties["external_deps"] = external_deps
                    break

    def _resolve_import(self, import_path: str, from_module: ModuleDef) -> str | None:
        """Try to resolve an import to a module node ID.

        Args:
            import_path: The import path (e.g., "mu.parser.models")
            from_module: The module containing the import

        Returns:
            Node ID if found, None otherwise
        """
        # Direct path match
        for path, node_id in self._module_id_map.items():
            # Check various matching patterns

            # Exact module name match (e.g., "mu.parser.models" -> "mu/parser/models.py")
            path_as_module = path.replace("/", ".").replace("\\", ".")
            if path_as_module.endswith(".py"):
                path_as_module = path_as_module[:-3]
            if path_as_module.endswith(".__init__"):
                path_as_module = path_as_module[:-9]

            if import_path == path_as_module:
                return node_id

            # Check if import is a suffix of the path
            # e.g., "models" matching "src/mu/parser/models.py"
            if path_as_module.endswith("." + import_path) or path_as_module == import_path:
                return node_id

            # Check path-based matching
            import_as_path = import_path.replace(".", "/")
            if path.endswith(f"{import_as_path}.py") or path.endswith(f"{import_as_path}/__init__.py"):
                return node_id

        # Handle relative imports
        if import_path.startswith("."):
            # Count dots and resolve relative to from_module
            dots = 0
            for c in import_path:
                if c == ".":
                    dots += 1
                else:
                    break

            remainder = import_path[dots:]
            from_parts = Path(from_module.path).parts

            if dots <= len(from_parts):
                base_parts = from_parts[:-dots]
                if remainder:
                    target_parts = list(base_parts) + remainder.split(".")
                else:
                    target_parts = list(base_parts)

                target_path = "/".join(target_parts)

                # Try to find matching module
                for path, node_id in self._module_id_map.items():
                    if path.startswith(target_path) and (
                        path.endswith(".py") or path.endswith("/__init__.py")
                    ):
                        return node_id

        return None

    def _resolve_base_class(self, base_name: str, module: ModuleDef) -> str:
        """Resolve a base class name to a node ID.

        For now, returns a placeholder ID. Full resolution would require
        tracking class definitions across all modules.
        """
        # Check if it's a simple name that might be in the same module
        for cls_node in self._nodes:
            if cls_node.type == NodeType.CLASS and cls_node.name == base_name:
                return cls_node.id

        # Return placeholder for unresolved base classes
        return f"cls:external:{base_name}"

    @staticmethod
    def from_module_defs(
        modules: list[ModuleDef],
        root_path: Path,
    ) -> tuple[list[Node], list[Edge]]:
        """Convenience method to build graph from modules.

        Args:
            modules: List of parsed ModuleDef objects
            root_path: Root path of the codebase

        Returns:
            Tuple of (nodes, edges) for the graph
        """
        builder = GraphBuilder(root_path)
        return builder.build(modules)


__all__ = [
    "GraphBuilder",
]
