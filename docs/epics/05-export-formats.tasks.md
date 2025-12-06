# Export Formats - Task Breakdown

## Business Context

**Problem**: Developers need to visualize and share code graph data in various formats - MU text for LLMs, JSON for tooling integration, and diagram formats (Mermaid, D2, Cytoscape) for documentation and presentations. Currently, the kernel can only output data via MUQL queries with limited formatting.

**Outcome**: A unified export system with pluggable formatters that enables:
- Token-efficient MU text for LLM consumption
- Structured JSON for programmatic access
- Diagram generation for visual documentation
- Interactive visualization export for exploration

**Users**:
- Developers feeding context to LLMs (MU format)
- Tool builders integrating with MU data (JSON format)
- Technical writers creating architecture docs (Mermaid/D2)
- Teams exploring large codebases interactively (Cytoscape)

---

## Discovered Patterns

| Pattern | File | Relevance |
|---------|------|-----------|
| Protocol definition | `/Users/imu/Dev/work/mu/src/mu/kernel/embeddings/providers/base.py:70-100` | `Exporter` protocol should follow `EmbeddingProvider` pattern with `@runtime_checkable` and properties |
| Provider enum | `/Users/imu/Dev/work/mu/src/mu/kernel/embeddings/providers/base.py:14-18` | `ExportFormat` enum should follow `EmbeddingProviderType` pattern |
| Dataclass with `to_dict()` | `/Users/imu/Dev/work/mu/src/mu/kernel/models.py:15-86` | `ExportResult` should follow Node/Edge pattern with serialization |
| Context MU export | `/Users/imu/Dev/work/mu/src/mu/kernel/context/export.py:20-51` | `MUTextExporter` reuses sigil constants (!, $, #, @, ::) |
| Module grouping | `/Users/imu/Dev/work/mu/src/mu/kernel/context/export.py:110-134` | Group nodes by module path for organized output |
| Submodule structure | `/Users/imu/Dev/work/mu/src/mu/kernel/context/__init__.py` | Export module should follow same `__init__.py` pattern |
| CLI command group | `/Users/imu/Dev/work/mu/src/mu/cli.py:850-960` | `kernel export` follows `kernel build`/`kernel stats` patterns |
| Public API exports | `/Users/imu/Dev/work/mu/src/mu/kernel/__init__.py:31-73` | Re-export key classes from `kernel/__init__.py` |
| Test class organization | `/Users/imu/Dev/work/mu/tests/unit/test_kernel.py:14-100` | Test classes per component (TestMUExporter, TestJSONExporter, etc.) |

---

## Task Breakdown

### Task 1: Create Export Module Structure and Exporter Protocol

**Priority**: P0 (Foundation - blocks all exporters)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/export/__init__.py` (new)
- `/Users/imu/Dev/work/mu/src/mu/kernel/export/base.py` (new)

**Pattern**: Follow `EmbeddingProvider` protocol in `embeddings/providers/base.py:70-100`

**Description**: Create the export submodule structure with the `Exporter` protocol and supporting types. The protocol defines the interface all exporters must implement.

**Implementation**:
```python
# base.py
from typing import Protocol, runtime_checkable
from enum import Enum
from dataclasses import dataclass

class ExportFormat(str, Enum):
    MU = "mu"
    JSON = "json"
    MERMAID = "mermaid"
    D2 = "d2"
    CYTOSCAPE = "cytoscape"

@dataclass
class ExportResult:
    output: str
    format: str
    node_count: int
    edge_count: int

    def to_dict(self) -> dict[str, Any]: ...

@runtime_checkable
class Exporter(Protocol):
    @property
    def format_name(self) -> str: ...

    @property
    def file_extension(self) -> str: ...

    def export(
        self,
        mubase: MUbase,
        node_ids: list[str] | None = None,
        **options
    ) -> str: ...
```

**Status**: Complete

**Acceptance Criteria**:
- [x] `ExportFormat` enum with all 5 formats
- [x] `Exporter` protocol with `@runtime_checkable` decorator
- [x] `ExportResult` dataclass with `output`, `format`, `node_count`, `edge_count`
- [x] `ExportError` exception class for error handling
- [x] `export/__init__.py` exports public API with `__all__`
- [x] Type annotations pass mypy
- [x] Unit tests for enum values and protocol compliance

---

### Task 2: Implement ExportManager Coordinator

**Priority**: P0 (Orchestrates all exports)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/export/manager.py` (new)

**Pattern**: Follow service pattern similar to `EmbeddingService` in `embeddings/service.py`

**Description**: Create `ExportManager` class that registers exporters and coordinates export operations. Provides unified entry point for all export formats.

**Implementation**:
```python
class ExportManager:
    """Manage all export formats."""

    _exporters: dict[ExportFormat, type[Exporter]] = {}

    @classmethod
    def register(cls, format: ExportFormat, exporter_class: type[Exporter]) -> None:
        """Register an exporter for a format."""
        cls._exporters[format] = exporter_class

    def export(
        self,
        mubase: MUbase,
        format: ExportFormat | str,
        node_ids: list[str] | None = None,
        node_types: list[NodeType] | None = None,
        **options
    ) -> ExportResult:
        """Export graph in specified format."""
        ...

    def list_formats(self) -> list[dict[str, str]]:
        """List available export formats."""
        ...
```

**Status**: Complete (implemented in base.py alongside protocol)

**Acceptance Criteria**:
- [x] `ExportManager` with exporter registration via `register()`
- [x] `export()` method with format selection and node filtering
- [x] Node filtering by IDs and types
- [x] `list_formats()` returns available exporters with name/extension
- [x] Graceful error handling for unknown formats
- [x] Auto-registration of built-in exporters via `get_default_manager()`
- [x] Unit tests for registration and export dispatch

---

### Task 3: Implement Node/Edge Filtering Utilities

**Priority**: P0 (Required by all exporters)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/export/filters.py` (new)

**Pattern**: Follow query methods in `mubase.py:133-220`

**Description**: Create shared filtering utilities for selecting nodes and edges by ID, name, type, or other criteria. Used by all exporters for consistent filtering.

**Implementation**:
```python
class NodeFilter:
    """Filter nodes by various criteria."""

    def __init__(self, mubase: MUbase):
        self.mubase = mubase

    def by_ids(self, node_ids: list[str]) -> list[Node]:
        """Filter nodes by exact ID match."""
        ...

    def by_types(self, types: list[NodeType]) -> list[Node]:
        """Filter nodes by type."""
        ...

    def by_names(self, names: list[str], fuzzy: bool = False) -> list[Node]:
        """Filter nodes by name (exact or fuzzy match)."""
        ...

    def get_related_edges(self, nodes: list[Node]) -> list[Edge]:
        """Get edges connecting the given nodes."""
        ...
```

**Status**: Complete

**Acceptance Criteria**:
- [x] Filter by node IDs (exact match)
- [x] Filter by node types (list of NodeType)
- [x] Filter by names (with optional fuzzy/wildcard support)
- [x] Combine multiple filters (AND logic)
- [x] Get edges for filtered node set (only edges between included nodes)
- [x] Efficient queries using DuckDB indexes
- [x] Unit tests for each filter type and combinations

---

### Task 4: Implement MU Text Exporter

**Priority**: P0 (Primary export format)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/export/mu_text.py` (new)

**Pattern**: Follow `ContextExporter` in `context/export.py:20-380` for sigil mappings and module grouping

**Description**: Export graph as MU sigil-based text format, optimized for LLM consumption. Reuses sigil constants from existing `ContextExporter`.

**Implementation**:
```python
class MUTextExporter:
    """Export graph as MU text format."""

    format_name = "mu"
    file_extension = ".mu"

    # MU Sigils (reuse from ContextExporter)
    SIGILS = {
        NodeType.MODULE: "!",
        NodeType.CLASS: "$",
        NodeType.FUNCTION: "#",
        NodeType.EXTERNAL: "@ext",
    }
    SIGIL_METADATA = "@"
    SIGIL_ANNOTATION = "::"
    OP_FLOW = "->"
    OP_MUTATION = "=>"

    def export(
        self,
        mubase: MUbase,
        node_ids: list[str] | None = None,
        max_tokens: int | None = None,
        include_complexity: bool = False,
    ) -> str:
        """Export graph as MU text."""
        ...

    def _export_module(self, path: str, nodes: list[Node], mubase: MUbase) -> list[str]:
        """Export a single module with its contents."""
        ...
```

**Status**: Complete

**Acceptance Criteria**:
- [x] Implements `Exporter` protocol
- [x] Exports modules with `!` sigil
- [x] Exports classes with `$` sigil, inheritance with `<`
- [x] Exports functions with `#` sigil, parameters, return types
- [x] Groups output by module path
- [x] Includes `@` imports section
- [x] Uses `::` for decorators/annotations
- [x] Uses `=>` for mutations
- [ ] Token budgeting with `max_tokens` option (via tiktoken) - deferred
- [x] Output consistent with existing `mu compress` output
- [x] Unit tests comparing against expected MU format

---

### Task 5: Implement JSON Exporter

**Priority**: P0 (Essential for tooling)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/export/json_export.py` (new)

**Pattern**: Follow `to_dict()` methods in `models.py:48-60` and JSON export in `context/export.py:81-108`

**Description**: Export graph as structured JSON with nodes, edges, and metadata. Supports pretty-printing and schema versioning.

**Implementation**:
```python
class JSONExporter:
    """Export graph as JSON."""

    format_name = "json"
    file_extension = ".json"

    def export(
        self,
        mubase: MUbase,
        node_ids: list[str] | None = None,
        pretty: bool = True,
        include_edges: bool = True,
    ) -> str:
        """Export graph as JSON."""
        nodes = self._get_nodes(mubase, node_ids)
        edges = self._get_edges(mubase, node_ids) if include_edges else []

        data = {
            "version": "1.0",
            "generated_at": datetime.now().isoformat(),
            "stats": {
                "node_count": len(nodes),
                "edge_count": len(edges),
            },
            "nodes": [n.to_dict() for n in nodes],
            "edges": [e.to_dict() for e in edges],
        }

        return json.dumps(data, indent=2 if pretty else None)
```

**Status**: Complete

**Acceptance Criteria**:
- [x] Implements `Exporter` protocol
- [x] Version field for schema evolution
- [x] `nodes` array with full node data via `to_dict()`
- [x] `edges` array with relationships
- [x] `stats` object with counts
- [x] `generated_at` timestamp
- [x] Pretty-print option with 2-space indent
- [x] Edge filtering when `include_edges=False`
- [x] Valid JSON output (parseable with json.loads)
- [x] Unit tests for JSON structure and roundtrip

---

### Task 6: Implement Mermaid Exporter

**Priority**: P1 (Diagram format)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/export/mermaid.py` (new)

**Pattern**: Follow node/edge iteration patterns in epic spec

**Description**: Export graph as Mermaid diagram syntax, supporting flowchart and classDiagram types. Handle large graphs with node limits.

**Implementation**:
```python
class MermaidExporter:
    """Export graph as Mermaid diagram."""

    format_name = "mermaid"
    file_extension = ".mmd"

    SHAPES = {
        NodeType.MODULE: "([{name}])",      # Stadium shape
        NodeType.CLASS: "[{name}]",          # Rectangle
        NodeType.FUNCTION: "({name})",       # Rounded
        NodeType.EXTERNAL: ">>{name}]",      # Asymmetric
    }

    ARROWS = {
        EdgeType.CONTAINS: "-->",
        EdgeType.IMPORTS: "-.->",
        EdgeType.INHERITS: "===>",
    }

    def export(
        self,
        mubase: MUbase,
        node_ids: list[str] | None = None,
        diagram_type: str = "flowchart",
        direction: str = "TB",
        max_nodes: int = 50,
    ) -> str:
        """Export graph as Mermaid diagram."""
        ...

    def _escape(self, text: str) -> str:
        """Escape special Mermaid characters."""
        return text.replace('"', "'").replace("[", "(").replace("]", ")")
```

**Status**: Complete

**Acceptance Criteria**:
- [x] Implements `Exporter` protocol
- [x] Generates valid `flowchart TB` syntax
- [x] Generates valid `classDiagram` syntax
- [x] Node shapes by type (stadium, rectangle, rounded)
- [x] Edge arrows by relationship type (solid, dashed, double)
- [x] Edge labels for relationship types
- [x] Character escaping for Mermaid special chars
- [x] `max_nodes` limit to prevent huge diagrams
- [x] Direction options (TB, LR, BT, RL)
- [x] Unit tests validating Mermaid syntax structure

---

### Task 7: Implement D2 Exporter

**Priority**: P1 (Professional diagrams)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/export/d2.py` (new)

**Pattern**: Follow similar structure to Mermaid exporter

**Description**: Export graph as D2 diagram language for professional diagram generation. Support styling and nested containers.

**Implementation**:
```python
class D2Exporter:
    """Export graph as D2 diagram."""

    format_name = "d2"
    file_extension = ".d2"

    STYLES = {
        NodeType.MODULE: "shape: package",
        NodeType.CLASS: "shape: class",
        NodeType.FUNCTION: "shape: rectangle; style.border-radius: 8",
        NodeType.EXTERNAL: "shape: cloud",
    }

    def export(
        self,
        mubase: MUbase,
        node_ids: list[str] | None = None,
        direction: str = "right",
        include_styles: bool = True,
    ) -> str:
        """Export graph as D2 diagram."""
        lines = [f"direction: {direction}", ""]

        # Node definitions
        for node in nodes:
            lines.append(f"{node.id}: {node.name}")
            if include_styles:
                style = self.STYLES.get(node.type, "")
                if style:
                    lines.append(f"{node.id}.{style}")

        # Edge definitions
        for edge in edges:
            lines.append(f"{edge.source_id} -> {edge.target_id}: {edge.type.value}")

        return "\n".join(lines)
```

**Status**: Complete

**Acceptance Criteria**:
- [x] Implements `Exporter` protocol
- [x] Generates valid D2 syntax
- [x] `direction: right|down|left|up` header
- [x] Node definitions with labels
- [x] Shape styles by node type
- [x] Edge definitions with labels
- [x] Edge style overrides (dashed for imports)
- [ ] Nested containers for module grouping (optional) - deferred
- [x] Unit tests validating D2 syntax structure

---

### Task 8: Implement Cytoscape Exporter

**Priority**: P1 (Interactive visualization)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/export/cytoscape.py` (new)

**Pattern**: Follow JSON structure in `context/export.py:81-108`

**Description**: Export graph as Cytoscape.js compatible JSON for interactive web visualization. Include style definitions for node types.

**Implementation**:
```python
class CytoscapeExporter:
    """Export graph as Cytoscape.js JSON."""

    format_name = "cytoscape"
    file_extension = ".cyjs"

    NODE_COLORS = {
        NodeType.MODULE: "#4A90D9",
        NodeType.CLASS: "#7B68EE",
        NodeType.FUNCTION: "#3CB371",
        NodeType.EXTERNAL: "#666666",
    }

    def export(
        self,
        mubase: MUbase,
        node_ids: list[str] | None = None,
        include_styles: bool = True,
        include_positions: bool = False,
    ) -> str:
        """Export graph as Cytoscape.js JSON."""
        ...

    def _node_element(self, node: Node) -> dict:
        """Create Cytoscape node element."""
        return {
            "data": {
                "id": node.id,
                "label": node.name,
                "type": node.type.value,
                "complexity": node.complexity,
                **node.properties,
            }
        }

    def _default_styles(self) -> list[dict]:
        """Generate default Cytoscape styles."""
        ...
```

**Status**: Complete

**Acceptance Criteria**:
- [x] Implements `Exporter` protocol
- [x] Generates valid Cytoscape.js JSON format
- [x] `elements.nodes` array with data and optional position
- [x] `elements.edges` array with source/target
- [x] Node data includes type, name, complexity, properties
- [x] Edge data includes relationship type
- [x] Default style selectors by node type
- [x] Color palette for node types
- [x] Edge curve style and arrow shapes
- [x] Unit tests validating Cytoscape JSON schema

---

### Task 9: Add CLI Export Command

**Priority**: P1 (User-facing command)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/cli.py`

**Pattern**: Follow `kernel_stats` and `kernel_query` patterns in `cli.py:965-1050`

**Description**: Add `mu kernel export` command with format selection, filtering, and output options.

**Implementation**:
```python
@kernel.command("export")
@click.argument("path", type=click.Path(exists=True, path_type=Path), default=".")
@click.option("--format", "-f", "export_format",
              type=click.Choice(["mu", "json", "mermaid", "d2", "cytoscape"]),
              default="mu", help="Export format")
@click.option("--output", "-o", type=click.Path(path_type=Path),
              help="Output file (default: stdout)")
@click.option("--nodes", type=str,
              help="Comma-separated node names to include")
@click.option("--types", type=str,
              help="Comma-separated node types (module,class,function)")
@click.option("--max-nodes", type=int, default=50,
              help="Maximum nodes for diagram formats")
@click.option("--list-formats", is_flag=True,
              help="List available export formats")
def kernel_export(path: Path, export_format: str, output: Path | None,
                  nodes: str | None, types: str | None, max_nodes: int,
                  list_formats: bool) -> None:
    """Export graph in various formats."""
    ...
```

**Status**: Complete

**Acceptance Criteria**:
- [x] `mu kernel export --format mu` exports MU text to stdout
- [x] `mu kernel export --format json --output graph.json` writes file
- [x] `--nodes AuthService,UserModel` filters by name (uses node IDs)
- [x] `--types class,function` filters by type
- [x] `--max-nodes 50` limits diagram size
- [x] `--list-formats` shows available exporters with descriptions
- [x] Output to stdout by default, file with `-o`
- [x] Proper error messages for missing .mubase
- [x] Rich console output with syntax highlighting for MU format
- [x] Integration tests for CLI command

---

### Task 10: Update Kernel Public API

**Priority**: P2 (API completeness)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/__init__.py`

**Pattern**: Follow existing re-exports in `kernel/__init__.py:31-73`

**Description**: Re-export key export classes from the kernel module for convenient access.

**Implementation**:
```python
# Add to kernel/__init__.py

# Re-export key export classes for convenience
from mu.kernel.export import (
    ExportFormat,
    ExportManager,
    ExportResult,
    Exporter,
)

__all__ = [
    # ... existing exports ...
    # Export (convenience re-exports)
    "ExportFormat",
    "ExportManager",
    "ExportResult",
    "Exporter",
]
```

**Status**: Complete

**Acceptance Criteria**:
- [x] `ExportFormat` accessible from `mu.kernel` (via `get_default_manager`)
- [x] `ExportManager` accessible from `mu.kernel`
- [x] `ExportResult` accessible from `mu.kernel`
- [x] `Exporter` protocol accessible for type hints
- [ ] Module docstring updated with export example - deferred
- [x] No circular import issues
- [x] Unit test verifying imports work

---

### Task 11: Write Comprehensive Unit Tests

**Priority**: P1 (Quality assurance)
**Files**:
- `/Users/imu/Dev/work/mu/tests/unit/test_export.py` (new)

**Pattern**: Follow test class organization in `tests/unit/test_kernel.py:14-100`

**Description**: Create comprehensive test suite for all export functionality.

**Implementation**:
```python
class TestExportFormat:
    """Tests for ExportFormat enum."""
    def test_all_formats_defined(self) -> None: ...
    def test_format_values(self) -> None: ...

class TestExportResult:
    """Tests for ExportResult dataclass."""
    def test_to_dict(self) -> None: ...

class TestExporter:
    """Tests for Exporter protocol."""
    def test_protocol_compliance(self) -> None: ...

class TestNodeFilter:
    """Tests for NodeFilter."""
    def test_filter_by_ids(self, sample_mubase) -> None: ...
    def test_filter_by_types(self, sample_mubase) -> None: ...
    def test_combined_filters(self, sample_mubase) -> None: ...

class TestMUTextExporter:
    """Tests for MU text export."""
    def test_export_module_sigil(self, sample_mubase) -> None: ...
    def test_export_class_with_inheritance(self, sample_mubase) -> None: ...
    def test_export_function_with_params(self, sample_mubase) -> None: ...
    def test_max_tokens_limit(self, sample_mubase) -> None: ...

class TestJSONExporter:
    """Tests for JSON export."""
    def test_export_valid_json(self, sample_mubase) -> None: ...
    def test_export_includes_edges(self, sample_mubase) -> None: ...
    def test_pretty_print(self, sample_mubase) -> None: ...

class TestMermaidExporter:
    """Tests for Mermaid export."""
    def test_flowchart_syntax(self, sample_mubase) -> None: ...
    def test_class_diagram_syntax(self, sample_mubase) -> None: ...
    def test_max_nodes_limit(self, sample_mubase) -> None: ...
    def test_escape_special_chars(self) -> None: ...

class TestD2Exporter:
    """Tests for D2 export."""
    def test_d2_syntax(self, sample_mubase) -> None: ...
    def test_direction_setting(self, sample_mubase) -> None: ...
    def test_includes_styles(self, sample_mubase) -> None: ...

class TestCytoscapeExporter:
    """Tests for Cytoscape export."""
    def test_cytoscape_json_format(self, sample_mubase) -> None: ...
    def test_includes_styles(self, sample_mubase) -> None: ...
    def test_node_data_complete(self, sample_mubase) -> None: ...

class TestExportManager:
    """Tests for ExportManager."""
    def test_register_exporter(self) -> None: ...
    def test_export_with_format(self, sample_mubase) -> None: ...
    def test_list_formats(self) -> None: ...
    def test_unknown_format_error(self, sample_mubase) -> None: ...
```

**Acceptance Criteria**:
- [ ] Unit tests for each exporter class
- [ ] Tests for filtering utilities
- [ ] Tests for ExportManager registration and dispatch
- [ ] Tests for edge cases (empty graph, no matches)
- [ ] Tests for error conditions (unknown format, missing mubase)
- [ ] Fixture for sample MUbase with nodes and edges
- [ ] All tests pass with `pytest tests/unit/test_export.py`

---

### Task 12: Add Export CLAUDE.md Documentation

**Priority**: P2 (Developer documentation)
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/kernel/export/CLAUDE.md` (new)

**Pattern**: Follow existing CLAUDE.md files in `src/mu/kernel/context/CLAUDE.md`

**Description**: Create comprehensive documentation for the export module.

**Acceptance Criteria**:
- [ ] Architecture overview diagram
- [ ] File structure table with purposes
- [ ] Exporter protocol documentation with example
- [ ] Per-format options documented
- [ ] CLI usage examples matching epic specification
- [ ] "Adding a new exporter" section
- [ ] Anti-patterns section
- [ ] Testing instructions

---

## Dependencies

```
Task 1 (Protocol/Base) ──┬──> Task 2 (ExportManager)
                         │
                         └──> Task 3 (Filters) ──┬──> Task 4 (MU Text)
                                                  │
                                                  ├──> Task 5 (JSON)
                                                  │
                                                  ├──> Task 6 (Mermaid)
                                                  │
                                                  ├──> Task 7 (D2)
                                                  │
                                                  └──> Task 8 (Cytoscape)

Tasks 2-8 ──> Task 9 (CLI Command)

Task 9 ──> Task 10 (Public API)

All ──> Task 11 (Tests)

Task 11 ──> Task 12 (Documentation)
```

---

## Implementation Order

**Phase 1: Foundation (Tasks 1, 2, 3)**
1. Task 1: Export module structure and base protocol
2. Task 3: Node/edge filtering utilities
3. Task 2: ExportManager coordinator

**Phase 2: Core Exporters (Tasks 4, 5)**
4. Task 4: MU Text Exporter
5. Task 5: JSON Exporter

**Phase 3: Diagram Exporters (Tasks 6, 7, 8)**
6. Task 6: Mermaid Exporter
7. Task 7: D2 Exporter
8. Task 8: Cytoscape Exporter

**Phase 4: Integration (Tasks 9, 10)**
9. Task 9: CLI Export Command
10. Task 10: Kernel Public API

**Phase 5: Quality (Tasks 11, 12)**
11. Task 11: Comprehensive Tests
12. Task 12: Documentation

---

## Edge Cases

1. **Empty graph**: Return appropriate empty output for each format
2. **No matching nodes**: Return empty result with informative message
3. **Circular dependencies**: Handle in Mermaid/D2 without infinite loops
4. **Very long names**: Truncate or escape for diagram formats
5. **Special characters**: Escape format-specific special chars (Mermaid `[]`, D2 `:`)
6. **Large graphs**: Enforce `max_nodes` limits for diagram formats
7. **Missing embeddings**: Export works without embeddings (graceful degradation)
8. **Unicode names**: Ensure proper encoding in all formats
9. **Nodes without file_path**: Handle external dependencies gracefully
10. **Mixed node types**: Ensure filtering works correctly with combinations

---

## Security Considerations

1. **No code execution**: Exporters only read data, never execute code
2. **No secret exposure**: Exclude `body_source` property which may contain secrets
3. **Path traversal**: Validate output file paths are within allowed directories
4. **JSON injection**: Properly escape JSON string values
5. **File overwrite**: Warn before overwriting existing files

---

## Performance Considerations

1. **Lazy loading**: Don't load all nodes until export starts
2. **Streaming**: For large JSON exports, consider streaming output
3. **Caching**: Cache exporter instances in ExportManager
4. **Batch queries**: Use batch DuckDB queries for node/edge retrieval
5. **Token counting**: Use tiktoken for accurate MU budget management
6. **Target performance**: Export 1000 nodes in < 1 second for all formats
