"""MCP server implementation for MU.

Provides MCP tools for code analysis through the semantic graph.
Uses the daemon client when available, falls back to direct MUbase access.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from mu.client import DEFAULT_DAEMON_URL, DaemonClient, DaemonError

logger = logging.getLogger(__name__)

# Create the MCP server instance
mcp = FastMCP(
    "MU Code Analysis",
    json_response=True,
)


@dataclass
class NodeInfo:
    """Information about a code node."""

    id: str
    type: str
    name: str
    qualified_name: str | None = None
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    complexity: int = 0


@dataclass
class QueryResult:
    """Result of a MUQL query."""

    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    execution_time_ms: float | None = None


@dataclass
class ContextResult:
    """Result of context extraction."""

    mu_text: str
    token_count: int
    node_count: int


@dataclass
class DepsResult:
    """Result of dependency lookup."""

    node_id: str
    direction: str
    dependencies: list[NodeInfo]


@dataclass
class ImpactResult:
    """Result of impact analysis."""

    node_id: str
    impacted_nodes: list[str]
    count: int


@dataclass
class AncestorsResult:
    """Result of ancestors analysis."""

    node_id: str
    ancestor_nodes: list[str]
    count: int


@dataclass
class CyclesResult:
    """Result of cycle detection."""

    cycles: list[list[str]]
    cycle_count: int
    total_nodes_in_cycles: int


def _get_client() -> DaemonClient:
    """Get a daemon client, raising if daemon not running."""
    client = DaemonClient(base_url=DEFAULT_DAEMON_URL)
    if not client.is_running():
        client.close()
        raise DaemonError("MU daemon is not running. Start it with: mu daemon start .")
    return client


def _find_mubase() -> Path | None:
    """Find .mubase file in current directory or parents."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        mubase = parent / ".mubase"
        if mubase.exists():
            return mubase
    return None


@mcp.tool()
def mu_query(query: str) -> QueryResult:
    """Execute a MUQL query against the code graph.

    MUQL is a SQL-like language for querying code structure. Examples:

    - SELECT * FROM functions WHERE complexity > 50
    - SELECT name, file_path FROM classes WHERE name LIKE '%Service%'
    - SHOW dependencies OF AuthService DEPTH 2
    - FIND functions CALLING process_payment
    - ANALYZE complexity

    Args:
        query: The MUQL query to execute

    Returns:
        Query results with columns and rows
    """
    try:
        client = _get_client()
        with client:
            result = client.query(query)

        return QueryResult(
            columns=result.get("columns", []),
            rows=result.get("rows", []),
            row_count=result.get("row_count", len(result.get("rows", []))),
            execution_time_ms=result.get("execution_time_ms"),
        )
    except DaemonError:
        # Try direct access if daemon not running
        mubase_path = _find_mubase()
        if not mubase_path:
            raise DaemonError("No .mubase found. Run 'mu daemon start .' first.") from None

        from mu.kernel import MUbase
        from mu.kernel.muql import MUQLEngine

        db = MUbase(mubase_path)
        try:
            engine = MUQLEngine(db)
            result = engine.query_dict(query)
            return QueryResult(
                columns=result.get("columns", []),
                rows=result.get("rows", []),
                row_count=result.get("row_count", len(result.get("rows", []))),
                execution_time_ms=result.get("execution_time_ms"),
            )
        finally:
            db.close()


@mcp.tool()
def mu_context(question: str, max_tokens: int = 8000) -> ContextResult:
    """Extract smart context for a natural language question.

    Analyzes the question, finds relevant code nodes, and returns
    a token-efficient MU format representation.

    Examples:
    - "How does authentication work?"
    - "What calls the payment processing logic?"
    - "Show me the database models"

    Args:
        question: Natural language question about the codebase
        max_tokens: Maximum tokens in the output (default 8000)

    Returns:
        MU format context with token count
    """
    try:
        client = _get_client()
        with client:
            result = client.context(question, max_tokens=max_tokens)

        return ContextResult(
            mu_text=result.get("mu_text", ""),
            token_count=result.get("token_count", 0),
            node_count=len(result.get("nodes", [])),
        )
    except DaemonError:
        # Try direct access
        mubase_path = _find_mubase()
        if not mubase_path:
            raise DaemonError("No .mubase found. Run 'mu daemon start .' first.") from None

        from mu.kernel import MUbase
        from mu.kernel.context import ExtractionConfig, SmartContextExtractor

        db = MUbase(mubase_path)
        try:
            cfg = ExtractionConfig(max_tokens=max_tokens)
            extractor = SmartContextExtractor(db, cfg)
            ctx_result = extractor.extract(question)
            return ContextResult(
                mu_text=ctx_result.mu_text,
                token_count=ctx_result.token_count,
                node_count=len(ctx_result.nodes),
            )
        finally:
            db.close()


