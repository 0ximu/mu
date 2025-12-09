"""Common models used across MCP tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
