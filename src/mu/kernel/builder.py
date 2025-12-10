"""Graph builder for converting parsed modules to graph nodes and edges.

Converts the existing ModuleDef structure from the parser into
Node and Edge objects for storage in the MUbase graph database.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

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
        self._function_id_map: dict[str, str] = {}  # qualified_name -> node_id
        self._import_map: dict[str, dict[str, str]] = {}  # module_path -> {name -> import_module}
        self._class_name_map: dict[str, str] = {}  # class_name -> node_id (for resolving uses)

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
        self._function_id_map = {}
        self._import_map = {}
        self._class_name_map = {}

        # First pass: create all module nodes and build import map
        for module in modules:
            self._create_module_node(module)
            self._build_import_map(module)

        # Second pass: create class/function nodes and edges
        for module in modules:
            self._process_module_contents(module)

        # Third pass: create CALLS edges (after all functions are registered)
        for module in modules:
            self._process_call_sites(module)

        # Fourth pass: create USES edges (after all classes are registered)
        for module in modules:
            self._process_uses_edges(module)

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

        # Store referenced types for USES edge creation
        if hasattr(cls, "referenced_types") and cls.referenced_types:
            class_node.properties["referenced_types"] = cls.referenced_types

        self._nodes.append(class_node)

        # Register class for USES resolution
        self._class_name_map[cls.name] = class_node_id

        # Module CONTAINS Class
        self._edges.append(
            Edge(
                id=f"edge:{module_node_id}:contains:{class_node_id}",
                source_id=module_node_id,
                target_id=class_node_id,
                type=EdgeType.CONTAINS,
            )
        )

        # INHERITS edges for base classes
        for base in cls.bases:
            # Create edge to base class
            # Target ID is a placeholder - we try to resolve it but may not find it
            base_target_id = self._resolve_base_class(base, module)
            self._edges.append(
                Edge(
                    id=f"edge:{class_node_id}:inherits:{base}",
                    source_id=class_node_id,
                    target_id=base_target_id,
                    type=EdgeType.INHERITS,
                    properties={"base_name": base},
                )
            )

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

        # Register function for call resolution
        self._function_id_map[func.name] = func_node_id
        self._function_id_map[qualified_name] = func_node_id
        # Also register by module.path:func_name for local resolution
        if class_name:
            self._function_id_map[f"{module.path}:{class_name}.{func.name}"] = func_node_id
        else:
            self._function_id_map[f"{module.path}:{func.name}"] = func_node_id

        # Parent CONTAINS Function
        self._edges.append(
            Edge(
                id=f"edge:{parent_node_id}:contains:{func_node_id}",
                source_id=parent_node_id,
                target_id=func_node_id,
                type=EdgeType.CONTAINS,
            )
        )

    def _build_import_map(self, module: ModuleDef) -> None:
        """Build a map of imported names to their source modules."""
        import_names: dict[str, str] = {}
        for imp in module.imports:
            if imp.is_dynamic:
                continue
            for name in imp.names:
                # Map the imported name to the source module
                import_names[name] = imp.module
            # Handle 'import X as Y' style
            if imp.alias:
                import_names[imp.alias] = imp.module
        self._import_map[module.path] = import_names

    def _process_call_sites(self, module: ModuleDef) -> None:
        """Create CALLS edges from function call sites."""
        # Process module-level functions
        for func in module.functions:
            self._create_calls_edges(func, module, class_name=None)

        # Process class methods
        for cls in module.classes:
            for method in cls.methods:
                self._create_calls_edges(method, module, class_name=cls.name)

    def _create_calls_edges(
        self,
        func: FunctionDef,
        module: ModuleDef,
        class_name: str | None,
    ) -> None:
        """Create CALLS edges for a function's call sites."""
        # Get the source function node ID
        if class_name:
            source_func_id = f"fn:{module.path}:{class_name}.{func.name}"
        else:
            source_func_id = f"fn:{module.path}:{func.name}"

        # Check if function has call_sites attribute (Rust parser provides this)
        call_sites = getattr(func, "call_sites", None)
        if not call_sites:
            return

        for call in call_sites:
            target_id = self._resolve_callee(call, module, class_name)
            if target_id:
                edge_id = f"edge:{source_func_id}:calls:{target_id}:{call.line}"
                # Avoid duplicate edges
                if not any(e.id == edge_id for e in self._edges):
                    self._edges.append(
                        Edge(
                            id=edge_id,
                            source_id=source_func_id,
                            target_id=target_id,
                            type=EdgeType.CALLS,
                            properties={"line": call.line},
                        )
                    )

    def _resolve_callee(
        self,
        call: Any,  # CallSiteDef from Rust
        module: ModuleDef,
        class_name: str | None,
    ) -> str | None:
        """Resolve a call site to a target function node ID.

        Resolution priority:
        1. Method call on self -> same class
        2. Local function in same module
        3. Imported function from another module
        4. Unresolved -> skip
        """
        callee_name = call.callee

        # 1. Method call on self -> same class method
        if call.is_method_call and call.receiver == "self" and class_name:
            target_id = f"fn:{module.path}:{class_name}.{callee_name}"
            if target_id in self._function_id_map.values():
                return target_id

        # 2. Local function in same module (module-level function)
        local_id = f"fn:{module.path}:{callee_name}"
        if local_id in self._function_id_map.values():
            return local_id

        # 3. Check if callee is an imported name
        import_names = self._import_map.get(module.path, {})
        if callee_name in import_names:
            source_module = import_names[callee_name]
            # Try to find the function in the imported module
            resolved_module_id = self._resolve_import(source_module, module)
            if resolved_module_id:
                # Extract the path from module node ID (mod:path -> path)
                target_module_path = resolved_module_id[4:]  # Remove "mod:" prefix
                target_func_id = f"fn:{target_module_path}:{callee_name}"
                if target_func_id in self._function_id_map.values():
                    return target_func_id

        # 4. Check for qualified calls like ClassName.method or module.func
        if "." in callee_name:
            parts = callee_name.split(".")
            receiver = parts[0]
            method = parts[-1]

            # Could be a class method call - check classes in same module
            class_method_id = f"fn:{module.path}:{receiver}.{method}"
            if class_method_id in self._function_id_map.values():
                return class_method_id

            # Could be an imported module's function
            if receiver in import_names:
                source_module = import_names[receiver]
                resolved_module_id = self._resolve_import(source_module, module)
                if resolved_module_id:
                    target_module_path = resolved_module_id[4:]
                    target_func_id = f"fn:{target_module_path}:{method}"
                    if target_func_id in self._function_id_map.values():
                        return target_func_id

        # Unresolved - skip
        return None

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
                    self._edges.append(
                        Edge(
                            id=edge_id,
                            source_id=module_node_id,
                            target_id=target_node_id,
                            type=EdgeType.IMPORTS,
                            properties={
                                "names": imp.names,
                                "alias": imp.alias,
                            },
                        )
                    )
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

            # Check path-based matching (require segment boundary to avoid
            # matching 'logging' to 'error_logging.py' or 're' to 'middleware.py')
            import_as_path = import_path.replace(".", "/")
            if (
                path.endswith(f"/{import_as_path}.py")
                or path == f"{import_as_path}.py"
                or path.endswith(f"/{import_as_path}/__init__.py")
                or path == f"{import_as_path}/__init__.py"
            ):
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

    def _process_uses_edges(self, module: ModuleDef) -> None:
        """Create USES edges for class-to-class type references."""
        for cls in module.classes:
            class_node_id = f"cls:{module.path}:{cls.name}"

            # Get referenced types from the class
            referenced_types = getattr(cls, "referenced_types", None)
            if not referenced_types:
                continue

            for type_name in referenced_types:
                # Try to resolve the type name to a class node
                target_id = self._resolve_type_reference(type_name, module)
                if target_id and target_id != class_node_id:
                    edge_id = f"edge:{class_node_id}:uses:{target_id}"
                    # Avoid duplicate edges
                    if not any(e.id == edge_id for e in self._edges):
                        self._edges.append(
                            Edge(
                                id=edge_id,
                                source_id=class_node_id,
                                target_id=target_id,
                                type=EdgeType.USES,
                                properties={"type_name": type_name},
                            )
                        )

    def _resolve_type_reference(self, type_name: str, from_module: ModuleDef) -> str | None:
        """Resolve a type name to a class node ID.

        Args:
            type_name: The type name to resolve (e.g., "Node", "MyClass")
            from_module: The module containing the type reference

        Returns:
            Node ID if found, None otherwise
        """
        # 1. Check if it's a class in the class name map (direct match)
        if type_name in self._class_name_map:
            return self._class_name_map[type_name]

        # 2. Check imported names
        import_names = self._import_map.get(from_module.path, {})
        if type_name in import_names:
            # The type was imported - try to find it in the source module
            source_module = import_names[type_name]
            resolved_module_id = self._resolve_import(source_module, from_module)
            if resolved_module_id:
                # Extract path from module ID and look for the class
                target_module_path = resolved_module_id[4:]  # Remove "mod:" prefix
                target_class_id = f"cls:{target_module_path}:{type_name}"
                # Check if this class exists
                for node in self._nodes:
                    if node.id == target_class_id:
                        return target_class_id

        # 3. Check all classes in the same module
        for node in self._nodes:
            if (
                node.type == NodeType.CLASS
                and node.name == type_name
                and node.file_path == from_module.path
            ):
                return node.id

        return None

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
