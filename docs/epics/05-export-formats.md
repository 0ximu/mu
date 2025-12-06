# Epic 5: Export Formats

**Priority**: P2 - Multiple output formats for different use cases
**Dependencies**: Kernel (complete)
**Estimated Complexity**: Medium
**PRD Reference**: Export Layer

---

## Overview

Extend MUbase to export the graph in multiple formats: MU text (optimized for LLMs), JSON (structured data), Mermaid/D2 (diagrams), and Cytoscape (interactive visualization).

## Goals

1. Support multiple export formats from single graph
2. Enable subgraph export (filter by nodes/types)
3. Provide format-specific optimizations
4. Integrate with CLI and Python API

---

## User Stories

### Story 5.1: MU Text Export
**As a** developer
**I want** MU text export from graph
**So that** I can feed it to LLMs efficiently

**Acceptance Criteria**:
- [ ] Export full graph or subgraph
- [ ] Preserve sigil syntax (!, $, #, @, etc.)
- [ ] Token-optimized output
- [ ] Consistent with existing `mu compress` output

### Story 5.2: JSON Export
**As a** developer
**I want** JSON export
**So that** I can integrate with other tools

**Acceptance Criteria**:
- [ ] Nodes and edges as structured JSON
- [ ] Include all properties
- [ ] Support filtering
- [ ] Schema-compliant output

### Story 5.3: Mermaid Export
**As a** developer
**I want** Mermaid diagrams
**So that** I can visualize in markdown

**Acceptance Criteria**:
- [ ] Generate valid Mermaid flowchart/classDiagram
- [ ] Support subgraph selection
- [ ] Handle large graphs (simplify)
- [ ] Customizable styling

### Story 5.4: D2 Export
**As a** developer
**I want** D2 diagram export
**So that** I can create professional diagrams

**Acceptance Criteria**:
- [ ] Generate valid D2 syntax
- [ ] Support layout directions
- [ ] Style by node type
- [ ] Include edge labels

### Story 5.5: Cytoscape Export
**As a** developer
**I want** Cytoscape-compatible JSON
**So that** I can use interactive visualization

**Acceptance Criteria**:
- [ ] Export cytoscape.js compatible format
- [ ] Include position hints
- [ ] Style data for node types
- [ ] Support large graphs

### Story 5.6: CLI Integration
**As a** developer
**I want** export from command line
**So that** I can generate outputs easily

**Acceptance Criteria**:
- [ ] `mu kernel export --format <fmt>`
- [ ] `--nodes` filter option
- [ ] `--types` filter option
- [ ] Output to file or stdout

---

## Technical Design

### File Structure

```
src/mu/kernel/
├── export/
│   ├── __init__.py          # Public API
│   ├── base.py              # Exporter protocol
│   ├── mu_text.py           # MU format exporter
│   ├── json_export.py       # JSON exporter
│   ├── mermaid.py           # Mermaid exporter
│   ├── d2.py                # D2 exporter
│   └── cytoscape.py         # Cytoscape exporter
```

### Exporter Protocol

```python
from typing import Protocol

class Exporter(Protocol):
    """Protocol for graph exporters."""

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


class ExportManager:
    """Manage all export formats."""

    formats: dict[str, type[Exporter]] = {
        "mu": MUTextExporter,
        "json": JSONExporter,
        "mermaid": MermaidExporter,
        "d2": D2Exporter,
        "cytoscape": CytoscapeExporter,
    }

    def export(
        self,
        mubase: MUbase,
        format: str,
        node_ids: list[str] | None = None,
        **options
    ) -> str:
        """Export graph in specified format."""
        exporter_class = self.formats.get(format)
        if not exporter_class:
            raise ValueError(f"Unknown format: {format}")

        exporter = exporter_class()
        return exporter.export(mubase, node_ids, **options)
```

### MU Text Exporter

```python
class MUTextExporter:
    """Export graph as MU text format."""

    format_name = "mu"
    file_extension = ".mu"

    # Sigil mappings
    SIGILS = {
        NodeType.MODULE: "!",
        NodeType.CLASS: "$",
        NodeType.FUNCTION: "#",
        NodeType.ENTITY: "$",
        NodeType.EXTERNAL: "@ext",
    }

    def export(
        self,
        mubase: MUbase,
        node_ids: list[str] | None = None,
        max_tokens: int | None = None,
        include_complexity: bool = False,
    ) -> str:
        nodes = self._get_nodes(mubase, node_ids)

        if max_tokens:
            nodes = self._fit_to_tokens(nodes, max_tokens)

        # Group by module
        by_module = self._group_by_module(nodes)

        lines = []
        for module_path, module_nodes in by_module.items():
            lines.extend(self._export_module(module_path, module_nodes, mubase))
            lines.append("")  # Blank line between modules

        return "\n".join(lines)

    def _export_module(
        self,
        path: str,
        nodes: list[Node],
        mubase: MUbase
    ) -> list[str]:
        """Export a single module."""
        lines = [f"! {path}"]

        # Separate by type
        classes = [n for n in nodes if n.type == NodeType.CLASS]
        functions = [n for n in nodes if n.type == NodeType.FUNCTION and not n.properties.get("parent_class")]

        # Export classes
        for cls in classes:
            lines.extend(self._export_class(cls, nodes, mubase))

        # Export standalone functions
        for func in functions:
            lines.append(self._export_function(func))

        # Export imports
        imports = mubase.get_imports(path)
        if imports:
            lines.append(f"  @ {', '.join(imports)}")

        return lines

    def _export_class(
        self,
        cls: Node,
        all_nodes: list[Node],
        mubase: MUbase
    ) -> list[str]:
        """Export a class with its methods."""
        lines = []

        # Class header with inheritance
        bases = cls.properties.get("bases", [])
        if bases:
            lines.append(f"  $ {cls.name} < {', '.join(bases)}")
        else:
            lines.append(f"  $ {cls.name}")

        # Methods
        methods = [n for n in all_nodes
                   if n.type == NodeType.FUNCTION
                   and n.properties.get("parent_class") == cls.id]

        for method in methods:
            lines.append("    " + self._export_function(method))

        return lines

    def _export_function(self, func: Node) -> str:
        """Export a function/method."""
        parts = [f"# {func.name}"]

        # Parameters
        params = func.properties.get("parameters", [])
        if params:
            param_str = ", ".join(
                f"{p['name']}: {p.get('type', '?')}"
                for p in params
            )
            parts[0] += f"({param_str})"

        # Return type
        ret = func.properties.get("return_type")
        if ret:
            parts[0] += f" -> {ret}"

        # Annotations
        decorators = func.properties.get("decorators", [])
        if decorators:
            parts.append(f":: {', '.join(decorators)}")

        # Mutations
        mutations = func.properties.get("mutations", [])
        if mutations:
            parts.append(f"=> {', '.join(mutations)}")

        return " ".join(parts)
```

### JSON Exporter

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
    ) -> str:
        nodes = self._get_nodes(mubase, node_ids)
        edges = self._get_edges(mubase, node_ids)

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

        if pretty:
            return json.dumps(data, indent=2)
        return json.dumps(data)
