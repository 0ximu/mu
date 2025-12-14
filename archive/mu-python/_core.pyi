# Python type stubs for mu._core
# Auto-generated from Rust types

class ParameterDef:
    """Function/method parameter definition."""

    name: str
    type_annotation: str | None
    default_value: str | None
    is_variadic: bool
    is_keyword: bool


class CallSiteDef:
    """A function call site within a function body."""

    callee: str  # "validate_user" or "self.save"
    line: int
    is_method_call: bool  # self.x() vs x()
    receiver: str | None  # "self", "user_service", etc.

    def __init__(
        self,
        callee: str,
        line: int = 0,
        is_method_call: bool = False,
        receiver: str | None = None,
    ) -> None: ...
    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary representation."""
        ...


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
    call_sites: list[CallSiteDef]  # Function calls within this function
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

# Semantic Diff types and functions

class EntityChange:
    """A single semantic change to a code entity."""

    change_type: str
    entity_type: str
    entity_name: str
    file_path: str
    parent_name: str | None
    details: str | None
    old_signature: str | None
    new_signature: str | None
    is_breaking: bool

    def __init__(
        self,
        change_type: str,
        entity_type: str,
        entity_name: str,
        file_path: str,
        parent_name: str | None = None,
        details: str | None = None,
        old_signature: str | None = None,
        new_signature: str | None = None,
        is_breaking: bool = False,
    ) -> None: ...
    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary representation."""
        ...
    def full_name(self) -> str:
        """Get fully qualified entity name."""
        ...

class DiffSummary:
    """Summary statistics for a diff."""

    modules_added: int
    modules_removed: int
    modules_modified: int
    functions_added: int
    functions_removed: int
    functions_modified: int
    classes_added: int
    classes_removed: int
    classes_modified: int
    methods_added: int
    methods_removed: int
    methods_modified: int
    parameters_added: int
    parameters_removed: int
    parameters_modified: int
    imports_added: int
    imports_removed: int
    breaking_changes: int

    def __init__(self) -> None: ...
    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary representation."""
        ...
    def text(self) -> str:
        """Generate human-readable summary string."""
        ...

class SemanticDiffResult:
    """Complete result of a semantic diff operation."""

    changes: list[EntityChange]
    breaking_changes: list[EntityChange]
    summary: DiffSummary
    summary_text: str
    duration_ms: float

    def __init__(self) -> None: ...
    def has_changes(self) -> bool:
        """Check if there are any changes."""
        ...
    def has_breaking_changes(self) -> bool:
        """Check if there are breaking changes."""
        ...
    def change_count(self) -> int:
        """Get change count."""
        ...
    def filter_by_type(self, entity_type: str) -> list[EntityChange]:
        """Filter changes by entity type."""
        ...
    def filter_by_path(self, file_path: str) -> list[EntityChange]:
        """Filter changes by file path."""
        ...
    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary representation."""
        ...
    def __len__(self) -> int: ...

def semantic_diff(
    base_modules: list[ModuleDef],
    head_modules: list[ModuleDef],
) -> SemanticDiffResult:
    """Compute semantic diff between two sets of parsed modules.

    Compares base and head modules to find added, removed, and modified entities
    including modules, functions, classes, methods, and parameters.

    Args:
        base_modules: List of ModuleDef from the base/old version
        head_modules: List of ModuleDef from the head/new version

    Returns:
        SemanticDiffResult containing all changes and statistics.
    """
    ...

def semantic_diff_files(
    base_path: str,
    head_path: str,
    language: str,
    normalize_paths: bool = True,
) -> SemanticDiffResult:
    """Read, parse, and diff two source files in one call.

    Convenience function that handles file reading, parsing, and diffing.
    Useful for CLI integration (mu diff file1.py file2.py --semantic).

    Args:
        base_path: Path to the base/old version file
        head_path: Path to the head/new version file
        language: Language identifier (python, typescript, javascript, go, java, rust, csharp)
        normalize_paths: If True (default), treats both files as the same module
            by using head_path for both. Set to False to compare as different modules.

    Returns:
        SemanticDiffResult containing all changes and statistics.

    Raises:
        IOError: If file cannot be read
        ValueError: If file cannot be parsed
    """
    ...

