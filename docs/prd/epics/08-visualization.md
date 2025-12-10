# Epic 8: Visualization

**Priority**: P4 - Web-based interactive graph exploration
**Dependencies**: Export Formats (Epic 5), Daemon Mode (Epic 6)
**Estimated Complexity**: High
**PRD Reference**: Section 3.4

---

## Overview

Build a web-based visualization UI for exploring the code graph. Interactive Cytoscape.js rendering with filtering, path highlighting, search, and time-travel capabilities.

## Goals

1. Interactive graph exploration in browser
2. Filter by type, complexity, module
3. Path highlighting between nodes
4. Search with instant results
5. Time-travel slider for historical views

---

## User Stories

### Story 8.1: Graph Rendering
**As a** developer
**I want** to see my codebase as a graph
**So that** I can understand structure visually

**Acceptance Criteria**:
- [ ] Cytoscape.js rendering
- [ ] Nodes colored by type
- [ ] Edges styled by relationship
- [ ] Zoom and pan controls
- [ ] Responsive layout

### Story 8.2: Filtering
**As a** developer
**I want** to filter the graph
**So that** I can focus on relevant nodes

**Acceptance Criteria**:
- [ ] Filter by node type
- [ ] Filter by complexity range
- [ ] Filter by module/path
- [ ] Show/hide edge types
- [ ] Filter presets (e.g., "High complexity only")

### Story 8.3: Search
**As a** developer
**I want** instant search
**So that** I can find nodes quickly

**Acceptance Criteria**:
- [ ] Search by name
- [ ] Fuzzy matching
- [ ] Highlight results in graph
- [ ] Jump to node on select
- [ ] Search history

### Story 8.4: Path Highlighting
**As a** developer
**I want** to see paths between nodes
**So that** I can trace dependencies

**Acceptance Criteria**:
- [ ] Select source and target nodes
- [ ] Show shortest path
- [ ] Highlight path edges
- [ ] Show alternative paths
- [ ] Path details panel

### Story 8.5: Node Details
**As a** developer
**I want** to see node information
**So that** I can understand code elements

**Acceptance Criteria**:
- [ ] Click node for details panel
- [ ] Show properties, complexity, location
- [ ] Link to source file
- [ ] Show connections
- [ ] Copy MU representation

### Story 8.6: Time-Travel
**As a** developer
**I want** to see historical states
**So that** I can understand evolution

**Acceptance Criteria**:
- [ ] Timeline slider
- [ ] Snapshot selection
- [ ] Visual diff (added/removed nodes)
- [ ] Animate changes
- [ ] Commit info display

### Story 8.7: Export
**As a** developer
**I want** to export visualizations
**So that** I can share with team

**Acceptance Criteria**:
- [ ] Export as PNG
- [ ] Export as SVG
- [ ] Export current view state
- [ ] Share link with filters

---

## Technical Design

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      MU Visualizer                           │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                    Frontend (React)                    │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐      │   │
│  │  │  Toolbar   │  │   Graph    │  │  Details   │      │   │
│  │  │ (filters)  │  │(cytoscape) │  │  (panel)   │      │   │
│  │  └────────────┘  └────────────┘  └────────────┘      │   │
│  │                                                        │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐      │   │
│  │  │  Search    │  │ Timeline   │  │  Legend    │      │   │
│  │  └────────────┘  └────────────┘  └────────────┘      │   │
│  └──────────────────────────────────────────────────────┘   │
│                           │                                  │
│                           ↓                                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                 MU Daemon API                          │   │
│  │      /export/cytoscape  /query  /context  /live       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Technology Stack

- **Frontend**: React + TypeScript
- **Graph Library**: Cytoscape.js
- **UI Components**: Radix UI / Shadcn
- **State Management**: Zustand
- **Styling**: Tailwind CSS
- **Build**: Vite
- **Backend**: MU Daemon (Epic 6)

### File Structure

