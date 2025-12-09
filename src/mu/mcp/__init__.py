"""MCP (Model Context Protocol) server for MU.

This module exposes MU's code analysis capabilities as MCP tools,
allowing AI assistants like Claude Code to query and understand
codebases through the semantic graph.

Tools (12 total):
    Setup:
        mu_status: Get daemon status and codebase statistics
        mu_bootstrap: Initialize MU for a codebase in one step

    Graph Access:
        mu_query: Execute MUQL queries against the code graph
        mu_read: Read source code for a specific node

    Context Extraction:
        mu_context: Extract smart context for natural language questions
        mu_context_omega: Extract OMEGA-compressed context (3-5x token reduction)

    Analysis:
        mu_deps: Show dependencies of a node (outgoing, incoming, or both)
        mu_impact: Find downstream impact of changing a node
        mu_semantic_diff: Compare two git refs semantically
        mu_review_diff: Comprehensive PR code review

    Guidance:
        mu_patterns: Get detected codebase patterns
        mu_warn: Get proactive warnings before modifying code

Example:
    # Run the MCP server
    mu mcp serve

    # Or programmatically
    from mu.mcp import create_server
    server = create_server()
    server.run(transport="stdio")
"""

from mu.mcp.server import create_server, mcp, run_server

__all__ = ["create_server", "run_server", "mcp"]
