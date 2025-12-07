# Python type stubs for mu._core
# Auto-generated from Rust types

from typing import List, Optional


class ParameterDef:
    """Function/method parameter definition."""
    name: str
    type_annotation: Optional[str]
    default_value: Optional[str]
    is_variadic: bool
    is_keyword: bool


class FunctionDef:
    """Function or method definition."""
    name: str
    decorators: List[str]
    parameters: List[ParameterDef]
    return_type: Optional[str]
    is_async: bool
    is_static: bool
    is_classmethod: bool
    is_property: bool
    is_method: bool
    docstring: Optional[str]
    body_complexity: int
    body_source: Optional[str]
    start_line: int
    end_line: int


class ClassDef:
    """Class or type definition."""
    name: str
    bases: List[str]
    decorators: List[str]
    docstring: Optional[str]
    methods: List[FunctionDef]
    attributes: List[str]
    start_line: int
    end_line: int


class ImportDef:
    """Import statement definition."""
    module: str
    names: List[str]
    alias: Optional[str]
    is_from: bool
    is_dynamic: bool
    dynamic_pattern: Optional[str]
    dynamic_source: Optional[str]
    line_number: int


class ModuleDef:
    """Module-level AST definition."""
    name: str
    path: str
    language: str
    module_docstring: Optional[str]
    imports: List[ImportDef]
    classes: List[ClassDef]
    functions: List[FunctionDef]
    total_lines: int
    error: Optional[str]

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        ...


class FileInfo:
    """File information for parsing."""
    path: str
    source: str
    language: str


class ParseResult:
    """Result of parsing a single file."""
    module: Optional[ModuleDef]
    error: Optional[str]


class SecretMatch:
    """A detected secret in source code."""
    pattern_name: str
    start: int
    end: int
    line: int
    column: int


def parse_file(source: str, file_path: str, language: str) -> ParseResult:
    """Parse a single source file.

    Args:
        source: Source code content
        file_path: Path to the source file
        language: Language identifier (python, typescript, javascript, go, java, rust, csharp)

    Returns:
        ParseResult containing ModuleDef or error
    """
    ...


def parse_files(file_infos: List[FileInfo], num_threads: Optional[int] = None) -> List[ParseResult]:
    """Parse multiple files in parallel.

    Args:
        file_infos: List of FileInfo objects
        num_threads: Number of threads (default: CPU count)

    Returns:
        List of ParseResult for each file
    """
    ...


def find_secrets(text: str) -> List[SecretMatch]:
    """Find secrets in text.

    Args:
        text: Source code or text to scan

    Returns:
        List of SecretMatch objects
    """
    ...


def redact_secrets(text: str) -> str:
    """Redact secrets from text.

    Args:
        text: Source code or text to redact

    Returns:
        Text with secrets replaced by [REDACTED]
    """
    ...


def calculate_complexity(source: str, language: str) -> int:
    """Calculate cyclomatic complexity for source code.

    Args:
        source: Source code
        language: Language identifier

    Returns:
        Complexity score
    """
    ...


def export_mu(module: ModuleDef) -> str:
    """Export module to MU format.

    Args:
        module: ModuleDef to export

    Returns:
        MU format string
    """
    ...


def export_json(module: ModuleDef, pretty: bool = False) -> str:
    """Export module to JSON format.

    Args:
        module: ModuleDef to export
        pretty: Whether to pretty-print

    Returns:
        JSON string
    """
    ...


def export_markdown(module: ModuleDef) -> str:
    """Export module to Markdown format.

    Args:
        module: ModuleDef to export

    Returns:
        Markdown string
    """
    ...