@mcp.tool()
def mu_deps(node_name: str, depth: int = 2, direction: str = "outgoing") -> DepsResult:
    """Show dependencies of a code node.

    Finds what a node depends on (outgoing) or what depends on it (incoming).

    Args:
        node_name: Name or ID of the node (e.g., "AuthService", "mod:src/auth.py")
        depth: How many levels deep to traverse (default 2)
        direction: "outgoing" (what it uses), "incoming" (what uses it), or "both"

    Returns:
        List of dependent nodes
    """
    # Use MUQL SHOW command for dependency traversal
    if direction == "incoming":
        query = f"SHOW dependents OF {node_name} DEPTH {depth}"
    elif direction == "both":
        query = f"SHOW dependencies OF {node_name} DEPTH {depth}"
    else:
        query = f"SHOW dependencies OF {node_name} DEPTH {depth}"

    try:
        client = _get_client()
        with client:
            result = client.query(query)

        # Convert rows to NodeInfo
        columns = result.get("columns", [])
        rows = result.get("rows", [])

        deps = []
        for row in rows:
            row_dict = dict(zip(columns, row, strict=False))
            deps.append(
                NodeInfo(
                    id=row_dict.get("id", ""),
                    type=row_dict.get("type", ""),
                    name=row_dict.get("name", ""),
                    qualified_name=row_dict.get("qualified_name"),
                    file_path=row_dict.get("file_path"),
                    line_start=row_dict.get("line_start"),
                    line_end=row_dict.get("line_end"),
                    complexity=row_dict.get("complexity", 0),
                )
            )

        return DepsResult(
            node_id=node_name,
            direction=direction,
            dependencies=deps,
        )
    except DaemonError:
        mubase_path = _find_mubase()
        if not mubase_path:
            raise DaemonError("No .mubase found. Run 'mu daemon start .' first.") from None

        from mu.kernel import MUbase
        from mu.kernel.muql import MUQLEngine

        db = MUbase(mubase_path)
        try:
            engine = MUQLEngine(db)
            result = engine.query_dict(query)

            columns = result.get("columns", [])
            rows = result.get("rows", [])

            deps = []
            for row in rows:
                row_dict = dict(zip(columns, row, strict=False))
                deps.append(
                    NodeInfo(
                        id=row_dict.get("id", ""),
                        type=row_dict.get("type", ""),
                        name=row_dict.get("name", ""),
                        qualified_name=row_dict.get("qualified_name"),
                        file_path=row_dict.get("file_path"),
                        line_start=row_dict.get("line_start"),
                        line_end=row_dict.get("line_end"),
                        complexity=row_dict.get("complexity", 0),
                    )
                )

            return DepsResult(
                node_id=node_name,
                direction=direction,
                dependencies=deps,
            )
        finally:
            db.close()


@mcp.tool()
def mu_node(node_id: str) -> NodeInfo:
    """Look up a specific code node by ID.

    Node IDs follow the pattern: type:path (e.g., "mod:src/auth.py", "class:AuthService")

    Args:
        node_id: The node ID to look up

    Returns:
        Node information including location and complexity
    """
    try:
        client = _get_client()
        with client:
            # Use a targeted query to find the node
            query = f"SELECT * FROM nodes WHERE id = '{node_id}' LIMIT 1"
            result = client.query(query)

        columns = result.get("columns", [])
        rows = result.get("rows", [])

        if not rows:
            raise ValueError(f"Node not found: {node_id}")

        row_dict = dict(zip(columns, rows[0], strict=False))
        return NodeInfo(
            id=row_dict.get("id", node_id),
            type=row_dict.get("type", ""),
            name=row_dict.get("name", ""),
            qualified_name=row_dict.get("qualified_name"),
            file_path=row_dict.get("file_path"),
            line_start=row_dict.get("line_start"),
            line_end=row_dict.get("line_end"),
            complexity=row_dict.get("complexity", 0),
        )
    except DaemonError:
        mubase_path = _find_mubase()
        if not mubase_path:
            raise DaemonError("No .mubase found. Run 'mu daemon start .' first.") from None

        from mu.kernel import MUbase

        db = MUbase(mubase_path)
        try:
            node = db.get_node(node_id)
            if not node:
                raise ValueError(f"Node not found: {node_id}")

            return NodeInfo(
                id=node.id,
                type=node.type.value,
                name=node.name,
                qualified_name=node.qualified_name,
                file_path=node.file_path,
                line_start=node.line_start,
                line_end=node.line_end,
                complexity=node.complexity,
            )
        finally:
            db.close()


