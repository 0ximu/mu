"""Base parser infrastructure and language routing."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from tree_sitter import Language, Node, Parser

from mu.errors import UnsupportedLanguageError
from mu.logging import get_logger
from mu.parser.models import ModuleDef

# Check if Rust core is available and should be used
_USE_RUST_CORE = False
try:
    from mu import _core as rust_core

    # Allow disabling via environment variable
    if os.environ.get("MU_DISABLE_RUST_CORE", "").lower() not in ("1", "true", "yes"):
        _USE_RUST_CORE = True
except ImportError:
    rust_core = None  # type: ignore[assignment]


def use_rust_core() -> bool:
    """Check if Rust core is being used for parsing."""
    return _USE_RUST_CORE


class LanguageExtractor(Protocol):
    """Protocol for language-specific AST extractors."""

    def extract(self, root: Node, source: bytes, file_path: str) -> ModuleDef:
        """Extract module definition from AST root node."""
        ...


@dataclass
class ParsedFile:
    """Result of parsing a single file."""

    path: str
    language: str
    module: ModuleDef | None = None
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.module is not None and self.error is None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "path": self.path,
            "language": self.language,
            "success": self.success,
        }
        if self.module:
            result["module"] = self.module.to_dict()
        if self.error:
            result["error"] = self.error
        return result


# Language registry
_languages: dict[str, Language] = {}
_extractors: dict[str, LanguageExtractor] = {}


def _get_language(lang: str) -> Language:
    """Get or create Tree-sitter Language instance."""
    if lang not in _languages:
        if lang == "python":
            import tree_sitter_python as tspython

            _languages[lang] = Language(tspython.language())
        elif lang in ("typescript", "tsx", "javascript", "jsx"):
            import tree_sitter_javascript as tsjavascript
            import tree_sitter_typescript as tstypescript

            if lang == "typescript":
                _languages[lang] = Language(tstypescript.language_typescript())
            elif lang == "tsx":
                _languages[lang] = Language(tstypescript.language_tsx())
            elif lang == "jsx":
                # JSX uses the JavaScript grammar which supports JSX
                _languages[lang] = Language(tsjavascript.language())
            else:
                _languages[lang] = Language(tsjavascript.language())
        elif lang == "csharp":
            import tree_sitter_c_sharp as tscsharp

            _languages[lang] = Language(tscsharp.language())
        elif lang == "go":
            import tree_sitter_go as tsgo

            _languages[lang] = Language(tsgo.language())
        elif lang == "rust":
            import tree_sitter_rust as tsrust

            _languages[lang] = Language(tsrust.language())
        elif lang == "java":
            import tree_sitter_java as tsjava

            _languages[lang] = Language(tsjava.language())
        else:
            raise UnsupportedLanguageError(lang, "")
    return _languages[lang]


def _get_extractor(lang: str) -> LanguageExtractor:
    """Get or create language-specific extractor."""
    if lang not in _extractors:
        if lang == "python":
            from mu.parser.python_extractor import PythonExtractor

            _extractors[lang] = PythonExtractor()
        elif lang in ("typescript", "tsx", "javascript", "jsx"):
            from mu.parser.typescript_extractor import TypeScriptExtractor

            _extractors[lang] = TypeScriptExtractor()
        elif lang == "csharp":
            from mu.parser.csharp_extractor import CSharpExtractor

            _extractors[lang] = CSharpExtractor()
        elif lang == "go":
            from mu.parser.go_extractor import GoExtractor

            _extractors[lang] = GoExtractor()
        elif lang == "rust":
            from mu.parser.rust_extractor import RustExtractor

            _extractors[lang] = RustExtractor()
        elif lang == "java":
            from mu.parser.java_extractor import JavaExtractor

            _extractors[lang] = JavaExtractor()
        else:
            raise UnsupportedLanguageError(lang, "")
    return _extractors[lang]


def _rust_module_to_python(rust_module: Any, stored_path: str) -> ModuleDef:
    """Convert Rust ModuleDef to Python ModuleDef.

    The Rust types are PyO3-bound and need conversion to Python dataclasses.
    """
    from mu.parser.models import CallSiteDef, ClassDef, FunctionDef, ImportDef, ParameterDef

    def convert_param(p: Any) -> ParameterDef:
        return ParameterDef(
            name=p.name,
            type_annotation=p.type_annotation,
            default_value=p.default_value,
            is_variadic=p.is_variadic,
            is_keyword=p.is_keyword,
        )

    def convert_call_site(c: Any) -> CallSiteDef:
        return CallSiteDef(
            callee=c.callee,
            line=c.line,
            is_method_call=c.is_method_call,
            receiver=c.receiver,
        )

    def convert_func(f: Any) -> FunctionDef:
        # Get call_sites if present (Rust parser provides this)
        call_sites = []
        if hasattr(f, "call_sites") and f.call_sites:
            call_sites = [convert_call_site(c) for c in f.call_sites]

        return FunctionDef(
            name=f.name,
            decorators=list(f.decorators),
            parameters=[convert_param(p) for p in f.parameters],
            return_type=f.return_type,
            is_async=f.is_async,
            is_static=f.is_static,
            is_classmethod=f.is_classmethod,
            is_property=f.is_property,
            is_method=f.is_method,
            docstring=f.docstring,
            body_complexity=f.body_complexity,
            body_source=f.body_source,
            call_sites=call_sites,
            start_line=f.start_line,
            end_line=f.end_line,
        )

    def convert_class(c: Any) -> ClassDef:
        return ClassDef(
            name=c.name,
            bases=list(c.bases),
            decorators=list(c.decorators),
            docstring=c.docstring,
            methods=[convert_func(m) for m in c.methods],
            attributes=list(c.attributes),
            start_line=c.start_line,
            end_line=c.end_line,
        )

    def convert_import(i: Any) -> ImportDef:
        return ImportDef(
            module=i.module,
            names=list(i.names),
            alias=i.alias,
            is_from=i.is_from,
            is_dynamic=i.is_dynamic,
            dynamic_pattern=i.dynamic_pattern,
            dynamic_source=i.dynamic_source,
            line_number=i.line_number,
        )

    return ModuleDef(
        name=rust_module.name,
        path=stored_path,
        language=rust_module.language,
        module_docstring=rust_module.module_docstring,
        imports=[convert_import(i) for i in rust_module.imports],
        classes=[convert_class(c) for c in rust_module.classes],
        functions=[convert_func(f) for f in rust_module.functions],
        total_lines=rust_module.total_lines,
    )


def _parse_file_rust(
    file_path: Path,
    language: str,
    stored_path: str,
) -> ParsedFile:
    """Parse file using Rust core."""
    result = ParsedFile(path=stored_path, language=language)

    try:
        source = file_path.read_text(errors="replace")
        rust_result = rust_core.parse_file(source, stored_path, language)

        if rust_result.error:
            result.error = rust_result.error
        elif rust_result.module:
            result.module = _rust_module_to_python(rust_result.module, stored_path)
        else:
            result.error = "No module returned from Rust parser"

    except FileNotFoundError:
        result.error = f"File not found: {file_path}"
    except PermissionError:
        result.error = f"Permission denied: {file_path}"
    except Exception as e:
        get_logger().exception(f"Rust parser error for {file_path}")
        result.error = str(e)

    return result


def _parse_file_python(
    file_path: Path,
    language: str,
    stored_path: str,
) -> ParsedFile:
    """Parse file using Python tree-sitter implementation."""
    logger = get_logger()
    result = ParsedFile(path=stored_path, language=language)

    try:
        # Read file content
        source = file_path.read_bytes()

        # Get language and parser
        try:
            lang = _get_language(language)
        except UnsupportedLanguageError:
            result.error = f"Unsupported language: {language}"
            return result

        parser = Parser(lang)

        # Parse the source
        tree = parser.parse(source)
        if tree.root_node.has_error:
            logger.warning(f"Parse errors in {file_path}")

        # Extract AST information
        try:
            extractor = _get_extractor(language)
            result.module = extractor.extract(tree.root_node, source, stored_path)
        except UnsupportedLanguageError:
            result.error = f"No extractor for language: {language}"
            return result

    except FileNotFoundError:
        result.error = f"File not found: {file_path}"
    except PermissionError:
        result.error = f"Permission denied: {file_path}"
    except Exception as e:
        logger.exception(f"Error parsing {file_path}")
        result.error = str(e)

    return result


def parse_file(
    file_path: Path,
    language: str,
    display_path: str | None = None,
) -> ParsedFile:
    """Parse a source file and extract AST information.

    Uses Rust core for parsing when available (2-5x faster).
    Falls back to Python tree-sitter implementation otherwise.

    Args:
        file_path: Path to the source file
        language: Programming language (python, typescript, javascript, csharp)
        display_path: Optional path to use in output (for worktree comparisons)

    Returns:
        ParsedFile with extracted module information or error
    """
    # Use display_path if provided (e.g., relative path for diff comparisons)
    stored_path = display_path if display_path is not None else str(file_path)

    if _USE_RUST_CORE:
        return _parse_file_rust(file_path, language, stored_path)
    else:
        return _parse_file_python(file_path, language, stored_path)


def count_nodes(node: Node) -> int:
    """Count total nodes in a subtree (for complexity measurement)."""
    count = 1
    for child in node.children:
        count += count_nodes(child)
    return count


# Decision point node types by language (tree-sitter node names)
DECISION_POINTS: dict[str, set[str]] = {
    "python": {
        "if_statement",
        "for_statement",
        "while_statement",
        "except_clause",
        "with_statement",
        "assert_statement",
        "boolean_operator",  # 'and', 'or' wrapped by tree-sitter
        "conditional_expression",  # ternary
        "match_statement",
        "case_clause",
        # Comprehension clauses (count each loop/condition inside)
        "for_in_clause",
        "if_clause",
    },
    "typescript": {
        "if_statement",
        "for_statement",
        "while_statement",
        "for_in_statement",
        "do_statement",
        "switch_case",
        "catch_clause",
        "ternary_expression",
        "binary_expression",  # SPECIAL: check operator
    },
    "javascript": {
        "if_statement",
        "for_statement",
        "while_statement",
        "for_in_statement",
        "do_statement",
        "switch_case",
        "catch_clause",
        "ternary_expression",
        "binary_expression",  # SPECIAL: check operator
    },
    "go": {
        "if_statement",
        "for_statement",
        "expression_case",
        "type_case",
        "communication_case",
        "binary_expression",  # SPECIAL: check operator
    },
    "java": {
        "if_statement",
        "for_statement",
        "while_statement",
        "do_statement",
        "enhanced_for_statement",
        "switch_block_statement_group",
        "catch_clause",
        "ternary_expression",
        "binary_expression",  # SPECIAL: check operator
    },
    "rust": {
        "if_expression",
        "for_expression",
        "while_expression",
        "loop_expression",
        "match_expression",
        "match_arm",
        "binary_expression",  # SPECIAL: check operator
    },
    "csharp": {
        "if_statement",
        "for_statement",
        "while_statement",
        "do_statement",
        "foreach_statement",
        "switch_section",
        "catch_clause",
        "conditional_expression",
        "binary_expression",  # SPECIAL: check operator
        "switch_expression",
        "switch_expression_arm",
        "conditional_access_expression",
    },
}

# Binary operators that count as decision points
DECISION_OPERATORS: set[str] = {"&&", "||", "and", "or", "??"}


def calculate_cyclomatic_complexity(node: Node, language: str, source: bytes) -> int:
    """Calculate McCabe cyclomatic complexity (decision point counting).

    Base complexity is 1. Each decision point adds 1.
    Decision points: if, for, while, case, catch, &&, ||, ternary, etc.

    Args:
        node: Tree-sitter AST node (typically function body)
        language: Programming language name
        source: Original source bytes for operator text extraction

    Returns:
        Cyclomatic complexity score (minimum 1)
    """
    decision_types = DECISION_POINTS.get(language, set())
    complexity = 1  # Base complexity

    def _is_decision_operator(n: Node) -> bool:
        """Check if binary_expression has a decision operator."""
        for child in n.children:
            text = source[child.start_byte : child.end_byte].decode("utf-8", errors="replace")
            if text in DECISION_OPERATORS:
                return True
        return False

    def traverse(n: Node) -> None:
        nonlocal complexity

        if n.type in decision_types:
            if n.type == "binary_expression":
                # Only count if operator is && || or ??
                if _is_decision_operator(n):
                    complexity += 1
            else:
                complexity += 1

        for child in n.children:
            traverse(child)

    traverse(node)
    return complexity


def get_node_text(node: Node, source: bytes) -> str:
    """Extract text content of a node."""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def find_children_by_type(node: Node, type_name: str) -> list[Node]:
    """Find all direct children with a specific type."""
    return [child for child in node.children if child.type == type_name]


def find_child_by_type(node: Node, type_name: str) -> Node | None:
    """Find first direct child with a specific type."""
    for child in node.children:
        if child.type == type_name:
            return child
    return None


def find_descendants_by_type(node: Node, type_name: str) -> list[Node]:
    """Find all descendants with a specific type (recursive)."""
    results = []
    if node.type == type_name:
        results.append(node)
    for child in node.children:
        results.extend(find_descendants_by_type(child, type_name))
    return results
