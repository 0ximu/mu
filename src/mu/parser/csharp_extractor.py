"""C#-specific AST extractor using Tree-sitter."""

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
    find_descendants_by_type,
)


class CSharpExtractor:
    """Extract AST information from C# source files."""

    def extract(self, root: Node, source: bytes, file_path: str) -> ModuleDef:
        """Extract module definition from C# AST."""
        module = ModuleDef(
            name=Path(file_path).stem,
            path=file_path,
            language="csharp",
            total_lines=root.end_point[0] + 1,
        )

        # Process compilation unit
        for child in root.children:
            self._process_node(child, source, module)

        return module

    def _process_node(self, node: Node, source: bytes, module: ModuleDef) -> None:
        """Process a top-level node."""
        if node.type == "using_directive":
            imp = self._extract_using(node, source)
            if imp:
                module.imports.append(imp)
        elif node.type == "namespace_declaration":
            self._process_namespace(node, source, module)
        elif node.type == "file_scoped_namespace_declaration":
            self._process_namespace(node, source, module)
        elif node.type == "class_declaration":
            module.classes.append(self._extract_class(node, source))
        elif node.type == "interface_declaration":
            module.classes.append(self._extract_interface(node, source))
        elif node.type == "struct_declaration":
            module.classes.append(self._extract_struct(node, source))
        elif node.type == "record_declaration":
            module.classes.append(self._extract_record(node, source))
        elif node.type == "global_statement":
            # Top-level statements (C# 9+)
            pass

    def _process_namespace(self, node: Node, source: bytes, module: ModuleDef) -> None:
        """Process namespace declaration."""
        for child in node.children:
            if child.type == "declaration_list":
                for decl in child.children:
                    self._process_node(decl, source, module)
            elif child.type in (
                "class_declaration",
                "interface_declaration",
                "struct_declaration",
                "record_declaration",
            ):
                self._process_node(child, source, module)

    def _extract_using(self, node: Node, source: bytes) -> ImportDef | None:
        """Extract using directive."""
        # using System;
        # using System.Collections.Generic;
        # using Alias = Namespace;
        module_name = ""
        alias = None

        for child in node.children:
            if child.type == "identifier" or child.type == "qualified_name":
                if alias is None:
                    module_name = get_node_text(child, source)
            elif child.type == "name_equals":
                # This is an alias
                id_node = find_child_by_type(child, "identifier")
                if id_node:
                    alias = get_node_text(id_node, source)

        if not module_name:
            return None

        return ImportDef(
            module=module_name,
            names=[],
            alias=alias,
            is_from=False,
        )

    def _extract_class(self, node: Node, source: bytes) -> ClassDef:
        """Extract class declaration."""
        class_def = ClassDef(
            name="",
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

        # Extract modifiers as decorators
        modifiers = self._extract_modifiers(node, source)
        class_def.decorators = modifiers

        for child in node.children:
            if child.type == "identifier":
                class_def.name = get_node_text(child, source)
            elif child.type == "base_list":
                # Inheritance
                for base_child in child.children:
                    if base_child.type in ("identifier", "qualified_name", "generic_name"):
                        class_def.bases.append(get_node_text(base_child, source))
            elif child.type == "declaration_list":
                self._extract_class_body(child, source, class_def)

        return class_def

    def _extract_interface(self, node: Node, source: bytes) -> ClassDef:
        """Extract interface declaration (treat as class)."""
        class_def = self._extract_class(node, source)
        class_def.decorators.insert(0, "interface")
        return class_def

    def _extract_struct(self, node: Node, source: bytes) -> ClassDef:
        """Extract struct declaration (treat as class)."""
        class_def = self._extract_class(node, source)
        class_def.decorators.insert(0, "struct")
        return class_def

    def _extract_record(self, node: Node, source: bytes) -> ClassDef:
        """Extract record declaration (treat as class)."""
        class_def = self._extract_class(node, source)
        class_def.decorators.insert(0, "record")
        return class_def

    def _extract_class_body(self, body: Node, source: bytes, class_def: ClassDef) -> None:
        """Extract class body contents."""
        for child in body.children:
            if child.type == "method_declaration":
                method = self._extract_method(child, source)
                class_def.methods.append(method)
            elif child.type == "constructor_declaration":
                method = self._extract_constructor(child, source, class_def.name)
                class_def.methods.append(method)
            elif child.type == "property_declaration":
                prop_name = self._extract_property_name(child, source)
                if prop_name:
                    class_def.attributes.append(prop_name)
            elif child.type == "field_declaration":
                field_names = self._extract_field_names(child, source)
                class_def.attributes.extend(field_names)
            elif child.type == "indexer_declaration":
                method = self._extract_indexer(child, source)
                class_def.methods.append(method)

    def _extract_method(self, node: Node, source: bytes) -> FunctionDef:
        """Extract method declaration."""
        func_def = FunctionDef(
            name="",
            is_method=True,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

        # Extract modifiers
        modifiers = self._extract_modifiers(node, source)
        func_def.decorators = modifiers

        if "static" in modifiers:
            func_def.is_static = True
        if "async" in modifiers:
            func_def.is_async = True

        for child in node.children:
            if child.type == "identifier":
                func_def.name = get_node_text(child, source)
            elif child.type in ("predefined_type", "identifier", "qualified_name", "generic_name", "nullable_type", "array_type"):
                # Return type comes before method name
                if not func_def.name:
                    func_def.return_type = get_node_text(child, source)
                else:
                    # This is the method name
                    pass
            elif child.type == "parameter_list":
                func_def.parameters = self._extract_parameters(child, source)
            elif child.type == "block":
                func_def.body_complexity = count_nodes(child)
                func_def.body_source = get_node_text(child, source)
            elif child.type == "arrow_expression_clause":
                func_def.body_complexity = count_nodes(child)
                func_def.body_source = get_node_text(child, source)

        return func_def

    def _extract_constructor(self, node: Node, source: bytes, class_name: str) -> FunctionDef:
        """Extract constructor declaration."""
        func_def = FunctionDef(
            name=class_name,
            is_method=True,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

        modifiers = self._extract_modifiers(node, source)
        func_def.decorators = ["constructor"] + modifiers

        for child in node.children:
            if child.type == "parameter_list":
                func_def.parameters = self._extract_parameters(child, source)
            elif child.type == "block":
                func_def.body_complexity = count_nodes(child)
                func_def.body_source = get_node_text(child, source)

        return func_def

    def _extract_indexer(self, node: Node, source: bytes) -> FunctionDef:
        """Extract indexer declaration."""
        func_def = FunctionDef(
            name="this[]",
            is_method=True,
            is_property=True,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

        for child in node.children:
            if child.type == "bracketed_parameter_list":
                func_def.parameters = self._extract_parameters(child, source)
            elif child.type in ("predefined_type", "identifier", "qualified_name", "generic_name"):
                func_def.return_type = get_node_text(child, source)

        return func_def

    def _extract_parameters(self, node: Node, source: bytes) -> list[ParameterDef]:
        """Extract method parameters."""
        params = []

        for child in node.children:
            if child.type == "parameter":
                params.append(self._extract_parameter(child, source))

        return params

    def _extract_parameter(self, node: Node, source: bytes) -> ParameterDef:
        """Extract a single parameter."""
        name = ""
        type_annotation = None
        default = None
        is_variadic = False

        for child in node.children:
            if child.type == "identifier":
                name = get_node_text(child, source)
            elif child.type in ("predefined_type", "qualified_name", "generic_name", "nullable_type", "array_type"):
                type_annotation = get_node_text(child, source)
            elif child.type == "equals_value_clause":
                # Default value
                for val_child in child.children:
                    if val_child.type != "=":
                        default = get_node_text(val_child, source)
                        break
            elif child.type == "parameter_modifier":
                modifier = get_node_text(child, source)
                if modifier == "params":
                    is_variadic = True

        return ParameterDef(
            name=name,
            type_annotation=type_annotation,
            default_value=default,
            is_variadic=is_variadic,
        )

    def _extract_modifiers(self, node: Node, source: bytes) -> list[str]:
        """Extract modifiers (public, private, static, async, etc.)."""
        modifiers = []
        for child in node.children:
            if child.type == "modifier":
                modifiers.append(get_node_text(child, source))
        return modifiers

    def _extract_property_name(self, node: Node, source: bytes) -> str | None:
        """Extract property name from property declaration."""
        for child in node.children:
            if child.type == "identifier":
                return get_node_text(child, source)
        return None

    def _extract_field_names(self, node: Node, source: bytes) -> list[str]:
        """Extract field names from field declaration."""
        names = []
        for child in node.children:
            if child.type == "variable_declaration":
                for var_child in child.children:
                    if var_child.type == "variable_declarator":
                        id_node = find_child_by_type(var_child, "identifier")
                        if id_node:
                            names.append(get_node_text(id_node, source))
        return names