```
mu-viz/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tailwind.config.js
├── index.html
├── public/
│   └── favicon.ico
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── api/
│   │   ├── client.ts        # API client
│   │   └── types.ts         # API types
│   ├── components/
│   │   ├── Graph/
│   │   │   ├── Graph.tsx    # Main graph component
│   │   │   ├── styles.ts    # Cytoscape styles
│   │   │   └── layouts.ts   # Layout configurations
│   │   ├── Toolbar/
│   │   │   ├── Toolbar.tsx
│   │   │   ├── FilterPanel.tsx
│   │   │   └── SearchBox.tsx
│   │   ├── Details/
│   │   │   ├── DetailsPanel.tsx
│   │   │   ├── NodeDetails.tsx
│   │   │   └── PathDetails.tsx
│   │   ├── Timeline/
│   │   │   ├── Timeline.tsx
│   │   │   └── CommitInfo.tsx
│   │   └── common/
│   │       ├── Button.tsx
│   │       └── Panel.tsx
│   ├── hooks/
│   │   ├── useGraph.ts
│   │   ├── useFilters.ts
│   │   ├── useSearch.ts
│   │   └── useWebSocket.ts
│   ├── store/
│   │   ├── graphStore.ts
│   │   └── uiStore.ts
│   └── utils/
│       ├── colors.ts
│       └── layout.ts
```

### Core Components

```typescript
// src/api/client.ts
import { Node, Edge, QueryResult } from './types';

class MUClient {
  constructor(private baseUrl: string = 'http://localhost:8765') {}

  async getStatus(): Promise<StatusResponse> {
    const res = await fetch(`${this.baseUrl}/status`);
    return res.json();
  }

  async getGraph(options?: GraphOptions): Promise<CytoscapeData> {
    const params = new URLSearchParams();
    if (options?.types) params.set('types', options.types.join(','));
    if (options?.maxNodes) params.set('max_nodes', String(options.maxNodes));

    const res = await fetch(`${this.baseUrl}/export?format=cytoscape&${params}`);
    return res.json();
  }

  async getNode(id: string): Promise<Node> {
    const res = await fetch(`${this.baseUrl}/nodes/${id}`);
    return res.json();
  }

  async query(muql: string): Promise<QueryResult> {
    const res = await fetch(`${this.baseUrl}/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ muql }),
    });
    return res.json();
  }

  async findPath(from: string, to: string): Promise<string[]> {
    const result = await this.query(`PATH FROM ${from} TO ${to}`);
    return result.rows[0]?.path || [];
  }

  connectWebSocket(onMessage: (event: GraphEvent) => void): WebSocket {
    const ws = new WebSocket(`ws://localhost:8765/live`);
    ws.onmessage = (e) => onMessage(JSON.parse(e.data));
    return ws;
  }
}

export const muClient = new MUClient();
```

```tsx
// src/components/Graph/Graph.tsx
import { useEffect, useRef, useCallback } from 'react';
import cytoscape, { Core, NodeSingular } from 'cytoscape';
import { useGraphStore } from '../../store/graphStore';
import { cytoscapeStyles } from './styles';
import { getLayout } from './layouts';