```

### Mermaid Exporter

```python
class MermaidExporter:
    """Export graph as Mermaid diagram."""

    format_name = "mermaid"
    file_extension = ".mmd"

    # Node shapes by type
    SHAPES = {
        NodeType.MODULE: "([{name}])",      # Stadium shape
        NodeType.CLASS: "[{name}]",          # Rectangle
        NodeType.FUNCTION: "({name})",       # Rounded
        NodeType.ENTITY: "[({name})]",       # Subroutine
        NodeType.EXTERNAL: ">>{name}]",      # Asymmetric
    }

    def export(
        self,
        mubase: MUbase,
        node_ids: list[str] | None = None,
        diagram_type: str = "flowchart",
        direction: str = "TB",
        max_nodes: int = 50,
    ) -> str:
        nodes = self._get_nodes(mubase, node_ids)[:max_nodes]
        edges = self._get_edges_for_nodes(mubase, nodes)

        if diagram_type == "flowchart":
            return self._export_flowchart(nodes, edges, direction)
        elif diagram_type == "classDiagram":
            return self._export_class_diagram(nodes, edges)
        else:
            raise ValueError(f"Unknown diagram type: {diagram_type}")

    def _export_flowchart(
        self,
        nodes: list[Node],
        edges: list[Edge],
        direction: str
    ) -> str:
        lines = [f"flowchart {direction}"]

        # Node definitions
        for node in nodes:
            shape = self.SHAPES.get(node.type, "[{name}]")
            node_def = shape.format(name=self._escape(node.name))
            lines.append(f"    {node.id}{node_def}")

        lines.append("")

        # Edge definitions
        for edge in edges:
            arrow = self._edge_arrow(edge.type)
            label = edge.type.value if edge.type != EdgeType.CONTAINS else ""
            if label:
                lines.append(f"    {edge.source_id} {arrow}|{label}| {edge.target_id}")
            else:
                lines.append(f"    {edge.source_id} {arrow} {edge.target_id}")

        return "\n".join(lines)

    def _edge_arrow(self, edge_type: EdgeType) -> str:
        arrows = {
            EdgeType.CONTAINS: "-->",
            EdgeType.IMPORTS: "-.->",
            EdgeType.INHERITS: "===>",
            EdgeType.CALLS: "-->",
            EdgeType.USES: "-.->",
        }
        return arrows.get(edge_type, "-->")

    def _escape(self, text: str) -> str:
        """Escape special Mermaid characters."""
        return text.replace('"', "'").replace("[", "(").replace("]", ")")
