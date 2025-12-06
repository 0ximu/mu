/**
 * MU Daemon API Client
 *
 * TypeScript client for communicating with the MU daemon HTTP API and WebSocket.
 * Handles all network requests, error handling, and WebSocket connection management.
 */

import * as vscode from 'vscode';
import * as http from 'http';
import * as https from 'https';
import WebSocket from 'ws';
import {
    StatusResponse,
    Node,
    NeighborsResponse,
    QueryResult,
    ContextResult,
    ContractsResult,
    GraphEvent,
    WebSocketMessage,
} from './types';

/** Event handler for graph updates */
export type GraphEventHandler = (events: GraphEvent[]) => void;

/** Connection state */
export type ConnectionState = 'disconnected' | 'connecting' | 'connected';

/**
 * MU Daemon API Client
 *
 * Provides methods for querying the MU daemon and receiving real-time updates.
 */
export class MUClient {
    private baseUrl: string;
    private ws: WebSocket | null = null;
    private eventHandlers: GraphEventHandler[] = [];
    private connectionState: ConnectionState = 'disconnected';
    private reconnectTimeout: NodeJS.Timeout | null = null;
    private readonly reconnectDelayMs = 5000;

    // Event emitters for connection state changes
    private _onConnectionStateChange = new vscode.EventEmitter<ConnectionState>();
    readonly onConnectionStateChange = this._onConnectionStateChange.event;

    constructor() {
        this.baseUrl = this.getBaseUrl();

        // Listen for configuration changes
        vscode.workspace.onDidChangeConfiguration((e) => {
            if (e.affectsConfiguration('mu.daemonUrl')) {
                this.baseUrl = this.getBaseUrl();
                // Reconnect WebSocket if connected
                if (this.ws) {
                    this.disconnect();
                    this.connectWebSocket();
                }
            }
        });
    }

    private getBaseUrl(): string {
        const config = vscode.workspace.getConfiguration('mu');
        return config.get<string>('daemonUrl', 'http://localhost:8765');
    }

    private getWsUrl(): string {
        const url = new URL(this.baseUrl);
        const protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
        return `${protocol}//${url.host}/live`;
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
        return this.request<QueryResult>('POST', '/query', { muql });
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
     * Escapes single quotes, double quotes, and validates against injection patterns.
     */
    private sanitizeForQuery(value: string): string {
        // Escape both single and double quotes
        return value.replace(/'/g, "''").replace(/"/g, '\\"');
    }

    /**
     * Validate that a node ID matches expected patterns.
     * Node IDs should match: mod:, cls:, fn:, ext: prefixed identifiers
     */
    private isValidNodeId(id: string): boolean {
        // Allow only alphanumeric, colons, dots, underscores, hyphens, and forward slashes
        return /^[a-zA-Z0-9:._\-/]+$/.test(id);
    }

    /**
     * Validate that a file path is safe for queries.
     */
    private isValidFilePath(path: string): boolean {
        // Disallow path traversal and dangerous characters
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
        // Validate node IDs to prevent injection
        if (!this.isValidNodeId(fromId) || !this.isValidNodeId(toId)) {
            throw new Error('Invalid node ID format');
        }
        const result = await this.query(`PATH FROM "${this.sanitizeForQuery(fromId)}" TO "${this.sanitizeForQuery(toId)}"`);
        if (!result.success) {
            throw new Error(result.error ?? 'Query failed');
        }
        // Extract path from result
        const rows = result.result as Record<string, unknown>[];
        if (rows && rows.length > 0 && Array.isArray(rows[0]?.path)) {
            return rows[0].path as string[];
        }
        return [];
    }

    // -------------------------------------------------------------------------
    // WebSocket Methods
    // -------------------------------------------------------------------------

    /**
     * Connect to the WebSocket for live updates
     */
    connectWebSocket(): void {
        if (this.ws) {
            return; // Already connected or connecting
        }

        this.setConnectionState('connecting');
        const wsUrl = this.getWsUrl();

        try {
            this.ws = new WebSocket(wsUrl);

            this.ws.on('open', () => {
                this.setConnectionState('connected');
                console.log('MU: WebSocket connected');
            });

            this.ws.on('message', (data) => {
                try {
                    const message = JSON.parse(data.toString()) as WebSocketMessage;
                    this.handleWebSocketMessage(message);
                } catch (err) {
                    console.error('MU: Failed to parse WebSocket message:', err);
                }
            });

            this.ws.on('close', () => {
                this.setConnectionState('disconnected');
                this.ws = null;
                console.log('MU: WebSocket disconnected');
                this.scheduleReconnect();
            });

            this.ws.on('error', (err) => {
                console.error('MU: WebSocket error:', err.message);
                // Don't set disconnected here - let 'close' handle it
            });
        } catch (err) {
            this.setConnectionState('disconnected');
            this.ws = null;
            console.error('MU: Failed to create WebSocket:', err);
            this.scheduleReconnect();
        }
    }

    private handleWebSocketMessage(message: WebSocketMessage): void {
        if (message.type === 'graph_update' && message.events) {
            // Notify all handlers
            for (const handler of this.eventHandlers) {
                try {
                    handler(message.events);
                } catch (err) {
                    console.error('MU: Error in graph event handler:', err);
                }
            }
        }
    }

    private setConnectionState(state: ConnectionState): void {
        if (this.connectionState !== state) {
            this.connectionState = state;
            this._onConnectionStateChange.fire(state);
        }
    }

    private scheduleReconnect(): void {
        if (this.reconnectTimeout) {
            return; // Already scheduled
        }

        this.reconnectTimeout = setTimeout(() => {
            this.reconnectTimeout = null;
            this.connectWebSocket();
        }, this.reconnectDelayMs);
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
     * Disconnect WebSocket and clean up
     */
    disconnect(): void {
        if (this.reconnectTimeout) {
            clearTimeout(this.reconnectTimeout);
            this.reconnectTimeout = null;
        }

        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }

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