export function Graph() {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  const {
    elements,
    selectedNode,
    highlightedPath,
    filters,
    setSelectedNode,
  } = useGraphStore();

  // Initialize Cytoscape
  useEffect(() => {
    if (!containerRef.current) return;

    const cy = cytoscape({
      container: containerRef.current,
      elements: [],
      style: cytoscapeStyles,
      layout: { name: 'preset' },
      wheelSensitivity: 0.3,
    });

    // Event handlers
    cy.on('tap', 'node', (evt) => {
      const node = evt.target as NodeSingular;
      setSelectedNode(node.id());
    });

    cy.on('tap', (evt) => {
      if (evt.target === cy) {
        setSelectedNode(null);
      }
    });

    cyRef.current = cy;

    return () => {
      cy.destroy();
    };
  }, []);

  // Update elements when data changes
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !elements) return;

    cy.elements().remove();
    cy.add(elements);

    // Apply layout
    const layout = getLayout(filters.layout || 'cose');
    cy.layout(layout).run();
  }, [elements]);

  // Apply filters
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    cy.nodes().forEach((node) => {
      const data = node.data();
      let visible = true;

      // Type filter
      if (filters.types && !filters.types.includes(data.type)) {
        visible = false;
      }

      // Complexity filter
      if (filters.minComplexity && data.complexity < filters.minComplexity) {
        visible = false;
      }

      // Path filter
      if (filters.pathPattern && !data.file_path?.match(filters.pathPattern)) {
        visible = false;
      }

      node.style('display', visible ? 'element' : 'none');
    });
  }, [filters]);

  // Highlight path
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    // Reset highlights
    cy.elements().removeClass('highlighted');

    if (highlightedPath && highlightedPath.length > 0) {
      for (let i = 0; i < highlightedPath.length; i++) {
        const nodeId = highlightedPath[i];
        cy.getElementById(nodeId).addClass('highlighted');

        if (i < highlightedPath.length - 1) {
          const nextId = highlightedPath[i + 1];
          cy.edges(`[source = "${nodeId}"][target = "${nextId}"]`)
            .addClass('highlighted');
        }
      }
    }
  }, [highlightedPath]);

  // Center on selected node
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !selectedNode) return;

    const node = cy.getElementById(selectedNode);
    if (node.length > 0) {
      cy.animate({
        center: { eles: node },
        zoom: 1.5,
        duration: 300,
      });
    }
  }, [selectedNode]);

  return (
    <div
      ref={containerRef}
      className="w-full h-full bg-gray-900"
    />
  );
}
```

```tsx
// src/components/Toolbar/FilterPanel.tsx
import { useGraphStore } from '../../store/graphStore';
import { NodeType } from '../../api/types';

const NODE_TYPES: NodeType[] = ['MODULE', 'CLASS', 'FUNCTION', 'ENTITY', 'EXTERNAL'];

export function FilterPanel() {
  const { filters, setFilters } = useGraphStore();

  const toggleType = (type: NodeType) => {
    const current = filters.types || NODE_TYPES;
    const updated = current.includes(type)
      ? current.filter((t) => t !== type)
      : [...current, type];
    setFilters({ ...filters, types: updated });
  };

  return (
    <div className="p-4 bg-gray-800 rounded-lg">
      <h3 className="text-sm font-medium text-gray-300 mb-3">Node Types</h3>

      <div className="flex flex-wrap gap-2">
        {NODE_TYPES.map((type) => (
          <button
            key={type}
            onClick={() => toggleType(type)}
            className={`px-3 py-1 rounded text-sm ${
              filters.types?.includes(type) ?? true
                ? 'bg-blue-600 text-white'
                : 'bg-gray-700 text-gray-400'
            }`}
          >
            {type}
          </button>
        ))}
      </div>

      <h3 className="text-sm font-medium text-gray-300 mt-4 mb-3">Complexity</h3>

      <input
        type="range"
        min={0}
        max={1000}
        value={filters.minComplexity || 0}
        onChange={(e) =>
          setFilters({ ...filters, minComplexity: Number(e.target.value) })
        }
        className="w-full"
      />
      <span className="text-gray-400 text-sm">
        Min: {filters.minComplexity || 0}
      </span>

      <h3 className="text-sm font-medium text-gray-300 mt-4 mb-3">Path Filter</h3>

      <input
        type="text"
        placeholder="e.g., src/services/*"
        value={filters.pathPattern || ''}
        onChange={(e) => setFilters({ ...filters, pathPattern: e.target.value })}
        className="w-full px-3 py-2 bg-gray-700 rounded text-white text-sm"
      />

      <h3 className="text-sm font-medium text-gray-300 mt-4 mb-3">Layout</h3>

      <select
        value={filters.layout || 'cose'}
        onChange={(e) => setFilters({ ...filters, layout: e.target.value })}
        className="w-full px-3 py-2 bg-gray-700 rounded text-white text-sm"
      >
        <option value="cose">Force-directed (CoSE)</option>
        <option value="dagre">Hierarchical (Dagre)</option>
        <option value="circle">Circle</option>
        <option value="grid">Grid</option>
      </select>
    </div>
  );
}
```

```tsx
// src/components/Details/NodeDetails.tsx
import { useEffect, useState } from 'react';
import { muClient } from '../../api/client';
import { Node } from '../../api/types';
import { useGraphStore } from '../../store/graphStore';

