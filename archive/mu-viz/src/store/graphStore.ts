import { create } from 'zustand';
import type { CytoscapeData, NodeType, GraphEvent, Snapshot } from '../api/types';
import { muClient } from '../api/client';

export interface Filters {
  types: NodeType[];
  minComplexity: number;
  pathPattern: string;
  layout: string;
  showEdgeLabels: boolean;
}

interface GraphState {
  // Data
  elements: CytoscapeData | null;
  loading: boolean;
  error: string | null;

  // Selection
  selectedNode: string | null;
  highlightedPath: string[];

  // Filters
  filters: Filters;

  // Timeline
  snapshots: Snapshot[];
  currentSnapshot: string | null;

  // WebSocket
  wsConnected: boolean;

  // Actions
  loadGraph: () => Promise<void>;
  loadGraphAtSnapshot: (commitHash: string) => Promise<void>;
  loadSnapshots: () => Promise<void>;
  setSelectedNode: (nodeId: string | null) => void;
  setHighlightedPath: (path: string[]) => void;
  setFilters: (filters: Partial<Filters>) => void;
  resetFilters: () => void;
  handleGraphEvent: (event: GraphEvent) => void;
  setWsConnected: (connected: boolean) => void;
}

const DEFAULT_FILTERS: Filters = {
  types: ['module', 'class', 'function', 'external'],
  minComplexity: 0,
  pathPattern: '',
  layout: 'cose',
  showEdgeLabels: false,
};

export const useGraphStore = create<GraphState>((set, get) => ({
  // Initial state
  elements: null,
  loading: false,
  error: null,
  selectedNode: null,
  highlightedPath: [],
  filters: DEFAULT_FILTERS,
  snapshots: [],
  currentSnapshot: null,
  wsConnected: false,

  // Actions
  loadGraph: async () => {
    set({ loading: true, error: null });
    try {
      const { filters } = get();
      const data = await muClient.getGraph({
        types: filters.types,
        minComplexity: filters.minComplexity || undefined,
        pathPattern: filters.pathPattern || undefined,
      });
      set({ elements: data, loading: false, currentSnapshot: null });
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to load graph',
        loading: false,
      });
    }
  },

  loadGraphAtSnapshot: async (commitHash: string) => {
    set({ loading: true, error: null });
    try {
      const data = await muClient.getGraphAtSnapshot(commitHash);
      set({ elements: data, loading: false, currentSnapshot: commitHash });
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to load snapshot',
        loading: false,
      });
    }
  },

  loadSnapshots: async () => {
    try {
      const result = await muClient.getSnapshots();
      set({ snapshots: result.rows as unknown as Snapshot[] });
    } catch (err) {
      console.error('Failed to load snapshots:', err);
    }
  },

  setSelectedNode: (nodeId) => {
    set({ selectedNode: nodeId });
  },

  setHighlightedPath: (path) => {
    set({ highlightedPath: path });
  },

  setFilters: (newFilters) => {
    set((state) => ({
      filters: { ...state.filters, ...newFilters },
    }));
  },

  resetFilters: () => {
    set({ filters: DEFAULT_FILTERS });
  },

  handleGraphEvent: (event) => {
    const { elements, currentSnapshot } = get();
    // Only handle live events if not viewing a snapshot
    if (currentSnapshot) return;

    if (event.type === 'full_refresh' && event.data) {
      set({ elements: event.data as CytoscapeData });
      return;
    }

    if (!elements) return;

    switch (event.type) {
      case 'node_added':
        set({
          elements: {
            ...elements,
            nodes: [...elements.nodes, event.data as CytoscapeData['nodes'][0]],
          },
        });
        break;
      case 'node_removed': {
        const nodeId = (event.data as { data: { id: string } })?.data?.id;
        if (nodeId) {
          set({
            elements: {
              ...elements,
              nodes: elements.nodes.filter((n) => n.data.id !== nodeId),
              edges: elements.edges.filter(
                (e) => e.data.source !== nodeId && e.data.target !== nodeId
              ),
            },
          });
        }
        break;
      }
      case 'node_modified': {
        const modNode = event.data as CytoscapeData['nodes'][0];
        if (modNode) {
          set({
            elements: {
              ...elements,
              nodes: elements.nodes.map((n) =>
                n.data.id === modNode.data.id ? modNode : n
              ),
            },
          });
        }
        break;
      }
      case 'edge_added':
        set({
          elements: {
            ...elements,
            edges: [...elements.edges, event.data as CytoscapeData['edges'][0]],
          },
        });
        break;
      case 'edge_removed': {
        const edgeId = (event.data as { data: { id: string } })?.data?.id;
        if (edgeId) {
          set({
            elements: {
              ...elements,
              edges: elements.edges.filter((e) => e.data.id !== edgeId),
            },
          });
        }
        break;
      }
    }
  },

  setWsConnected: (connected) => {
    set({ wsConnected: connected });
  },
}));
