"""Node and edge filtering utilities for export operations.

Provides shared filtering functionality used by all exporters
for selecting nodes and edges by various criteria.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mu.kernel.models import Edge, Node
from mu.kernel.schema import EdgeType, NodeType

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase


class NodeFilter:
    """Filter nodes by various criteria.

    Provides methods for selecting nodes from a MUbase database
    based on IDs, types, names, and other properties.
    """

    def __init__(self, mubase: MUbase) -> None:
        """Initialize the node filter.

        Args:
            mubase: The MUbase database to filter nodes from.
        """
        self.mubase = mubase

    def by_ids(self, node_ids: list[str]) -> list[Node]:
        """Filter nodes by exact ID match.

        Args:
            node_ids: List of node IDs to retrieve.

        Returns:
            List of matching nodes (preserves order, skips missing).
        """
        nodes: list[Node] = []
        for node_id in node_ids:
            node = self.mubase.get_node(node_id)
            if node:
                nodes.append(node)
        return nodes

    def by_types(self, types: list[NodeType]) -> list[Node]:
        """Filter nodes by type.

        Args:
            types: List of node types to include.

        Returns:
            List of nodes matching any of the specified types.
        """
        nodes: list[Node] = []
        for node_type in types:
            nodes.extend(self.mubase.get_nodes(node_type))
        return nodes

    def by_names(
        self,
        names: list[str],
        fuzzy: bool = False,
        node_type: NodeType | None = None,
    ) -> list[Node]:
        """Filter nodes by name.

        Args:
            names: List of names to match.
            fuzzy: If True, use wildcard matching (% for any chars).
            node_type: Optional filter by node type.

        Returns:
            List of matching nodes.
        """
        nodes: list[Node] = []
        for name in names:
            pattern = f"%{name}%" if fuzzy else name
            matches = self.mubase.find_by_name(pattern, node_type)
            nodes.extend(matches)

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[Node] = []
        for node in nodes:
            if node.id not in seen:
                seen.add(node.id)
                unique.append(node)

        return unique

    def by_complexity(
        self,
        min_complexity: int | None = None,
        max_complexity: int | None = None,
    ) -> list[Node]:
        """Filter nodes by complexity range.

        Args:
            min_complexity: Minimum complexity threshold (inclusive).
            max_complexity: Maximum complexity threshold (inclusive).

        Returns:
            List of nodes within the complexity range.
        """
        min_val = min_complexity or 0
        return self.mubase.find_by_complexity(min_val, max_complexity)

    def by_file_path(self, file_path: str) -> list[Node]:
        """Filter nodes by file path.

        Args:
            file_path: The file path to match.

        Returns:
            List of nodes from the specified file.
        """
        return self.mubase.get_nodes(file_path=file_path)

    def combined(
        self,
        node_ids: list[str] | None = None,
        types: list[NodeType] | None = None,
        names: list[str] | None = None,
        fuzzy_names: bool = False,
        min_complexity: int | None = None,
        max_complexity: int | None = None,
        file_path: str | None = None,
    ) -> list[Node]:
        """Apply multiple filters with AND logic.

        All specified filters must match. If a filter is None,
        it is not applied (matches all nodes for that criterion).

        Args:
            node_ids: Filter by specific IDs (if provided, only these nodes).
            types: Filter by node types.
            names: Filter by names.
            fuzzy_names: Use fuzzy matching for names.
            min_complexity: Minimum complexity.
            max_complexity: Maximum complexity.
            file_path: Filter by file path.

        Returns:
            List of nodes matching all specified criteria.
        """
        # If specific IDs requested, start with those
        if node_ids:
            candidates = self.by_ids(node_ids)
        else:
            candidates = self.mubase.get_nodes()

        # Filter by types
        if types:
            type_set = set(types)
            candidates = [n for n in candidates if n.type in type_set]

        # Filter by names
        if names:
            if fuzzy_names:
                name_nodes = self.by_names(names, fuzzy=True)
            else:
                name_nodes = self.by_names(names, fuzzy=False)
            name_ids = {n.id for n in name_nodes}
            candidates = [n for n in candidates if n.id in name_ids]

        # Filter by complexity
        if min_complexity is not None or max_complexity is not None:
            min_val = min_complexity or 0
            max_val = max_complexity
            if max_val is not None:
                candidates = [n for n in candidates if min_val <= n.complexity <= max_val]
            else:
                candidates = [n for n in candidates if n.complexity >= min_val]

        # Filter by file path
        if file_path:
            candidates = [n for n in candidates if n.file_path == file_path]

        return candidates


class EdgeFilter:
    """Filter edges by various criteria.

    Provides methods for selecting edges from a MUbase database
    based on node sets and edge types.
    """

    def __init__(self, mubase: MUbase) -> None:
        """Initialize the edge filter.

        Args:
            mubase: The MUbase database to filter edges from.
        """
        self.mubase = mubase

    def for_nodes(
        self,
        nodes: list[Node],
        edge_types: list[EdgeType] | None = None,
    ) -> list[Edge]:
        """Get edges connecting the given nodes.

        Only returns edges where both source and target are
        in the provided node set.

        Args:
            nodes: List of nodes to get edges for.
            edge_types: Optional filter by edge types.

        Returns:
            List of edges between the given nodes.
        """
        node_ids = {n.id for n in nodes}
        all_edges = self.mubase.get_edges()

        # Filter to edges within our node set
        edges = [e for e in all_edges if e.source_id in node_ids and e.target_id in node_ids]

        # Filter by edge type
        if edge_types:
            type_set = set(edge_types)
            edges = [e for e in edges if e.type in type_set]

        return edges

    def by_type(self, edge_type: EdgeType) -> list[Edge]:
        """Get all edges of a specific type.

        Args:
            edge_type: The edge type to filter by.

        Returns:
            List of edges of the specified type.
        """
        return self.mubase.get_edges(edge_type=edge_type)

    def outgoing(
        self,
        node_id: str,
        edge_types: list[EdgeType] | None = None,
    ) -> list[Edge]:
        """Get outgoing edges from a node.

        Args:
            node_id: The source node ID.
            edge_types: Optional filter by edge types.

        Returns:
            List of outgoing edges.
        """
        edges = self.mubase.get_edges(source_id=node_id)

        if edge_types:
            type_set = set(edge_types)
            edges = [e for e in edges if e.type in type_set]

        return edges

    def incoming(
        self,
        node_id: str,
        edge_types: list[EdgeType] | None = None,
    ) -> list[Edge]:
        """Get incoming edges to a node.

        Args:
            node_id: The target node ID.
            edge_types: Optional filter by edge types.

        Returns:
            List of incoming edges.
        """
        edges = self.mubase.get_edges(target_id=node_id)

        if edge_types:
            type_set = set(edge_types)
            edges = [e for e in edges if e.type in type_set]

        return edges


__all__ = [
    "NodeFilter",
    "EdgeFilter",
]
