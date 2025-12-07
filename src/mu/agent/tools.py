"""Tool definitions and execution for MU Agent."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mu.client import DaemonClient

# Tool definitions in Anthropic API format
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "mu_query",
        "description": """Execute MUQL query against the code graph.

MUQL is a SQL-like language for querying code structure. Examples:
- SELECT: SELECT name, complexity FROM functions WHERE complexity > 50
- SHOW: SHOW dependencies OF UserService DEPTH 2
- FIND: FIND classes IMPLEMENTING Repository
- PATH: PATH FROM api_routes TO database MAX DEPTH 5
- ANALYZE: ANALYZE circular, ANALYZE coupling""",
        "input_schema": {
            "type": "object",
            "properties": {
                "muql": {
                    "type": "string",
                    "description": "The MUQL query to execute",
                }
            },
            "required": ["muql"],
        },
    },
    {
        "name": "mu_context",
        "description": """Extract smart context for a natural language question.

Returns the optimal code subgraph for answering the question in MU format.
Use this for broad questions that need comprehensive context.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Natural language question about the codebase",
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Maximum tokens in output (default 4000)",
                    "default": 4000,
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "mu_deps",
        "description": """Get dependencies of a code node.

Find what a node depends on (outgoing), what depends on it (incoming), or both.
Useful for understanding relationships between components.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "node": {
                    "type": "string",
                    "description": "Node name or ID (e.g., 'AuthService', 'mod:src/auth.py')",
                },
                "depth": {
                    "type": "integer",
                    "description": "How many levels deep to traverse (default 2)",
                    "default": 2,
                },
                "direction": {
                    "type": "string",
                    "enum": ["outgoing", "incoming", "both"],
                    "description": "Direction to traverse (default 'outgoing')",
                    "default": "outgoing",
                },
            },
            "required": ["node"],
        },
    },
    {
        "name": "mu_impact",
        "description": """Find downstream impact of changing a node.

Answer: "If I change X, what might break?"
Returns all nodes that would be affected by changes to this node.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "node": {
                    "type": "string",
                    "description": "Node name or ID to analyze impact for",
                },
                "edge_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Edge types to follow: imports, calls, inherits, contains",
                },
            },
            "required": ["node"],
        },
    },
    {
        "name": "mu_ancestors",
        "description": """Find upstream dependencies of a node.

Answer: "What does X depend on?"
Returns all nodes that this node transitively depends on.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "node": {
                    "type": "string",
                    "description": "Node name or ID to find ancestors for",
                },
                "edge_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Edge types to follow: imports, calls, inherits, contains",
                },
            },
            "required": ["node"],
        },
    },
    {
        "name": "mu_cycles",
        "description": """Detect circular dependencies in the codebase.

Find all circular dependency chains that could cause issues.
Returns cycles grouped by severity.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "edge_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Edge types to consider: imports, calls, inherits, contains",
                }
            },
            "required": [],
        },
    },
]


def execute_tool(
    name: str,
    args: dict[str, Any],
    client: DaemonClient,
) -> dict[str, Any]:
    """Execute a tool and return results.

    Args:
        name: The tool name to execute.
        args: Arguments for the tool.
        client: DaemonClient for making requests.

    Returns:
        Tool result as a dictionary. On error, returns {"error": "message"}.
    """
    try:
        if name == "mu_query":
            return _execute_query(args, client)
        elif name == "mu_context":
            return _execute_context(args, client)
        elif name == "mu_deps":
            return _execute_deps(args, client)
        elif name == "mu_impact":
            return _execute_impact(args, client)
        elif name == "mu_ancestors":
            return _execute_ancestors(args, client)
        elif name == "mu_cycles":
            return _execute_cycles(args, client)
        else:
            return {"error": f"Unknown tool: {name}"}
    except Exception as e:
        return {"error": str(e)}


def _execute_query(args: dict[str, Any], client: DaemonClient) -> dict[str, Any]:
    """Execute a MUQL query."""
    muql = args.get("muql", "")
    if not muql:
        return {"error": "Missing required argument: muql"}

    result = client.query(muql)
    return result


