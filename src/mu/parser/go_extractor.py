"""Go-specific AST extractor using Tree-sitter."""

from __future__ import annotations

from pathlib import Path
from tree_sitter import Node

from mu.parser.models import (
    ClassDef,
    FunctionDef,
    ImportDef,
    ModuleDef,
    ParameterDef,
)
from mu.parser.base import (
    count_nodes,
    get_node_text,
    find_child_by_type,
    find_children_by_type,
)


class GoExtractor:
    """Extract AST information from Go source files."""

    def extract(self, root: Node, source: bytes, file_path: str) -> ModuleDef:
        """Extract module definition from Go AST."""
        module = ModuleDef(
            name=Path(file_path).stem,
            path=file_path,
            language="go",
            total_lines=root.end_point[0] + 1,
        )

        # Process top-level declarations
        for child in root.children:
            if child.type == "package_clause":
                # Extract package name as module name
                name_node = find_child_by_type(child, "package_identifier")
                if name_node:
                    module.name = get_node_text(name_node, source)
            elif child.type == "import_declaration":
                imports = self._extract_imports(child, source)
                module.imports.extend(imports)
            elif child.type == "function_declaration":
                func = self._extract_function(child, source)
                if func:
                    module.functions.append(func)
            elif child.type == "method_declaration":
                # Methods are attached to types, we'll handle them specially
                method = self._extract_method(child, source)
                if method:
                    # Store methods as top-level for now, could be grouped by receiver
                    module.functions.append(method)
            elif child.type == "type_declaration":
                types = self._extract_type_declaration(child, source)
                module.classes.extend(types)
            elif child.type == "const_declaration" or child.type == "var_declaration":
                # Could extract constants/variables as module-level attributes
                pass

        return module

    def _extract_imports(self, node: Node, source: bytes) -> list[ImportDef]:
        """Extract import declarations."""
        imports = []

        # Check for import spec list (grouped imports)
        import_spec_list = find_child_by_type(node, "import_spec_list")
        if import_spec_list:
            for spec in import_spec_list.children:
                if spec.type == "import_spec":
                    imp = self._extract_import_spec(spec, source)
                    if imp:
                        imports.append(imp)
        else:
            # Single import
            spec = find_child_by_type(node, "import_spec")
            if spec:
                imp = self._extract_import_spec(spec, source)
                if imp:
                    imports.append(imp)

        return imports

    def _extract_import_spec(self, node: Node, source: bytes) -> ImportDef | None:
        """Extract a single import spec."""
        path_node = find_child_by_type(node, "interpreted_string_literal")
        if not path_node:
            return None

        # Get import path (remove quotes)
        path = get_node_text(path_node, source).strip('"')

        # Check for alias (package_identifier before the path)
        alias = None
        name_node = find_child_by_type(node, "package_identifier")
        if name_node:
            alias = get_node_text(name_node, source)

        # Check for blank identifier (side-effect import)
        blank_node = find_child_by_type(node, "blank_identifier")
        if blank_node:
            alias = "_"

        # Check for dot import
        dot_node = find_child_by_type(node, "dot")
        if dot_node:
            alias = "."

        return ImportDef(
            module=path,
            names=[],  # Go imports entire packages
            alias=alias,
            is_from=False,
        )

    def _extract_function(self, node: Node, source: bytes) -> FunctionDef | None:
        """Extract a function declaration."""
        func = FunctionDef(
            name="",
            is_method=False,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

        found_params = False
        for child in node.children:
            if child.type == "identifier":
                func.name = get_node_text(child, source)
            elif child.type == "parameter_list":
                if not found_params:
                    func.parameters = self._extract_parameters(child, source)
                    found_params = True
                else:
                    # Second parameter_list is the return type (multiple returns)
                    func.return_type = get_node_text(child, source)
            elif child.type == "type_identifier":
                # Simple return type
                func.return_type = get_node_text(child, source)
            elif child.type in ("pointer_type", "slice_type", "array_type",
                               "map_type", "channel_type", "qualified_type",
                               "interface_type", "struct_type", "function_type"):
                # Complex return type
                func.return_type = get_node_text(child, source)
            elif child.type == "block":
                func.body_complexity = count_nodes(child)
                func.body_source = get_node_text(child, source)

        # Check if this is an exported function (starts with uppercase)
        if func.name and func.name[0].isupper():
            func.decorators.append("exported")

        return func if func.name else None

    def _extract_method(self, node: Node, source: bytes) -> FunctionDef | None:
        """Extract a method declaration (function with receiver)."""
        func = FunctionDef(
            name="",
            is_method=True,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

        receiver_type = None
        param_list_count = 0

        for child in node.children:
            if child.type == "parameter_list":
                if param_list_count == 0:
                    # First parameter_list is the receiver
                    receiver = self._extract_receiver(child, source)
                    if receiver:
                        receiver_type = receiver
                        func.decorators.append(f"receiver:{receiver}")
                elif param_list_count == 1:
                    # Second parameter_list is the actual parameters
                    func.parameters = self._extract_parameters(child, source)
                else:
                    # Third parameter_list is multiple return types
                    func.return_type = get_node_text(child, source)
                param_list_count += 1
            elif child.type == "field_identifier":
                # Method name uses field_identifier
                func.name = get_node_text(child, source)
            elif child.type == "identifier":
                # Fallback for older tree-sitter versions
                func.name = get_node_text(child, source)
            elif child.type == "type_identifier":
                # Simple return type
                func.return_type = get_node_text(child, source)
            elif child.type in ("pointer_type", "slice_type", "array_type",
                               "map_type", "channel_type", "qualified_type",
                               "interface_type", "struct_type", "function_type"):
                # Complex return type
                func.return_type = get_node_text(child, source)
            elif child.type == "block":
                func.body_complexity = count_nodes(child)
                func.body_source = get_node_text(child, source)

        # Check if exported
        if func.name and func.name[0].isupper():
            func.decorators.append("exported")

        return func if func.name else None

    def _extract_receiver(self, node: Node, source: bytes) -> str | None:
        """Extract the receiver type from a method."""
        for child in node.children:
            if child.type == "parameter_declaration":
                # Look for the type
                type_node = find_child_by_type(child, "type_identifier")
                if type_node:
                    return get_node_text(type_node, source)
                # Could be pointer type
                pointer_type = find_child_by_type(child, "pointer_type")
                if pointer_type:
                    inner = find_child_by_type(pointer_type, "type_identifier")
                    if inner:
                        return "*" + get_node_text(inner, source)
        return None

    def _extract_parameters(self, node: Node, source: bytes) -> list[ParameterDef]:
        """Extract function parameters."""
        params = []

        for child in node.children:
            if child.type == "parameter_declaration":
                param_defs = self._extract_parameter_declaration(child, source)
                params.extend(param_defs)
            elif child.type == "variadic_parameter_declaration":
                param = self._extract_variadic_parameter(child, source)
                if param:
                    params.append(param)

        return params

    def _extract_parameter_declaration(self, node: Node, source: bytes) -> list[ParameterDef]:
        """Extract parameter declaration (may have multiple names with same type)."""
        params = []
        names = []
        type_str = None

        for child in node.children:
            if child.type == "identifier":
                names.append(get_node_text(child, source))
            elif child.type in ("type_identifier", "pointer_type", "slice_type",
                               "array_type", "map_type", "channel_type",
                               "function_type", "interface_type", "struct_type",
                               "qualified_type"):
                type_str = get_node_text(child, source)

        # If no names but we have a type, it's an unnamed parameter
        if not names and type_str:
            params.append(ParameterDef(name="", type_annotation=type_str))
        else:
            for name in names:
                params.append(ParameterDef(name=name, type_annotation=type_str))

        return params

    def _extract_variadic_parameter(self, node: Node, source: bytes) -> ParameterDef | None:
        """Extract variadic parameter (...type)."""
        name = ""
        type_str = None

        for child in node.children:
            if child.type == "identifier":
                name = get_node_text(child, source)
            elif child.type in ("type_identifier", "pointer_type", "slice_type",
                               "array_type", "interface_type", "qualified_type"):
                type_str = "..." + get_node_text(child, source)

        return ParameterDef(name=name, type_annotation=type_str, is_variadic=True) if type_str else None

    def _extract_result_type(self, node: Node, source: bytes) -> str:
        """Extract return type from result node."""
        # Could be a single type or a parameter_list for multiple returns
        param_list = find_child_by_type(node, "parameter_list")
        if param_list:
            # Multiple return values
            return get_node_text(param_list, source)

        # Single return type
        for child in node.children:
            if child.type in ("type_identifier", "pointer_type", "slice_type",
                             "array_type", "map_type", "channel_type",
                             "function_type", "interface_type", "struct_type",
                             "qualified_type"):
                return get_node_text(child, source)

        return get_node_text(node, source)

    def _extract_type_declaration(self, node: Node, source: bytes) -> list[ClassDef]:
        """Extract type declarations (struct, interface, type alias)."""
        types = []

        # Check for type spec list (grouped types)
        spec_list = find_child_by_type(node, "type_spec_list")
        if spec_list:
            for spec in spec_list.children:
                if spec.type == "type_spec":
                    type_def = self._extract_type_spec(spec, source)
                    if type_def:
                        types.append(type_def)
        else:
            # Single type spec
            spec = find_child_by_type(node, "type_spec")
            if spec:
                type_def = self._extract_type_spec(spec, source)
                if type_def:
                    types.append(type_def)

        return types

    def _extract_type_spec(self, node: Node, source: bytes) -> ClassDef | None:
        """Extract a single type specification."""
        class_def = ClassDef(
            name="",
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

        for child in node.children:
            if child.type == "type_identifier":
                class_def.name = get_node_text(child, source)
            elif child.type == "struct_type":
                class_def.decorators.append("struct")
                self._extract_struct_fields(child, source, class_def)
            elif child.type == "interface_type":
                class_def.decorators.append("interface")
                self._extract_interface_methods(child, source, class_def)
            elif child.type in ("type_identifier", "pointer_type", "slice_type",
                               "array_type", "map_type", "channel_type",
                               "function_type", "qualified_type"):
                # Type alias
                class_def.decorators.append("alias")
                class_def.bases.append(get_node_text(child, source))

        # Check if exported
        if class_def.name and class_def.name[0].isupper():
            class_def.decorators.append("exported")

        return class_def if class_def.name else None

    def _extract_struct_fields(self, node: Node, source: bytes, class_def: ClassDef) -> None:
        """Extract struct fields."""
        field_list = find_child_by_type(node, "field_declaration_list")
        if not field_list:
            return

        for child in field_list.children:
            if child.type == "field_declaration":
                # Get field names - check for field_identifier first (named fields)
                has_field_name = False
                for field_child in child.children:
                    if field_child.type == "field_identifier":
                        class_def.attributes.append(get_node_text(field_child, source))
                        has_field_name = True
                    elif field_child.type == "identifier":
                        # Fallback for older tree-sitter
                        class_def.attributes.append(get_node_text(field_child, source))
                        has_field_name = True

                # If no named field, check for embedded types
                if not has_field_name:
                    for field_child in child.children:
                        if field_child.type == "type_identifier":
                            # Embedded type (anonymous field)
                            class_def.bases.append(get_node_text(field_child, source))
                        elif field_child.type == "pointer_type":
                            # Embedded pointer type
                            inner = find_child_by_type(field_child, "type_identifier")
                            if inner:
                                class_def.bases.append("*" + get_node_text(inner, source))

    def _extract_interface_methods(self, node: Node, source: bytes, class_def: ClassDef) -> None:
        """Extract interface method signatures."""
        for child in node.children:
            if child.type == "method_elem":
                # New tree-sitter-go uses method_elem
                method = self._extract_method_elem(child, source)
                if method:
                    class_def.methods.append(method)
            elif child.type == "method_spec":
                # Older tree-sitter-go uses method_spec
                method = self._extract_method_elem(child, source)
                if method:
                    class_def.methods.append(method)
            elif child.type == "type_elem":
                # Embedded interface or type constraint (Go 1.18+)
                type_id = find_child_by_type(child, "type_identifier")
                if type_id:
                    class_def.bases.append(get_node_text(type_id, source))
                else:
                    # Check for qualified type
                    qual_type = find_child_by_type(child, "qualified_type")
                    if qual_type:
                        class_def.bases.append(get_node_text(qual_type, source))
            elif child.type == "type_identifier":
                # Embedded interface
                class_def.bases.append(get_node_text(child, source))
            elif child.type == "qualified_type":
                # Embedded qualified interface (pkg.Interface)
                class_def.bases.append(get_node_text(child, source))

    def _extract_method_elem(self, node: Node, source: bytes) -> FunctionDef | None:
        """Extract interface method specification."""
        func = FunctionDef(
            name="",
            is_method=True,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

        param_list_count = 0
        for child in node.children:
            if child.type == "field_identifier":
                func.name = get_node_text(child, source)
            elif child.type == "identifier":
                # Fallback for older tree-sitter
                func.name = get_node_text(child, source)
            elif child.type == "parameter_list":
                if param_list_count == 0:
                    func.parameters = self._extract_parameters(child, source)
                else:
                    # Multiple return values
                    func.return_type = get_node_text(child, source)
                param_list_count += 1
            elif child.type == "type_identifier":
                # Simple return type
                func.return_type = get_node_text(child, source)
            elif child.type in ("pointer_type", "slice_type", "array_type",
                               "map_type", "channel_type", "qualified_type",
                               "interface_type", "struct_type", "function_type"):
                # Complex return type
                func.return_type = get_node_text(child, source)

        return func if func.name else None