```

### D2 Exporter

```python
class D2Exporter:
    """Export graph as D2 diagram."""

    format_name = "d2"
    file_extension = ".d2"

    # Node styles by type
    STYLES = {
        NodeType.MODULE: "shape: package",
        NodeType.CLASS: "shape: class",
        NodeType.FUNCTION: "shape: rectangle; style.border-radius: 8",
        NodeType.ENTITY: "shape: stored_data",
        NodeType.EXTERNAL: "shape: cloud",
    }

    def export(
        self,
        mubase: MUbase,
        node_ids: list[str] | None = None,
        direction: str = "right",
        include_styles: bool = True,
    ) -> str:
        nodes = self._get_nodes(mubase, node_ids)
        edges = self._get_edges_for_nodes(mubase, nodes)

        lines = [f"direction: {direction}", ""]

        # Node definitions with styles
        for node in nodes:
            label = self._node_label(node)
            lines.append(f"{node.id}: {label}")
            if include_styles:
                style = self.STYLES.get(node.type, "")
                if style:
                    lines.append(f"{node.id}.{style}")

        lines.append("")

        # Edge definitions
        for edge in edges:
            style = self._edge_style(edge.type)
            lines.append(f"{edge.source_id} -> {edge.target_id}: {edge.type.value}{style}")

        return "\n".join(lines)

    def _node_label(self, node: Node) -> str:
        """Create node label with icon."""
        icons = {
            NodeType.MODULE: "M",
            NodeType.CLASS: "C",
            NodeType.FUNCTION: "f",
        }
        icon = icons.get(node.type, "")
        return f"{icon} {node.name}" if icon else node.name

    def _edge_style(self, edge_type: EdgeType) -> str:
        styles = {
            EdgeType.INHERITS: " { style.stroke-dash: 5 }",
            EdgeType.IMPORTS: " { style.opacity: 0.5 }",
        }
        return styles.get(edge_type, "")
```

### Cytoscape Exporter

```python
class CytoscapeExporter:
    """Export graph as Cytoscape.js compatible JSON."""

    format_name = "cytoscape"
    file_extension = ".cyjs"

    def export(
        self,
        mubase: MUbase,
        node_ids: list[str] | None = None,
        include_styles: bool = True,
    ) -> str:
        nodes = self._get_nodes(mubase, node_ids)
        edges = self._get_edges_for_nodes(mubase, nodes)

        elements = {
            "nodes": [self._node_element(n) for n in nodes],
            "edges": [self._edge_element(e) for e in edges],
        }

        data = {"elements": elements}

        if include_styles:
            data["style"] = self._default_styles()

        return json.dumps(data, indent=2)

    def _node_element(self, node: Node) -> dict:
        return {
            "data": {
                "id": node.id,
                "label": node.name,
                "type": node.type.value,
                "complexity": node.complexity or 0,
                **node.properties,
            }
        }

    def _edge_element(self, edge: Edge) -> dict:
        return {
            "data": {
                "id": edge.id,
                "source": edge.source_id,
                "target": edge.target_id,
                "type": edge.type.value,
            }
        }

    def _default_styles(self) -> list[dict]:
        return [
            {
                "selector": "node",
                "style": {
                    "label": "data(label)",
                    "background-color": "#666",
                }
            },
            {
                "selector": "node[type='MODULE']",
                "style": {"background-color": "#4A90D9"}
            },
            {
                "selector": "node[type='CLASS']",
                "style": {"background-color": "#7B68EE"}
            },
            {
                "selector": "node[type='FUNCTION']",
                "style": {"background-color": "#3CB371"}
            },
            {
                "selector": "edge",
                "style": {
                    "curve-style": "bezier",
                    "target-arrow-shape": "triangle",
                }
            },
        ]
