/**
 * MU Daemon API Types
 *
 * TypeScript interfaces for communicating with the MU daemon HTTP API.
 * Ported from mu-viz/src/api/types.ts with adjustments for VS Code extension use.
 */

/** Node types in the code graph */
export type NodeType = 'module' | 'class' | 'function' | 'external';

/** Edge types representing relationships between nodes */
export type EdgeType = 'imports' | 'inherits' | 'contains' | 'calls';

/** A node in the code graph */
export interface Node {
    id: string;
    name: string;
    type: NodeType;
    qualified_name?: string;
    file_path?: string;
    line_start?: number;
    line_end?: number;
    complexity?: number;
    properties?: Record<string, unknown>;
}

/** An edge connecting two nodes */
export interface Edge {
    id: string;
    source: string;
    target: string;
    type: EdgeType;
    properties?: Record<string, unknown>;
}

/** Response from GET /status */
export interface StatusResponse {
    status: 'running' | 'stopped';
    mubase_path: string;
    stats: {
        nodes: number;
        edges: number;
        [key: string]: unknown;
    };
    connections: number;
    uptime_seconds: number;
}

/** Response from GET /nodes/{id}/neighbors */
export interface NeighborsResponse {
    node_id: string;
    direction: string;
    neighbors: Node[];
}

/** Response from POST /query */
export interface QueryResult {
    result: unknown;
    success: boolean;
    error?: string;
}

/** Response from POST /context */
export interface ContextResult {
    mu_text: string;
    token_count: number;
    nodes: Node[];
}

/** A contract violation from /contracts/verify */
export interface ContractViolation {
    contract: string;
    rule: string;
    message: string;
    severity: 'error' | 'warning';
    file_path?: string;
    line?: number;
    node_id?: string;
}

/** Response from POST /contracts/verify */
export interface ContractsResult {
    passed: boolean;
    error_count: number;
    warning_count: number;
    violations: ContractViolation[];
}

/** Graph event types from WebSocket */
export type GraphEventType =
    | 'connected'
    | 'graph_update'
    | 'node_added'
    | 'node_modified'
    | 'node_removed'
    | 'edge_added'
    | 'edge_removed'
    | 'full_refresh';

/** A single graph event from the daemon */
export interface GraphEvent {
    event_type: GraphEventType;
    node_id?: string;
    node_type?: NodeType;
    file_path?: string;
    timestamp?: number;
}

/** WebSocket message envelope */
export interface WebSocketMessage {
    type: string;
    events?: GraphEvent[];
    message?: string;
    timestamp: number;
}

/** Options for graph export */
export interface ExportOptions {
    format?: 'mu' | 'json' | 'mermaid' | 'd2' | 'cytoscape';
    nodes?: string[];
    types?: NodeType[];
    max_nodes?: number;
}