export function NodeDetails() {
  const { selectedNode, setHighlightedPath } = useGraphStore();
  const [node, setNode] = useState<Node | null>(null);
  const [pathTarget, setPathTarget] = useState<string>('');

  useEffect(() => {
    if (selectedNode) {
      muClient.getNode(selectedNode).then(setNode);
    } else {
      setNode(null);
    }
  }, [selectedNode]);

  const handleFindPath = async () => {
    if (selectedNode && pathTarget) {
      const path = await muClient.findPath(selectedNode, pathTarget);
      setHighlightedPath(path);
    }
  };

  if (!node) {
    return (
      <div className="p-4 text-gray-400">
        Select a node to view details
      </div>
    );
  }

  return (
    <div className="p-4 bg-gray-800 rounded-lg">
      <h2 className="text-lg font-bold text-white mb-2">{node.name}</h2>

      <div className="space-y-2 text-sm">
        <div className="flex justify-between">
          <span className="text-gray-400">Type</span>
          <span className={`px-2 py-0.5 rounded ${getTypeColor(node.type)}`}>
            {node.type}
          </span>
        </div>

        <div className="flex justify-between">
          <span className="text-gray-400">Complexity</span>
          <span className="text-white">{node.complexity || 'N/A'}</span>
        </div>

        <div className="flex justify-between">
          <span className="text-gray-400">File</span>
          <span className="text-blue-400 truncate max-w-[200px]">
            {node.file_path}
          </span>
        </div>

        <div className="flex justify-between">
          <span className="text-gray-400">Lines</span>
          <span className="text-white">
            {node.line_start}-{node.line_end}
          </span>
        </div>
      </div>

      {/* Properties */}
      {node.properties && Object.keys(node.properties).length > 0 && (
        <div className="mt-4">
          <h3 className="text-sm font-medium text-gray-300 mb-2">Properties</h3>
          <pre className="text-xs bg-gray-900 p-2 rounded overflow-auto max-h-[200px]">
            {JSON.stringify(node.properties, null, 2)}
          </pre>
        </div>
      )}

      {/* Path finder */}
      <div className="mt-4">
        <h3 className="text-sm font-medium text-gray-300 mb-2">Find Path To</h3>
        <div className="flex gap-2">
          <input
            type="text"
            placeholder="Target node name"
            value={pathTarget}
            onChange={(e) => setPathTarget(e.target.value)}
            className="flex-1 px-2 py-1 bg-gray-700 rounded text-white text-sm"
          />
          <button
            onClick={handleFindPath}
            className="px-3 py-1 bg-blue-600 rounded text-white text-sm"
          >
            Find
          </button>
        </div>
      </div>
    </div>
  );
}

function getTypeColor(type: string): string {
  const colors: Record<string, string> = {
    MODULE: 'bg-blue-600',
    CLASS: 'bg-purple-600',
    FUNCTION: 'bg-green-600',
    ENTITY: 'bg-yellow-600',
    EXTERNAL: 'bg-gray-600',
  };
  return colors[type] || 'bg-gray-600';
}
```

```tsx
// src/components/Timeline/Timeline.tsx
import { useEffect, useState } from 'react';
import { muClient } from '../../api/client';
import { Snapshot } from '../../api/types';
import { useGraphStore } from '../../store/graphStore';

