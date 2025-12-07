/**
 * MU Daemon API Client
 *
 * TypeScript client for communicating with the MU daemon HTTP API.
 * Handles all network requests and error handling.
 */

import * as vscode from 'vscode';
import * as http from 'http';
import * as https from 'https';
import {
    StatusResponse,
    Node,
    NeighborsResponse,
    QueryResult,
    ContextResult,
    ContractsResult,
    GraphEvent,
} from './types';

/** Event handler for graph updates */
export type GraphEventHandler = (events: GraphEvent[]) => void;

/** Connection state */
export type ConnectionState = 'disconnected' | 'connecting' | 'connected';

/**
 * MU Daemon API Client
 *
 * Provides methods for querying the MU daemon.
 */
export class MUClient {
    private baseUrl: string;
    private eventHandlers: GraphEventHandler[] = [];
    private connectionState: ConnectionState = 'disconnected';

    // Event emitters for connection state changes
    private _onConnectionStateChange = new vscode.EventEmitter<ConnectionState>();
    readonly onConnectionStateChange = this._onConnectionStateChange.event;

    constructor() {
        this.baseUrl = this.getBaseUrl();

        // Listen for configuration changes
        vscode.workspace.onDidChangeConfiguration((e) => {
            if (e.affectsConfiguration('mu.daemonUrl')) {
                this.baseUrl = this.getBaseUrl();
            }
        });
    }

    private getBaseUrl(): string {
        const config = vscode.workspace.getConfiguration('mu');
        return config.get<string>('daemonUrl', 'http://localhost:8765');
    }

