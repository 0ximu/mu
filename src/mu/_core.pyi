# Python type stubs for mu._core
# Auto-generated from Rust types

class ParameterDef:
    """Function/method parameter definition."""

    name: str
    type_annotation: str | None
    default_value: str | None
    is_variadic: bool
    is_keyword: bool

class FunctionDef:
    """Function or method definition."""

    name: str
    decorators: list[str]
    parameters: list[ParameterDef]
    return_type: str | None
    is_async: bool
    is_static: bool
    is_classmethod: bool
    is_property: bool
    is_method: bool
    docstring: str | None
    body_complexity: int
    body_source: str | None
    start_line: int
    end_line: int

class ClassDef:
    """Class or type definition."""

    name: str
    bases: list[str]
    decorators: list[str]
    docstring: str | None
    methods: list[FunctionDef]
    attributes: list[str]
    start_line: int
    end_line: int

class ImportDef:
    """Import statement definition."""

    module: str
    names: list[str]
    alias: str | None
    is_from: bool
    is_dynamic: bool
    dynamic_pattern: str | None
    dynamic_source: str | None
    line_number: int

class ModuleDef:
    """Module-level AST definition."""

    name: str
    path: str
    language: str
    module_docstring: str | None
    imports: list[ImportDef]
    classes: list[ClassDef]
    functions: list[FunctionDef]
    total_lines: int
    error: str | None

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary representation."""
        ...

class FileInfo:
    """File information for parsing."""

    path: str
    source: str
    language: str

class ParseResult:
    """Result of parsing a single file."""

    module: ModuleDef | None
    error: str | None

class SecretMatch:
    """A detected secret in source code."""

    pattern_name: str
    start: int
    end: int
    line: int
    column: int

class GraphEngine:
    """High-performance graph engine for code analysis."""

    def __init__(self, nodes: list[str], edges: list[tuple[str, str, str]]) -> None:
        """Initialize the graph engine with nodes and edges."""
        ...

    def node_count(self) -> int:
        """Return the number of nodes in the graph."""
        ...

    def edge_count(self) -> int:
        """Return the number of edges in the graph."""
        ...

    def edge_types(self) -> list[str]:
        """Return unique edge types in the graph."""
        ...

    def has_node(self, node_id: str) -> bool:
        """Check if a node exists."""
        ...

    def find_cycles(self, edge_types: list[str] | None = None) -> list[list[str]]:
        """Find all cycles (strongly connected components with >1 node)."""
        ...

    def impact(self, node_id: str, edge_types: list[str] | None = None) -> list[str]:
        """Find downstream nodes (what might break if this changes)."""
        ...

    def ancestors(self, node_id: str, edge_types: list[str] | None = None) -> list[str]:
        """Find upstream nodes (what this depends on)."""
        ...

    def shortest_path(
        self,
        from_id: str,
        to_id: str,
        edge_types: list[str] | None = None,
    ) -> list[str] | None:
        """Find shortest path between two nodes."""
        ...

    def neighbors(
        self,
        node_id: str,
        direction: str,
        depth: int,
        edge_types: list[str] | None = None,
    ) -> list[str]:
        """Find neighbors at given depth in given direction."""
        ...

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

def parse_files(file_infos: list[FileInfo], num_threads: int | None = None) -> list[ParseResult]:
    """Parse multiple files in parallel.

    Args:
        file_infos: List of FileInfo objects
        num_threads: Number of threads (default: CPU count)

    Returns:
        List of ParseResult for each file
    """
    ...

def find_secrets(text: str) -> list[SecretMatch]:
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

def version() -> str:
    """Get the version of the Rust core.

    Returns:
        Version string
    """
    ...

# Scanner types and functions

class ScannedFile:
    """Information about a scanned file."""

    path: str
    language: str
    size_bytes: int
    hash: str | None
    lines: int

    def __init__(
        self,
        path: str,
        language: str,
        size_bytes: int,
        hash: str | None = None,
        lines: int = 0,
    ) -> None: ...
    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary representation."""
        ...

class ScanResult:
    """Result of scanning a directory."""

    files: list[ScannedFile]
    skipped_count: int
    error_count: int
    duration_ms: float

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary representation."""
        ...

    def __len__(self) -> int: ...

def scan_directory(
    root_path: str,
    extensions: list[str] | None = None,
    ignore_patterns: list[str] | None = None,
    follow_symlinks: bool = False,
    compute_hashes: bool = False,
    count_lines_flag: bool = False,
) -> ScanResult:
    """Scan a directory for source files.

    Uses the `ignore` crate for fast, parallel traversal with gitignore support.

    Args:
        root_path: Root directory to scan
        extensions: Optional list of file extensions to include (e.g., ["py", "ts"])
        ignore_patterns: Additional patterns to ignore (beyond .gitignore)
        follow_symlinks: Whether to follow symbolic links
        compute_hashes: Whether to compute file hashes (slower but useful for caching)
        count_lines_flag: Whether to count lines in files

    Returns:
        ScanResult containing discovered files and statistics.
    """
    ...
