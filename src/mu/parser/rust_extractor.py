"""Rust-specific AST extractor using Tree-sitter."""

from __future__ import annotations

from pathlib import Path

from tree_sitter import Node

from mu.parser.base import (
    calculate_cyclomatic_complexity,
    find_child_by_type,
    get_node_text,
)
from mu.parser.models import (
    ClassDef,
    FunctionDef,
    ImportDef,
    ModuleDef,
    ParameterDef,
)


class RustExtractor:
    """Extract AST information from Rust source files."""

    def extract(self, root: Node, source: bytes, file_path: str) -> ModuleDef:
        """Extract module definition from Rust AST."""
        module = ModuleDef(
            name=Path(file_path).stem,
            path=file_path,
            language="rust",
            total_lines=root.end_point[0] + 1,
        )

        # Track impl blocks to associate methods with types
        impl_methods: dict[str, list[FunctionDef]] = {}

        # Process top-level items
        for child in root.children:
            if child.type == "use_declaration":
                imports = self._extract_use(child, source)
                module.imports.extend(imports)
            elif child.type == "function_item":
                func = self._extract_function(child, source)
                if func:
                    module.functions.append(func)
            elif child.type == "struct_item":
                struct = self._extract_struct(child, source)
                if struct:
                    module.classes.append(struct)
            elif child.type == "enum_item":
                enum = self._extract_enum(child, source)
                if enum:
                    module.classes.append(enum)
            elif child.type == "trait_item":
                trait = self._extract_trait(child, source)
                if trait:
                    module.classes.append(trait)
            elif child.type == "impl_item":
                self._extract_impl(child, source, impl_methods, module)
            elif child.type == "mod_item":
                # Module declaration - treat as import for internal modules
                mod_import = self._extract_mod(child, source)
                if mod_import:
                    module.imports.append(mod_import)

        # Associate impl methods with their types
        for type_name, methods in impl_methods.items():
            # Find the matching struct/enum/trait
            for cls in module.classes:
                if cls.name == type_name:
                    cls.methods.extend(methods)
                    break
            else:
                # No matching type found - add methods as module-level functions
                for method in methods:
                    method.decorators.append(f"impl:{type_name}")
                    module.functions.append(method)

        return module

    def _extract_use(self, node: Node, source: bytes) -> list[ImportDef]:
        """Extract use declarations."""
        imports = []

        # Find the use path/tree
        for child in node.children:
            if child.type == "scoped_identifier":
                # Simple use: use std::io;
                path = get_node_text(child, source).replace("::", ".")
                imports.append(
                    ImportDef(
                        module=path,
                        names=[],
                        alias=None,
                        is_from=False,
                    )
                )
            elif child.type == "scoped_use_list":
                # Use with list: use std::io::{Read, Write};
                imports.extend(self._extract_scoped_use_list(child, source))
            elif child.type == "use_as_clause":
                # Aliased use: use std::io as io_module;
                path_node = find_child_by_type(child, "scoped_identifier")
                alias_node = find_child_by_type(child, "identifier")
                if path_node and alias_node:
                    path = get_node_text(path_node, source).replace("::", ".")
                    alias = get_node_text(alias_node, source)
                    imports.append(
                        ImportDef(
                            module=path,
                            names=[],
                            alias=alias,
                            is_from=False,
                        )
                    )
            elif child.type == "use_wildcard":
                # Glob import: use std::io::*;
                path_node = find_child_by_type(child, "scoped_identifier")
                if path_node:
                    path = get_node_text(path_node, source).replace("::", ".")
                    imports.append(
                        ImportDef(
                            module=path,
                            names=["*"],
                            alias=None,
                            is_from=True,
                        )
                    )
            elif child.type == "identifier":
                # Simple identifier use: use crate;
                name = get_node_text(child, source)
                imports.append(
                    ImportDef(
                        module=name,
                        names=[],
                        alias=None,
                        is_from=False,
                    )
                )

        return imports

    def _extract_scoped_use_list(self, node: Node, source: bytes) -> list[ImportDef]:
        """Extract scoped use list like std::io::{Read, Write}."""
        imports = []

        # Get the base path
        base_path = ""
        names = []

        for child in node.children:
            if child.type == "scoped_identifier":
                base_path = get_node_text(child, source).replace("::", ".")
            elif child.type == "identifier":
                base_path = get_node_text(child, source)
            elif child.type == "use_list":
                for list_child in child.children:
                    if list_child.type == "identifier":
                        names.append(get_node_text(list_child, source))
                    elif list_child.type == "self":
                        names.append("self")
                    elif list_child.type == "scoped_identifier":
                        # Nested path in use list
                        nested_path = get_node_text(list_child, source).replace("::", ".")
                        imports.append(
                            ImportDef(
                                module=f"{base_path}.{nested_path}" if base_path else nested_path,
                                names=[],
                                alias=None,
                                is_from=False,
                            )
                        )

        if names:
            imports.append(
                ImportDef(
                    module=base_path,
                    names=names,
                    alias=None,
                    is_from=True,
                )
            )

        return imports

    def _extract_function(self, node: Node, source: bytes) -> FunctionDef | None:
        """Extract a function item."""
        func = FunctionDef(
            name="",
            is_method=False,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

        is_async = False

        for child in node.children:
            if child.type == "visibility_modifier":
                func.decorators.append("pub")
            elif child.type == "function_modifiers":
                mods_text = get_node_text(child, source)
                if "async" in mods_text:
                    is_async = True
                if "const" in mods_text:
                    func.decorators.append("const")
                if "unsafe" in mods_text:
                    func.decorators.append("unsafe")
            elif child.type == "identifier":
                func.name = get_node_text(child, source)
            elif child.type == "type_parameters":
                # Generic parameters <T, U>
                func.decorators.append(f"generic:{get_node_text(child, source)}")
            elif child.type == "parameters":
                func.parameters = self._extract_parameters(child, source)
            elif child.type in (
                "type_identifier",
                "primitive_type",
                "generic_type",
                "reference_type",
                "pointer_type",
                "array_type",
                "tuple_type",
                "unit_type",
                "scoped_type_identifier",
            ):
                func.return_type = get_node_text(child, source)
            elif child.type == "block":
                func.body_complexity = calculate_cyclomatic_complexity(child, "rust", source)
                func.body_source = get_node_text(child, source)
            elif child.type == "where_clause":
                func.decorators.append(f"where:{get_node_text(child, source)}")

        func.is_async = is_async

        return func if func.name else None

    def _extract_parameters(self, node: Node, source: bytes) -> list[ParameterDef]:
        """Extract function parameters."""
        params = []

        for child in node.children:
            if child.type == "parameter":
                param = self._extract_parameter(child, source)
                if param:
                    params.append(param)
            elif child.type == "self_parameter":
                # self, &self, &mut self
                self_text = get_node_text(child, source)
                params.append(
                    ParameterDef(
                        name="self",
                        type_annotation=self_text,
                    )
                )

        return params

    def _extract_parameter(self, node: Node, source: bytes) -> ParameterDef | None:
        """Extract a single parameter."""
        name = ""
        type_annotation = None
        is_mutable = False

        for child in node.children:
            if child.type == "identifier":
                name = get_node_text(child, source)
            elif child.type == "mutable_specifier":
                is_mutable = True
            elif child.type in (
                "type_identifier",
                "primitive_type",
                "generic_type",
                "reference_type",
                "pointer_type",
                "array_type",
                "tuple_type",
                "scoped_type_identifier",
                "function_type",
            ):
                type_annotation = get_node_text(child, source)

        if not name:
            return None

        param = ParameterDef(name=name, type_annotation=type_annotation)
        if is_mutable:
            param.type_annotation = f"mut {type_annotation}" if type_annotation else "mut"

        return param

    def _extract_struct(self, node: Node, source: bytes) -> ClassDef | None:
        """Extract a struct definition."""
        struct = ClassDef(
            name="",
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )
        struct.decorators.append("struct")

        for child in node.children:
            if child.type == "visibility_modifier":
                struct.decorators.append("pub")
            elif child.type == "type_identifier":
                struct.name = get_node_text(child, source)
            elif child.type == "type_parameters":
                struct.decorators.append(f"generic:{get_node_text(child, source)}")
            elif child.type == "field_declaration_list":
                self._extract_struct_fields(child, source, struct)
            elif child.type == "ordered_field_declaration_list":
                # Tuple struct: struct Point(i32, i32);
                struct.decorators.append("tuple_struct")
                for i, field_child in enumerate(child.children):
                    if field_child.type in (
                        "type_identifier",
                        "primitive_type",
                        "generic_type",
                        "reference_type",
                    ):
                        struct.attributes.append(f"_{i}")
            elif child.type == "where_clause":
                struct.decorators.append(f"where:{get_node_text(child, source)}")

        return struct if struct.name else None

    def _extract_struct_fields(self, node: Node, source: bytes, struct: ClassDef) -> None:
        """Extract struct fields."""
        for child in node.children:
            if child.type == "field_declaration":
                is_pub = False
                field_name = ""

                for field_child in child.children:
                    if field_child.type == "visibility_modifier":
                        is_pub = True
                    elif field_child.type == "field_identifier":
                        field_name = get_node_text(field_child, source)

                if field_name:
                    if is_pub:
                        struct.attributes.append(f"pub {field_name}")
                    else:
                        struct.attributes.append(field_name)

    def _extract_enum(self, node: Node, source: bytes) -> ClassDef | None:
        """Extract an enum definition."""
        enum = ClassDef(
            name="",
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )
        enum.decorators.append("enum")

        for child in node.children:
            if child.type == "visibility_modifier":
                enum.decorators.append("pub")
            elif child.type == "type_identifier":
                enum.name = get_node_text(child, source)
            elif child.type == "type_parameters":
                enum.decorators.append(f"generic:{get_node_text(child, source)}")
            elif child.type == "enum_variant_list":
                for variant in child.children:
                    if variant.type == "enum_variant":
                        variant_name = ""
                        for vc in variant.children:
                            if vc.type == "identifier":
                                variant_name = get_node_text(vc, source)
                                break
                        if variant_name:
                            enum.attributes.append(variant_name)

        return enum if enum.name else None

    def _extract_trait(self, node: Node, source: bytes) -> ClassDef | None:
        """Extract a trait definition."""
        trait = ClassDef(
            name="",
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )
        trait.decorators.append("trait")

        for child in node.children:
            if child.type == "visibility_modifier":
                trait.decorators.append("pub")
            elif child.type == "type_identifier":
                trait.name = get_node_text(child, source)
            elif child.type == "type_parameters":
                trait.decorators.append(f"generic:{get_node_text(child, source)}")
            elif child.type == "trait_bounds":
                # Supertraits: trait Foo: Bar + Baz
                for bound in child.children:
                    if bound.type in ("type_identifier", "scoped_type_identifier"):
                        trait.bases.append(get_node_text(bound, source))
            elif child.type == "declaration_list":
                self._extract_trait_items(child, source, trait)

        return trait if trait.name else None

    def _extract_trait_items(self, node: Node, source: bytes, trait: ClassDef) -> None:
        """Extract trait method signatures and associated items."""
        for child in node.children:
            if child.type == "function_signature_item":
                method = self._extract_function_signature(child, source)
                if method:
                    trait.methods.append(method)
            elif child.type == "function_item":
                # Default implementation
                method = self._extract_function(child, source)
                if method:
                    method.decorators.append("default")
                    trait.methods.append(method)

    def _extract_function_signature(self, node: Node, source: bytes) -> FunctionDef | None:
        """Extract a function signature (no body)."""
        func = FunctionDef(
            name="",
            is_method=True,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

        for child in node.children:
            if child.type == "identifier":
                func.name = get_node_text(child, source)
            elif child.type == "type_parameters":
                func.decorators.append(f"generic:{get_node_text(child, source)}")
            elif child.type == "parameters":
                func.parameters = self._extract_parameters(child, source)
            elif child.type in (
                "type_identifier",
                "primitive_type",
                "generic_type",
                "reference_type",
                "scoped_type_identifier",
            ):
                func.return_type = get_node_text(child, source)

        return func if func.name else None

    def _extract_impl(
        self,
        node: Node,
        source: bytes,
        impl_methods: dict[str, list[FunctionDef]],
        module: ModuleDef,
    ) -> None:
        """Extract impl block methods."""
        impl_type = ""
        trait_name = None
        is_for_trait = False

        for child in node.children:
            if child.type == "type_identifier":
                if is_for_trait:
                    impl_type = get_node_text(child, source)
                else:
                    # Could be trait name or type name
                    impl_type = get_node_text(child, source)
            elif child.type == "for":
                is_for_trait = True
                trait_name = impl_type
                impl_type = ""
            elif child.type == "generic_type":
                text = get_node_text(child, source)
                if is_for_trait:
                    impl_type = text
                else:
                    impl_type = text
            elif child.type == "declaration_list":
                methods = []
                for decl in child.children:
                    if decl.type == "function_item":
                        method = self._extract_function(decl, source)
                        if method:
                            method.is_method = True
                            if trait_name:
                                method.decorators.append(f"impl:{trait_name}")
                            methods.append(method)

                if impl_type:
                    if impl_type not in impl_methods:
                        impl_methods[impl_type] = []
                    impl_methods[impl_type].extend(methods)
                else:
                    # Trait impl without specific type handling
                    for method in methods:
                        module.functions.append(method)

    def _extract_mod(self, node: Node, source: bytes) -> ImportDef | None:
        """Extract mod declaration as import."""
        mod_name = ""

        for child in node.children:
            if child.type == "identifier":
                mod_name = get_node_text(child, source)

        if mod_name:
            return ImportDef(
                module=mod_name,
                names=[],
                alias=None,
                is_from=False,
            )

        return None