@mcp.tool()
def mu_search(
    pattern: str,
    node_type: str | None = None,
    limit: int = 20,
) -> QueryResult:
    """Search for code nodes by name pattern.

    Uses SQL LIKE pattern matching. Use % for wildcards.

    Args:
        pattern: Name pattern to search (e.g., "%auth%", "User%", "%Service")
        node_type: Optional filter by type: "function", "class", "module"
        limit: Maximum results to return (default 20)

    Returns:
        Matching nodes with location info
    """
    # Build MUQL query
    type_filter = ""
    if node_type:
        type_filter = f" AND type = '{node_type}'"

    query = (
        f"SELECT id, type, name, file_path, line_start, complexity "
        f"FROM nodes WHERE name LIKE '{pattern}'{type_filter} "
        f"ORDER BY complexity DESC LIMIT {limit}"
    )

    try:
        client = _get_client()
        with client:
            result = client.query(query)

        return QueryResult(
            columns=result.get("columns", []),
            rows=result.get("rows", []),
            row_count=result.get("row_count", len(result.get("rows", []))),
            execution_time_ms=result.get("execution_time_ms"),
        )
    except DaemonError:
        mubase_path = _find_mubase()
        if not mubase_path:
            raise DaemonError("No .mubase found. Run 'mu daemon start .' first.") from None

        from mu.kernel import MUbase
        from mu.kernel.muql import MUQLEngine

        db = MUbase(mubase_path)
        try:
            engine = MUQLEngine(db)
            result = engine.query_dict(query)
            return QueryResult(
                columns=result.get("columns", []),
                rows=result.get("rows", []),
                row_count=result.get("row_count", len(result.get("rows", []))),
                execution_time_ms=result.get("execution_time_ms"),
            )
        finally:
            db.close()


@mcp.tool()
def mu_status() -> dict[str, Any]:
    """Get MU daemon status and codebase statistics.

    Returns information about:
    - Whether daemon is running
    - Node counts by type
    - Edge counts
    - Database location
    - Actionable next_action for agents

    Returns:
        Status information and statistics with next_action guidance
    """
    # Check for config file
    config_exists = (Path.cwd() / ".murc.toml").exists()
    mubase_path = _find_mubase()
    embeddings_exist = False

    if mubase_path:
        # Check for embeddings
        embeddings_db = mubase_path.parent / ".mu-embeddings.db"
        embeddings_exist = embeddings_db.exists()

    try:
        client = _get_client()
        with client:
            status = client.status()

        return {
            "daemon_running": True,
            "config_exists": config_exists,
            "mubase_exists": True,
            "mubase_path": status.get("mubase_path", ""),
            "embeddings_exist": embeddings_exist,
            "stats": status.get("stats", {}),
            "connections": status.get("connections", 0),
            "uptime_seconds": status.get("uptime_seconds", 0),
            "next_action": None,
            "message": "MU ready. All systems operational.",
        }
    except DaemonError:
        # Check for local mubase
        if mubase_path:
            from mu.kernel import MUbase

            db = MUbase(mubase_path)
            try:
                stats = db.stats()
                return {
                    "daemon_running": False,
                    "config_exists": config_exists,
                    "mubase_exists": True,
                    "mubase_path": str(mubase_path),
                    "embeddings_exist": embeddings_exist,
                    "stats": stats,
                    "connections": 0,
                    "uptime_seconds": 0,
                    "next_action": "mu_embed" if not embeddings_exist else None,
                    "message": (
                        "MU ready (direct access). Run mu_embed() to enable semantic search."
                        if not embeddings_exist
                        else "MU ready (direct access)."
                    ),
                }
            finally:
                db.close()

        # No mubase found - guide agent to bootstrap
        if not config_exists:
            return {
                "daemon_running": False,
                "config_exists": False,
                "mubase_exists": False,
                "mubase_path": None,
                "embeddings_exist": False,
                "stats": {},
                "next_action": "mu_init",
                "message": "No .murc.toml found. Run mu_init() to create configuration.",
            }
        else:
            return {
                "daemon_running": False,
                "config_exists": True,
                "mubase_exists": False,
                "mubase_path": None,
                "embeddings_exist": False,
                "stats": {},
                "next_action": "mu_build",
                "message": "No .mubase found. Run mu_build() to build the code graph.",
            }


