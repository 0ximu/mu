"""Data models for the MU Kernel graph storage.

Defines Node and Edge dataclasses that map to DuckDB tables.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from mu.kernel.schema import EdgeType, NodeType


@dataclass
class Node:
    """A node in the code graph.

    Represents a code entity: module, class, function, or external dependency.
    """

    id: str
    type: NodeType
    name: str
    qualified_name: str | None = None
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    complexity: int = 0

    def to_tuple(self) -> tuple[str, str, str, str | None, str | None, int | None, int | None, str, int]:
        """Convert to tuple for DuckDB insertion."""
        return (
            self.id,
            self.type.value,
            self.name,
            self.qualified_name,
            self.file_path,
            self.line_start,
            self.line_end,
            json.dumps(self.properties) if self.properties else "{}",
            self.complexity,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "type": self.type.value,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "properties": self.properties,
            "complexity": self.complexity,
        }

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> Node:
        """Create Node from DuckDB row.

        Expected row format:
        (id, type, name, qualified_name, file_path, line_start, line_end, properties, complexity)
        """
        properties = row[7]
        if isinstance(properties, str):
            properties = json.loads(properties)
        elif properties is None:
            properties = {}

        return cls(
            id=row[0],
            type=NodeType(row[1]),
            name=row[2],
            qualified_name=row[3],
            file_path=row[4],
            line_start=row[5],
            line_end=row[6],
            properties=properties,
            complexity=row[8] if len(row) > 8 else 0,
        )


@dataclass
class Edge:
    """An edge in the code graph.

    Represents a relationship between two nodes: contains, imports, inherits.
    """

    id: str
    source_id: str
    target_id: str
    type: EdgeType
    properties: dict[str, Any] = field(default_factory=dict)

    def to_tuple(self) -> tuple[str, str, str, str, str]:
        """Convert to tuple for DuckDB insertion."""
        return (
            self.id,
            self.source_id,
            self.target_id,
            self.type.value,
            json.dumps(self.properties) if self.properties else "{}",
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "type": self.type.value,
            "properties": self.properties,
        }

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> Edge:
        """Create Edge from DuckDB row.

        Expected row format:
        (id, source_id, target_id, type, properties)
        """
        properties = row[4]
        if isinstance(properties, str):
            properties = json.loads(properties)
        elif properties is None:
            properties = {}

        return cls(
            id=row[0],
            source_id=row[1],
            target_id=row[2],
            type=EdgeType(row[3]),
            properties=properties,
        )


__all__ = [
    "Node",
    "Edge",
]
