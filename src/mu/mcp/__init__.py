"""MCP (Model Context Protocol) server for MU.

This module exposes MU's code analysis capabilities as MCP tools,
allowing AI assistants like Claude Code to query and understand
codebases through the semantic graph.

Tools:
    mu_query: Execute MUQL queries against the code graph
    mu_context: Extract smart context for natural language questions
    mu_deps: Show dependencies of a node
    mu_node: Look up a node by ID or name
    mu_search: Search for nodes by pattern

Example:
    # Run the MCP server
    mu mcp serve

    # Or programmatically
    from mu.mcp import create_server
    server = create_server()
    server.run(transport="stdio")
"""

from mu.mcp.server import create_server, run_server

__all__ = ["create_server", "run_server"]