# =============================================================================
# Bootstrap Tools (P0) - Enable agents to fully bootstrap a codebase
# =============================================================================


@dataclass
class InitResult:
    """Result of mu_init."""

    success: bool
    config_path: str
    message: str


@dataclass
class BuildResult:
    """Result of mu_build."""

    success: bool
    mubase_path: str
    stats: dict[str, Any]
    duration_ms: float


@dataclass
class SemanticDiffOutput:
    """Result of mu_semantic_diff."""

    base_ref: str
    head_ref: str
    changes: list[dict[str, Any]]
    breaking_changes: list[dict[str, Any]]
    summary_text: str
    has_breaking_changes: bool
    total_changes: int


@mcp.tool()
def mu_init(path: str = ".", force: bool = False) -> InitResult:
    """Initialize MU configuration for a codebase.

    Creates .murc.toml with sensible defaults.
    Safe to run multiple times (won't overwrite existing config unless force=True).

    Args:
        path: Path to initialize (default: current directory)
        force: Overwrite existing .murc.toml if present

    Returns:
        InitResult with success status and config path
    """
    from mu.config import get_default_config_toml

    root = Path(path).resolve()
    config_path = root / ".murc.toml"

    if config_path.exists() and not force:
        return InitResult(
            success=True,
            config_path=str(config_path),
            message="Configuration already exists. Use force=True to overwrite.",
        )

    try:
        config_path.write_text(get_default_config_toml())
        return InitResult(
            success=True,
            config_path=str(config_path),
            message=f"Created {config_path}. Run mu_build() next to build the code graph.",
        )
    except PermissionError:
        return InitResult(
            success=False,
            config_path=str(config_path),
            message=f"Permission denied writing to {config_path}",
        )
    except Exception as e:
        return InitResult(
            success=False,
            config_path=str(config_path),
            message=f"Failed to create config: {e}",
        )


@mcp.tool()
def mu_build(path: str = ".", force: bool = False) -> BuildResult:
    """Build or rebuild the .mubase code graph.

    This is the main bootstrap command. Run this before using
    mu_query, mu_context, mu_deps, etc.

    Args:
        path: Path to codebase (default: current directory)
        force: Force rebuild even if .mubase exists

    Returns:
        BuildResult with stats and duration
    """
    import time

    from mu.config import MUConfig
    from mu.kernel import MUbase
    from mu.parser.base import parse_file
    from mu.scanner import SUPPORTED_LANGUAGES, scan_codebase_auto

    start_time = time.time()
    root_path = Path(path).resolve()
    mubase_path = root_path / ".mubase"

    # Check if rebuild is needed
    if mubase_path.exists() and not force:
        # Return existing stats
        db = MUbase(mubase_path)
        try:
            stats = db.stats()
            return BuildResult(
                success=True,
                mubase_path=str(mubase_path),
                stats=stats,
                duration_ms=0.0,
            )
        finally:
            db.close()

    try:
        config = MUConfig.load()
    except Exception:
        config = MUConfig()

    # Scan codebase
    scan_result = scan_codebase_auto(root_path, config)

    if not scan_result.files:
        return BuildResult(
            success=False,
            mubase_path=str(mubase_path),
            stats={},
            duration_ms=(time.time() - start_time) * 1000,
        )

    # Parse all files
    modules = []
    for file_info in scan_result.files:
        if file_info.language not in SUPPORTED_LANGUAGES:
            continue
        parsed = parse_file(Path(root_path / file_info.path), file_info.language)
        if parsed.success and parsed.module:
            modules.append(parsed.module)

    if not modules:
        return BuildResult(
            success=False,
            mubase_path=str(mubase_path),
            stats={"error": "No modules parsed successfully"},
            duration_ms=(time.time() - start_time) * 1000,
        )

    # Build graph
    db = MUbase(mubase_path)
    db.build(modules, root_path)
    stats = db.stats()
    db.close()

    duration_ms = (time.time() - start_time) * 1000

    return BuildResult(
        success=True,
        mubase_path=str(mubase_path),
        stats=stats,
        duration_ms=duration_ms,
    )