export function Timeline() {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [selectedIndex, setSelectedIndex] = useState<number>(-1);
  const { loadGraphAtSnapshot } = useGraphStore();

  useEffect(() => {
    // Load snapshots
    muClient.query('SELECT * FROM snapshots ORDER BY commit_date DESC')
      .then((result) => {
        setSnapshots(result.rows as Snapshot[]);
        setSelectedIndex(0); // Latest
      });
  }, []);

  const handleSliderChange = (index: number) => {
    setSelectedIndex(index);
    const snapshot = snapshots[index];
    if (snapshot) {
      loadGraphAtSnapshot(snapshot.commit_hash);
    }
  };

  if (snapshots.length === 0) {
    return <div className="text-gray-400 text-sm">No history available</div>;
  }

  const current = snapshots[selectedIndex];

  return (
    <div className="p-4 bg-gray-800 rounded-lg">
      <h3 className="text-sm font-medium text-gray-300 mb-3">Timeline</h3>

      <input
        type="range"
        min={0}
        max={snapshots.length - 1}
        value={selectedIndex}
        onChange={(e) => handleSliderChange(Number(e.target.value))}
        className="w-full mb-3"
      />

      {current && (
        <div className="text-sm space-y-1">
          <div className="text-white font-mono">{current.commit_hash.slice(0, 8)}</div>
          <div className="text-gray-400">{current.commit_message}</div>
          <div className="text-gray-500 text-xs">
            {current.commit_author} · {formatDate(current.commit_date)}
          </div>
          <div className="text-xs mt-2">
            <span className="text-green-400">+{current.nodes_added}</span>
            {' · '}
            <span className="text-red-400">-{current.nodes_removed}</span>
            {' · '}
            <span className="text-yellow-400">~{current.nodes_modified}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function formatDate(date: string): string {
  return new Date(date).toLocaleDateString();
}
```

### Cytoscape Styles

```typescript
// src/components/Graph/styles.ts
import { Stylesheet } from 'cytoscape';

export const cytoscapeStyles: Stylesheet[] = [
  // Base node style
  {
    selector: 'node',
    style: {
      'label': 'data(label)',
      'text-valign': 'center',
      'text-halign': 'center',
      'font-size': '10px',
      'color': '#fff',
      'text-outline-color': '#000',
      'text-outline-width': 1,
      'width': 40,
      'height': 40,
    },
  },

  // Node types
  {
    selector: 'node[type="MODULE"]',
    style: {
      'background-color': '#4A90D9',
      'shape': 'round-rectangle',
      'width': 60,
      'height': 30,
    },
  },
  {
    selector: 'node[type="CLASS"]',
    style: {
      'background-color': '#7B68EE',
      'shape': 'rectangle',
    },
  },
  {
    selector: 'node[type="FUNCTION"]',
    style: {
      'background-color': '#3CB371',
      'shape': 'ellipse',
    },
  },
  {
    selector: 'node[type="ENTITY"]',
    style: {
      'background-color': '#FFB347',
      'shape': 'diamond',
    },
  },
  {
    selector: 'node[type="EXTERNAL"]',
    style: {
      'background-color': '#808080',
      'shape': 'hexagon',
    },
  },

  // Complexity-based sizing
  {
    selector: 'node[complexity > 100]',
    style: {
      'width': 50,
      'height': 50,
    },
  },
  {
    selector: 'node[complexity > 500]',
    style: {
      'width': 60,
      'height': 60,
      'border-width': 3,
      'border-color': '#FF6B6B',
    },
  },

  // Base edge style
  {
    selector: 'edge',
    style: {
      'width': 1,
      'line-color': '#666',
      'target-arrow-color': '#666',
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      'arrow-scale': 0.8,
    },
  },

  // Edge types
  {
    selector: 'edge[type="CONTAINS"]',
    style: {
      'line-style': 'dashed',
      'line-color': '#888',
    },
  },
  {
    selector: 'edge[type="IMPORTS"]',
    style: {
      'line-color': '#4A90D9',
      'target-arrow-color': '#4A90D9',
    },
  },
  {
    selector: 'edge[type="INHERITS"]',
    style: {
      'line-color': '#7B68EE',
      'target-arrow-color': '#7B68EE',
      'width': 2,
      'target-arrow-shape': 'triangle-tee',
    },
  },
  {
    selector: 'edge[type="CALLS"]',
    style: {
      'line-color': '#3CB371',
      'target-arrow-color': '#3CB371',
    },
  },

  // Selected state
  {
    selector: 'node:selected',
    style: {
      'border-width': 3,
      'border-color': '#FFD700',
    },
  },

  // Highlighted path
  {
    selector: '.highlighted',
    style: {
      'background-color': '#FFD700',
      'line-color': '#FFD700',
      'target-arrow-color': '#FFD700',
      'width': 3,
      'z-index': 999,
    },
  },

  // Dimmed (when path is highlighted)
  {
    selector: '.dimmed',
    style: {
      'opacity': 0.3,
    },
  },
];
```

---

## Implementation Plan

### Phase 1: Project Setup (Day 1)
1. Initialize Vite + React + TypeScript project
2. Configure Tailwind CSS
3. Set up project structure
4. Add Cytoscape.js dependency

### Phase 2: API Client (Day 1)
1. Create API client for MU Daemon
2. Define TypeScript types
3. Add WebSocket connection
4. Test with daemon

### Phase 3: Basic Graph (Day 2)
1. Implement Graph component
2. Load and render nodes/edges
3. Add zoom/pan controls
4. Style by node type

### Phase 4: Filtering (Day 2-3)
1. Create FilterPanel component
2. Implement type filtering
3. Implement complexity filtering
4. Implement path filtering
5. Add layout options

### Phase 5: Search (Day 3)
1. Create SearchBox component
2. Implement fuzzy search
3. Highlight results in graph
4. Add keyboard shortcuts

### Phase 6: Node Details (Day 3-4)
1. Create DetailsPanel component
2. Show node properties
3. Link to source file
4. Add MU representation copy

### Phase 7: Path Highlighting (Day 4)
1. Implement path finding UI
2. Highlight path in graph
3. Show path details
4. Animate path

### Phase 8: Timeline (Day 4-5)
1. Create Timeline component
2. Load snapshots
3. Implement time-travel
4. Show visual diff

### Phase 9: Export (Day 5)
1. Add PNG export
2. Add SVG export
3. Add view state sharing
4. Test all exports

### Phase 10: Polish (Day 5)
1. Add loading states
2. Add error handling
3. Improve performance
4. Add keyboard shortcuts

---

## CLI Integration

```bash
# Start visualization server (uses daemon)
$ mu viz
Starting MU Visualizer...
Open http://localhost:3000 in your browser

# Or with custom port
$ mu viz --port 3001

# Or open in browser automatically
$ mu viz --open
```

---

## Testing Strategy

### Unit Tests
- Component rendering tests with React Testing Library
- API client tests with MSW (Mock Service Worker)
- Store tests with Zustand

### Integration Tests
- Full graph rendering
- Filter interactions
- Search functionality

### E2E Tests
- Playwright tests for critical paths
- Visual regression tests

---

## Success Criteria

- [ ] Graph renders 1000+ nodes smoothly
- [ ] Filters update in < 100ms
- [ ] Search returns results in < 50ms
- [ ] Path highlighting works correctly
- [ ] Timeline loads historical views
- [ ] Export produces valid images

---

## Future Enhancements

1. **3D visualization**: Three.js-based 3D graph
2. **Collaborative mode**: Multiple users viewing same graph
3. **Annotation**: Add notes to nodes
4. **Custom layouts**: Save and share layouts
5. **Embedding**: Embed in documentation
