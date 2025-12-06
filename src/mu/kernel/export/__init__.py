"""MU Kernel Export - Multiple output formats for graph data.

Provides exporters for various output formats from the MUbase graph:
- MU text format (LLM optimized)
- JSON (structured data for tools)
- Mermaid (diagrams for markdown)
- D2 (professional diagrams)
- Cytoscape.js (interactive visualization)

Example:
    >>> from mu.kernel import MUbase
    >>> from mu.kernel.export import get_default_manager, ExportOptions
    >>>
    >>> db = MUbase(".mubase")
    >>> manager = get_default_manager()
    >>>
    >>> # Export full graph as MU format
    >>> result = manager.export(db, "mu")
    >>> print(result.output)
    >>>
    >>> # Export filtered nodes as JSON
    >>> from mu.kernel.schema import NodeType
    >>> options = ExportOptions(node_types=[NodeType.CLASS], max_nodes=50)
    >>> result = manager.export(db, "json", options)
    >>>
    >>> # Export as Mermaid diagram
    >>> options = ExportOptions(extra={"diagram_type": "flowchart", "direction": "LR"})
    >>> result = manager.export(db, "mermaid", options)
    >>>
    >>> # List available formats
    >>> for fmt in manager.list_exporters():
    ...     print(f"{fmt['name']}: {fmt['description']}")
"""

from mu.kernel.export.base import (
    Exporter,
    ExportManager,
    ExportOptions,
    ExportResult,
    get_default_manager,
)
from mu.kernel.export.cytoscape import CytoscapeExporter
from mu.kernel.export.d2 import D2Exporter
from mu.kernel.export.filters import EdgeFilter, NodeFilter
from mu.kernel.export.json_export import JSONExporter
from mu.kernel.export.mermaid import MermaidExporter
from mu.kernel.export.mu_text import MUTextExporter

__all__ = [
    # Protocol and core classes
    "Exporter",
    "ExportOptions",
    "ExportResult",
    "ExportManager",
    "get_default_manager",
    # Filters
    "NodeFilter",
    "EdgeFilter",
    # Individual exporters
    "MUTextExporter",
    "JSONExporter",
    "MermaidExporter",
    "D2Exporter",
    "CytoscapeExporter",
]