@mcp.tool()
def mu_semantic_diff(
    base_ref: str,
    head_ref: str,
    path: str = ".",
) -> SemanticDiffOutput:
    """Compare two git refs and return semantic changes.

    Returns structured diff with:
    - Added/removed/modified functions, classes, methods
    - Breaking change detection
    - Human-readable summary

    Args:
        base_ref: Base git ref (e.g., "main", "HEAD~1")
        head_ref: Head git ref (e.g., "feature-branch", "HEAD")
        path: Path to codebase (default: current directory)

    Returns:
        SemanticDiffOutput with changes, breaking_changes, summary_text

    Example:
        result = mu_semantic_diff("main", "HEAD")
        if result.has_breaking_changes:
            for bc in result.breaking_changes:
                print(f"BREAKING: {bc['change_type']} {bc['entity_name']}")
    """
    from mu.assembler import assemble
    from mu.config import MUConfig
    from mu.diff import (
        SemanticDiffer,
        semantic_diff_modules,
    )
    from mu.diff.git_utils import compare_refs
    from mu.parser import parse_file
    from mu.parser.models import ModuleDef
    from mu.reducer import reduce_codebase
    from mu.reducer.rules import TransformationRules
    from mu.scanner import scan_codebase_auto

    root_path = Path(path).resolve()

    try:
        config = MUConfig.load()
    except Exception:
        config = MUConfig()

    rules = TransformationRules(
        strip_stdlib_imports=True,
        strip_relative_imports=False,
        strip_dunder_methods=True,
        strip_property_getters=True,
        strip_empty_methods=True,
        include_docstrings=False,
        include_decorators=True,
        include_type_annotations=True,
    )

    def process_version(version_path: Path) -> tuple[Any, list[ModuleDef]]:
        scan_result = scan_codebase_auto(version_path, config)
        if scan_result.stats.total_files == 0:
            return None, []

        modules: list[ModuleDef] = []
        for file_info in scan_result.files:
            file_path = version_path / file_info.path
            parse_result = parse_file(file_path, file_info.language)
            if parse_result.success and parse_result.module is not None:
                modules.append(parse_result.module)

        reduced = reduce_codebase(modules, version_path, rules)
        assembled = assemble(modules, reduced, version_path)
        return assembled, modules

    with compare_refs(root_path, base_ref, head_ref) as (
        base_path,
        target_path,
        _base_git_ref,
        _target_git_ref,
    ):
        base_assembled, base_modules = process_version(base_path)
        target_assembled, target_modules = process_version(target_path)

        if base_assembled is None or target_assembled is None:
            return SemanticDiffOutput(
                base_ref=base_ref,
                head_ref=head_ref,
                changes=[],
                breaking_changes=[],
                summary_text="No supported files found in one or both refs",
                has_breaking_changes=False,
                total_changes=0,
            )

        # Try Rust semantic diff first (faster, more detailed)
        rust_result = semantic_diff_modules(base_modules, target_modules)
        if rust_result is not None:
            changes = [
                {
                    "entity_type": c.entity_type,
                    "entity_name": c.entity_name,
                    "change_type": c.change_type,
                    "details": c.details,
                    "module_path": c.module_path,
                    "is_breaking": c.is_breaking,
                }
                for c in rust_result.changes
            ]
            breaking_changes = [
                {
                    "entity_type": c.entity_type,
                    "entity_name": c.entity_name,
                    "change_type": c.change_type,
                    "details": c.details,
                    "module_path": c.module_path,
                }
                for c in rust_result.breaking_changes
            ]
            return SemanticDiffOutput(
                base_ref=base_ref,
                head_ref=head_ref,
                changes=changes,
                breaking_changes=breaking_changes,
                summary_text=rust_result.summary.text(),
                has_breaking_changes=len(breaking_changes) > 0,
                total_changes=len(changes),
            )

        # Fallback to Python differ
        differ = SemanticDiffer(base_assembled, target_assembled, base_ref, head_ref)
        result = differ.diff()

        # Convert to simplified format
        changes = []
        breaking_changes = []

        for mod_diff in result.module_diffs:
            # Added functions
            for func_name in mod_diff.added_functions:
                changes.append(
                    {
                        "entity_type": "function",
                        "entity_name": func_name,
                        "change_type": "added",
                        "details": f"New function in {mod_diff.path}",
                        "module_path": mod_diff.path,
                        "is_breaking": False,
                    }
                )

            # Removed functions (breaking)
            for func_name in mod_diff.removed_functions:
                change = {
                    "entity_type": "function",
                    "entity_name": func_name,
                    "change_type": "removed",
                    "details": f"Function removed from {mod_diff.path}",
                    "module_path": mod_diff.path,
                    "is_breaking": True,
                }
                changes.append(change)
                breaking_changes.append(change)

            # Added/removed classes
            for cls_name in mod_diff.added_classes:
                changes.append(
                    {
                        "entity_type": "class",
                        "entity_name": cls_name,
                        "change_type": "added",
                        "details": f"New class in {mod_diff.path}",
                        "module_path": mod_diff.path,
                        "is_breaking": False,
                    }
                )

            for cls_name in mod_diff.removed_classes:
                change = {
                    "entity_type": "class",
                    "entity_name": cls_name,
                    "change_type": "removed",
                    "details": f"Class removed from {mod_diff.path}",
                    "module_path": mod_diff.path,
                    "is_breaking": True,
                }
                changes.append(change)
                breaking_changes.append(change)

        summary_lines = [f"Comparing {base_ref} → {head_ref}:"]
        summary_lines.append(f"  Total changes: {len(changes)}")
        if breaking_changes:
            summary_lines.append(f"  Breaking changes: {len(breaking_changes)}")

        return SemanticDiffOutput(
            base_ref=base_ref,
            head_ref=head_ref,
            changes=changes,
            breaking_changes=breaking_changes,
            summary_text="\n".join(summary_lines),
            has_breaking_changes=len(breaking_changes) > 0,
            total_changes=len(changes),
        )