```

---

## Implementation Plan

### Phase 1: Base Infrastructure (Day 1)
1. Create `export/` module structure
2. Define `Exporter` protocol
3. Implement `ExportManager`
4. Add node/edge filtering utilities

### Phase 2: MU Text Exporter (Day 1)
1. Implement `MUTextExporter`
2. Handle all sigil mappings
3. Group by module
4. Test against existing `mu compress` output

### Phase 3: JSON Exporter (Day 1-2)
1. Implement `JSONExporter`
2. Define JSON schema
3. Add pretty-print option
4. Test serialization roundtrip

### Phase 4: Mermaid Exporter (Day 2)
1. Implement `MermaidExporter`
2. Support flowchart and classDiagram
3. Handle large graph simplification
4. Test in Mermaid Live Editor

### Phase 5: D2 Exporter (Day 2-3)
1. Implement `D2Exporter`
2. Add styling options
3. Support nested containers
4. Test with D2 playground

### Phase 6: Cytoscape Exporter (Day 3)
1. Implement `CytoscapeExporter`
2. Add default styles
3. Include layout hints
4. Test with Cytoscape.js

### Phase 7: CLI Integration (Day 3-4)
1. Add `mu kernel export` command
2. Add format, nodes, types options
3. Add output file option
4. Add max-nodes limit for diagrams

### Phase 8: Testing (Day 4)
1. Unit tests for each exporter
2. Integration tests with sample graph
3. Output validation tests
4. Performance tests for large graphs

---

## CLI Interface

```bash
# Export full graph as MU
$ mu kernel export --format mu > system.mu

# Export as JSON
$ mu kernel export --format json --output graph.json

# Export specific nodes as Mermaid
$ mu kernel export --format mermaid --nodes AuthService,UserRepository

# Export classes only as D2
$ mu kernel export --format d2 --types CLASS --output classes.d2

# Export for Cytoscape visualization
$ mu kernel export --format cytoscape --max-nodes 100 > graph.cyjs

# List available formats
$ mu kernel export --list-formats
Available formats:
  mu        - MU text format (LLM optimized)
  json      - Structured JSON
  mermaid   - Mermaid diagram
  d2        - D2 diagram language
  cytoscape - Cytoscape.js JSON
```

---

## Testing Strategy

### Unit Tests
```python
def test_mu_export_includes_sigils(sample_graph):
    exporter = MUTextExporter()
    output = exporter.export(sample_graph)
    assert "!" in output  # Module sigil
    assert "$" in output  # Class sigil
    assert "#" in output  # Function sigil

def test_json_export_valid(sample_graph):
    exporter = JSONExporter()
    output = exporter.export(sample_graph)
    data = json.loads(output)
    assert "nodes" in data
    assert "edges" in data

def test_mermaid_export_valid_syntax(sample_graph):
    exporter = MermaidExporter()
    output = exporter.export(sample_graph)
    assert output.startswith("flowchart")
    # Could validate with mermaid-cli
```

---

## Success Criteria

- [ ] All exporters produce valid output
- [ ] MU export matches existing compress output
- [ ] Mermaid renders correctly in GitHub
- [ ] D2 renders correctly in playground
- [ ] Cytoscape loads without errors
- [ ] Export time < 1 second for 1000 nodes

---

## Future Enhancements

1. **GraphML export**: For other graph tools
2. **SVG/PNG export**: Direct image generation
3. **PlantUML export**: Alternative diagram format
4. **Custom templates**: User-defined export templates
5. **Streaming export**: For very large graphs