def _execute_context(args: dict[str, Any], client: DaemonClient) -> dict[str, Any]:
    """Execute smart context extraction."""
    question = args.get("question", "")
    if not question:
        return {"error": "Missing required argument: question"}

    max_tokens = args.get("max_tokens", 4000)
    result = client.context(question, max_tokens=max_tokens)
    return result


def _execute_deps(args: dict[str, Any], client: DaemonClient) -> dict[str, Any]:
    """Execute dependency lookup."""
    node = args.get("node", "")
    if not node:
        return {"error": "Missing required argument: node"}

    depth = args.get("depth", 2)
    direction = args.get("direction", "outgoing")

    # Build MUQL query for deps
    if direction == "incoming":
        muql = f"SHOW dependents OF {node} DEPTH {depth}"
    else:
        muql = f"SHOW dependencies OF {node} DEPTH {depth}"

    result = client.query(muql)
    result["node"] = node
    result["direction"] = direction
    return result


def _execute_impact(args: dict[str, Any], client: DaemonClient) -> dict[str, Any]:
    """Execute impact analysis."""
    node = args.get("node", "")
    if not node:
        return {"error": "Missing required argument: node"}

    edge_types = args.get("edge_types")
    result = client.impact(node, edge_types=edge_types)
    return result


def _execute_ancestors(args: dict[str, Any], client: DaemonClient) -> dict[str, Any]:
    """Execute ancestors lookup."""
    node = args.get("node", "")
    if not node:
        return {"error": "Missing required argument: node"}

    edge_types = args.get("edge_types")
    result = client.ancestors(node, edge_types=edge_types)
    return result


def _execute_cycles(args: dict[str, Any], client: DaemonClient) -> dict[str, Any]:
    """Execute cycle detection."""
    edge_types = args.get("edge_types")
    result = client.cycles(edge_types=edge_types)
    return result


def format_tool_result(result: dict[str, Any]) -> str:
    """Format a tool result for display to the LLM.

    Args:
        result: The raw tool result dictionary.

    Returns:
        Formatted string representation.
    """
    if "error" in result:
        return f"Error: {result['error']}"

    # Handle query results with columns/rows
    if "columns" in result and "rows" in result:
        return _format_query_result(result)

    # Handle context results
    if "mu_text" in result:
        return str(result["mu_text"])

    # Handle impact/ancestors results
    if "impacted_nodes" in result:
        nodes = result["impacted_nodes"]
        return f"Impact analysis: {len(nodes)} affected nodes\n" + "\n".join(
            f"  - {n}" for n in nodes[:50]
        )

    if "ancestor_nodes" in result:
        nodes = result["ancestor_nodes"]
        return f"Ancestors: {len(nodes)} dependencies\n" + "\n".join(f"  - {n}" for n in nodes[:50])

    # Handle cycles results
    if "cycles" in result:
        cycles = result["cycles"]
        if not cycles:
            return "No circular dependencies found."
        lines = [f"Found {len(cycles)} circular dependency cycles:"]
        for i, cycle in enumerate(cycles[:10], 1):
            lines.append(f"  Cycle {i}: {' -> '.join(cycle)}")
        return "\n".join(lines)

    # Default: JSON format
    return json.dumps(result, indent=2, default=str)


def _format_query_result(result: dict[str, Any]) -> str:
    """Format a query result with columns and rows."""
    columns = result.get("columns", [])
    rows = result.get("rows", [])
    row_count = result.get("row_count", len(rows))

    if not rows:
        return "No results found."

    lines = [f"Query returned {row_count} rows:"]

    # Format as simple table
    for row in rows[:50]:  # Limit to 50 rows
        row_dict = dict(zip(columns, row, strict=False))
        parts = []
        for col, val in row_dict.items():
            if val is not None:
                parts.append(f"{col}={val}")
        lines.append("  " + ", ".join(parts))

    if row_count > 50:
        lines.append(f"  ... and {row_count - 50} more rows")

    return "\n".join(lines)


__all__ = [
    "TOOL_DEFINITIONS",
    "execute_tool",
    "format_tool_result",
]