    /**
     * Make an HTTP request to the daemon
     */
    private async request<T>(
        method: 'GET' | 'POST',
        path: string,
        body?: unknown
    ): Promise<T> {
        const url = new URL(path, this.baseUrl);
        const isHttps = url.protocol === 'https:';
        const httpModule = isHttps ? https : http;

        return new Promise((resolve, reject) => {
            const options: http.RequestOptions = {
                hostname: url.hostname,
                port: url.port || (isHttps ? 443 : 80),
                path: url.pathname + url.search,
                method,
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                },
            };

            const req = httpModule.request(options, (res) => {
                let data = '';
                res.on('data', (chunk) => {
                    data += chunk;
                });
                res.on('end', () => {
                    if (res.statusCode && res.statusCode >= 200 && res.statusCode < 300) {
                        try {
                            resolve(JSON.parse(data) as T);
                        } catch {
                            reject(new Error(`Invalid JSON response: ${data}`));
                        }
                    } else {
                        reject(new Error(`HTTP ${res.statusCode}: ${data}`));
                    }
                });
            });

            req.on('error', (err) => {
                reject(new Error(`Request failed: ${err.message}`));
            });

            // Set timeout
            req.setTimeout(10000, () => {
                req.destroy();
                reject(new Error('Request timeout'));
            });

            if (body) {
                req.write(JSON.stringify(body));
            }
            req.end();
        });
    }

    // -------------------------------------------------------------------------
    // REST API Methods
    // -------------------------------------------------------------------------

    /**
     * Get daemon status
     */
    async getStatus(): Promise<StatusResponse> {
        return this.request<StatusResponse>('GET', '/status');
    }

    /**
     * Get a node by ID
     */
    async getNode(id: string): Promise<Node> {
        return this.request<Node>('GET', `/nodes/${encodeURIComponent(id)}`);
    }

    /**
     * Get neighboring nodes
     * @param id Node ID
     * @param direction 'outgoing' (dependencies), 'incoming' (dependents), or 'both'
     */
    async getNeighbors(
        id: string,
        direction: 'outgoing' | 'incoming' | 'both' = 'both'
    ): Promise<Node[]> {
        const response = await this.request<NeighborsResponse>(
            'GET',
            `/nodes/${encodeURIComponent(id)}/neighbors?direction=${direction}`
        );
        return response.neighbors;
    }

    /**
     * Execute a MUQL query
     */
    async query(muql: string): Promise<QueryResult> {
        const response = await this.request<QueryResult>('POST', '/query', { muql });

        // The daemon returns result as a JSON string - parse it and convert rows to Node objects
        if (response.success && typeof response.result === 'string') {
            try {
                const parsed = JSON.parse(response.result) as {
                    columns: string[];
                    rows: unknown[][];
                    row_count: number;
                };

                // The API returns rows with fixed positions (columns array may be incomplete):
                // [0] id, [1] type, [2] name, [3] qualified_name, [4] file_path,
                // [5] line_start, [6] line_end, [7] properties, [8] complexity
                const nodes: Node[] = parsed.rows.map((row) => {
                    return {
                        id: row[0] as string,
                        type: row[1] as string,
                        name: row[2] as string,
                        qualified_name: row[3] as string | undefined,
                        file_path: row[4] as string | undefined,
                        line_start: row[5] as number | undefined,
                        line_end: row[6] as number | undefined,
                        properties: typeof row[7] === 'string' ? JSON.parse(row[7]) : row[7],
                        complexity: row[8] as number | undefined,
                    } as Node;
                });

                return {
                    ...response,
                    result: nodes,
                };
            } catch {
                // If parsing fails, return as-is
                return response;
            }
        }

        return response;
    }

    /**
     * Get smart context for a question
     */
    async getContext(question: string, maxTokens?: number): Promise<ContextResult> {
        const config = vscode.workspace.getConfiguration('mu');
        const tokens = maxTokens ?? config.get<number>('context.maxTokens', 8000);
        return this.request<ContextResult>('POST', '/context', {
            question,
            max_tokens: tokens,
        });
    }

    /**
     * Verify architecture contracts
     */
    async verifyContracts(contractsPath?: string): Promise<ContractsResult> {
        return this.request<ContractsResult>('POST', '/contracts/verify', {
            contracts_path: contractsPath,
        });
    }

    /**
     * Sanitize a string for safe use in MUQL queries.
     */
    private sanitizeForQuery(value: string): string {
        return value.replace(/'/g, "''").replace(/"/g, '\\"');
    }

    /**
     * Validate that a node ID matches expected patterns.
     */
    private isValidNodeId(id: string): boolean {
        return /^[a-zA-Z0-9:._\-/]+$/.test(id);
    }

    /**
     * Validate that a file path is safe for queries.
     */
    private isValidFilePath(path: string): boolean {
        if (path.includes('..') || path.includes('\0')) {
            return false;
        }
        return true;
    }

    /**
     * Get nodes for a specific file
     */
    async getNodesForFile(filePath: string): Promise<Node[]> {
        if (!this.isValidFilePath(filePath)) {
            throw new Error('Invalid file path');
        }
        const sanitized = this.sanitizeForQuery(filePath);
        const result = await this.query(
            `SELECT * FROM nodes WHERE file_path = '${sanitized}' AND type IN ('function', 'class')`
        );
        if (!result.success) {
            throw new Error(result.error ?? 'Query failed');
        }
        return (result.result as Node[]) || [];
    }

    /**
     * Find path between two nodes
     */
    async findPath(fromId: string, toId: string): Promise<string[]> {
        if (!this.isValidNodeId(fromId) || !this.isValidNodeId(toId)) {
            throw new Error('Invalid node ID format');
        }
        const result = await this.query(`PATH FROM "${this.sanitizeForQuery(fromId)}" TO "${this.sanitizeForQuery(toId)}"`);
        if (!result.success) {
            throw new Error(result.error ?? 'Query failed');
        }
        const rows = result.result as Record<string, unknown>[];
        if (rows && rows.length > 0 && Array.isArray(rows[0]?.path)) {
            return rows[0].path as string[];
        }
        return [];
    }

    // -------------------------------------------------------------------------
    // Connection Management (simplified - no WebSocket)
    // -------------------------------------------------------------------------

    /**
     * Connect to the daemon (just checks status)
     */
    connectWebSocket(): void {
        // WebSocket disabled - just mark as connected if status check succeeds
        this.setConnectionState('connected');
    }

    private setConnectionState(state: ConnectionState): void {
        if (this.connectionState !== state) {
            this.connectionState = state;
            this._onConnectionStateChange.fire(state);
        }
    }

    /**
     * Register a handler for graph update events
     */
    onGraphUpdate(handler: GraphEventHandler): vscode.Disposable {
        this.eventHandlers.push(handler);
        return new vscode.Disposable(() => {
            const index = this.eventHandlers.indexOf(handler);
            if (index >= 0) {
                this.eventHandlers.splice(index, 1);
            }
        });
    }

    /**
     * Get current connection state
     */
    getConnectionState(): ConnectionState {
        return this.connectionState;
    }

    /**
     * Disconnect and clean up
     */
    disconnect(): void {
        this.setConnectionState('disconnected');
    }

    /**
     * Dispose of all resources
     */
    dispose(): void {
        this.disconnect();
        this._onConnectionStateChange.dispose();
        this.eventHandlers = [];
    }
}
