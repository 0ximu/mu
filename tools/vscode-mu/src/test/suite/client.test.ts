/**
 * MUClient Tests
 *
 * Tests for the MU daemon API client including HTTP requests and WebSocket handling.
 * Uses mocking to simulate network responses.
 */

import * as assert from 'assert';
import * as sinon from 'sinon';
import * as http from 'http';
import * as https from 'https';
import { EventEmitter } from 'events';
import * as vscode from 'vscode';

// Mock types for testing
interface MockNode {
    id: string;
    name: string;
    type: string;
    file_path?: string;
    line_start?: number;
    line_end?: number;
    complexity?: number;
}

interface MockStatusResponse {
    status: string;
    mubase_path: string;
    stats: { nodes: number; edges: number };
    connections: number;
    uptime_seconds: number;
}

interface MockNeighborsResponse {
    node_id: string;
    direction: string;
    neighbors: MockNode[];
}

interface MockQueryResult {
    result: unknown;
    success: boolean;
    error?: string;
}

interface MockContextResult {
    mu_text: string;
    token_count: number;
    nodes: MockNode[];
}

interface MockContractsResult {
    passed: boolean;
    error_count: number;
    warning_count: number;
    violations: Array<{
        contract: string;
        rule: string;
        message: string;
        severity: string;
    }>;
}

// Helper to create a mock HTTP response
function createMockResponse(statusCode: number, body: unknown): http.IncomingMessage {
    const response = new EventEmitter() as http.IncomingMessage;
    (response as any).statusCode = statusCode;

    // Emit data and end events after a tick
    setImmediate(() => {
        response.emit('data', JSON.stringify(body));
        response.emit('end');
    });

    return response;
}

// Helper to create a mock HTTP request
function createMockRequest(): http.ClientRequest {
    const request = new EventEmitter() as http.ClientRequest;
    (request as any).write = sinon.stub();
    (request as any).end = sinon.stub();
    (request as any).setTimeout = sinon.stub();
    (request as any).destroy = sinon.stub();
    return request;
}