# =============================================================================
# Discovery Tools (P1) - Fast codebase exploration
# =============================================================================


@dataclass
class ScanOutput:
    """Result of mu_scan."""

    files: list[dict[str, Any]]
    total_files: int
    total_lines: int
    by_language: dict[str, int]
    duration_ms: float


@dataclass
class CompressOutput:
    """Result of mu_compress."""

    output: str
    token_count: int
    compression_ratio: float
    file_count: int


@mcp.tool()
def mu_scan(
    path: str = ".",
    extensions: list[str] | None = None,
) -> ScanOutput:
    """Scan codebase and return file statistics.

    Fast discovery without full graph build.
    Uses Rust scanner (6-7x faster than Python).

    Args:
        path: Path to scan (default: current directory)
        extensions: Filter by extensions (e.g., ["py", "ts"])

    Returns:
        ScanOutput with file list and statistics
    """
    import time

    from mu.config import MUConfig
    from mu.scanner import scan_codebase_auto

    start_time = time.time()
    root_path = Path(path).resolve()

    try:
        config = MUConfig.load()
    except Exception:
        config = MUConfig()

    scan_result = scan_codebase_auto(root_path, config)

    # Convert to output format
    files: list[dict[str, Any]] = []
    total_lines = 0
    for f in scan_result.files:
        # Filter by extension if specified
        if extensions:
            file_ext = Path(f.path).suffix.lstrip(".")
            if file_ext not in extensions and f.language not in extensions:
                continue
        files.append(
            {
                "path": f.path,
                "language": f.language,
                "lines": f.lines,
                "size_bytes": f.size_bytes,
            }
        )
        total_lines += f.lines

    duration_ms = (time.time() - start_time) * 1000

    return ScanOutput(
        files=files,
        total_files=len(files),
        total_lines=total_lines,
        by_language=scan_result.stats.languages,
        duration_ms=duration_ms,
    )


