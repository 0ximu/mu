"""MCP server implementation for MU.

Provides MCP tools for code analysis through the semantic graph.
Uses the daemon client when available, falls back to direct MUbase access.

This is the main entry point for the MCP server. Tool implementations
are in the tools/ subpackage and models are in the models/ subpackage.
"""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

# Re-export all models for backward compatibility
from mu.mcp.models import (
    BootstrapResult,
    ContextResult,
    DepsResult,
    ImpactResult,
    NodeInfo,
    OmegaContextOutput,
    PatternInfo,
    PatternsOutput,
    QueryResult,
    ReadResult,
    ReviewDiffOutput,
    SemanticDiffOutput,
    ViolationInfo,
    WarningInfo,
    WarningsOutput,
)

# Import registration function
from mu.mcp.tools import register_all_tools

# Re-export tool functions for backward compatibility
from mu.mcp.tools.analysis import (
    mu_deps,
    mu_impact,
    mu_review_diff,
    mu_semantic_diff,
)
from mu.mcp.tools.context import mu_context, mu_context_omega
from mu.mcp.tools.graph import mu_query, mu_read
from mu.mcp.tools.guidance import mu_patterns, mu_warn
from mu.mcp.tools.setup import mu_bootstrap, mu_status

# Create the MCP server instance
mcp = FastMCP(
    "MU Code Analysis",
    json_response=True,
)

# Register all tools
register_all_tools(mcp)

# Registry of all MCP tools with descriptions for testing/listing
TOOL_REGISTRY: dict[str, dict[str, str]] = {
    # Setup
    "mu_status": {"description": "Get MU daemon status and codebase statistics"},
    "mu_bootstrap": {"description": "Bootstrap MU for a codebase in one step"},
    # Graph
    "mu_query": {"description": "Execute a MUQL query against the code graph"},
    "mu_read": {"description": "Read source code for a specific node"},
    # Context
    "mu_context": {"description": "Extract smart context for a natural language question"},
    "mu_context_omega": {"description": "Extract OMEGA-compressed context for a question"},
    # Analysis
    "mu_deps": {"description": "Show dependencies of a code node"},
    "mu_impact": {"description": "Find downstream impact of changing a node"},
    "mu_semantic_diff": {"description": "Compare two git refs and return semantic changes"},
    "mu_review_diff": {"description": "Comprehensive code review of changes between git refs"},
    # Guidance
    "mu_patterns": {"description": "Get detected codebase patterns"},
    "mu_warn": {"description": "Get proactive warnings about a target before modification"},
}


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


def _get_test_node_id() -> str | None:
    """Find an actual node ID from the graph for testing.

    Returns:
        A valid node ID from the graph, or None if no nodes found.
    """
    try:
        # Query for any function node (most codebases have functions)
        result = mu_query("SELECT id FROM functions LIMIT 1")
        if result.rows and len(result.rows) > 0:
            return str(result.rows[0][0])

        # Fallback to any class
        result = mu_query("SELECT id FROM classes LIMIT 1")
        if result.rows and len(result.rows) > 0:
            return str(result.rows[0][0])

        # Fallback to any module
        result = mu_query("SELECT id FROM modules LIMIT 1")
        if result.rows and len(result.rows) > 0:
            return str(result.rows[0][0])

        return None
    except Exception:
        return None


def _get_test_file_path() -> str | None:
    """Find an actual file path from the graph for testing.

    Returns:
        A valid file path from the graph, or None if no files found.
    """
    try:
        result = mu_query("SELECT file_path FROM modules WHERE file_path IS NOT NULL LIMIT 1")
        if result.rows and len(result.rows) > 0:
            return str(result.rows[0][0])
        return None
    except Exception:
        return None


def test_tool(tool_name: str, tool_input: dict[str, Any] | None = None) -> dict[str, Any]:
    """Test a specific MCP tool with optional input.

    Args:
        tool_name: Name of the tool to test (e.g., "mu_status", "mu_query")
        tool_input: Optional dict of arguments to pass to the tool

    Returns:
        Dictionary with test result: {"ok": bool, "result": Any, "error": str | None}
    """
    from collections.abc import Callable

    # Tool function lookup
    tool_funcs: dict[str, Callable[..., Any]] = {
        "mu_status": mu_status,
        "mu_bootstrap": mu_bootstrap,
        "mu_query": mu_query,
        "mu_read": mu_read,
        "mu_context": mu_context,
        "mu_context_omega": mu_context_omega,
        "mu_deps": mu_deps,
        "mu_impact": mu_impact,
        "mu_semantic_diff": mu_semantic_diff,
        "mu_review_diff": mu_review_diff,
        "mu_patterns": mu_patterns,
        "mu_warn": mu_warn,
    }

    tool_func = tool_funcs.get(tool_name)
    if not tool_func:
        return {"ok": False, "error": f"Unknown tool: {tool_name}"}

    try:
        if tool_input:
            result = tool_func(**tool_input)
        else:
            # Use default test arguments - query for real nodes when needed
            test_node_id = None
            test_file_path = None

            # Tools that need a real node ID
            node_requiring_tools = {"mu_read", "mu_deps", "mu_impact", "mu_warn"}
            if tool_name in node_requiring_tools:
                test_node_id = _get_test_node_id()
                test_file_path = _get_test_file_path()
                if not test_node_id and not test_file_path:
                    return {
                        "ok": False,
                        "error": "No nodes found in graph. Run mu_bootstrap first.",
                        "skipped": True,
                    }

            defaults: dict[str, dict[str, Any]] = {
                "mu_status": {},
                "mu_bootstrap": {"path": "."},
                "mu_query": {"query": "DESCRIBE tables"},
                "mu_read": {"node_id": test_node_id or ""},
                "mu_context": {"question": "what does this codebase do", "max_tokens": 100},
                "mu_context_omega": {"question": "what does this codebase do", "max_tokens": 100},
                "mu_deps": {"node_name": test_node_id or ""},
                "mu_impact": {"node_id": test_node_id or ""},
                "mu_semantic_diff": {"base_ref": "HEAD~1", "head_ref": "HEAD"},
                "mu_review_diff": {"base_ref": "HEAD~1", "head_ref": "HEAD"},
                "mu_patterns": {},
                "mu_warn": {"target": test_file_path or test_node_id or ""},
            }
            tool_defaults = defaults.get(tool_name, {})
            result = tool_func(**tool_defaults)

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

    for tool_name in TOOL_REGISTRY:
        results[tool_name] = test_tool(tool_name)

    return results


__all__ = [
    "mcp",
    "create_server",
    "run_server",
    "test_tools",
    "test_tool",
    "TOOL_REGISTRY",
    # Tool functions
    "mu_status",
    "mu_bootstrap",
    "mu_query",
    "mu_read",
    "mu_context",
    "mu_context_omega",
    "mu_deps",
    "mu_impact",
    "mu_semantic_diff",
    "mu_review_diff",
    "mu_patterns",
    "mu_warn",
    # Data types
    "NodeInfo",
    "QueryResult",
    "ReadResult",
    "ContextResult",
    "DepsResult",
    "ImpactResult",
    "PatternInfo",
    "PatternsOutput",
    "BootstrapResult",
    "SemanticDiffOutput",
    "ReviewDiffOutput",
    "ViolationInfo",
    "WarningInfo",
    "WarningsOutput",
    "OmegaContextOutput",
]
