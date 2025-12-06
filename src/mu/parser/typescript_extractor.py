"""TypeScript/JavaScript-specific AST extractor using Tree-sitter."""

from __future__ import annotations

from pathlib import Path

from tree_sitter import Node

from mu.parser.base import (
    count_nodes,
    find_child_by_type,
    find_children_by_type,
    get_node_text,
)
from mu.parser.models import (
    ClassDef,
    FunctionDef,
    ImportDef,
    ModuleDef,
    ParameterDef,
)


class TypeScriptExtractor:
    """Extract AST information from TypeScript/JavaScript source files."""

    def extract(self, root: Node, source: bytes, file_path: str) -> ModuleDef:
        """Extract module definition from TypeScript/JavaScript AST."""
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix == ".tsx":
            language = "tsx"
        elif suffix == ".ts":
            language = "typescript"
        elif suffix == ".jsx":
            language = "jsx"
        else:
            language = "javascript"

        module = ModuleDef(
            name=path.stem,
            path=file_path,
            language=language,
            total_lines=root.end_point[0] + 1,
        )

        # Process top-level statements
        for child in root.children:
            self._process_node(child, source, module)

        # Detect dynamic imports in entire module
        dynamic_imports = self._extract_dynamic_imports(root, source)
        module.imports.extend(dynamic_imports)

        return module

    def _process_node(self, node: Node, source: bytes, module: ModuleDef) -> None:
        """Process a top-level node."""
        if node.type == "import_statement":
            imp = self._extract_import(node, source)
            if imp:
                module.imports.append(imp)
        elif node.type == "class_declaration":
            module.classes.append(self._extract_class(node, source))
        elif node.type == "function_declaration":
            module.functions.append(self._extract_function(node, source))
        elif node.type == "export_statement":
            # Handle exported declarations
            self._process_export(node, source, module)
        elif node.type == "lexical_declaration":
            # const/let declarations - check for arrow functions
            for decl in find_children_by_type(node, "variable_declarator"):
                func = self._extract_arrow_function(decl, source)
                if func:
                    module.functions.append(func)
        elif node.type == "expression_statement":
            # Module-level expressions (e.g., IIFE)
            pass

    def _process_export(self, node: Node, source: bytes, module: ModuleDef) -> None:
        """Process export statement."""
        for child in node.children:
            if child.type == "class_declaration":
                module.classes.append(self._extract_class(child, source))
            elif child.type == "function_declaration":
                module.functions.append(self._extract_function(child, source))
            elif child.type == "lexical_declaration":
                for decl in find_children_by_type(child, "variable_declarator"):
                    func = self._extract_arrow_function(decl, source)
                    if func:
                        module.functions.append(func)

    def _extract_import(self, node: Node, source: bytes) -> ImportDef | None:
        """Extract import statement."""
        # import x from 'module'
        # import { a, b } from 'module'
        # import * as x from 'module'
        module_path = ""
        names = []
        alias = None
        is_from = True

        for child in node.children:
            if child.type == "string":
                module_path = self._extract_string(child, source)
            elif child.type == "import_clause":
                for clause_child in child.children:
                    if clause_child.type == "identifier":
                        # Default import
                        names.append(get_node_text(clause_child, source))
                    elif clause_child.type == "named_imports":
                        # { a, b, c }
                        for spec in find_children_by_type(clause_child, "import_specifier"):
                            name = self._extract_import_specifier(spec, source)
                            if name:
                                names.append(name)
                    elif clause_child.type == "namespace_import":
                        # * as name
                        id_node = find_child_by_type(clause_child, "identifier")
                        if id_node:
                            alias = get_node_text(id_node, source)
                            names.append("*")

        if not module_path:
            return None

        return ImportDef(
            module=module_path,
            names=names,
            alias=alias,
            is_from=is_from,
        )

    def _extract_import_specifier(self, node: Node, source: bytes) -> str | None:
        """Extract import specifier name."""
        identifiers = find_children_by_type(node, "identifier")
        if identifiers:
            # Use the last identifier (handles 'x as y')
            return get_node_text(identifiers[-1], source)
        return None

    def _extract_class(
        self, node: Node, source: bytes, decorators: list[str] | None = None
    ) -> ClassDef:
        """Extract class declaration."""
        class_def = ClassDef(
            name="",
            decorators=decorators or [],
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

        for child in node.children:
            if child.type == "type_identifier" or child.type == "identifier":
                class_def.name = get_node_text(child, source)
            elif child.type == "class_heritage":
                # extends and implements
                for heritage_child in child.children:
                    if heritage_child.type == "extends_clause":
                        type_node = find_child_by_type(heritage_child, "type_identifier")
                        if not type_node:
                            type_node = find_child_by_type(heritage_child, "identifier")
                        if type_node:
                            class_def.bases.append(get_node_text(type_node, source))
                    elif heritage_child.type == "implements_clause":
                        for impl in heritage_child.children:
                            if impl.type in ("type_identifier", "identifier"):
                                class_def.bases.append(get_node_text(impl, source))
            elif child.type == "class_body":
                self._extract_class_body(child, source, class_def)

        return class_def

    def _extract_class_body(self, body: Node, source: bytes, class_def: ClassDef) -> None:
        """Extract class body contents."""
        for child in body.children:
            if child.type == "method_definition":
                method = self._extract_method(child, source)
                class_def.methods.append(method)
            elif child.type == "public_field_definition":
                # Class field/property
                name_node = find_child_by_type(child, "property_identifier")
                if name_node:
                    class_def.attributes.append(get_node_text(name_node, source))
            elif child.type == "field_definition":
                name_node = find_child_by_type(child, "property_identifier")
                if name_node:
                    class_def.attributes.append(get_node_text(name_node, source))

    def _extract_method(self, node: Node, source: bytes) -> FunctionDef:
        """Extract method definition."""
        func_def = FunctionDef(
            name="",
            is_method=True,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

        # Check for async, static, get/set
        for child in node.children:
            if child.type == "async":
                func_def.is_async = True
            elif child.type == "static":
                func_def.is_static = True
            elif child.type == "get":
                func_def.is_property = True
                func_def.decorators.append("getter")
            elif child.type == "set":
                func_def.decorators.append("setter")
            elif child.type == "property_identifier":
                func_def.name = get_node_text(child, source)
            elif child.type == "formal_parameters":
                func_def.parameters = self._extract_parameters(child, source)
            elif child.type == "type_annotation":
                func_def.return_type = self._extract_type_annotation(child, source)
            elif child.type == "statement_block":
                func_def.body_complexity = count_nodes(child)
                func_def.body_source = get_node_text(child, source)

        return func_def

    def _extract_function(self, node: Node, source: bytes) -> FunctionDef:
        """Extract function declaration."""
        func_def = FunctionDef(
            name="",
            is_method=False,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

        for child in node.children:
            if child.type == "async":
                func_def.is_async = True
            elif child.type == "identifier":
                func_def.name = get_node_text(child, source)
            elif child.type == "formal_parameters":
                func_def.parameters = self._extract_parameters(child, source)
            elif child.type == "type_annotation":
                func_def.return_type = self._extract_type_annotation(child, source)
            elif child.type == "statement_block":
                func_def.body_complexity = count_nodes(child)
                func_def.body_source = get_node_text(child, source)

        return func_def

    def _extract_arrow_function(self, node: Node, source: bytes) -> FunctionDef | None:
        """Extract arrow function from variable declarator."""
        name = ""
        arrow_fn = None

        for child in node.children:
            if child.type == "identifier":
                name = get_node_text(child, source)
            elif child.type == "arrow_function":
                arrow_fn = child

        if not arrow_fn or not name:
            return None

        func_def = FunctionDef(
            name=name,
            is_method=False,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

        for child in arrow_fn.children:
            if child.type == "async":
                func_def.is_async = True
            elif child.type == "formal_parameters":
                func_def.parameters = self._extract_parameters(child, source)
            elif child.type == "identifier":
                # Single parameter without parens
                func_def.parameters.append(ParameterDef(name=get_node_text(child, source)))
            elif child.type == "type_annotation":
                func_def.return_type = self._extract_type_annotation(child, source)
            elif child.type == "statement_block":
                func_def.body_complexity = count_nodes(child)
                func_def.body_source = get_node_text(child, source)

        return func_def

    def _extract_parameters(self, node: Node, source: bytes) -> list[ParameterDef]:
        """Extract function parameters."""
        params = []

        for child in node.children:
            if child.type == "identifier":
                params.append(ParameterDef(name=get_node_text(child, source)))
            elif child.type == "required_parameter":
                params.append(self._extract_typed_parameter(child, source))
            elif child.type == "optional_parameter":
                param = self._extract_typed_parameter(child, source)
                if param.default_value is None:
                    param.default_value = "undefined"
                params.append(param)
            elif child.type == "rest_parameter":
                # ...args
                id_node = find_child_by_type(child, "identifier")
                name = get_node_text(id_node, source) if id_node else "args"
                params.append(ParameterDef(name=name, is_variadic=True))

        return params

    def _extract_typed_parameter(self, node: Node, source: bytes) -> ParameterDef:
        """Extract a typed parameter."""
        name = ""
        type_annotation = None
        default = None

        for child in node.children:
            if child.type == "identifier":
                name = get_node_text(child, source)
            elif child.type == "type_annotation":
                type_annotation = self._extract_type_annotation(child, source)
            elif child.type == "=":
                # Find next sibling for default value
                pass
            # Default value comes after =
            elif child.type not in (":", "identifier", "type_annotation", "?"):
                default = get_node_text(child, source)

        return ParameterDef(name=name, type_annotation=type_annotation, default_value=default)

    def _extract_type_annotation(self, node: Node, source: bytes) -> str:
        """Extract type annotation text."""
        # Skip the colon and get the type
        for child in node.children:
            if child.type not in (":",):
                return get_node_text(child, source)
        return get_node_text(node, source)

    def _extract_string(self, node: Node, source: bytes) -> str:
        """Extract string content, removing quotes."""
        text = get_node_text(node, source)
        if text.startswith('"') or text.startswith("'") or text.startswith("`"):
            return text[1:-1]
        return text

    def _extract_dynamic_imports(self, root: Node, source: bytes) -> list[ImportDef]:
        """Extract dynamic import patterns from the AST.

        Detects:
        - Dynamic import() expressions: import(`./handlers/${type}.js`)
        - require() calls with dynamic arguments: require(moduleName)
        """
        dynamic_imports: list[ImportDef] = []

        # Recursively find all call expressions
        self._find_dynamic_imports_recursive(root, source, dynamic_imports)

        return dynamic_imports

    def _find_dynamic_imports_recursive(
        self,
        node: Node,
        source: bytes,
        results: list[ImportDef],
    ) -> None:
        """Recursively search for dynamic import patterns."""
        # Check for dynamic import() expression
        if node.type == "call_expression":
            dynamic_import = self._check_dynamic_import_call(node, source)
            if dynamic_import:
                results.append(dynamic_import)

        # Recurse into children
        for child in node.children:
            self._find_dynamic_imports_recursive(child, source, results)

    def _check_dynamic_import_call(self, node: Node, source: bytes) -> ImportDef | None:
        """Check if a call expression is a dynamic import pattern."""
        # Get the function being called
        func_node = node.children[0] if node.children else None
        if not func_node:
            return None

        func_text = get_node_text(func_node, source)
        line_number = node.start_point[0] + 1

        # Check for dynamic import() - note: in tree-sitter this is "import" keyword
        if func_node.type == "import" or func_text == "import":
            return self._extract_dynamic_import_expr(node, source, line_number)

        # Check for require() calls
        if func_text == "require":
            return self._extract_require_call(node, source, line_number)

        return None

    def _extract_dynamic_import_expr(
        self, node: Node, source: bytes, line_number: int
    ) -> ImportDef | None:
        """Extract dynamic import() expression."""
        # Find the arguments - typically the second child after "import" keyword
        args_node = find_child_by_type(node, "arguments")
        if not args_node:
            # Try direct children - import() might have args directly
            for child in node.children:
                if child.type == "string" or child.type == "template_string":
                    return self._create_import_def_from_arg(child, source, line_number, "import()")
            return None

        # Get first argument
        first_arg = None
        for child in args_node.children:
            if child.type not in ("(", ")", ","):
                first_arg = child
                break

        if not first_arg:
            return None

        return self._create_import_def_from_arg(first_arg, source, line_number, "import()")

    def _extract_require_call(
        self, node: Node, source: bytes, line_number: int
    ) -> ImportDef | None:
        """Extract require() call."""
        args_node = find_child_by_type(node, "arguments")
        if not args_node:
            return None

        # Get first argument
        first_arg = None
        for child in args_node.children:
            if child.type not in ("(", ")", ","):
                first_arg = child
                break

        if not first_arg:
            return None

        # Only flag as dynamic if the argument is not a simple string literal
        # Static require() calls are already handled by the static import extraction
        if first_arg.type == "string":
            # Static require - skip (handled elsewhere or treat as static)
            return None

        return self._create_import_def_from_arg(first_arg, source, line_number, "require()")

    def _create_import_def_from_arg(
        self,
        arg_node: Node,
        source: bytes,
        line_number: int,
        dynamic_source: str,
    ) -> ImportDef:
        """Create ImportDef from an argument node."""
        arg_text = get_node_text(arg_node, source)

        if arg_node.type == "string":
            # Static string in dynamic import: import("./module")
            module_name = self._extract_string(arg_node, source)
            return ImportDef(
                module=module_name,
                is_dynamic=True,
                dynamic_source=dynamic_source,
                line_number=line_number,
            )
        elif arg_node.type == "template_string":
            # Template literal: import(`./handlers/${type}.js`)
            return ImportDef(
                module="<dynamic>",
                is_dynamic=True,
                dynamic_pattern=arg_text,
                dynamic_source=dynamic_source,
                line_number=line_number,
            )
        else:
            # Variable or expression: import(modulePath)
            return ImportDef(
                module="<dynamic>",
                is_dynamic=True,
                dynamic_pattern=arg_text,
                dynamic_source=dynamic_source,
                line_number=line_number,
            )