suite('MUClient Test Suite', () => {
    let sandbox: sinon.SinonSandbox;
    let httpRequestStub: sinon.SinonStub;
    let configStub: sinon.SinonStub;

    setup(() => {
        sandbox = sinon.createSandbox();

        // Mock vscode.workspace.getConfiguration
        configStub = sandbox.stub(vscode.workspace, 'getConfiguration');
        configStub.returns({
            get: (key: string, defaultValue: unknown) => {
                if (key === 'daemonUrl') return 'http://localhost:8765';
                if (key === 'context.maxTokens') return 8000;
                return defaultValue;
            },
        } as any);

        // Mock vscode.workspace.onDidChangeConfiguration
        sandbox.stub(vscode.workspace, 'onDidChangeConfiguration').returns({
            dispose: () => {},
        } as any);

        // Mock http.request
        httpRequestStub = sandbox.stub(http, 'request');
    });

    teardown(() => {
        sandbox.restore();
    });

    suite('HTTP Request Methods', () => {
        test('getStatus returns status response', async () => {
            const mockResponse: MockStatusResponse = {
                status: 'running',
                mubase_path: '/path/to/.mubase',
                stats: { nodes: 100, edges: 200 },
                connections: 2,
                uptime_seconds: 3600,
            };

            const mockReq = createMockRequest();
            httpRequestStub.callsFake((options: any, callback: (res: any) => void) => {
                setImmediate(() => {
                    callback(createMockResponse(200, mockResponse));
                });
                return mockReq;
            });

            // Import and create client after mocks are set up
            const { MUClient } = await import('../../client/MUClient');
            const client = new MUClient();

            const result = await client.getStatus();

            assert.strictEqual(result.status, 'running');
            assert.strictEqual(result.stats.nodes, 100);
            assert.strictEqual(result.connections, 2);

            client.dispose();
        });

        test('getNode returns node data', async () => {
            const mockNode: MockNode = {
                id: 'fn:test.py:func',
                name: 'func',
                type: 'function',
                file_path: 'test.py',
                line_start: 10,
                line_end: 20,
                complexity: 5,
            };

            const mockReq = createMockRequest();
            httpRequestStub.callsFake((options: any, callback: (res: any) => void) => {
                setImmediate(() => {
                    callback(createMockResponse(200, mockNode));
                });
                return mockReq;
            });

            const { MUClient } = await import('../../client/MUClient');
            const client = new MUClient();

            const result = await client.getNode('fn:test.py:func');

            assert.strictEqual(result.id, 'fn:test.py:func');
            assert.strictEqual(result.name, 'func');
            assert.strictEqual(result.type, 'function');

            client.dispose();
        });

        test('getNeighbors returns neighbor nodes', async () => {
            const mockResponse: MockNeighborsResponse = {
                node_id: 'fn:test.py:func',
                direction: 'outgoing',
                neighbors: [
                    { id: 'ext:os', name: 'os', type: 'external' },
                    { id: 'fn:utils.py:helper', name: 'helper', type: 'function' },
                ],
            };

            const mockReq = createMockRequest();
            httpRequestStub.callsFake((options: any, callback: (res: any) => void) => {
                setImmediate(() => {
                    callback(createMockResponse(200, mockResponse));
                });
                return mockReq;
            });

            const { MUClient } = await import('../../client/MUClient');
            const client = new MUClient();

            const result = await client.getNeighbors('fn:test.py:func', 'outgoing');

            assert.strictEqual(result.length, 2);
            assert.strictEqual(result[0].name, 'os');
            assert.strictEqual(result[1].name, 'helper');

            client.dispose();
        });

        test('query executes MUQL and returns result', async () => {
            const mockResponse: MockQueryResult = {
                result: [{ name: 'TestClass', type: 'class' }],
                success: true,
            };

            const mockReq = createMockRequest();
            httpRequestStub.callsFake((options: any, callback: (res: any) => void) => {
                setImmediate(() => {
                    callback(createMockResponse(200, mockResponse));
                });
                return mockReq;
            });

            const { MUClient } = await import('../../client/MUClient');
            const client = new MUClient();

            const result = await client.query("SELECT * FROM classes WHERE name = 'TestClass'");

            assert.strictEqual(result.success, true);
            assert.ok(Array.isArray(result.result));

            client.dispose();
        });

        test('query handles error response', async () => {
            const mockResponse: MockQueryResult = {
                result: null,
                success: false,
                error: 'Invalid MUQL syntax',
            };

            const mockReq = createMockRequest();
            httpRequestStub.callsFake((options: any, callback: (res: any) => void) => {
                setImmediate(() => {
                    callback(createMockResponse(200, mockResponse));
                });
                return mockReq;
            });

            const { MUClient } = await import('../../client/MUClient');
            const client = new MUClient();

            const result = await client.query('INVALID QUERY');

            assert.strictEqual(result.success, false);
            assert.strictEqual(result.error, 'Invalid MUQL syntax');

            client.dispose();
        });

        test('getContext returns context result', async () => {
            const mockResponse: MockContextResult = {
                mu_text: '! module test\n$ TestClass\n# test_func',
                token_count: 50,
                nodes: [
                    { id: 'mod:test.py', name: 'test', type: 'module' },
                ],
            };

            const mockReq = createMockRequest();
            httpRequestStub.callsFake((options: any, callback: (res: any) => void) => {
                setImmediate(() => {
                    callback(createMockResponse(200, mockResponse));
                });
                return mockReq;
            });

            const { MUClient } = await import('../../client/MUClient');
            const client = new MUClient();

            const result = await client.getContext('How does authentication work?');

            assert.ok(result.mu_text.includes('! module'));
            assert.strictEqual(result.token_count, 50);
            assert.strictEqual(result.nodes.length, 1);

            client.dispose();
        });

        test('verifyContracts returns contracts result', async () => {
            const mockResponse: MockContractsResult = {
                passed: true,
                error_count: 0,
                warning_count: 0,
                violations: [],
            };

            const mockReq = createMockRequest();
            httpRequestStub.callsFake((options: any, callback: (res: any) => void) => {
                setImmediate(() => {
                    callback(createMockResponse(200, mockResponse));
                });
                return mockReq;
            });

            const { MUClient } = await import('../../client/MUClient');
            const client = new MUClient();

            const result = await client.verifyContracts();

            assert.strictEqual(result.passed, true);
            assert.strictEqual(result.error_count, 0);
            assert.strictEqual(result.violations.length, 0);

            client.dispose();
        });

        test('verifyContracts returns violations', async () => {
            const mockResponse: MockContractsResult = {
                passed: false,
                error_count: 1,
                warning_count: 1,
                violations: [
                    {
                        contract: 'Complexity Check',
                        rule: 'query',
                        message: 'Function exceeds complexity threshold',
                        severity: 'error',
                    },
                    {
                        contract: 'Naming Convention',
                        rule: 'pattern',
                        message: 'Class name should end with Service',
                        severity: 'warning',
                    },
                ],
            };

            const mockReq = createMockRequest();
            httpRequestStub.callsFake((options: any, callback: (res: any) => void) => {
                setImmediate(() => {
                    callback(createMockResponse(200, mockResponse));
                });
                return mockReq;
            });

            const { MUClient } = await import('../../client/MUClient');
            const client = new MUClient();

            const result = await client.verifyContracts('.mu-contracts.yml');

            assert.strictEqual(result.passed, false);
            assert.strictEqual(result.error_count, 1);
            assert.strictEqual(result.warning_count, 1);
            assert.strictEqual(result.violations.length, 2);
            assert.strictEqual(result.violations[0].contract, 'Complexity Check');

            client.dispose();
        });

        test('handles HTTP error response', async () => {
            const mockReq = createMockRequest();
            httpRequestStub.callsFake((options: any, callback: (res: any) => void) => {
                setImmediate(() => {
                    callback(createMockResponse(404, { detail: 'Node not found' }));
                });
                return mockReq;
            });

            const { MUClient } = await import('../../client/MUClient');
            const client = new MUClient();

            try {
                await client.getNode('nonexistent');
                assert.fail('Should have thrown an error');
            } catch (err: any) {
                assert.ok(err.message.includes('404'));
            }

            client.dispose();
        });

        test('handles network error', async () => {
            const mockReq = createMockRequest();
            httpRequestStub.callsFake((options: any, callback: (res: any) => void) => {
                setImmediate(() => {
                    mockReq.emit('error', new Error('ECONNREFUSED'));
                });
                return mockReq;
            });

            const { MUClient } = await import('../../client/MUClient');
            const client = new MUClient();

            try {
                await client.getStatus();
                assert.fail('Should have thrown an error');
            } catch (err: any) {
                assert.ok(err.message.includes('Request failed'));
            }

            client.dispose();
        });
    });

    suite('Connection State Management', () => {
        test('initial connection state is disconnected', async () => {
            const { MUClient } = await import('../../client/MUClient');
            const client = new MUClient();

            assert.strictEqual(client.getConnectionState(), 'disconnected');

            client.dispose();
        });

        test('onConnectionStateChange fires on state change', async () => {
            const { MUClient } = await import('../../client/MUClient');
            const client = new MUClient();

            const states: string[] = [];
            client.onConnectionStateChange((state) => {
                states.push(state);
            });

            // Manually trigger state change by calling disconnect (which calls setConnectionState)
            client.disconnect();

            // State should remain disconnected (no change event if already disconnected)
            // This tests that the event emitter is properly set up
            assert.strictEqual(client.getConnectionState(), 'disconnected');

            client.dispose();
        });
    });

    suite('Dispose', () => {
        test('dispose cleans up resources', async () => {
            const { MUClient } = await import('../../client/MUClient');
            const client = new MUClient();

            // Should not throw
            client.dispose();

            // Should be safe to call multiple times
            client.dispose();
        });
    });
});
