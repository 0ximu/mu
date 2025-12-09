"""Setup tools: status and bootstrap."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from mu.client import DaemonError
from mu.mcp.models import BootstrapResult
from mu.mcp.tools._utils import find_mubase, get_client
from mu.paths import MU_DIR, MUBASE_FILE, get_mubase_path


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
    cwd = str(Path.cwd())
    config_exists = (Path.cwd() / ".murc.toml").exists()
    mubase_path = find_mubase()
    embeddings_exist = False

    if mubase_path:
        embeddings_db = mubase_path.parent / "embeddings.db"
        embeddings_exist = embeddings_db.exists()

    try:
        client = get_client()
        with client:
            status = client.status(cwd=cwd)

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
                        "MU ready (direct access). Run `mu kernel embed .` to enable mu_search()."
                        if not embeddings_exist
                        else "MU ready (direct access)."
                    ),
                }
            finally:
                db.close()

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
        suggestion="For semantic search, run: mu kernel embed . (requires OPENAI_API_KEY)",
    )


def register_setup_tools(mcp: FastMCP) -> None:
    """Register setup tools with FastMCP server."""
    mcp.tool()(mu_status)
    mcp.tool()(mu_bootstrap)
