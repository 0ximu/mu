"""Base protocol for graph exporters.

Defines the interface that all exporters must implement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase
    from mu.kernel.schema import NodeType


@dataclass
class ExportOptions:
    """Options for export operations.

    Common options that apply to all exporters.
    """

    node_ids: list[str] | None = None
    """Filter to specific node IDs."""

    node_types: list[NodeType] | None = None
    """Filter by node types."""

    max_nodes: int | None = None
    """Maximum number of nodes to export."""

    include_edges: bool = True
    """Whether to include edges in export."""

    extra: dict[str, Any] = field(default_factory=dict)
    """Format-specific options."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "node_ids": self.node_ids,
            "node_types": [t.value for t in self.node_types] if self.node_types else None,
            "max_nodes": self.max_nodes,
            "include_edges": self.include_edges,
            "extra": self.extra,
        }


@dataclass
class ExportResult:
    """Result of an export operation."""

    output: str
    """The exported content as a string."""

    format: str
    """The format name (e.g., 'mu', 'json', 'mermaid')."""

    node_count: int
    """Number of nodes in the export."""

    edge_count: int
    """Number of edges in the export."""

    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    """Timestamp of generation."""

    error: str | None = None
    """Error message if export failed."""

    @property
    def success(self) -> bool:
        """Check if export succeeded."""
        return self.error is None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "output": self.output,
            "format": self.format,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "generated_at": self.generated_at,
            "error": self.error,
            "success": self.success,
        }


@runtime_checkable
class Exporter(Protocol):
    """Protocol for graph exporters.

    All exporters must implement this interface to be registered
    with the ExportManager.
    """

    @property
    def format_name(self) -> str:
        """Return the format name identifier."""
        ...

    @property
    def file_extension(self) -> str:
        """Return the default file extension for this format."""
        ...

    @property
    def description(self) -> str:
        """Return a short description of this format."""
        ...

    def export(
        self,
        mubase: MUbase,
        options: ExportOptions | None = None,
    ) -> ExportResult:
        """Export graph to this format.

        Args:
            mubase: The MUbase database to export from.
            options: Export options for filtering and customization.

        Returns:
            ExportResult with the exported content.
        """
        ...


class ExportManager:
    """Manage and dispatch to registered exporters.

    Provides a central registry for all export formats and handles
    format lookup and dispatching.
    """

    def __init__(self) -> None:
        """Initialize the export manager with default exporters."""
        self._exporters: dict[str, Exporter] = {}

    def register(self, exporter: Exporter) -> None:
        """Register an exporter.

        Args:
            exporter: The exporter instance to register.
        """
        self._exporters[exporter.format_name] = exporter

    def get_exporter(self, format_name: str) -> Exporter | None:
        """Get an exporter by format name.

        Args:
            format_name: The format identifier.

        Returns:
            The exporter if found, None otherwise.
        """
        return self._exporters.get(format_name)

    def export(
        self,
        mubase: MUbase,
        format_name: str,
        options: ExportOptions | None = None,
    ) -> ExportResult:
        """Export graph in the specified format.

        Args:
            mubase: The MUbase database to export from.
            format_name: The format to export to.
            options: Export options for filtering and customization.

        Returns:
            ExportResult with the exported content.
        """
        exporter = self._exporters.get(format_name)
        if exporter is None:
            return ExportResult(
                output="",
                format=format_name,
                node_count=0,
                edge_count=0,
                error=f"Unknown format: {format_name}. Available: {', '.join(self.list_formats())}",
            )

        return exporter.export(mubase, options)

    def list_formats(self) -> list[str]:
        """List all registered format names.

        Returns:
            List of format names.
        """
        return sorted(self._exporters.keys())

    def list_exporters(self) -> list[dict[str, str]]:
        """List all registered exporters with details.

        Returns:
            List of dictionaries with format info.
        """
        return [
            {
                "name": exp.format_name,
                "extension": exp.file_extension,
                "description": exp.description,
            }
            for exp in sorted(self._exporters.values(), key=lambda e: e.format_name)
        ]


def get_default_manager() -> ExportManager:
    """Get an ExportManager with all default exporters registered.

    Returns:
        ExportManager with MU, JSON, Mermaid, D2, Cytoscape, and Lisp exporters.
    """
    from mu.kernel.export.cytoscape import CytoscapeExporter
    from mu.kernel.export.d2 import D2Exporter
    from mu.kernel.export.json_export import JSONExporter
    from mu.kernel.export.lisp import LispExporter
    from mu.kernel.export.mermaid import MermaidExporter
    from mu.kernel.export.mu_text import MUTextExporter

    manager = ExportManager()
    manager.register(MUTextExporter())
    manager.register(JSONExporter())
    manager.register(MermaidExporter())
    manager.register(D2Exporter())
    manager.register(CytoscapeExporter())
    manager.register(LispExporter())
    return manager


__all__ = [
    "ExportOptions",
    "ExportResult",
    "Exporter",
    "ExportManager",
    "get_default_manager",
]
