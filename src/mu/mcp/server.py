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
from mu.paths import MU_DIR, MUBASE_FILE, find_mubase_path, get_mubase_path

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


@dataclass
class PatternInfo:
    """Information about a detected pattern."""

    name: str
    category: str
    description: str
    frequency: int
    confidence: float
    examples: list[dict[str, Any]]
    anti_patterns: list[str]


@dataclass
class PatternsOutput:
    """Result of mu_patterns - detected codebase patterns."""

    patterns: list[PatternInfo]
    total_patterns: int
    categories_found: list[str]
    detection_time_ms: float


@dataclass
class GeneratedFileInfo:
    """Information about a generated file."""

    path: str
    content: str
    description: str
    is_primary: bool


@dataclass
class GenerateOutput:
    """Result of mu_generate - code template generation."""

    template_type: str
    name: str
    files: list[GeneratedFileInfo]
    patterns_used: list[str]
    suggestions: list[str]


@dataclass
class ViolationInfo:
    """Information about a pattern violation."""

    file_path: str
    line_start: int | None
    line_end: int | None
    severity: str
    rule: str
    message: str
    suggestion: str
    pattern_category: str


@dataclass
class ValidateOutput:
    """Result of mu_validate - pattern validation for changes."""

    valid: bool
    violations: list[ViolationInfo]
    patterns_checked: list[str]
    files_checked: list[str]
    error_count: int
    warning_count: int
    info_count: int
    validation_time_ms: float


@dataclass
class ReadResult:
    """Result of mu_read - source code extraction."""

    node_id: str
    file_path: str
    line_start: int
    line_end: int
    source: str
    context_before: str
    context_after: str
    language: str


def _get_client() -> DaemonClient:
    """Get a daemon client, raising if daemon not running."""
    client = DaemonClient(base_url=DEFAULT_DAEMON_URL)
    if not client.is_running():
        client.close()
        raise DaemonError("MU daemon is not running. Start it with: mu daemon start .")
    return client


