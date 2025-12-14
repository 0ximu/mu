"""MCP Tool registration.

This module registers all MCP tools with the FastMCP server instance.
Tools are organized by category for maintainability.
"""

from mcp.server.fastmcp import FastMCP

from mu.mcp.tools.analysis import register_analysis_tools
from mu.mcp.tools.context import register_context_tools
from mu.mcp.tools.graph import register_graph_tools
from mu.mcp.tools.guidance import register_guidance_tools
from mu.mcp.tools.setup import register_setup_tools


def register_all_tools(mcp: FastMCP) -> None:
    """Register all MCP tools with the server.

    Tools are registered in dependency order:
    1. Setup (mu_status, mu_bootstrap)
    2. Graph (mu_query, mu_read)
    3. Context (mu_context, mu_context_omega)
    4. Analysis (mu_deps, mu_impact, mu_semantic_diff, mu_review_diff)
    5. Guidance (mu_patterns, mu_warn)
    """
    register_setup_tools(mcp)
    register_graph_tools(mcp)
    register_context_tools(mcp)
    register_analysis_tools(mcp)
    register_guidance_tools(mcp)


__all__ = ["register_all_tools"]