# Incremental Parser types

class IncrementalParseResult:
    """Result of an incremental parse operation."""

    module: ModuleDef
    parse_time_ms: float
    changed_ranges: list[tuple[int, int]]

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary representation."""
        ...

class IncrementalParser:
    """Incremental parser that maintains tree-sitter state for efficient re-parsing.

    This parser keeps the parse tree and source code in memory, allowing
    subsequent edits to be applied incrementally rather than requiring
    a full re-parse each time. Enables sub-10ms updates in daemon mode.

    Supports: Python, TypeScript, JavaScript, Go, Java, Rust, C#
    """

    def __init__(self, source: str, language: str, file_path: str) -> None:
        """Create a new incremental parser with initial source code.

        Args:
            source: The initial source code
            language: Language identifier (python, typescript, go, etc.)
            file_path: Path to the file (used for module naming)

        Raises:
            ValueError: If the language is not supported
            RuntimeError: If parsing fails
        """
        ...

    def apply_edit(
        self,
        start_byte: int,
        old_end_byte: int,
        new_end_byte: int,
        new_text: str,
    ) -> IncrementalParseResult:
        """Apply an edit to the source and incrementally re-parse.

        Args:
            start_byte: Byte offset where the edit starts
            old_end_byte: Byte offset where the old text ended
            new_end_byte: Byte offset where the new text ends
            new_text: The new text to insert (can be empty for deletions)

        Returns:
            IncrementalParseResult containing the updated module and timing info.

        Raises:
            ValueError: If byte offsets are invalid
            RuntimeError: If parsing fails

        Examples:
            # Insert 'x' at position 100
            result = parser.apply_edit(100, 100, 101, "x")

            # Delete 5 characters starting at position 50
            result = parser.apply_edit(50, 55, 50, "")

            # Replace "foo" with "bar" at position 200 (foo is 3 bytes)
            result = parser.apply_edit(200, 203, 203, "bar")
        """
        ...

    def get_module(self) -> ModuleDef:
        """Get the current module definition.

        Returns:
            The ModuleDef for the current source state.

        Raises:
            RuntimeError: If parsing fails
        """
        ...

    def get_source(self) -> str:
        """Get the current source code."""
        ...

    def get_language(self) -> str:
        """Get the language of this parser."""
        ...

    def get_file_path(self) -> str:
        """Get the file path of this parser."""
        ...

    def byte_to_position(self, byte_offset: int) -> tuple[int, int]:
        """Convert a byte offset to a (line, column) position.

        Args:
            byte_offset: The byte offset in the source

        Returns:
            A tuple of (line, column), both 0-indexed.

        Raises:
            ValueError: If byte_offset is beyond source length
        """
        ...

    def position_to_byte(self, line: int, column: int) -> int:
        """Convert a (line, column) position to a byte offset.

        Args:
            line: The line number (0-indexed)
            column: The column number (0-indexed)

        Returns:
            The byte offset in the source.
        """
        ...

    def has_tree(self) -> bool:
        """Check if the parser has a valid tree."""
        ...

    def has_errors(self) -> bool:
        """Check if the current tree has syntax errors."""
        ...

    def line_count(self) -> int:
        """Get the number of lines in the source."""
        ...

    def byte_count(self) -> int:
        """Get the source length in bytes."""
        ...

    def reset(self, source: str) -> IncrementalParseResult:
        """Reset the parser with new source code.

        This performs a full re-parse, discarding the previous tree.

        Args:
            source: The new source code

        Returns:
            IncrementalParseResult with the parsed module.

        Raises:
            RuntimeError: If parsing fails
        """
        ...