def _find_mubase() -> Path | None:
    """Find mubase file in current directory or parents."""
    return find_mubase_path(Path.cwd())


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
    # Get current working directory for multi-project routing
    cwd = str(Path.cwd())

    try:
        client = _get_client()
        with client:
            result = client.query(query, cwd=cwd)

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
            raise DaemonError(
                f"No {MU_DIR}/{MUBASE_FILE} found. Run 'mu daemon start .' first."
            ) from None

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
    # Get current working directory for multi-project routing
    cwd = str(Path.cwd())

    try:
        client = _get_client()
        with client:
            result = client.context(question, max_tokens=max_tokens, cwd=cwd)

        return ContextResult(
            mu_text=result.get("mu_text", ""),
            token_count=result.get("token_count", 0),
            node_count=len(result.get("nodes", [])),
        )
    except DaemonError:
        # Try direct access
        mubase_path = _find_mubase()
        if not mubase_path:
            raise DaemonError(
                f"No {MU_DIR}/{MUBASE_FILE} found. Run 'mu daemon start .' first."
            ) from None

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
def mu_read(node_id: str, context_lines: int = 3) -> ReadResult:
    """Read source code for a specific node.

    Closes the find→read loop: after finding nodes with mu_query or mu_context,
    use mu_read to see the actual source code.

    Args:
        node_id: Node ID or name (e.g., "AuthService", "cls:src/auth.py:AuthService")
        context_lines: Lines of context before/after the node (default 3)

    Returns:
        ReadResult with source code and surrounding context

    Example:
        # Find a class, then read its source
        result = mu_query("SELECT id FROM classes WHERE name = 'AuthService'")
        source = mu_read(result.rows[0][0])
        print(source.source)  # The actual class code
    """
    cwd = str(Path.cwd())
    mubase_path = _find_mubase()

    # Helper to extract source from node data
    def _extract_source(
        node_data: dict[str, Any],
        resolved_id: str,
        root_path: Path,
    ) -> ReadResult:
        file_path_str = node_data.get("file_path")
        line_start = node_data.get("line_start")
        line_end = node_data.get("line_end")
        node_type = node_data.get("node_type", node_data.get("type", ""))

        if not file_path_str or not line_start or not line_end:
            missing = []
            if not file_path_str:
                missing.append("file_path")
            if not line_start:
                missing.append("line_start")
            if not line_end:
                missing.append("line_end")

            if node_type == "external":
                hint = " (external dependencies don't have source)"
            elif not file_path_str:
                hint = " (try mu_query to find nodes with file paths)"
            else:
                hint = f" (file: {file_path_str}, try reading the file directly)"

            raise ValueError(
                f"Node '{node_id}' has no source location (missing: {', '.join(missing)}){hint}"
            )

        # Read the source file
        file_path = Path(file_path_str)
        if not file_path.is_absolute():
            file_path = root_path / file_path

        if not file_path.exists():
            raise ValueError(f"Source file not found: {file_path}")

        lines = file_path.read_text().splitlines()
        total_lines = len(lines)

        start_idx = line_start - 1
        end_idx = line_end

        context_start = max(0, start_idx - context_lines)
        context_end = min(total_lines, end_idx + context_lines)

        source_lines = lines[start_idx:end_idx]
        context_before_lines = lines[context_start:start_idx]
        context_after_lines = lines[end_idx:context_end]

        ext = file_path.suffix.lstrip(".")
        lang_map = {
            "py": "python",
            "ts": "typescript",
            "tsx": "typescript",
            "js": "javascript",
            "jsx": "javascript",
            "go": "go",
            "rs": "rust",
            "java": "java",
            "cs": "csharp",
        }
        language = lang_map.get(ext, ext)

        return ReadResult(
            node_id=resolved_id,
            file_path=str(file_path),
            line_start=line_start,
            line_end=line_end,
            source="\n".join(source_lines),
            context_before="\n".join(context_before_lines),
            context_after="\n".join(context_after_lines),
            language=language,
        )

    # Try daemon first (no lock)
    try:
        client = _get_client()
        with client:
            # Resolve node name to ID if needed
            if node_id.startswith(("mod:", "cls:", "fn:")):
                resolved_id = node_id
                node_data = client.node(node_id, cwd=cwd)
            else:
                # Find by name using MUQL
                found = client.find_node(node_id, cwd=cwd)
                if not found:
                    raise ValueError(f"Node not found: {node_id}")
                resolved_id = found.get("id", node_id)
                node_data = found

            if not node_data:
                raise ValueError(f"Node not found: {node_id}")

            # Determine root path
            root_path = mubase_path.parent if mubase_path else Path.cwd()
            return _extract_source(node_data, resolved_id, root_path)

    except DaemonError:
        # Fall back to direct MUbase access
        pass

    # Direct MUbase access fallback
    if not mubase_path:
        raise DaemonError(f"No {MU_DIR}/{MUBASE_FILE} found. Run mu_bootstrap() first.") from None

    from mu.kernel import MUbase

    db = MUbase(mubase_path)
    root_path = mubase_path.parent
    try:
        resolved_id = _resolve_node_id(db, node_id, root_path)
        node = db.get_node(resolved_id)

        if not node:
            raise ValueError(f"Node not found: {node_id}")

        # Convert node to dict for _extract_source
        node_data = {
            "file_path": node.file_path,
            "line_start": node.line_start,
            "line_end": node.line_end,
            "node_type": node.type.value if hasattr(node.type, "value") else str(node.type),
        }

        return _extract_source(node_data, resolved_id, root_path)
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
    # Get current working directory for multi-project routing
    cwd = str(Path.cwd())

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
            result = client.query(query, cwd=cwd)

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
            raise DaemonError(
                f"No {MU_DIR}/{MUBASE_FILE} found. Run 'mu daemon start .' first."
            ) from None

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
    # Get current working directory for multi-project routing
    cwd = str(Path.cwd())

    # Check for config file
    config_exists = (Path.cwd() / ".murc.toml").exists()
    mubase_path = _find_mubase()
    embeddings_exist = False

    if mubase_path:
        # Check for embeddings (stored in same .mu/ directory)
        embeddings_db = mubase_path.parent / "embeddings.db"
        embeddings_exist = embeddings_db.exists()

    try:
        client = _get_client()
        with client:
            status = client.status(cwd=cwd)

        # Get language stats from the response
        language_stats = status.get("language_stats", {})

        return {
            "daemon_running": True,
            "config_exists": config_exists,
            "mubase_exists": True,
            "mubase_path": status.get("mubase_path", ""),
            "embeddings_exist": embeddings_exist,
            "stats": status.get("stats", {}),
            "language_stats": language_stats,
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
                language_stats = db.get_language_stats()
                return {
                    "daemon_running": False,
                    "config_exists": config_exists,
                    "mubase_exists": True,
                    "mubase_path": str(mubase_path),
                    "embeddings_exist": embeddings_exist,
                    "stats": stats,
                    "language_stats": language_stats,
                    "connections": 0,
                    "uptime_seconds": 0,
                    "next_action": "mu_embed" if not embeddings_exist else None,
                    "message": (
                        "MU ready (direct access). 💡 Run `mu kernel embed .` to enable mu_search() (semantic search)."
                        if not embeddings_exist
                        else "MU ready (direct access)."
                    ),
                }
            finally:
                db.close()

        # No mubase found - guide agent to bootstrap
        return {
            "daemon_running": False,
            "config_exists": config_exists,
            "mubase_exists": False,
            "mubase_path": None,
            "embeddings_exist": False,
            "stats": {},
            "language_stats": {},
            "next_action": "mu_bootstrap",
            "message": f"No {MU_DIR}/{MUBASE_FILE} found. Run mu_bootstrap() to initialize MU.",
        }


# =============================================================================
# Bootstrap Tools (P0) - Enable agents to fully bootstrap a codebase
# =============================================================================


@dataclass
class BootstrapResult:
    """Result of mu_bootstrap."""

    success: bool
    mubase_path: str
    stats: dict[str, Any]
    duration_ms: float
    message: str
    suggestion: str | None = None  # Optional next step hint


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


@dataclass
class ReviewDiffOutput:
    """Result of mu_review_diff - semantic diff with pattern validation.

    Combines semantic diff analysis with pattern validation to provide
    a comprehensive code review for changes between git refs.
    """

    base_ref: str
    """Base git reference (e.g., 'main', 'HEAD~1')."""

    head_ref: str
    """Head git reference (e.g., 'feature-branch', 'HEAD')."""

    # Semantic diff section
    changes: list[dict[str, Any]]
    """All semantic changes (added/removed/modified entities)."""

    breaking_changes: list[dict[str, Any]]
    """Breaking changes that may affect downstream code."""

    has_breaking_changes: bool
    """Whether any breaking changes were detected."""

    total_changes: int
    """Total number of semantic changes."""

    # Pattern validation section
    violations: list[ViolationInfo]
    """Pattern violations found in changed files."""

    patterns_checked: list[str]
    """Names of patterns that were validated against."""

    files_checked: list[str]
    """Files that were validated."""

    error_count: int
    """Number of error-level violations (should fix)."""

    warning_count: int
    """Number of warning-level violations (consider fixing)."""

    info_count: int
    """Number of info-level suggestions."""

    patterns_valid: bool
    """Whether all changes pass pattern validation (no errors)."""

    # Summary
    review_summary: str
    """Human-readable review summary with recommendations."""

    review_time_ms: float
    """Total time for review (diff + validation) in milliseconds."""


@mcp.tool()
def mu_bootstrap(path: str = ".", force: bool = False) -> BootstrapResult:
    """Bootstrap MU for a codebase in one step.

    This single command:
    1. Creates .murc.toml config if missing
    2. Builds the .mubase code graph
    3. Returns ready-to-query status

    Safe to run multiple times. Use force=True to rebuild.

    Args:
        path: Path to codebase (default: current directory)
        force: Force rebuild even if .mubase exists

    Returns:
        BootstrapResult with stats and ready status

    Example:
        result = mu_bootstrap(".")
        if result.success:
            # Now use mu_query, mu_context, mu_deps, etc.
            pass
    """
    import time

    from mu.config import MUConfig, get_default_config_toml
    from mu.kernel import MUbase
    from mu.parser.base import parse_file
    from mu.scanner import SUPPORTED_LANGUAGES, scan_codebase_auto

    start_time = time.time()
    root_path = Path(path).resolve()
    config_path = root_path / ".murc.toml"
    mubase_path = get_mubase_path(root_path)

    # Step 1: Ensure config exists
    if not config_path.exists():
        try:
            config_path.write_text(get_default_config_toml())
        except PermissionError:
            return BootstrapResult(
                success=False,
                mubase_path=str(mubase_path),
                stats={},
                duration_ms=(time.time() - start_time) * 1000,
                message=f"Permission denied writing to {config_path}",
            )

    # Step 2: Check if rebuild is needed
    if mubase_path.exists() and not force:
        db = MUbase(mubase_path)
        try:
            stats = db.stats()
            return BootstrapResult(
                success=True,
                mubase_path=str(mubase_path),
                stats=stats,
                duration_ms=0.0,
                message="MU ready. Graph already exists.",
            )
        finally:
            db.close()

    # Step 3: Load config and scan
    try:
        config = MUConfig.load()
    except Exception:
        config = MUConfig()

    scan_result = scan_codebase_auto(root_path, config)

    if not scan_result.files:
        return BootstrapResult(
            success=False,
            mubase_path=str(mubase_path),
            stats={},
            duration_ms=(time.time() - start_time) * 1000,
            message="No supported files found in codebase.",
        )

    # Step 4: Parse all files
    modules = []
    for file_info in scan_result.files:
        if file_info.language not in SUPPORTED_LANGUAGES:
            continue
        parsed = parse_file(Path(root_path / file_info.path), file_info.language)
        if parsed.success and parsed.module:
            modules.append(parsed.module)

    if not modules:
        return BootstrapResult(
            success=False,
            mubase_path=str(mubase_path),
            stats={"error": "No modules parsed successfully"},
            duration_ms=(time.time() - start_time) * 1000,
            message="Failed to parse any files.",
        )

    # Step 5: Build graph
    db = MUbase(mubase_path)
    db.build(modules, root_path)
    stats = db.stats()
    db.close()

    duration_ms = (time.time() - start_time) * 1000

    return BootstrapResult(
        success=True,
        mubase_path=str(mubase_path),
        stats=stats,
        duration_ms=duration_ms,
        message=f"MU ready. Built graph with {stats.get('nodes', 0)} nodes in {duration_ms:.0f}ms.",
        suggestion="💡 For semantic search (mu_search), run: mu kernel embed . (requires OPENAI_API_KEY or local embeddings)",
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

    def normalize_path(p: str, *worktree_paths: Path) -> str:
        """Strip worktree prefix to get relative path.

        Handles multiple worktree paths (for base and target versions)
        and also strips any temp directory paths.
        """
        if not p:
            return p

        # Try each worktree path
        for worktree_path in worktree_paths:
            worktree_str = str(worktree_path)
            if p.startswith(worktree_str):
                p_path = Path(p)
                try:
                    rel = p_path.relative_to(worktree_path)
                    return str(rel)
                except ValueError:
                    pass

        # Also handle /var/folders/... type temp paths by detecting common patterns
        # Pattern: /var/folders/.../worktree-XXX/actual/path
        # or /tmp/mu-diff-.../worktree-XXX/actual/path
        p_path = Path(p)
        parts = p_path.parts
        for i, part in enumerate(parts):
            if part.startswith("worktree-") or part.startswith("mu-diff-"):
                # Return everything after this part
                if i + 1 < len(parts):
                    return str(Path(*parts[i + 1 :]))

        return p

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
        # Note: Rust differ expects mu._core.ModuleDef, not Python dataclass ModuleDef.
        # The Python parser returns Python dataclasses, so this will typically fail.
        # We catch the type conversion error and fall back to Python differ.
        rust_result = None
        try:
            rust_result = semantic_diff_modules(base_modules, target_modules)
        except TypeError:
            # Expected when using Python-parsed ModuleDefs (dataclasses) vs Rust ModuleDefs
            pass

        if rust_result is not None:
            # Normalize paths for Rust results - strip worktree prefix (try both paths)
            changes = [
                {
                    "entity_type": c.entity_type,
                    "entity_name": c.entity_name,
                    "change_type": c.change_type,
                    "details": c.details,
                    "module_path": normalize_path(c.module_path, base_path, target_path),
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
                    "module_path": normalize_path(c.module_path, base_path, target_path),
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

        # Convert to simplified format, normalizing paths
        changes = []
        breaking_changes = []

        for mod_diff in result.module_diffs:
            # Normalize module path to strip worktree prefix (try both paths)
            norm_path = normalize_path(mod_diff.path, base_path, target_path)

            # Added functions
            for func_name in mod_diff.added_functions:
                changes.append(
                    {
                        "entity_type": "function",
                        "entity_name": func_name,
                        "change_type": "added",
                        "details": f"New function in {norm_path}",
                        "module_path": norm_path,
                        "is_breaking": False,
                    }
                )

            # Removed functions (breaking)
            for func_name in mod_diff.removed_functions:
                change = {
                    "entity_type": "function",
                    "entity_name": func_name,
                    "change_type": "removed",
                    "details": f"Function removed from {norm_path}",
                    "module_path": norm_path,
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
                        "details": f"New class in {norm_path}",
                        "module_path": norm_path,
                        "is_breaking": False,
                    }
                )

            for cls_name in mod_diff.removed_classes:
                change = {
                    "entity_type": "class",
                    "entity_name": cls_name,
                    "change_type": "removed",
                    "details": f"Class removed from {norm_path}",
                    "module_path": norm_path,
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


@mcp.tool()
def mu_review_diff(
    base_ref: str,
    head_ref: str,
    path: str = ".",
    validate_patterns: bool = True,
    pattern_category: str | None = None,
) -> ReviewDiffOutput:
    """Perform a comprehensive code review of changes between git refs.

    Combines semantic diff analysis with pattern validation to provide
    actionable review feedback. This is the recommended tool for PR reviews.

    **Analysis includes:**
    - Semantic changes: Added/removed/modified functions, classes, methods
    - Breaking change detection: Removed public APIs, signature changes
    - Pattern validation: Check new code follows codebase conventions
    - Review summary: Human-readable feedback with recommendations

    Args:
        base_ref: Base git ref (e.g., "main", "develop", "HEAD~5")
        head_ref: Head git ref (e.g., "HEAD", "feature-branch")
        path: Path to codebase (default: current directory)
        validate_patterns: Whether to run pattern validation (default True)
        pattern_category: Optional category to validate (all if None).
                         Valid: naming, architecture, testing, imports,
                         error_handling, api, async, logging

    Returns:
        ReviewDiffOutput with comprehensive review including:
        - Semantic changes and breaking change warnings
        - Pattern violations with fix suggestions
        - Overall review summary and recommendations

    Examples:
        # Review PR against main
        mu_review_diff("main", "HEAD")

        # Review last 3 commits
        mu_review_diff("HEAD~3", "HEAD")

        # Review with naming conventions only
        mu_review_diff("develop", "feature-branch", pattern_category="naming")

        # Skip pattern validation (just semantic diff)
        mu_review_diff("main", "HEAD", validate_patterns=False)

    Use Cases:
        - PR review: Automated review before merge
        - Pre-commit: Check your changes before committing
        - Code audit: Review large changes for issues
        - Learning: Understand what patterns to follow
    """
    import subprocess
    import time

    start_time = time.time()
    root_path = Path(path).resolve()

    # Step 1: Get semantic diff
    diff_result = mu_semantic_diff(base_ref, head_ref, path)

    # Initialize validation results
    violations: list[ViolationInfo] = []
    patterns_checked: list[str] = []
    files_checked: list[str] = []
    error_count = 0
    warning_count = 0
    info_count = 0
    patterns_valid = True

    # Step 2: Get changed files from git and validate patterns
    if validate_patterns:
        mubase_path = _find_mubase()
        if mubase_path:
            from mu.intelligence import PatternCategory
            from mu.intelligence.validator import ChangeValidator
            from mu.kernel import MUbase

            # Validate category if provided
            cat_enum = None
            if pattern_category:
                try:
                    cat_enum = PatternCategory(pattern_category)
                except ValueError:
                    valid_cats = [c.value for c in PatternCategory]
                    raise ValueError(
                        f"Invalid pattern_category: {pattern_category}. Valid: {valid_cats}"
                    ) from None

            # Get changed files from git
            try:
                result = subprocess.run(
                    ["git", "diff", "--name-only", base_ref, head_ref],
                    capture_output=True,
                    text=True,
                    cwd=root_path,
                    check=False,
                )
                if result.returncode == 0:
                    changed_files = [
                        f.strip() for f in result.stdout.strip().splitlines() if f.strip()
                    ]

                    # Filter to only files that still exist (not deleted)
                    existing_files = [f for f in changed_files if (root_path / f).exists()]

                    if existing_files:
                        db = MUbase(mubase_path)
                        try:
                            validator = ChangeValidator(db)
                            validation_result = validator.validate(
                                files=existing_files, category=cat_enum
                            )

                            # Convert violations to output format
                            violations = [
                                ViolationInfo(
                                    file_path=v.file_path,
                                    line_start=v.line_start,
                                    line_end=v.line_end,
                                    severity=v.severity.value,
                                    rule=v.rule,
                                    message=v.message,
                                    suggestion=v.suggestion,
                                    pattern_category=v.pattern_category,
                                )
                                for v in validation_result.violations
                            ]

                            patterns_checked = validation_result.patterns_checked
                            files_checked = validation_result.files_checked
                            error_count = validation_result.error_count
                            warning_count = validation_result.warning_count
                            info_count = validation_result.info_count
                            patterns_valid = validation_result.valid
                        finally:
                            db.close()
            except (subprocess.SubprocessError, FileNotFoundError):
                pass  # Git not available or not in a repo

    # Step 3: Generate review summary
    summary_parts = []

    # Header
    summary_parts.append(f"# Code Review: {base_ref} → {head_ref}")
    summary_parts.append("")

    # Semantic changes summary
    summary_parts.append("## Semantic Changes")
    if diff_result.total_changes == 0:
        summary_parts.append("No semantic changes detected.")
    else:
        summary_parts.append(f"- Total changes: {diff_result.total_changes}")

        # Group by change type
        added = [c for c in diff_result.changes if c.get("change_type") == "added"]
        removed = [c for c in diff_result.changes if c.get("change_type") == "removed"]
        modified = [
            c for c in diff_result.changes if c.get("change_type") not in ("added", "removed")
        ]

        if added:
            summary_parts.append(f"- Added: {len(added)}")
        if removed:
            summary_parts.append(f"- Removed: {len(removed)}")
        if modified:
            summary_parts.append(f"- Modified: {len(modified)}")

    summary_parts.append("")

    # Breaking changes warning
    if diff_result.has_breaking_changes:
        summary_parts.append("## ⚠️ Breaking Changes Detected")
        for bc in diff_result.breaking_changes[:5]:  # Limit to first 5
            entity = bc.get("entity_name", "unknown")
            change_type = bc.get("change_type", "modified")
            summary_parts.append(f"- **{entity}**: {change_type}")
        if len(diff_result.breaking_changes) > 5:
            summary_parts.append(f"  ... and {len(diff_result.breaking_changes) - 5} more")
        summary_parts.append("")

    # Pattern validation summary
    if validate_patterns:
        summary_parts.append("## Pattern Validation")
        if not files_checked:
            summary_parts.append("No files to validate (no .mubase or no changed files).")
        elif patterns_valid and not violations:
            summary_parts.append("✅ All changes follow codebase patterns.")
        else:
            if error_count > 0:
                summary_parts.append(f"❌ {error_count} error(s) - should fix before merge")
            if warning_count > 0:
                summary_parts.append(f"⚠️ {warning_count} warning(s) - consider fixing")
            if info_count > 0:
                summary_parts.append(f"ℹ️ {info_count} suggestion(s)")

            # Top violations
            if violations:
                summary_parts.append("")
                summary_parts.append("### Key Issues:")
                for v in violations[:3]:  # Top 3
                    summary_parts.append(f"- **{v.rule}** ({v.file_path}:{v.line_start or '?'})")
                    summary_parts.append(f"  {v.message}")
                    if v.suggestion:
                        summary_parts.append(f"  → {v.suggestion}")
        summary_parts.append("")

    # Recommendation
    summary_parts.append("## Recommendation")
    if diff_result.has_breaking_changes:
        summary_parts.append(
            "⚠️ **Review breaking changes carefully** before merging. "
            "Ensure downstream code is updated."
        )
    elif error_count > 0:
        summary_parts.append(
            "❌ **Address pattern violations** before merging. "
            "New code should follow established conventions."
        )
    elif warning_count > 0:
        summary_parts.append(
            "⚠️ **Consider addressing warnings** for consistency. Changes are otherwise acceptable."
        )
    else:
        summary_parts.append("✅ **Looks good!** No blocking issues found.")

    review_summary = "\n".join(summary_parts)
    review_time_ms = (time.time() - start_time) * 1000

    return ReviewDiffOutput(
        base_ref=base_ref,
        head_ref=head_ref,
        # Semantic diff
        changes=diff_result.changes,
        breaking_changes=diff_result.breaking_changes,
        has_breaking_changes=diff_result.has_breaking_changes,
        total_changes=diff_result.total_changes,
        # Pattern validation
        violations=violations,
        patterns_checked=patterns_checked,
        files_checked=files_checked,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        patterns_valid=patterns_valid,
        # Summary
        review_summary=review_summary,
        review_time_ms=review_time_ms,
    )


# =============================================================================
# Discovery Tools (P1) - Fast codebase exploration
# =============================================================================


@dataclass
class CompressOutput:
    """Result of mu_compress."""

    output: str
    token_count: int
    compression_ratio: float
    file_count: int


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
    # Get current working directory for multi-project routing
    cwd = str(Path.cwd())

    try:
        client = _get_client()
        with client:
            result = client.impact(node_id, edge_types=edge_types, cwd=cwd)

        return ImpactResult(
            node_id=result.get("node_id", node_id),
            impacted_nodes=result.get("impacted_nodes", []),
            count=result.get("count", 0),
        )
    except DaemonError:
        # Fallback: direct MUbase access
        mubase_path = _find_mubase()
        if not mubase_path:
            raise DaemonError(
                f"No {MU_DIR}/{MUBASE_FILE} found. Run 'mu kernel build .' first."
            ) from None

        from mu.kernel import MUbase
        from mu.kernel.graph import GraphManager

        db = MUbase(mubase_path)
        root_path = mubase_path.parent
        try:
            gm = GraphManager(db.conn)
            gm.load()

            # Resolve node name to ID if needed (supports paths like src/foo.ts)
            resolved_id = _resolve_node_id(db, node_id, root_path)

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
    # Get current working directory for multi-project routing
    cwd = str(Path.cwd())

    try:
        client = _get_client()
        with client:
            result = client.ancestors(node_id, edge_types=edge_types, cwd=cwd)

        return AncestorsResult(
            node_id=result.get("node_id", node_id),
            ancestor_nodes=result.get("ancestor_nodes", []),
            count=result.get("count", 0),
        )
    except DaemonError:
        # Fallback: direct MUbase access
        mubase_path = _find_mubase()
        if not mubase_path:
            raise DaemonError(
                f"No {MU_DIR}/{MUBASE_FILE} found. Run 'mu kernel build .' first."
            ) from None

        from mu.kernel import MUbase
        from mu.kernel.graph import GraphManager

        db = MUbase(mubase_path)
        root_path = mubase_path.parent
        try:
            gm = GraphManager(db.conn)
            gm.load()

            # Resolve node name to ID if needed (supports paths like src/foo.ts)
            resolved_id = _resolve_node_id(db, node_id, root_path)

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
    # Get current working directory for multi-project routing
    cwd = str(Path.cwd())

    try:
        client = _get_client()
        with client:
            result = client.cycles(edge_types=edge_types, cwd=cwd)

        return CyclesResult(
            cycles=result.get("cycles", []),
            cycle_count=result.get("cycle_count", 0),
            total_nodes_in_cycles=result.get("total_nodes_in_cycles", 0),
        )
    except DaemonError:
        # Fallback: direct MUbase access
        mubase_path = _find_mubase()
        if not mubase_path:
            raise DaemonError(
                f"No {MU_DIR}/{MUBASE_FILE} found. Run 'mu kernel build .' first."
            ) from None

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


# =============================================================================
# Intelligence Layer Tools
# =============================================================================


@mcp.tool()
def mu_patterns(
    category: str | None = None,
    refresh: bool = False,
) -> PatternsOutput:
    """Get detected codebase patterns.

    Analyzes the codebase to detect recurring patterns including:
    - Naming conventions (file/function/class naming)
    - Error handling patterns
    - Import organization
    - Architectural patterns (services, repositories)
    - Testing patterns
    - API patterns

    Args:
        category: Optional filter by category. Valid categories:
                  error_handling, state_management, api, naming,
                  testing, components, imports, architecture, async, logging
        refresh: Force re-analysis (bypass cached patterns)

    Returns:
        PatternsOutput with detected patterns and examples

    Examples:
        - mu_patterns() - Get all detected patterns
        - mu_patterns("naming") - Get naming convention patterns only
        - mu_patterns("error_handling") - Get error handling patterns
        - mu_patterns(refresh=True) - Force re-analysis
    """
    mubase_path = _find_mubase()
    if not mubase_path:
        raise DaemonError(f"No {MU_DIR}/{MUBASE_FILE} found. Run mu_bootstrap() first.") from None

    from mu.intelligence import PatternCategory, PatternDetector
    from mu.kernel import MUbase

    db = MUbase(mubase_path)
    try:
        # Check for cached patterns unless refresh requested
        if not refresh and db.has_patterns():
            stored_patterns = db.get_patterns(category)
            if stored_patterns:
                # Get categories from stored patterns
                categories_found = list({p.category.value for p in stored_patterns})

                patterns_info = [
                    PatternInfo(
                        name=p.name,
                        category=p.category.value,
                        description=p.description,
                        frequency=p.frequency,
                        confidence=p.confidence,
                        examples=[e.to_dict() for e in p.examples],
                        anti_patterns=p.anti_patterns,
                    )
                    for p in stored_patterns
                ]

                return PatternsOutput(
                    patterns=patterns_info,
                    total_patterns=len(patterns_info),
                    categories_found=categories_found,
                    detection_time_ms=0.0,  # From cache
                )

        # Run pattern detection
        detector = PatternDetector(db)

        # Convert category string to enum if provided
        cat_enum = None
        if category:
            try:
                cat_enum = PatternCategory(category)
            except ValueError:
                valid_cats = [c.value for c in PatternCategory]
                raise ValueError(
                    f"Invalid category: {category}. Valid categories: {valid_cats}"
                ) from None

        result = detector.detect(category=cat_enum, refresh=refresh)

        # Save patterns for future use (only if detecting all)
        if not category:
            db.save_patterns(result.patterns)

        # Convert to output format
        patterns_info = [
            PatternInfo(
                name=p.name,
                category=p.category.value,
                description=p.description,
                frequency=p.frequency,
                confidence=p.confidence,
                examples=[e.to_dict() for e in p.examples],
                anti_patterns=p.anti_patterns,
            )
            for p in result.patterns
        ]

        return PatternsOutput(
            patterns=patterns_info,
            total_patterns=result.total_patterns,
            categories_found=result.categories_found,
            detection_time_ms=result.detection_time_ms,
        )
    finally:
        db.close()


@mcp.tool()
def mu_generate(
    template_type: str,
    name: str,
    options: dict[str, Any] | None = None,
) -> GenerateOutput:
    """Generate code following codebase patterns.

    Creates boilerplate code that matches the detected patterns and conventions
    of your codebase. Supports multiple template types for different architectural
    components.

    Args:
        template_type: What to generate. Valid types:
                      hook, component, service, repository, api_route,
                      test, model, controller
        name: Name for the generated code (e.g., "UserProfile", "useAuth", "PaymentService")
        options: Additional options:
                - entity: Entity name for services/repositories (e.g., "User")
                - fields: List of fields for models [{"name": "email", "type": "str"}]
                - target: Target module for test generation
                - props: Props definition for components (TypeScript)

    Returns:
        GenerateOutput with generated files, patterns used, and suggestions

    Examples:
        - mu_generate("hook", "useAuth") - Generate React hook
        - mu_generate("service", "User") - Generate UserService class
        - mu_generate("api_route", "users") - Generate API route handlers
        - mu_generate("model", "Product", {"fields": [{"name": "price", "type": "float"}]})
        - mu_generate("test", "auth", {"target": "src/auth.py"})
    """
    mubase_path = _find_mubase()
    if not mubase_path:
        raise DaemonError(f"No {MU_DIR}/{MUBASE_FILE} found. Run mu_bootstrap() first.") from None

    from mu.intelligence import CodeGenerator, TemplateType
    from mu.kernel import MUbase

    # Validate template type
    try:
        tt = TemplateType(template_type)
    except ValueError:
        valid_types = [t.value for t in TemplateType]
        raise ValueError(
            f"Invalid template_type: {template_type}. Valid types: {valid_types}"
        ) from None

    db = MUbase(mubase_path)
    try:
        generator = CodeGenerator(db)
        result = generator.generate(tt, name, options)

        # Convert to output format
        files_info = [
            GeneratedFileInfo(
                path=f.path,
                content=f.content,
                description=f.description,
                is_primary=f.is_primary,
            )
            for f in result.files
        ]

        return GenerateOutput(
            template_type=result.template_type.value,
            name=result.name,
            files=files_info,
            patterns_used=result.patterns_used,
            suggestions=result.suggestions,
        )
    finally:
        db.close()


@mcp.tool()
def mu_validate(
    files: list[str] | None = None,
    staged: bool = False,
    category: str | None = None,
) -> ValidateOutput:
    """Validate code changes against detected codebase patterns.

    Pre-commit validation that checks if new or modified code follows
    established conventions and architectural rules. Can validate:
    - Specific files
    - Git staged changes
    - All uncommitted changes

    Args:
        files: Optional list of file paths to validate. If None, uses git status.
        staged: If True and files is None, validate only staged changes.
        category: Optional category filter. Valid categories:
                  naming, architecture, testing, imports, error_handling,
                  api, async, logging, state_management, components

    Returns:
        ValidateOutput with violations, patterns checked, and counts

    Examples:
        - mu_validate() - Validate all uncommitted changes
        - mu_validate(staged=True) - Validate only staged changes (pre-commit)
        - mu_validate(["src/new_service.py"]) - Validate specific files
        - mu_validate(category="naming") - Only check naming conventions
        - mu_validate(staged=True, category="architecture") - Architecture check before commit

    Use Cases:
        - Pre-commit hook: mu_validate(staged=True)
        - Code review: mu_validate(["file1.py", "file2.py"])
        - Style check: mu_validate(category="naming")
    """
    mubase_path = _find_mubase()
    if not mubase_path:
        raise DaemonError(f"No {MU_DIR}/{MUBASE_FILE} found. Run mu_bootstrap() first.") from None

    from mu.intelligence import PatternCategory
    from mu.intelligence.validator import ChangeValidator
    from mu.kernel import MUbase

    # Validate category if provided
    cat_enum = None
    if category:
        try:
            cat_enum = PatternCategory(category)
        except ValueError:
            valid_cats = [c.value for c in PatternCategory]
            raise ValueError(
                f"Invalid category: {category}. Valid categories: {valid_cats}"
            ) from None

    db = MUbase(mubase_path)
    try:
        validator = ChangeValidator(db)
        result = validator.validate(files=files, staged=staged, category=cat_enum)

        # Convert violations to output format
        violations_info = [
            ViolationInfo(
                file_path=v.file_path,
                line_start=v.line_start,
                line_end=v.line_end,
                severity=v.severity.value,
                rule=v.rule,
                message=v.message,
                suggestion=v.suggestion,
                pattern_category=v.pattern_category,
            )
            for v in result.violations
        ]

        return ValidateOutput(
            valid=result.valid,
            violations=violations_info,
            patterns_checked=result.patterns_checked,
            files_checked=result.files_checked,
            error_count=result.error_count,
            warning_count=result.warning_count,
            info_count=result.info_count,
            validation_time_ms=result.validation_time_ms,
        )
    finally:
        db.close()


# =============================================================================
# Proactive Warnings Tools
# =============================================================================


@dataclass
class WarningInfo:
    """Information about a proactive warning."""

    category: str
    level: str
    message: str
    details: dict[str, Any]


@dataclass
class WarningsOutput:
    """Result of mu_warn - proactive warnings for a target."""

    target: str
    target_type: str
    warnings: list[WarningInfo]
    summary: str
    risk_score: float
    analysis_time_ms: float


@mcp.tool()
def mu_warn(target: str) -> WarningsOutput:
    """Get proactive warnings about a target before modification.

    Analyzes a file or node to identify potential issues that should be
    considered before making changes. Returns warnings about:
    - High impact: Many files depend on this (>10 dependents)
    - Stale code: Not modified in >6 months
    - Security sensitive: Contains auth/crypto/secrets logic
    - No tests: No test coverage detected
    - High complexity: Cyclomatic complexity >20
    - Deprecated: Marked as deprecated in code

    Args:
        target: File path or node ID to analyze
                Examples: "src/auth.py", "AuthService", "cls:src/auth.py:AuthService"

    Returns:
        WarningsOutput with all detected warnings and risk score

    Examples:
        - mu_warn("src/auth.py") - Check auth module before modifying
        - mu_warn("AuthService") - Check a specific class
        - mu_warn("mod:src/payments.py") - Check by node ID

    Use Cases:
        - Before modifying critical code: Check impact and risks
        - PR review: Understand what you're touching
        - New to codebase: Get context before changes
    """
    mubase_path = _find_mubase()
    if not mubase_path:
        raise DaemonError(f"No {MU_DIR}/{MUBASE_FILE} found. Run mu_bootstrap() first.") from None

    from mu.intelligence.warnings import ProactiveWarningGenerator
    from mu.kernel import MUbase

    db = MUbase(mubase_path)
    try:
        generator = ProactiveWarningGenerator(db, root_path=mubase_path.parent)
        result = generator.analyze(target)

        # Convert to output format
        warnings_info = [
            WarningInfo(
                category=w.category.value,
                level=w.level,
                message=w.message,
                details=w.details,
            )
            for w in result.warnings
        ]

        return WarningsOutput(
            target=result.target,
            target_type=result.target_type,
            warnings=warnings_info,
            summary=result.summary,
            risk_score=result.risk_score,
            analysis_time_ms=result.analysis_time_ms,
        )
    finally:
        db.close()


# =============================================================================
# Natural Language Query Tools
# =============================================================================


@dataclass
class AskResult:
    """Result of mu_ask - NL to MUQL translation and execution."""

    question: str
    muql: str
    explanation: str
    confidence: float
    executed: bool
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    error: str | None = None


@dataclass
class TaskFileContext:
    """File context for task-aware extraction."""

    path: str
    relevance: float
    reason: str
    is_entry_point: bool
    suggested_action: str


@dataclass
class TaskContextOutput:
    """Result of mu_task_context - curated context for development tasks."""

    relevant_files: list[TaskFileContext]
    entry_points: list[str]
    patterns: list[PatternInfo]
    warnings: list[dict[str, str]]
    suggestions: list[dict[str, str]]
    mu_text: str
    token_count: int
    confidence: float
    task_type: str
    entity_types: list[str]
    keywords: list[str]


@mcp.tool()
def mu_ask(
    question: str,
    execute: bool = True,
    model: str | None = None,
) -> AskResult:
    """Translate a natural language question to MUQL and optionally execute it.

    Converts questions like "What are the most complex functions?" into
    executable MUQL queries using an LLM. Optionally executes the query
    and returns results.

    Args:
        question: Natural language question about the codebase
        execute: Whether to execute the generated query (default True)
        model: Optional LLM model override (default: claude-3-haiku)

    Returns:
        AskResult with generated MUQL, explanation, and query results

    Examples:
        - mu_ask("What are the most complex functions?")
        - mu_ask("Show me all service classes")
        - mu_ask("What depends on AuthService?")
        - mu_ask("Are there any circular dependencies?")
        - mu_ask("Find functions with the cache decorator")
        - mu_ask("How do I get from the API to the database?")

    Note:
        Requires an API key for the LLM provider (ANTHROPIC_API_KEY by default).
        The translation uses claude-3-haiku for cost efficiency (~$0.001/query).
    """
    mubase_path = _find_mubase()
    if not mubase_path:
        raise DaemonError(f"No {MU_DIR}/{MUBASE_FILE} found. Run mu_bootstrap() first.") from None

    from mu.intelligence import NL2MUQLTranslator
    from mu.kernel import MUbase

    db = MUbase(mubase_path)
    try:
        translator = NL2MUQLTranslator(db=db, model=model)
        result = translator.translate(question, execute=execute)

        # Extract query results if available
        columns: list[str] = []
        rows: list[list[Any]] = []
        row_count = 0

        if result.result:
            columns = result.result.get("columns", [])
            rows = result.result.get("rows", [])
            row_count = result.result.get("row_count", len(rows))

        return AskResult(
            question=result.question,
            muql=result.muql,
            explanation=result.explanation,
            confidence=result.confidence,
            executed=result.executed,
            columns=columns,
            rows=rows,
            row_count=row_count,
            error=result.error,
        )
    finally:
        db.close()


@mcp.tool()
def mu_task_context(
    task: str,
    max_tokens: int = 8000,
    include_tests: bool = True,
    include_patterns: bool = True,
) -> TaskContextOutput:
    """Extract comprehensive context for a development task.

    Given a natural language task description, returns a curated context bundle
    containing everything an AI assistant needs to complete the task:
    - Relevant files to read/modify
    - Entry points (where to start)
    - Codebase patterns to follow
    - Code examples of similar implementations
    - Warnings about high-impact files
    - Suggestions for related changes

    This is the killer feature for AI coding assistants - reduces exploration
    from 30-60 seconds to 5-10 seconds by providing focused, relevant context.

    Args:
        task: Natural language task description (e.g., "Add rate limiting to API endpoints")
        max_tokens: Maximum tokens in the MU output (default 8000)
        include_tests: Include relevant test patterns (default True)
        include_patterns: Include detected codebase patterns (default True)

    Returns:
        TaskContextOutput with files, patterns, warnings, and curated MU context

    Examples:
        - mu_task_context("Add rate limiting to the API endpoints")
        - mu_task_context("Fix the authentication bug in login flow")
        - mu_task_context("Refactor UserService to use repository pattern")
        - mu_task_context("Add unit tests for payment processing")

    Token Budget Allocation:
        - 60% for core relevant files
        - 20% for patterns and examples
        - 10% for dependencies
        - 10% for warnings and metadata
    """
    mubase_path = _find_mubase()
    if not mubase_path:
        raise DaemonError(f"No {MU_DIR}/{MUBASE_FILE} found. Run mu_bootstrap() first.") from None

    from mu.intelligence import TaskContextConfig, TaskContextExtractor
    from mu.kernel import MUbase

    db = MUbase(mubase_path)
    try:
        config = TaskContextConfig(
            max_tokens=max_tokens,
            include_tests=include_tests,
            include_patterns=include_patterns,
        )

        extractor = TaskContextExtractor(db, config)
        result = extractor.extract(task)

        # Convert to output format
        file_contexts = [
            TaskFileContext(
                path=f.path,
                relevance=f.relevance,
                reason=f.reason,
                is_entry_point=f.is_entry_point,
                suggested_action=f.suggested_action,
            )
            for f in result.relevant_files
        ]

        patterns_info = [
            PatternInfo(
                name=p.name,
                category=p.category.value,
                description=p.description,
                frequency=p.frequency,
                confidence=p.confidence,
                examples=[e.to_dict() for e in p.examples],
                anti_patterns=p.anti_patterns,
            )
            for p in result.patterns
        ]

        warnings_list = [w.to_dict() for w in result.warnings]
        suggestions_list = [s.to_dict() for s in result.suggestions]

        # Extract task analysis info
        task_type = result.task_analysis.task_type.value if result.task_analysis else "modify"
        entity_types = (
            [et.value for et in result.task_analysis.entity_types] if result.task_analysis else []
        )
        keywords = result.task_analysis.keywords if result.task_analysis else []

        return TaskContextOutput(
            relevant_files=file_contexts,
            entry_points=result.entry_points,
            patterns=patterns_info,
            warnings=warnings_list,
            suggestions=suggestions_list,
            mu_text=result.mu_text,
            token_count=result.token_count,
            confidence=result.confidence,
            task_type=task_type,
            entity_types=entity_types,
            keywords=keywords,
        )
    finally:
        db.close()


# =============================================================================
# Related Files Tools (F4)
# =============================================================================


@dataclass
class RelatedFileInfo:
    """Information about a related file."""

    path: str
    exists: bool
    action: str  # "update", "create", "review"
    reason: str
    confidence: float
    source: str  # "convention", "git_cochange", "dependency"
    template: str | None = None


@dataclass
class RelatedFilesOutput:
    """Result of mu_related - suggest related files."""

    file_path: str
    change_type: str
    related_files: list[RelatedFileInfo]
    detection_time_ms: float


@mcp.tool()
def mu_related(
    file_path: str,
    change_type: Literal["create", "modify", "delete"] = "modify",
) -> RelatedFilesOutput:
    """Suggest related files that should change together.

    Given a file being modified, suggests related files that typically
    change together based on:

    1. **Convention patterns**: Test files, stories, index exports
       - `src/hooks/useFoo.ts` → `src/hooks/__tests__/useFoo.test.ts`
       - `src/auth.py` → `tests/unit/test_auth.py`

    2. **Git co-change analysis**: Files that historically change together
       - "When A changes, B changes 80% of the time"

    3. **Dependency analysis**: Files that import the changed file
       - What might break if this file changes

    Args:
        file_path: The file being modified (relative or absolute path)
        change_type: Type of change: "create", "modify", or "delete"

    Returns:
        RelatedFilesOutput with suggested files and reasons

    Examples:
        - mu_related("src/auth.py") - Find files related to auth.py
        - mu_related("src/hooks/useAuth.ts") - Find test/story files
        - mu_related("src/new_feature.py", "create") - Creating a new file
        - mu_related("src/old_module.py", "delete") - Deleting a file

    Use Cases:
        - Before committing: Check what else might need updating
        - Creating new files: See what supporting files to create
        - Deleting code: See what might break or need cleanup
    """
    mubase_path = _find_mubase()

    # MUbase is optional for this tool - conventions work without it
    db = None
    if mubase_path:
        from mu.kernel import MUbase

        try:
            db = MUbase(mubase_path)
        except Exception:
            pass

    try:
        from mu.intelligence import RelatedFilesDetector

        root_path = mubase_path.parent if mubase_path else Path.cwd()
        detector = RelatedFilesDetector(db=db, root_path=root_path)

        result = detector.detect(
            file_path,
            change_type=change_type,
            include_conventions=True,
            include_git_cochange=True,
            include_dependencies=db is not None,
        )

        related_info = [
            RelatedFileInfo(
                path=rf.path,
                exists=rf.exists,
                action=rf.action,
                reason=rf.reason,
                confidence=rf.confidence,
                source=rf.source,
                template=rf.template,
            )
            for rf in result.related_files
        ]

        return RelatedFilesOutput(
            file_path=result.file_path,
            change_type=result.change_type,
            related_files=related_info,
            detection_time_ms=result.detection_time_ms,
        )
    finally:
        if db:
            db.close()


# =============================================================================
# Cross-Session Memory Tools (F6)
# =============================================================================


@dataclass
class MemoryInfo:
    """Information about a stored memory."""

    id: str
    category: str
    content: str
    context: str
    source: str
    confidence: float
    importance: int
    tags: list[str]
    created_at: str
    updated_at: str
    access_count: int


@dataclass
class RememberResult:
    """Result of mu_remember - memory storage."""

    memory_id: str
    category: str
    content: str
    importance: int
    is_update: bool
    message: str


@dataclass
class RecallOutput:
    """Result of mu_recall - memory retrieval."""

    memories: list[MemoryInfo]
    query: str
    category: str | None
    total_matches: int
    recall_time_ms: float


@mcp.tool()
def mu_remember(
    content: str,
    category: str = "learning",
    context: str = "",
    source: str = "",
    importance: int = 2,
    tags: list[str] | None = None,
) -> RememberResult:
    """Store a memory for future recall across sessions.

    Saves learnings, decisions, preferences, and context that should
    persist across agent sessions. Memories are automatically deduplicated
    based on content - storing the same content updates the existing memory.

    Args:
        content: The memory content to store. Should be concise and actionable.
        category: Memory category. Valid values:
                  - preference: User preferences (coding style, tool choices)
                  - decision: Architectural/design decisions with rationale
                  - context: Project context that persists across sessions
                  - learning: Learned patterns or insights about the codebase
                  - pitfall: Known issues, gotchas, or things to avoid
                  - convention: Team or project conventions
                  - todo: Deferred tasks or ideas for later
                  - reference: Reference information (docs, links, examples)
        context: Optional context about when/why this was learned.
        source: Optional source (file path, conversation, etc.).
        importance: Importance level 1-5 (1=low, 5=essential). Default: 2.
        tags: Optional list of tags for categorization and search.

    Returns:
        RememberResult with memory ID and confirmation.

    Examples:
        # Store a user preference
        mu_remember(
            "User prefers snake_case for Python function names",
            category="preference",
            importance=3,
            tags=["python", "naming"]
        )

        # Store an architectural decision
        mu_remember(
            "Using PostgreSQL over MySQL for better JSON support",
            category="decision",
            context="Discussed during architecture review",
            importance=4,
            tags=["database", "architecture"]
        )

        # Store a pitfall discovered during debugging
        mu_remember(
            "Never use datetime.now() in tests - use freezegun instead",
            category="pitfall",
            source="tests/test_scheduler.py",
            importance=3,
            tags=["testing", "datetime"]
        )

        # Store a TODO for later
        mu_remember(
            "Consider adding rate limiting to the API endpoints",
            category="todo",
            importance=2,
            tags=["api", "security"]
        )
    """
    mubase_path = _find_mubase()
    if not mubase_path:
        raise DaemonError(f"No {MU_DIR}/{MUBASE_FILE} found. Run mu_bootstrap() first.") from None

    from mu.intelligence import MemoryCategory, MemoryManager
    from mu.kernel import MUbase

    # Validate category
    valid_categories = [c.value for c in MemoryCategory]
    if category not in valid_categories:
        raise ValueError(f"Invalid category: {category}. Valid categories: {valid_categories}")

    db = MUbase(mubase_path)
    try:
        manager = MemoryManager(db)

        # Check if this would be an update
        import hashlib

        content_hash = hashlib.sha256(content.encode()).hexdigest()[:12]
        existing_id = f"mem:{category}:{content_hash}"
        is_update = db.get_memory(existing_id) is not None

        memory_id = manager.remember(
            content=content,
            category=category,
            context=context,
            source=source,
            importance=importance,
            tags=tags,
        )

        action = "Updated" if is_update else "Stored"
        return RememberResult(
            memory_id=memory_id,
            category=category,
            content=content,
            importance=importance,
            is_update=is_update,
            message=f"{action} memory [{category}] with importance {importance}",
        )
    finally:
        db.close()


@mcp.tool()
def mu_recall(
    query: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    min_importance: int = 0,
    limit: int = 10,
) -> RecallOutput:
    """Recall memories based on search criteria.

    Retrieves stored memories that match the given criteria. Memories are
    returned sorted by importance and access frequency. Each recall
    updates the memory's access count and timestamp.

    Args:
        query: Optional text search in content and context.
        category: Optional category filter. Valid values:
                  preference, decision, context, learning, pitfall,
                  convention, todo, reference
        tags: Optional list of tags to filter by (matches any tag).
        min_importance: Minimum importance level (0-5, 0 = all). Default: 0.
        limit: Maximum number of memories to return. Default: 10.

    Returns:
        RecallOutput with matching memories.

    Examples:
        # Recall all memories
        mu_recall()

        # Search for specific content
        mu_recall(query="database")

        # Get all decisions
        mu_recall(category="decision")

        # Get high-importance memories
        mu_recall(min_importance=4)

        # Search by tags
        mu_recall(tags=["testing", "python"])

        # Combined search
        mu_recall(query="API", category="pitfall", min_importance=2)

    Use Cases:
        - Start of session: Recall important context and preferences
        - Before coding: Check for relevant pitfalls and conventions
        - Architecture work: Review past decisions
        - Planning: Check TODOs and deferred items
    """
    mubase_path = _find_mubase()
    if not mubase_path:
        raise DaemonError(f"No {MU_DIR}/{MUBASE_FILE} found. Run mu_bootstrap() first.") from None

    from mu.intelligence import MemoryCategory, MemoryManager
    from mu.kernel import MUbase

    # Validate category if provided
    if category:
        valid_categories = [c.value for c in MemoryCategory]
        if category not in valid_categories:
            raise ValueError(f"Invalid category: {category}. Valid categories: {valid_categories}")

    db = MUbase(mubase_path)
    try:
        manager = MemoryManager(db)
        result = manager.recall(
            query=query,
            category=category,
            tags=tags,
            min_importance=min_importance,
            limit=limit,
        )

        memories_info = [
            MemoryInfo(
                id=m.id,
                category=m.category.value,
                content=m.content,
                context=m.context,
                source=m.source,
                confidence=m.confidence,
                importance=m.importance,
                tags=m.tags,
                created_at=m.created_at,
                updated_at=m.updated_at,
                access_count=m.access_count,
            )
            for m in result.memories
        ]

        return RecallOutput(
            memories=memories_info,
            query=query or "",
            category=category,
            total_matches=result.total_matches,
            recall_time_ms=result.recall_time_ms,
        )
    finally:
        db.close()


# =============================================================================
# Why Layer Tools (F7) - Git history analysis for code rationale
# =============================================================================


@dataclass
class CommitInfoOutput:
    """Information about a git commit."""

    hash: str
    full_hash: str
    author: str
    author_email: str
    date: str
    message: str
    full_message: str
    files_changed: list[str]
    issue_refs: list[str]
    pr_refs: list[str]


@dataclass
class WhyOutput:
    """Result of mu_why - git history analysis for code rationale."""

    target: str
    target_type: str
    file_path: str
    line_start: int | None
    line_end: int | None
    origin_commit: CommitInfoOutput | None
    origin_reason: str
    total_commits: int
    recent_commits: list[CommitInfoOutput]
    evolution_summary: str
    primary_author: str
    contributors: list[dict[str, Any]]
    issue_refs: list[str]
    pr_refs: list[str]
    frequently_changed_with: list[str]
    analysis_time_ms: float


@mcp.tool()
def mu_why(
    target: str,
    max_commits: int = 20,
    include_cochanges: bool = True,
) -> WhyOutput:
    """Analyze git history to understand why code exists.

    Answers "Why does this code exist?" by analyzing git history:
    - Origin commit and reason for creation
    - Evolution over time (commits, contributors)
    - Issue/PR references from commit messages
    - Files that frequently change together

    Args:
        target: What to analyze. Can be:
                - Node name: "AuthService", "login"
                - Node ID: "cls:src/auth.py:AuthService"
                - File path: "src/auth.py"
                - File with lines: "src/auth.py:10-50"
        max_commits: Maximum commits to analyze (default 20)
        include_cochanges: Include co-change analysis (default True)

    Returns:
        WhyOutput with origin, evolution, and context information

    Examples:
        - mu_why("AuthService") - Why does AuthService exist?
        - mu_why("src/auth.py") - History of the auth module
        - mu_why("src/auth.py:10-50") - History of specific lines
        - mu_why("cls:src/auth.py:AuthService") - Using node ID

    Use Cases:
        - Understanding unfamiliar code: "Why was this written this way?"
        - Code archaeology: Finding the original intent
        - Blame context: Understanding who to ask about code
        - Change impact: What else typically changes with this code
    """
    mubase_path = _find_mubase()

    # MUbase is optional for this tool - works without it for file paths
    db = None
    if mubase_path:
        from mu.kernel import MUbase

        try:
            db = MUbase(mubase_path)
        except Exception:
            pass

    try:
        from mu.intelligence import WhyAnalyzer

        root_path = mubase_path.parent if mubase_path else Path.cwd()
        analyzer = WhyAnalyzer(db=db, root_path=root_path)

        result = analyzer.analyze(
            target,
            max_commits=max_commits,
            include_cochanges=include_cochanges,
        )

        # Convert origin commit
        origin_commit_output = None
        if result.origin_commit:
            origin_commit_output = CommitInfoOutput(
                hash=result.origin_commit.hash,
                full_hash=result.origin_commit.full_hash,
                author=result.origin_commit.author,
                author_email=result.origin_commit.author_email,
                date=result.origin_commit.date.isoformat() if result.origin_commit.date else "",
                message=result.origin_commit.message,
                full_message=result.origin_commit.full_message,
                files_changed=result.origin_commit.files_changed,
                issue_refs=result.origin_commit.issue_refs,
                pr_refs=result.origin_commit.pr_refs,
            )

        # Convert recent commits
        recent_commits_output = [
            CommitInfoOutput(
                hash=c.hash,
                full_hash=c.full_hash,
                author=c.author,
                author_email=c.author_email,
                date=c.date.isoformat() if c.date else "",
                message=c.message,
                full_message=c.full_message,
                files_changed=c.files_changed,
                issue_refs=c.issue_refs,
                pr_refs=c.pr_refs,
            )
            for c in result.recent_commits
        ]

        return WhyOutput(
            target=result.target,
            target_type=result.target_type,
            file_path=result.file_path,
            line_start=result.line_start,
            line_end=result.line_end,
            origin_commit=origin_commit_output,
            origin_reason=result.origin_reason,
            total_commits=result.total_commits,
            recent_commits=recent_commits_output,
            evolution_summary=result.evolution_summary,
            primary_author=result.primary_author,
            contributors=result.contributors,
            issue_refs=result.issue_refs,
            pr_refs=result.pr_refs,
            frequently_changed_with=result.frequently_changed_with,
            analysis_time_ms=result.analysis_time_ms,
        )
    finally:
        if db:
            db.close()


def _resolve_node_id(db: Any, node_ref: str, root_path: Path | None = None) -> str:
    """Resolve a node reference to a full node ID.

    Handles:
    - Full node IDs: mod:src/cli.py, cls:src/file.py:ClassName
    - Simple names: MUbase, AuthService
    - File paths: src/hooks/useTransactions.ts -> mod:...
    - Absolute paths: /Users/.../src/auth.py -> mod:...

    Args:
        db: MUbase instance
        node_ref: Node reference (ID, name, or file path)
        root_path: Project root path for resolving relative paths

    Returns:
        Resolved node ID or original string if not found
    """
    # If it already looks like a full node ID, return it
    if node_ref.startswith(("mod:", "cls:", "fn:")):
        return node_ref

    # Try exact name match first
    nodes = db.find_by_name(node_ref)
    if nodes:
        return str(nodes[0].id)

    # Check if it looks like a file path (contains / or \ or ends with known extension)
    looks_like_path = (
        "/" in node_ref
        or "\\" in node_ref
        or node_ref.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rs", ".cs"))
    )

    if looks_like_path:
        # Try to resolve as file path
        ref_path = Path(node_ref)

        # If absolute path, try to make it relative to root
        if ref_path.is_absolute() and root_path:
            try:
                ref_path = ref_path.relative_to(root_path)
            except ValueError:
                pass  # Not relative to root, use as-is

        # Normalize path separators
        normalized_path = str(ref_path).replace("\\", "/")

        # Try exact file_path match via SQL
        result = db.execute(
            "SELECT id FROM nodes WHERE file_path = ? AND type = 'module' LIMIT 1",
            [normalized_path],
        )
        if result:
            return str(result[0][0])

        # Try matching with path suffix (for partial paths)
        result = db.execute(
            "SELECT id FROM nodes WHERE file_path LIKE ? AND type = 'module' LIMIT 1",
            [f"%{normalized_path}"],
        )
        if result:
            return str(result[0][0])

        # For paths like "src/foo.ts", also try constructing the node ID directly
        # Module IDs are typically "mod:{file_path}" where file_path is relative
        possible_id = f"mod:{normalized_path}"
        if db.get_node(possible_id):
            return possible_id

    # Try pattern match on name
    nodes = db.find_by_name(f"%{node_ref}%")
    if nodes:
        # Prefer exact name matches
        for node in nodes:
            if node.name == node_ref:
                return str(node.id)
        return str(nodes[0].id)

    # Return original if not found (will fail in has_node check)
    return node_ref


# Registry of all MCP tools with descriptions for testing/listing
TOOL_REGISTRY: dict[str, dict[str, str]] = {
    "mu_status": {"description": "Get MU daemon status and codebase statistics"},
    "mu_bootstrap": {"description": "Bootstrap MU for a codebase in one step"},
    "mu_query": {"description": "Execute a MUQL query against the code graph"},
    "mu_read": {"description": "Read source code for a specific node"},
    "mu_context": {"description": "Extract smart context for a natural language question"},
    "mu_deps": {"description": "Show dependencies of a code node"},
    "mu_impact": {"description": "Find downstream impact of changing a node"},
    "mu_ancestors": {"description": "Find upstream dependencies of a node"},
    "mu_cycles": {"description": "Detect circular dependencies in the codebase"},
    "mu_patterns": {"description": "Get detected codebase patterns"},
    "mu_generate": {"description": "Generate code following codebase patterns"},
    "mu_validate": {"description": "Validate code changes against detected patterns"},
    "mu_warn": {"description": "Get proactive warnings about a target before modification"},
    "mu_ask": {"description": "Translate natural language to MUQL and execute"},
    "mu_task_context": {"description": "Extract comprehensive context for a development task"},
    "mu_related": {"description": "Suggest related files that should change together"},
    "mu_remember": {"description": "Store a memory for future recall across sessions"},
    "mu_recall": {"description": "Recall memories based on search criteria"},
    "mu_why": {"description": "Analyze git history to understand why code exists"},
    "mu_compress": {"description": "Generate compressed MU representation"},
    "mu_semantic_diff": {"description": "Compare two git refs and return semantic changes"},
    "mu_review_diff": {"description": "Comprehensive code review of changes between git refs"},
}


def test_tool(tool_name: str, tool_input: dict[str, Any] | None = None) -> dict[str, Any]:
    """Test a specific MCP tool with optional input.

    Args:
        tool_name: Name of the tool to test (e.g., "mu_status", "mu_query")
        tool_input: Optional dict of arguments to pass to the tool

    Returns:
        Dictionary with test result: {"ok": bool, "result": Any, "error": str | None}
    """
    # Map tool names to functions
    tool_funcs = {
        "mu_status": mu_status,
        "mu_bootstrap": mu_bootstrap,
        "mu_query": mu_query,
        "mu_read": mu_read,
        "mu_context": mu_context,
        "mu_deps": mu_deps,
        "mu_impact": mu_impact,
        "mu_ancestors": mu_ancestors,
        "mu_cycles": mu_cycles,
        "mu_patterns": mu_patterns,
        "mu_generate": mu_generate,
        "mu_validate": mu_validate,
        "mu_warn": mu_warn,
        "mu_ask": mu_ask,
        "mu_task_context": mu_task_context,
        "mu_related": mu_related,
        "mu_remember": mu_remember,
        "mu_recall": mu_recall,
        "mu_why": mu_why,
        "mu_compress": mu_compress,
        "mu_semantic_diff": mu_semantic_diff,
        "mu_review_diff": mu_review_diff,
    }

    if tool_name not in tool_funcs:
        return {"ok": False, "error": f"Unknown tool: {tool_name}"}

    func = tool_funcs[tool_name]

    try:
        if tool_input:
            result = func(**tool_input)
        else:
            # Use default test arguments for each tool
            defaults = {
                "mu_status": {},
                "mu_bootstrap": {"path": "."},
                "mu_query": {"query": "DESCRIBE tables"},
                "mu_read": {"node_id": "test"},  # Will likely fail
                "mu_context": {"question": "test", "max_tokens": 100},
                "mu_deps": {"node_name": "test"},
                "mu_impact": {"node_id": "test"},
                "mu_ancestors": {"node_id": "test"},
                "mu_cycles": {},
                "mu_patterns": {},
                "mu_generate": {"template_type": "hook", "name": "test"},
                "mu_validate": {},
                "mu_warn": {"target": "test"},
                "mu_ask": {"question": "what functions exist?", "execute": False},
                "mu_task_context": {"task": "test", "max_tokens": 100},
                "mu_related": {"file_path": "test.py"},
                "mu_remember": {"content": "test", "category": "learning"},
                "mu_recall": {},
                "mu_why": {"target": "test"},
                "mu_compress": {"path": "."},
                "mu_semantic_diff": {"base_ref": "HEAD~1", "head_ref": "HEAD"},
                "mu_review_diff": {"base_ref": "HEAD~1", "head_ref": "HEAD"},
            }
            tool_defaults = defaults.get(tool_name, {})
            result = func(**tool_defaults)  # type: ignore[arg-type]

        # Convert dataclass to dict if needed
        if hasattr(result, "__dataclass_fields__"):
            from dataclasses import asdict

            result = asdict(result)

        return {"ok": True, "result": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


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

    # Test mu_read
    try:
        # Try to read any function
        query_result = mu_query("SELECT id FROM functions LIMIT 1")
        if query_result.rows:
            read_result = mu_read(query_result.rows[0][0])
            results["mu_read"] = {
                "ok": True,
                "has_source": len(read_result.source) > 0,
            }
        else:
            results["mu_read"] = {"ok": True, "skipped": "no functions found"}
    except Exception as e:
        results["mu_read"] = {"ok": False, "error": str(e)}

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
    "test_tool",
    "TOOL_REGISTRY",
    # Bootstrap (single command)
    "mu_bootstrap",
    "mu_status",
    # Query & Read
    "mu_query",
    "mu_read",
    "mu_context",
    # Natural Language Query
    "mu_ask",
    # Dependencies
    "mu_deps",
    # Graph reasoning (petgraph-backed)
    "mu_impact",
    "mu_ancestors",
    "mu_cycles",
    # Intelligence Layer
    "mu_patterns",
    "mu_generate",
    "mu_validate",
    "mu_warn",
    "mu_task_context",
    "mu_related",
    # Cross-Session Memory
    "mu_remember",
    "mu_recall",
    # Why Layer
    "mu_why",
    # Compression
    "mu_compress",
    # Diff
    "mu_semantic_diff",
    # Diff Review
    "mu_review_diff",
    # Data types
    "NodeInfo",
    "QueryResult",
    "ReadResult",
    "ContextResult",
    "DepsResult",
    "ImpactResult",
    "AncestorsResult",
    "CyclesResult",
    "PatternInfo",
    "PatternsOutput",
    "GeneratedFileInfo",
    "GenerateOutput",
    "BootstrapResult",
    "SemanticDiffOutput",
    "ReviewDiffOutput",
    "CompressOutput",
    "AskResult",
    "TaskFileContext",
    "TaskContextOutput",
    "ViolationInfo",
    "ValidateOutput",
    "WarningInfo",
    "WarningsOutput",
    "RelatedFileInfo",
    "RelatedFilesOutput",
    "MemoryInfo",
    "RememberResult",
    "RecallOutput",
    "CommitInfoOutput",
    "WhyOutput",
]
