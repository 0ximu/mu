import type {
  StatusResponse,
  CytoscapeData,
  Node,
  QueryResult,
  GraphOptions,
  GraphEvent,
  ContextResult,
} from './types';

class MUClient {
  private baseUrl: string;
  private wsUrl: string;

  constructor(baseUrl = '/api', wsUrl = '/ws') {
    this.baseUrl = baseUrl;
    this.wsUrl = wsUrl;
  }

  async getStatus(): Promise<StatusResponse> {
    const res = await fetch(`${this.baseUrl}/status`);
    if (!res.ok) throw new Error(`Status request failed: ${res.statusText}`);
    return res.json();
  }

  async getGraph(options?: GraphOptions): Promise<CytoscapeData> {
    const params = new URLSearchParams();
    params.set('format', 'cytoscape');
    if (options?.types) params.set('types', options.types.join(','));
    if (options?.maxNodes) params.set('max_nodes', String(options.maxNodes));
    if (options?.minComplexity) params.set('min_complexity', String(options.minComplexity));
    if (options?.pathPattern) params.set('path_pattern', options.pathPattern);

    const res = await fetch(`${this.baseUrl}/export?${params}`);
    if (!res.ok) throw new Error(`Graph request failed: ${res.statusText}`);
    const data = await res.json();
    // API returns {elements: {nodes, edges}, style, layout} - extract elements
    return data.elements;
  }

  async getNode(id: string): Promise<Node> {
    const res = await fetch(`${this.baseUrl}/nodes/${encodeURIComponent(id)}`);
    if (!res.ok) throw new Error(`Node request failed: ${res.statusText}`);
    return res.json();
  }

  async getNodeNeighbors(id: string): Promise<CytoscapeData> {
    const res = await fetch(`${this.baseUrl}/nodes/${encodeURIComponent(id)}/neighbors`);
    if (!res.ok) throw new Error(`Neighbors request failed: ${res.statusText}`);
    return res.json();
  }

  async query(muql: string): Promise<QueryResult> {
    const res = await fetch(`${this.baseUrl}/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ muql }),
    });
    if (!res.ok) throw new Error(`Query request failed: ${res.statusText}`);
    return res.json();
  }

  async getContext(question: string): Promise<ContextResult> {
    const res = await fetch(`${this.baseUrl}/context`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    });
    if (!res.ok) throw new Error(`Context request failed: ${res.statusText}`);
    return res.json();
  }

  async findPath(from: string, to: string): Promise<string[]> {
    const result = await this.query(`PATH FROM "${from}" TO "${to}"`);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return (result.rows[0] as any)?.path || [];
  }

  async getSnapshots(): Promise<QueryResult> {
    return this.query('SELECT * FROM snapshots ORDER BY commit_date DESC');
  }

  async getGraphAtSnapshot(commitHash: string): Promise<CytoscapeData> {
    const params = new URLSearchParams();
    params.set('format', 'cytoscape');
    params.set('at', commitHash);
    const res = await fetch(`${this.baseUrl}/export?${params}`);
    if (!res.ok) throw new Error(`Snapshot graph request failed: ${res.statusText}`);
    const data = await res.json();
    return data.elements;
  }

  connectWebSocket(onMessage: (event: GraphEvent) => void): WebSocket {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsHost = window.location.host;
    const ws = new WebSocket(`${protocol}//${wsHost}${this.wsUrl}/live`);

    ws.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data) as GraphEvent;
        onMessage(event);
      } catch (err) {
        console.error('Failed to parse WebSocket message:', err);
      }
    };

    ws.onerror = (e) => {
      console.error('WebSocket error:', e);
    };

    return ws;
  }
}

export const muClient = new MUClient();
export { MUClient };