@mcp.tool()
def mu_compress(
    path: str,
    format: str = "mu",
) -> CompressOutput:
    """Generate compressed MU representation of a file or directory.

    Args:
        path: File or directory to compress
        format: Output format ("mu", "json", "markdown")

    Returns:
        CompressOutput with compressed output and statistics
    """
    from mu.assembler import assemble
    from mu.assembler.exporters import export_json, export_markdown, export_mu
    from mu.config import MUConfig
    from mu.parser import parse_file
    from mu.parser.models import ModuleDef
    from mu.reducer import reduce_codebase
    from mu.reducer.rules import TransformationRules
    from mu.scanner import scan_codebase_auto

    target_path = Path(path).resolve()

    try:
        config = MUConfig.load()
    except Exception:
        config = MUConfig()

    # Scan
    scan_result = scan_codebase_auto(target_path, config)

    if not scan_result.files:
        return CompressOutput(
            output="",
            token_count=0,
            compression_ratio=0.0,
            file_count=0,
        )

    # Parse
    parsed_modules: list[ModuleDef] = []
    for file_info in scan_result.files:
        file_path = target_path / file_info.path if target_path.is_dir() else target_path
        result = parse_file(file_path, file_info.language)
        if result.success and result.module is not None:
            parsed_modules.append(result.module)

    if not parsed_modules:
        return CompressOutput(
            output="",
            token_count=0,
            compression_ratio=0.0,
            file_count=0,
        )

    # Reduce
    rules = TransformationRules(
        strip_stdlib_imports=True,
        strip_relative_imports=False,
        strip_dunder_methods=True,
        strip_property_getters=True,
        strip_empty_methods=True,
        include_docstrings=False,
        include_decorators=True,
        include_type_annotations=True,
    )
    reduced = reduce_codebase(parsed_modules, target_path, rules)

    # Assemble
    assembled = assemble(parsed_modules, reduced, target_path)

    # Export
    if format == "json":
        output_str = export_json(assembled, include_full_graph=False, pretty=True)
    elif format == "markdown":
        output_str = export_markdown(assembled)
    else:
        output_str = export_mu(assembled, shell_safe=False)

    # Estimate token count (rough: ~4 chars per token)
    token_count = len(output_str) // 4

    # Calculate compression ratio
    original_lines = scan_result.stats.total_lines
    output_lines = output_str.count("\n") + 1
    compression_ratio = 1.0 - (output_lines / original_lines) if original_lines > 0 else 0.0

    return CompressOutput(
        output=output_str,
        token_count=token_count,
        compression_ratio=compression_ratio,
        file_count=len(parsed_modules),
    )


# =============================================================================
# Graph Reasoning Tools (petgraph-backed)
# =============================================================================


@mcp.tool()
def mu_impact(node_id: str, edge_types: list[str] | None = None) -> ImpactResult:
    """Find downstream impact of changing a node.

    "If I change X, what might break?"

    Uses BFS traversal via Rust petgraph: O(V + E)

    Args:
        node_id: Node ID or name (e.g., "mod:src/auth.py", "AuthService")
        edge_types: Optional list of edge types to follow (imports, calls, inherits, contains)

    Returns:
        List of node IDs that would be impacted by changes to this node

    Examples:
        - mu_impact("mod:src/auth.py") - What breaks if auth.py changes?
        - mu_impact("AuthService", ["imports"]) - Only follow import edges
    """
    mubase_path = _find_mubase()
    if not mubase_path:
        raise DaemonError("No .mubase found. Run 'mu kernel build .' first.")

    from mu.kernel import MUbase
    from mu.kernel.graph import GraphManager

    db = MUbase(mubase_path)
    try:
        gm = GraphManager(db.conn)
        gm.load()

        # Resolve node name to ID if needed
        resolved_id = _resolve_node_id(db, node_id)

        if not gm.has_node(resolved_id):
            raise ValueError(f"Node not found in graph: {resolved_id}")

        impacted = gm.impact(resolved_id, edge_types)

        return ImpactResult(
            node_id=resolved_id,
            impacted_nodes=impacted,
            count=len(impacted),
        )
    finally:
        db.close()


@mcp.tool()
def mu_ancestors(node_id: str, edge_types: list[str] | None = None) -> AncestorsResult:
    """Find upstream dependencies of a node.

    "What does X depend on?"

    Uses BFS traversal via Rust petgraph: O(V + E)

    Args:
        node_id: Node ID or name (e.g., "mod:src/cli.py", "MUbase")
        edge_types: Optional list of edge types to follow (imports, calls, inherits, contains)

    Returns:
        List of node IDs that this node depends on

    Examples:
        - mu_ancestors("mod:src/cli.py") - What does cli.py depend on?
        - mu_ancestors("fn:src/auth.py:login", ["calls"]) - What does login() call?
    """
    mubase_path = _find_mubase()
    if not mubase_path:
        raise DaemonError("No .mubase found. Run 'mu kernel build .' first.")

    from mu.kernel import MUbase
    from mu.kernel.graph import GraphManager

    db = MUbase(mubase_path)
    try:
        gm = GraphManager(db.conn)
        gm.load()

        # Resolve node name to ID if needed
        resolved_id = _resolve_node_id(db, node_id)

        if not gm.has_node(resolved_id):
            raise ValueError(f"Node not found in graph: {resolved_id}")

        ancestor_nodes = gm.ancestors(resolved_id, edge_types)

        return AncestorsResult(
            node_id=resolved_id,
            ancestor_nodes=ancestor_nodes,
            count=len(ancestor_nodes),
        )
    finally:
        db.close()


