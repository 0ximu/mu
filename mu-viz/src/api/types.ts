// MU Daemon API Types

export type NodeType = 'module' | 'class' | 'function' | 'external';
export type EdgeType = 'imports' | 'inherits' | 'contains';

export interface Node {
  id: string;
  name: string;
  type: NodeType;
  file_path?: string;
  line_start?: number;
  line_end?: number;
  complexity?: number;
  properties?: Record<string, unknown>;
  mu_representation?: string;
}

export interface Edge {
  id: string;
  source: string;
  target: string;
  type: EdgeType;
  properties?: Record<string, unknown>;
}

export interface CytoscapeNode {
  data: {
    id: string;
    label: string;
    type: NodeType;
    file_path?: string;
    line_start?: number;
    line_end?: number;
    complexity?: number;
    [key: string]: unknown;
  };
  position?: { x: number; y: number };
}

export interface CytoscapeEdge {
  data: {
    id: string;
    source: string;
    target: string;
    type: EdgeType;
    [key: string]: unknown;
  };
}

export interface CytoscapeData {
  nodes: CytoscapeNode[];
  edges: CytoscapeEdge[];
}

export interface StatusResponse {
  status: 'running' | 'stopped';
  root_path?: string;
  nodes_count?: number;
  edges_count?: number;
  last_update?: string;
}

export interface QueryResult {
  columns: string[];
  rows: Record<string, unknown>[];
  count: number;
}

export interface Snapshot {
  id: string;
  commit_hash: string;
  commit_message: string;
  commit_author: string;
  commit_date: string;
  nodes_added: number;
  nodes_removed: number;
  nodes_modified: number;
}

export interface GraphOptions {
  types?: NodeType[];
  maxNodes?: number;
  minComplexity?: number;
  pathPattern?: string;
}

export interface GraphEvent {
  type: 'node_added' | 'node_removed' | 'node_modified' | 'edge_added' | 'edge_removed' | 'full_refresh';
  data: CytoscapeNode | CytoscapeEdge | CytoscapeData | null;
  timestamp: string;
}

export interface ContextResult {
  question: string;
  mu_output: string;
  nodes_included: number;
  confidence: number;
}
