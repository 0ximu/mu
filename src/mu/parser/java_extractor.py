"""Java-specific AST extractor using Tree-sitter."""

from __future__ import annotations

from pathlib import Path

from tree_sitter import Node

from mu.parser.base import (
    count_nodes,
    get_node_text,
)
from mu.parser.models import (
    ClassDef,
    FunctionDef,
    ImportDef,
    ModuleDef,
    ParameterDef,
)


class JavaExtractor:
    """Extract AST information from Java source files."""

    def extract(self, root: Node, source: bytes, file_path: str) -> ModuleDef:
        """Extract module definition from Java AST."""
        module = ModuleDef(
            name=Path(file_path).stem,
            path=file_path,
            language="java",
            total_lines=root.end_point[0] + 1,
        )

        # Process top-level declarations
        for child in root.children:
            if child.type == "package_declaration":
                package_name = self._extract_package(child, source)
                if package_name:
                    module.name = package_name
            elif child.type == "import_declaration":
                imp = self._extract_import(child, source)
                if imp:
                    module.imports.append(imp)
            elif child.type == "class_declaration":
                cls = self._extract_class(child, source)
                if cls:
                    module.classes.append(cls)
            elif child.type == "interface_declaration":
                iface = self._extract_interface(child, source)
                if iface:
                    module.classes.append(iface)
            elif child.type == "enum_declaration":
                enum = self._extract_enum(child, source)
                if enum:
                    module.classes.append(enum)
            elif child.type == "record_declaration":
                record = self._extract_record(child, source)
                if record:
                    module.classes.append(record)
            elif child.type == "annotation_type_declaration":
                annotation = self._extract_annotation_type(child, source)
                if annotation:
                    module.classes.append(annotation)

        return module

    def _extract_package(self, node: Node, source: bytes) -> str | None:
        """Extract package declaration."""
        for child in node.children:
            if child.type == "scoped_identifier":
                return get_node_text(child, source)
            elif child.type == "identifier":
                return get_node_text(child, source)
        return None

    def _extract_import(self, node: Node, source: bytes) -> ImportDef | None:
        """Extract import declaration."""
        is_static = False
        is_wildcard = False
        import_path = ""

        for child in node.children:
            if child.type == "static":
                is_static = True
            elif child.type == "scoped_identifier":
                import_path = get_node_text(child, source)
            elif child.type == "identifier":
                import_path = get_node_text(child, source)
            elif child.type == "asterisk":
                is_wildcard = True

        if not import_path:
            return None

        # Handle wildcard imports
        names = ["*"] if is_wildcard else []

        # For static imports, extract the member name
        if is_static and "." in import_path:
            parts = import_path.rsplit(".", 1)
            import_path = parts[0]
            if not is_wildcard:
                names = [parts[1]]

        imp = ImportDef(
            module=import_path,
            names=names,
            alias=None,
            is_from=is_static or is_wildcard,
        )

        if is_static:
            imp.alias = "static"  # Mark as static import

        return imp

    def _extract_class(self, node: Node, source: bytes) -> ClassDef | None:
        """Extract class declaration."""
        cls = ClassDef(
            name="",
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

        for child in node.children:
            if child.type == "modifiers":
                self._extract_modifiers(child, source, cls)
            elif child.type == "identifier":
                cls.name = get_node_text(child, source)
            elif child.type == "type_parameters":
                cls.decorators.append(f"generic:{get_node_text(child, source)}")
            elif child.type == "superclass":
                # extends clause
                for sc in child.children:
                    if sc.type in ("type_identifier", "generic_type", "scoped_type_identifier"):
                        cls.bases.append(get_node_text(sc, source))
            elif child.type == "super_interfaces":
                # implements clause
                for iface in child.children:
                    if iface.type in (
                        "type_identifier",
                        "generic_type",
                        "scoped_type_identifier",
                        "type_list",
                    ):
                        if iface.type == "type_list":
                            for t in iface.children:
                                if t.type in (
                                    "type_identifier",
                                    "generic_type",
                                    "scoped_type_identifier",
                                ):
                                    cls.bases.append(get_node_text(t, source))
                        else:
                            cls.bases.append(get_node_text(iface, source))
            elif child.type == "class_body":
                self._extract_class_body(child, source, cls)

        return cls if cls.name else None

    def _extract_modifiers(
        self, node: Node, source: bytes, cls_or_func: ClassDef | FunctionDef
    ) -> None:
        """Extract modifiers (public, private, static, etc.) and annotations."""
        for child in node.children:
            if child.type in (
                "public",
                "private",
                "protected",
                "static",
                "final",
                "abstract",
                "synchronized",
                "native",
                "transient",
                "volatile",
                "default",
                "strictfp",
            ):
                cls_or_func.decorators.append(child.type)
                if child.type == "static" and isinstance(cls_or_func, FunctionDef):
                    cls_or_func.is_static = True
            elif child.type in ("marker_annotation", "annotation"):
                annotation_text = get_node_text(child, source)
                cls_or_func.decorators.append(annotation_text)

    def _extract_class_body(self, node: Node, source: bytes, cls: ClassDef) -> None:
        """Extract class body members."""
        for child in node.children:
            if child.type == "field_declaration":
                self._extract_field(child, source, cls)
            elif child.type == "method_declaration":
                method = self._extract_method(child, source)
                if method:
                    cls.methods.append(method)
            elif child.type == "constructor_declaration":
                ctor = self._extract_constructor(child, source)
                if ctor:
                    cls.methods.append(ctor)
            elif child.type == "class_declaration":
                # Inner class
                inner = self._extract_class(child, source)
                if inner:
                    inner.decorators.append("inner")
                    cls.methods.append(
                        FunctionDef(
                            name=f"class:{inner.name}",
                            is_method=False,
                            start_line=inner.start_line,
                            end_line=inner.end_line,
                        )
                    )
            elif child.type == "static_initializer":
                cls.methods.append(
                    FunctionDef(
                        name="<clinit>",
                        is_method=True,
                        is_static=True,
                        start_line=child.start_point[0] + 1,
                        end_line=child.end_point[0] + 1,
                    )
                )

    def _extract_field(self, node: Node, source: bytes, cls: ClassDef) -> None:
        """Extract field declaration."""
        modifiers = []
        field_names = []

        for child in node.children:
            if child.type == "modifiers":
                for mod in child.children:
                    if mod.type in (
                        "public",
                        "private",
                        "protected",
                        "static",
                        "final",
                        "transient",
                        "volatile",
                    ):
                        modifiers.append(mod.type)
            elif child.type == "variable_declarator":
                for vc in child.children:
                    if vc.type == "identifier":
                        field_names.append(get_node_text(vc, source))

        for name in field_names:
            if "public" in modifiers:
                cls.attributes.append(f"public {name}")
            elif "private" in modifiers:
                cls.attributes.append(f"private {name}")
            elif "protected" in modifiers:
                cls.attributes.append(f"protected {name}")
            else:
                cls.attributes.append(name)

    def _extract_method(self, node: Node, source: bytes) -> FunctionDef | None:
        """Extract method declaration."""
        method = FunctionDef(
            name="",
            is_method=True,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

        for child in node.children:
            if child.type == "modifiers":
                self._extract_modifiers(child, source, method)
                # Check for async-like patterns
                for mod in child.children:
                    if mod.type in ("marker_annotation", "annotation"):
                        text = get_node_text(mod, source)
                        if "Async" in text:
                            method.is_async = True
            elif child.type == "type_parameters":
                method.decorators.append(f"generic:{get_node_text(child, source)}")
            elif child.type in (
                "type_identifier",
                "generic_type",
                "void_type",
                "integral_type",
                "floating_point_type",
                "boolean_type",
                "scoped_type_identifier",
                "array_type",
            ):
                method.return_type = get_node_text(child, source)
            elif child.type == "identifier":
                method.name = get_node_text(child, source)
            elif child.type == "formal_parameters":
                method.parameters = self._extract_parameters(child, source)
            elif child.type == "throws":
                # throws clause
                exceptions = []
                for exc in child.children:
                    if exc.type in ("type_identifier", "scoped_type_identifier"):
                        exceptions.append(get_node_text(exc, source))
                if exceptions:
                    method.decorators.append(f"throws:{','.join(exceptions)}")
            elif child.type == "block":
                method.body_complexity = count_nodes(child)
                method.body_source = get_node_text(child, source)

        return method if method.name else None

    def _extract_constructor(self, node: Node, source: bytes) -> FunctionDef | None:
        """Extract constructor declaration."""
        ctor = FunctionDef(
            name="",
            is_method=True,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )
        ctor.decorators.append("constructor")

        for child in node.children:
            if child.type == "modifiers":
                self._extract_modifiers(child, source, ctor)
            elif child.type == "identifier":
                ctor.name = get_node_text(child, source)
            elif child.type == "type_parameters":
                ctor.decorators.append(f"generic:{get_node_text(child, source)}")
            elif child.type == "formal_parameters":
                ctor.parameters = self._extract_parameters(child, source)
            elif child.type == "throws":
                exceptions = []
                for exc in child.children:
                    if exc.type in ("type_identifier", "scoped_type_identifier"):
                        exceptions.append(get_node_text(exc, source))
                if exceptions:
                    ctor.decorators.append(f"throws:{','.join(exceptions)}")
            elif child.type == "constructor_body":
                ctor.body_complexity = count_nodes(child)
                ctor.body_source = get_node_text(child, source)

        return ctor if ctor.name else None

    def _extract_parameters(self, node: Node, source: bytes) -> list[ParameterDef]:
        """Extract method parameters."""
        params = []

        for child in node.children:
            if child.type == "formal_parameter":
                param = self._extract_parameter(child, source)
                if param:
                    params.append(param)
            elif child.type == "spread_parameter":
                # Varargs: String... args
                param = self._extract_spread_parameter(child, source)
                if param:
                    params.append(param)
            elif child.type == "receiver_parameter":
                # Explicit receiver: EnclosingClass.this
                params.append(ParameterDef(name="this", type_annotation="receiver"))

        return params

    def _extract_parameter(self, node: Node, source: bytes) -> ParameterDef | None:
        """Extract a single parameter."""
        name = ""
        type_annotation = None
        is_final = False
        annotations = []

        for child in node.children:
            if child.type == "modifiers":
                for mod in child.children:
                    if mod.type == "final":
                        is_final = True
                    elif mod.type in ("marker_annotation", "annotation"):
                        annotations.append(get_node_text(mod, source))
            elif child.type in (
                "type_identifier",
                "generic_type",
                "integral_type",
                "floating_point_type",
                "boolean_type",
                "array_type",
                "scoped_type_identifier",
            ):
                type_annotation = get_node_text(child, source)
            elif child.type == "identifier":
                name = get_node_text(child, source)

        if not name:
            return None

        if is_final and type_annotation:
            type_annotation = f"final {type_annotation}"

        param = ParameterDef(name=name, type_annotation=type_annotation)
        return param

    def _extract_spread_parameter(self, node: Node, source: bytes) -> ParameterDef | None:
        """Extract varargs parameter."""
        name = ""
        type_annotation = None

        for child in node.children:
            if child.type in (
                "type_identifier",
                "generic_type",
                "integral_type",
                "floating_point_type",
                "boolean_type",
                "scoped_type_identifier",
            ):
                type_annotation = get_node_text(child, source) + "..."
            elif child.type == "variable_declarator":
                for vc in child.children:
                    if vc.type == "identifier":
                        name = get_node_text(vc, source)
            elif child.type == "identifier":
                name = get_node_text(child, source)

        if not name:
            return None

        return ParameterDef(name=name, type_annotation=type_annotation, is_variadic=True)

    def _extract_interface(self, node: Node, source: bytes) -> ClassDef | None:
        """Extract interface declaration."""
        iface = ClassDef(
            name="",
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )
        iface.decorators.append("interface")

        for child in node.children:
            if child.type == "modifiers":
                self._extract_modifiers(child, source, iface)
            elif child.type == "identifier":
                iface.name = get_node_text(child, source)
            elif child.type == "type_parameters":
                iface.decorators.append(f"generic:{get_node_text(child, source)}")
            elif child.type == "extends_interfaces":
                for ext in child.children:
                    if ext.type in (
                        "type_identifier",
                        "generic_type",
                        "scoped_type_identifier",
                        "type_list",
                    ):
                        if ext.type == "type_list":
                            for t in ext.children:
                                if t.type in (
                                    "type_identifier",
                                    "generic_type",
                                    "scoped_type_identifier",
                                ):
                                    iface.bases.append(get_node_text(t, source))
                        else:
                            iface.bases.append(get_node_text(ext, source))
            elif child.type == "interface_body":
                self._extract_interface_body(child, source, iface)

        return iface if iface.name else None

    def _extract_interface_body(self, node: Node, source: bytes, iface: ClassDef) -> None:
        """Extract interface body members."""
        for child in node.children:
            if child.type == "method_declaration":
                method = self._extract_method(child, source)
                if method:
                    iface.methods.append(method)
            elif child.type == "constant_declaration":
                # Interface constants
                for vc in child.children:
                    if vc.type == "variable_declarator":
                        for vcc in vc.children:
                            if vcc.type == "identifier":
                                iface.attributes.append(get_node_text(vcc, source))

    def _extract_enum(self, node: Node, source: bytes) -> ClassDef | None:
        """Extract enum declaration."""
        enum = ClassDef(
            name="",
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )
        enum.decorators.append("enum")

        for child in node.children:
            if child.type == "modifiers":
                self._extract_modifiers(child, source, enum)
            elif child.type == "identifier":
                enum.name = get_node_text(child, source)
            elif child.type == "super_interfaces":
                # implements clause
                for iface in child.children:
                    if iface.type in (
                        "type_identifier",
                        "generic_type",
                        "scoped_type_identifier",
                        "type_list",
                    ):
                        if iface.type == "type_list":
                            for t in iface.children:
                                if t.type in ("type_identifier", "generic_type"):
                                    enum.bases.append(get_node_text(t, source))
                        else:
                            enum.bases.append(get_node_text(iface, source))
            elif child.type == "enum_body":
                self._extract_enum_body(child, source, enum)

        return enum if enum.name else None

    def _extract_enum_body(self, node: Node, source: bytes, enum: ClassDef) -> None:
        """Extract enum body."""
        for child in node.children:
            if child.type == "enum_constant":
                for ec in child.children:
                    if ec.type == "identifier":
                        enum.attributes.append(get_node_text(ec, source))
                        break
            elif child.type == "enum_body_declarations":
                # Methods and fields in enum
                for decl in child.children:
                    if decl.type == "method_declaration":
                        method = self._extract_method(decl, source)
                        if method:
                            enum.methods.append(method)
                    elif decl.type == "constructor_declaration":
                        ctor = self._extract_constructor(decl, source)
                        if ctor:
                            enum.methods.append(ctor)

    def _extract_record(self, node: Node, source: bytes) -> ClassDef | None:
        """Extract record declaration (Java 14+)."""
        record = ClassDef(
            name="",
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )
        record.decorators.append("record")

        for child in node.children:
            if child.type == "modifiers":
                self._extract_modifiers(child, source, record)
            elif child.type == "identifier":
                record.name = get_node_text(child, source)
            elif child.type == "type_parameters":
                record.decorators.append(f"generic:{get_node_text(child, source)}")
            elif child.type == "formal_parameters":
                # Record components are the constructor params
                params = self._extract_parameters(child, source)
                for param in params:
                    record.attributes.append(param.name)
            elif child.type == "super_interfaces":
                for iface in child.children:
                    if iface.type in (
                        "type_identifier",
                        "generic_type",
                        "scoped_type_identifier",
                        "type_list",
                    ):
                        if iface.type == "type_list":
                            for t in iface.children:
                                if t.type in ("type_identifier", "generic_type"):
                                    record.bases.append(get_node_text(t, source))
                        else:
                            record.bases.append(get_node_text(iface, source))
            elif child.type == "class_body":
                self._extract_class_body(child, source, record)

        return record if record.name else None

    def _extract_annotation_type(self, node: Node, source: bytes) -> ClassDef | None:
        """Extract annotation type declaration."""
        annotation = ClassDef(
            name="",
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )
        annotation.decorators.append("@interface")

        for child in node.children:
            if child.type == "modifiers":
                self._extract_modifiers(child, source, annotation)
            elif child.type == "identifier":
                annotation.name = get_node_text(child, source)
            elif child.type == "annotation_type_body":
                for member in child.children:
                    if member.type == "annotation_type_element_declaration":
                        # Extract annotation elements as methods
                        for elem in member.children:
                            if elem.type == "identifier":
                                annotation.attributes.append(get_node_text(elem, source))

        return annotation if annotation.name else None
