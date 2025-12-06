"""Base parser infrastructure and language routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from tree_sitter import Language, Parser, Node

from mu.parser.models import ModuleDef
from mu.errors import ParseError, UnsupportedLanguageError
from mu.logging import get_logger


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
        elif lang in ("typescript", "javascript"):
            import tree_sitter_typescript as tstypescript
            import tree_sitter_javascript as tsjavascript
            if lang == "typescript":
                _languages[lang] = Language(tstypescript.language_typescript())
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
        elif lang in ("typescript", "javascript"):
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


def parse_file(file_path: Path, language: str) -> ParsedFile:
    """Parse a source file and extract AST information.

    Args:
        file_path: Path to the source file
        language: Programming language (python, typescript, javascript, csharp)

    Returns:
        ParsedFile with extracted module information or error
    """
    logger = get_logger()
    result = ParsedFile(path=str(file_path), language=language)

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
            result.module = extractor.extract(tree.root_node, source, str(file_path))
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


def count_nodes(node: Node) -> int:
    """Count total nodes in a subtree (for complexity measurement)."""
    count = 1
    for child in node.children:
        count += count_nodes(child)
    return count


def get_node_text(node: Node, source: bytes) -> str:
    """Extract text content of a node."""
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


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
