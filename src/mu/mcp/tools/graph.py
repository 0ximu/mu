"""Graph access tools: query and read."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from mu.client import DaemonError
from mu.mcp.models import QueryResult, ReadResult
from mu.mcp.tools._utils import find_mubase, get_client, resolve_node_id
from mu.paths import MU_DIR, MUBASE_FILE


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
    cwd = str(Path.cwd())

    try:
        client = get_client()
        with client:
            result = client.query(query, cwd=cwd)

        return QueryResult(
            columns=result.get("columns", []),
            rows=result.get("rows", []),
            row_count=result.get("row_count", len(result.get("rows", []))),
            execution_time_ms=result.get("execution_time_ms"),
            error=result.get("error"),
        )
    except DaemonError:
        mubase_path = find_mubase()
        if not mubase_path:
            raise DaemonError(
                f"No {MU_DIR}/{MUBASE_FILE} found. Run 'mu daemon start .' first."
            ) from None

        from mu.kernel import MUbase
        from mu.kernel.muql import MUQLEngine

        db = MUbase(mubase_path, read_only=True)
        try:
            engine = MUQLEngine(db)
            result = engine.query_dict(query)
            return QueryResult(
                columns=result.get("columns", []),
                rows=result.get("rows", []),
                row_count=result.get("row_count", len(result.get("rows", []))),
                execution_time_ms=result.get("execution_time_ms"),
                error=result.get("error"),
            )
        finally:
            db.close()


def mu_read(node_id: str, context_lines: int = 3) -> ReadResult:
    """Read source code for a specific node.

    Closes the find->read loop: after finding nodes with mu_query or mu_context,
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
    mubase_path = find_mubase()

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

    looks_like_path = (
        "/" in node_id
        or "\\" in node_id
        or node_id.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rs", ".cs"))
    )

    try:
        client = get_client()
        with client:
            if node_id.startswith(("mod:", "cls:", "fn:")):
                resolved_id = node_id
                node_data = client.node(node_id, cwd=cwd)
            elif looks_like_path:
                normalized_path = node_id.replace("\\", "/")
                resolved_id = f"mod:{normalized_path}"
                node_data = client.node(resolved_id, cwd=cwd)
                if not node_data:
                    query = f"SELECT * FROM nodes WHERE file_path LIKE '%{normalized_path}' AND type = 'module' LIMIT 1"
                    result = client.query(query, cwd=cwd)
                    if result.get("rows"):
                        cols = result.get("columns", [])
                        row = result["rows"][0]
                        node_data = dict(zip(cols, row, strict=False))
                        resolved_id = node_data.get("id", resolved_id)
            else:
                found = client.find_node(node_id, cwd=cwd)
                if found:
                    resolved_id = found.get("id", node_id)
                    node_data = found
                else:
                    node_data = None

            if node_data:
                root_path = mubase_path.parent.parent if mubase_path else Path.cwd()
                return _extract_source(node_data, resolved_id, root_path)
            # Daemon is running but couldn't find the node - raise error
            raise ValueError(f"Node not found: {node_id}")

    except DaemonError:
        pass  # Daemon not running, fall through to local mode

    if not mubase_path:
        raise DaemonError(f"No {MU_DIR}/{MUBASE_FILE} found. Run mu_bootstrap() first.") from None

    from mu.kernel import MUbase

    db = MUbase(mubase_path, read_only=True)
    root_path = mubase_path.parent.parent
    try:
        resolved_id = resolve_node_id(db, node_id, root_path)
        node = db.get_node(resolved_id)

        if not node:
            raise ValueError(f"Node not found: {node_id}")

        node_data = {
            "file_path": node.file_path,
            "line_start": node.line_start,
            "line_end": node.line_end,
            "node_type": node.type.value if hasattr(node.type, "value") else str(node.type),
        }

        return _extract_source(node_data, resolved_id, root_path)
    finally:
        db.close()


def register_graph_tools(mcp: FastMCP) -> None:
    """Register graph access tools with FastMCP server."""
    mcp.tool()(mu_query)
    mcp.tool()(mu_read)
