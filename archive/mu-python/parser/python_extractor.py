"""Python-specific AST extractor using Tree-sitter."""

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


class PythonExtractor:
    """Extract AST information from Python source files."""

    def extract(self, root: Node, source: bytes, file_path: str) -> ModuleDef:
        """Extract module definition from Python AST."""
        module = ModuleDef(
            name=Path(file_path).stem,
            path=file_path,
            language="python",
            total_lines=root.end_point[0] + 1,
        )

        # Extract module docstring (first expression if it's a string)
        for child in root.children:
            if child.type == "expression_statement":
                expr = find_child_by_type(child, "string")
                if expr:
                    module.module_docstring = self._extract_string(expr, source)
                break
            elif child.type not in ("comment",):
                break

        # Process top-level statements
        for child in root.children:
            if child.type == "import_statement":
                module.imports.append(self._extract_import(child, source))
            elif child.type == "import_from_statement":
                module.imports.append(self._extract_from_import(child, source))
            elif child.type == "class_definition":
                module.classes.append(self._extract_class(child, source))
            elif child.type == "function_definition":
                module.functions.append(self._extract_function(child, source, is_method=False))
            elif child.type == "decorated_definition":
                decorated = self._extract_decorated(child, source)
                if isinstance(decorated, ClassDef):
                    module.classes.append(decorated)
                elif isinstance(decorated, FunctionDef):
                    module.functions.append(decorated)

        # Detect dynamic imports in entire module
        dynamic_imports = self._extract_dynamic_imports(root, source)
        module.imports.extend(dynamic_imports)

        return module

    def _extract_import(self, node: Node, source: bytes) -> ImportDef:
        """Extract regular import statement."""
        # import x, y, z or import x as alias
        names = []
        alias = None

        for child in node.children:
            if child.type == "dotted_name":
                names.append(get_node_text(child, source))
            elif child.type == "aliased_import":
                name_node = find_child_by_type(child, "dotted_name")
                alias_node = find_child_by_type(child, "identifier")
                if name_node:
                    names.append(get_node_text(name_node, source))
                if alias_node:
                    alias = get_node_text(alias_node, source)

        return ImportDef(
            module=names[0] if names else "",
            names=names[1:] if len(names) > 1 else [],
            alias=alias,
            is_from=False,
        )

    def _extract_from_import(self, node: Node, source: bytes) -> ImportDef:
        """Extract from...import statement."""
        module = ""
        names = []
        alias = None
        seen_import_keyword = False

        for child in node.children:
            if child.type == "import":
                seen_import_keyword = True
            elif child.type == "dotted_name":
                if not seen_import_keyword:
                    # Before 'import' keyword = module name
                    module = get_node_text(child, source)
                else:
                    # After 'import' keyword = imported name
                    names.append(get_node_text(child, source))
            elif child.type == "relative_import":
                # Handle relative imports like "from . import x"
                module = get_node_text(child, source)
            elif child.type == "identifier" and seen_import_keyword:
                # Imported name (single identifier, not dotted)
                names.append(get_node_text(child, source))
            elif child.type == "aliased_import":
                name_node = child.children[0] if child.children else None
                if name_node:
                    names.append(get_node_text(name_node, source))
                # Check for alias
                for c in child.children:
                    if c.type == "identifier" and c != name_node:
                        alias = get_node_text(c, source)
            elif child.type == "wildcard_import":
                names.append("*")

        return ImportDef(
            module=module,
            names=names,
            alias=alias,
            is_from=True,
        )

    def _extract_class(
        self, node: Node, source: bytes, decorators: list[str] | None = None
    ) -> ClassDef:
        """Extract class definition."""
        class_def = ClassDef(
            name="",
            decorators=decorators or [],
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

        for child in node.children:
            if child.type == "identifier":
                class_def.name = get_node_text(child, source)
            elif child.type == "argument_list":
                # Base classes
                for arg in child.children:
                    if arg.type == "identifier":
                        class_def.bases.append(get_node_text(arg, source))
                    elif arg.type == "attribute":
                        class_def.bases.append(get_node_text(arg, source))
            elif child.type == "block":
                self._extract_class_body(child, source, class_def)

        # Collect referenced types from methods
        class_def.referenced_types = self._collect_referenced_types(class_def)

        return class_def

    def _collect_referenced_types(self, class_def: ClassDef) -> list[str]:
        """Collect all type references from a class's methods.

        Extracts type names from:
        - Method parameter type annotations
        - Method return type annotations
        """
        type_refs: set[str] = set()

        for method in class_def.methods:
            # Extract from parameters
            for param in method.parameters:
                if param.type_annotation:
                    types = self._extract_type_names(param.type_annotation)
                    type_refs.update(types)

            # Extract from return type
            if method.return_type:
                types = self._extract_type_names(method.return_type)
                type_refs.update(types)

        # Remove self-references and common built-in types
        builtin_types = {
            "str", "int", "float", "bool", "bytes", "None", "Any", "Self",
            "list", "dict", "set", "tuple", "List", "Dict", "Set", "Tuple",
            "Optional", "Union", "Callable", "Iterable", "Iterator", "Generator",
            "Sequence", "Mapping", "Type", "ClassVar", "Final", "Literal",
            "TypeVar", "Generic", "Protocol", "Awaitable", "Coroutine",
            "AsyncIterator", "AsyncIterable", "AsyncGenerator",
            class_def.name,  # Exclude self-reference
        }
        type_refs -= builtin_types

        return sorted(type_refs)

    def _extract_type_names(self, type_annotation: str) -> list[str]:
        """Extract type names from a type annotation string.

        Handles:
        - Simple types: Node, MyClass
        - Generic types: list[Node], dict[str, Node]
        - Union types: Node | None, Union[Node, Error]
        - Nested types: list[dict[str, Node]]
        """
        import re

        # Extract all identifiers that look like type names (capitalized or contain uppercase)
        # This regex matches: Node, MyClass, HTTPClient, etc.
        # But not: str, int, list, dict (common lowercase built-ins)
        pattern = r'\b([A-Z][a-zA-Z0-9_]*)\b'
        matches = re.findall(pattern, type_annotation)

        return matches

    def _extract_class_body(self, block: Node, source: bytes, class_def: ClassDef) -> None:
        """Extract class body contents."""
        first_statement = True

        for child in block.children:
            if child.type == "expression_statement" and first_statement:
                # Check for docstring
                expr = find_child_by_type(child, "string")
                if expr:
                    class_def.docstring = self._extract_string(expr, source)
                first_statement = False
            elif child.type == "function_definition":
                class_def.methods.append(self._extract_function(child, source, is_method=True))
                first_statement = False
            elif child.type == "decorated_definition":
                decorated = self._extract_decorated(child, source, is_method=True)
                if isinstance(decorated, FunctionDef):
                    class_def.methods.append(decorated)
                first_statement = False
            elif child.type == "expression_statement":
                # Look for class attributes (simple assignments at class level)
                assignment = find_child_by_type(child, "assignment")
                if assignment:
                    left = find_child_by_type(assignment, "identifier")
                    if left:
                        class_def.attributes.append(get_node_text(left, source))
                first_statement = False
            else:
                first_statement = False

    def _extract_function(
        self,
        node: Node,
        source: bytes,
        is_method: bool = False,
        decorators: list[str] | None = None,
    ) -> FunctionDef:
        """Extract function/method definition."""
        func_def = FunctionDef(
            name="",
            is_method=is_method,
            decorators=decorators or [],
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

        # Check for async
        for child in node.children:
            if child.type == "async":
                func_def.is_async = True
                break

        # Check decorators for special methods
        for dec in func_def.decorators:
            if dec == "staticmethod":
                func_def.is_static = True
            elif dec == "classmethod":
                func_def.is_classmethod = True
            elif dec == "property":
                func_def.is_property = True

        for child in node.children:
            if child.type == "identifier":
                func_def.name = get_node_text(child, source)
            elif child.type == "parameters":
                func_def.parameters = self._extract_parameters(child, source)
            elif child.type == "type":
                func_def.return_type = get_node_text(child, source)
            elif child.type == "block":
                func_def.body_complexity = calculate_cyclomatic_complexity(child, "python", source)
                # Store the full function body source for LLM summarization
                func_def.body_source = get_node_text(child, source)
                # Check for docstring
                for stmt in child.children:
                    if stmt.type == "expression_statement":
                        expr = find_child_by_type(stmt, "string")
                        if expr:
                            func_def.docstring = self._extract_string(expr, source)
                        break
                    elif stmt.type not in ("comment",):
                        break

        return func_def

    def _extract_parameters(self, node: Node, source: bytes) -> list[ParameterDef]:
        """Extract function parameters."""
        params = []

        for child in node.children:
            if child.type == "identifier":
                params.append(ParameterDef(name=get_node_text(child, source)))
            elif child.type == "typed_parameter":
                param = self._extract_typed_parameter(child, source)
                params.append(param)
            elif child.type == "default_parameter":
                param = self._extract_default_parameter(child, source)
                params.append(param)
            elif child.type == "typed_default_parameter":
                param = self._extract_typed_default_parameter(child, source)
                params.append(param)
            elif child.type == "list_splat_pattern":
                # *args
                name_node = find_child_by_type(child, "identifier")
                name = get_node_text(name_node, source) if name_node else "args"
                params.append(ParameterDef(name=name, is_variadic=True))
            elif child.type == "dictionary_splat_pattern":
                # **kwargs
                name_node = find_child_by_type(child, "identifier")
                name = get_node_text(name_node, source) if name_node else "kwargs"
                params.append(ParameterDef(name=name, is_keyword=True))

        return params

    def _extract_typed_parameter(self, node: Node, source: bytes) -> ParameterDef:
        """Extract a typed parameter (name: type)."""
        name = ""
        type_annotation = None

        for child in node.children:
            if child.type == "identifier":
                name = get_node_text(child, source)
            elif child.type == "type":
                type_annotation = get_node_text(child, source)

        return ParameterDef(name=name, type_annotation=type_annotation)

    def _extract_default_parameter(self, node: Node, source: bytes) -> ParameterDef:
        """Extract a parameter with default value (name=value)."""
        name = ""
        default = None

        children = list(node.children)
        for i, child in enumerate(children):
            if child.type == "identifier" and not name:
                name = get_node_text(child, source)
            elif child.type == "=":
                # Next child is the default value
                if i + 1 < len(children):
                    default = get_node_text(children[i + 1], source)

        return ParameterDef(name=name, default_value=default)

    def _extract_typed_default_parameter(self, node: Node, source: bytes) -> ParameterDef:
        """Extract a typed parameter with default value (name: type = value)."""
        name = ""
        type_annotation = None
        default = None

        children = list(node.children)
        for i, child in enumerate(children):
            if child.type == "identifier" and not name:
                name = get_node_text(child, source)
            elif child.type == "type":
                type_annotation = get_node_text(child, source)
            elif child.type == "=":
                # Next child is the default value
                if i + 1 < len(children):
                    default = get_node_text(children[i + 1], source)

        return ParameterDef(name=name, type_annotation=type_annotation, default_value=default)

    def _extract_decorated(
        self,
        node: Node,
        source: bytes,
        is_method: bool = False,
    ) -> ClassDef | FunctionDef:
        """Extract decorated class or function."""
        decorators = []

        for child in node.children:
            if child.type == "decorator":
                dec_text = get_node_text(child, source)
                # Remove @ prefix
                if dec_text.startswith("@"):
                    dec_text = dec_text[1:]
                # Get just the decorator name (not arguments)
                if "(" in dec_text:
                    dec_text = dec_text[: dec_text.index("(")]
                decorators.append(dec_text)
            elif child.type == "class_definition":
                return self._extract_class(child, source, decorators)
            elif child.type == "function_definition":
                return self._extract_function(child, source, is_method, decorators)

        # Fallback - shouldn't reach here
        return FunctionDef(name="unknown", decorators=decorators)

    def _extract_string(self, node: Node, source: bytes) -> str:
        """Extract string content, removing quotes."""
        text = get_node_text(node, source)
        # Handle triple-quoted strings
        if text.startswith('"""') or text.startswith("'''"):
            return text[3:-3].strip()
        # Handle regular strings
        elif text.startswith('"') or text.startswith("'"):
            return text[1:-1]
        # Handle f-strings and other prefixed strings
        elif len(text) > 1 and text[1] in ('"', "'"):
            if text[2:4] in ('""', "''"):
                return text[4:-3].strip()
            return text[2:-1]
        return text

    def _extract_dynamic_imports(self, root: Node, source: bytes) -> list[ImportDef]:
        """Extract dynamic import patterns from the AST.

        Detects:
        - importlib.import_module("module") or importlib.import_module(f"plugins.{name}")
        - __import__("module")
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
        if node.type == "call":
            dynamic_import = self._check_dynamic_import_call(node, source)
            if dynamic_import:
                results.append(dynamic_import)

        # Recurse into children
        for child in node.children:
            self._find_dynamic_imports_recursive(child, source, results)

    def _check_dynamic_import_call(self, node: Node, source: bytes) -> ImportDef | None:
        """Check if a call node is a dynamic import pattern."""
        # Get the function being called
        func_node = find_child_by_type(node, "attribute") or find_child_by_type(node, "identifier")
        if not func_node:
            return None

        func_text = get_node_text(func_node, source)
        line_number = node.start_point[0] + 1

        # Check for importlib.import_module()
        if func_text == "importlib.import_module" or func_text.endswith(".import_module"):
            return self._extract_importlib_call(node, source, line_number)

        # Check for __import__()
        if func_text == "__import__":
            return self._extract_builtin_import_call(node, source, line_number)

        return None

    def _extract_importlib_call(
        self, node: Node, source: bytes, line_number: int
    ) -> ImportDef | None:
        """Extract importlib.import_module() call."""
        args_node = find_child_by_type(node, "argument_list")
        if not args_node:
            return None

        # Get first argument (the module name/pattern)
        first_arg = None
        for child in args_node.children:
            if child.type not in ("(", ")", ","):
                first_arg = child
                break

        if not first_arg:
            return None

        arg_text = get_node_text(first_arg, source)

        # Determine if it's a static string or dynamic pattern
        # Note: tree-sitter uses "string" for regular strings and various types for
        # f-strings, concatenated strings, etc.
        if first_arg.type == "string" and not arg_text.startswith(("f'", 'f"', "F'", 'F"')):
            # Static string: importlib.import_module("my_module")
            module_name = self._extract_string(first_arg, source)
            return ImportDef(
                module=module_name,
                is_dynamic=True,
                dynamic_source="importlib",
                line_number=line_number,
            )
        else:
            # Dynamic pattern: f-string, variable, concatenation, etc.
            return ImportDef(
                module="<dynamic>",
                is_dynamic=True,
                dynamic_pattern=arg_text,
                dynamic_source="importlib",
                line_number=line_number,
            )

    def _extract_builtin_import_call(
        self, node: Node, source: bytes, line_number: int
    ) -> ImportDef | None:
        """Extract __import__() call."""
        args_node = find_child_by_type(node, "argument_list")
        if not args_node:
            return None

        # Get first argument (the module name/pattern)
        first_arg = None
        for child in args_node.children:
            if child.type not in ("(", ")", ","):
                first_arg = child
                break

        if not first_arg:
            return None

        arg_text = get_node_text(first_arg, source)

        # Determine if it's a static string or dynamic pattern
        if first_arg.type == "string":
            # Static string: __import__("my_module")
            module_name = self._extract_string(first_arg, source)
            return ImportDef(
                module=module_name,
                is_dynamic=True,
                dynamic_source="__import__",
                line_number=line_number,
            )
        else:
            # Dynamic pattern: variable, concatenation, etc.
            return ImportDef(
                module="<dynamic>",
                is_dynamic=True,
                dynamic_pattern=arg_text,
                dynamic_source="__import__",
                line_number=line_number,
            )
