declare module 'cytoscape-dagre' {
  import { Core, LayoutOptions } from 'cytoscape';

  const dagre: (cytoscape: typeof import('cytoscape')) => void;
  export default dagre;

  export interface DagreLayoutOptions extends LayoutOptions {
    name: 'dagre';
    rankDir?: 'TB' | 'BT' | 'LR' | 'RL';
    rankSep?: number;
    nodeSep?: number;
    edgeSep?: number;
    ranker?: 'network-simplex' | 'tight-tree' | 'longest-path';
  }
}