@mcp.tool()
def mu_cycles(edge_types: list[str] | None = None) -> CyclesResult:
    """Detect circular dependencies in the codebase.

    Uses Kosaraju's strongly connected components algorithm via Rust petgraph: O(V + E)

    Args:
        edge_types: Optional list of edge types to consider (imports, calls, inherits, contains).
                   If not specified, all edge types are used.

    Returns:
        List of cycles, where each cycle is a list of node IDs

    Examples:
        - mu_cycles() - Find all circular dependencies
        - mu_cycles(["imports"]) - Find only import cycles
    """
    mubase_path = _find_mubase()
    if not mubase_path:
        raise DaemonError("No .mubase found. Run 'mu kernel build .' first.")

    from mu.kernel import MUbase
    from mu.kernel.graph import GraphManager

    db = MUbase(mubase_path)
    try:
        gm = GraphManager(db.conn)
        gm.load()

        cycles = gm.find_cycles(edge_types)

        return CyclesResult(
            cycles=cycles,
            cycle_count=len(cycles),
            total_nodes_in_cycles=sum(len(c) for c in cycles),
        )
    finally:
        db.close()


def _resolve_node_id(db: Any, node_ref: str) -> str:
    """Resolve a node reference to a full node ID.

    Handles:
    - Full node IDs: mod:src/cli.py, cls:src/file.py:ClassName
    - Simple names: MUbase, AuthService
    """
    # If it already looks like a full node ID, return it
    if node_ref.startswith(("mod:", "cls:", "fn:")):
        return node_ref

    # Try exact name match
    nodes = db.find_by_name(node_ref)
    if nodes:
        return str(nodes[0].id)

    # Try pattern match
    nodes = db.find_by_name(f"%{node_ref}%")
    if nodes:
        # Prefer exact name matches
        for node in nodes:
            if node.name == node_ref:
                return str(node.id)
        return str(nodes[0].id)

    # Return original if not found (will fail in has_node check)
    return node_ref


def test_tools() -> dict[str, Any]:
    """Test all MCP tools without starting the server.

    Runs each tool with a simple test case and reports success/failure.

    Returns:
        Dictionary with test results for each tool
    """
    results: dict[str, Any] = {}

    # Test mu_status (no database needed, always works)
    try:
        status = mu_status()
        results["mu_status"] = {
            "ok": True,
            "daemon_running": status.get("daemon_running", False),
        }
    except Exception as e:
        results["mu_status"] = {"ok": False, "error": str(e)}

    # Test mu_query (requires .mubase)
    try:
        result = mu_query("DESCRIBE tables")
        results["mu_query"] = {
            "ok": True,
            "tables_found": result.row_count,
        }
    except Exception as e:
        results["mu_query"] = {"ok": False, "error": str(e)}

    # Test mu_search
    try:
        result = mu_search("%", limit=1)
        results["mu_search"] = {
            "ok": True,
            "found": result.row_count > 0,
        }
    except Exception as e:
        results["mu_search"] = {"ok": False, "error": str(e)}

    # Test mu_context (requires embeddings, may fail gracefully)
    try:
        result = mu_context("test", max_tokens=100)
        results["mu_context"] = {
            "ok": True,
            "tokens": result.token_count,
        }
    except Exception as e:
        results["mu_context"] = {"ok": False, "error": str(e)}

    return results


def create_server() -> FastMCP:
    """Create the MCP server instance.

    Returns:
        Configured FastMCP server with all MU tools registered
    """
    return mcp


TransportType = Literal["stdio", "sse", "streamable-http"]


def run_server(transport: TransportType = "stdio") -> None:
    """Run the MCP server.

    Args:
        transport: Transport type ("stdio", "sse", or "streamable-http")
    """
    mcp.run(transport=transport)


__all__ = [
    "mcp",
    "create_server",
    "run_server",
    "test_tools",
    # Bootstrap tools (P0)
    "mu_init",
    "mu_build",
    "mu_semantic_diff",
    # Discovery tools (P1)
    "mu_scan",
    "mu_compress",
    # Query tools
    "mu_query",
    "mu_context",
    "mu_deps",
    "mu_node",
    "mu_search",
    "mu_status",
    # Graph reasoning tools (petgraph-backed)
    "mu_impact",
    "mu_ancestors",
    "mu_cycles",
    # Data types
    "NodeInfo",
    "QueryResult",
    "ContextResult",
    "DepsResult",
    "ImpactResult",
    "AncestorsResult",
    "CyclesResult",
    "InitResult",
    "BuildResult",
    "SemanticDiffOutput",
    "ScanOutput",
    "CompressOutput",
]
