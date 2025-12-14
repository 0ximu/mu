import type { LayoutOptions } from 'cytoscape';

export type LayoutName = 'cose' | 'dagre' | 'circle' | 'grid' | 'concentric' | 'breadthfirst';

export interface LayoutConfig {
  name: LayoutName;
  label: string;
  description: string;
}

export const LAYOUT_OPTIONS: LayoutConfig[] = [
  {
    name: 'cose',
    label: 'Force-Directed',
    description: 'Physics-based layout with natural clustering',
  },
  {
    name: 'dagre',
    label: 'Hierarchical',
    description: 'Top-down directed graph layout',
  },
  {
    name: 'circle',
    label: 'Circle',
    description: 'Nodes arranged in a circle',
  },
  {
    name: 'grid',
    label: 'Grid',
    description: 'Nodes in a grid pattern',
  },
  {
    name: 'concentric',
    label: 'Concentric',
    description: 'Rings based on centrality',
  },
  {
    name: 'breadthfirst',
    label: 'Breadth-First',
    description: 'Tree-like from root nodes',
  },
];

export function getLayout(name: LayoutName): LayoutOptions {
  const layouts: Record<LayoutName, LayoutOptions> = {
    cose: {
      name: 'cose',
      animate: false, // Disable animation for large graphs
      fit: true,
      padding: 50,
      nodeRepulsion: () => 4500,
      idealEdgeLength: () => 50,
      edgeElasticity: () => 45,
      gravity: 0.4,
      numIter: 100, // Reduced iterations for performance
      randomize: false,
      componentSpacing: 60,
      nodeOverlap: 10,
      nestingFactor: 1.2,
      initialTemp: 200,
      coolingFactor: 0.95,
      minTemp: 1.0,
    },
    dagre: {
      name: 'dagre',
      animate: false,
      fit: true,
      padding: 50,
      rankDir: 'TB',
      rankSep: 50,
      nodeSep: 30,
      edgeSep: 10,
    } as LayoutOptions,
    circle: {
      name: 'circle',
      animate: false,
      fit: true,
      padding: 50,
      avoidOverlap: true,
      spacingFactor: 1.2,
    },
    grid: {
      name: 'grid',
      animate: false,
      fit: true,
      padding: 50,
      avoidOverlap: true,
      condense: true,
      rows: undefined,
      cols: undefined,
    },
    concentric: {
      name: 'concentric',
      animate: false,
      fit: true,
      padding: 50,
      minNodeSpacing: 30,
      concentric: (node) => {
        // Place by degree centrality
        return node.degree();
      },
      levelWidth: () => 3,
    },
    breadthfirst: {
      name: 'breadthfirst',
      animate: false,
      fit: true,
      padding: 50,
      directed: true,
      spacingFactor: 1.2,
      circle: false,
      grid: false,
      avoidOverlap: true,
    },
  };

  return layouts[name] || layouts.cose;
}
