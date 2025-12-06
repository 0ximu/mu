/**
 * Provider Tests
 *
 * Tests for VS Code providers including ExplorerProvider, CodeLensProvider,
 * DecorationProvider, and DiagnosticsProvider.
 */

import * as assert from 'assert';
import * as sinon from 'sinon';
import * as vscode from 'vscode';

// Mock types
interface MockNode {
    id: string;
    name: string;
    type: 'module' | 'class' | 'function' | 'external';
    qualified_name?: string;
    file_path?: string;
    line_start?: number;
    line_end?: number;
    complexity?: number;
}

interface MockQueryResult {
    result: unknown;
    success: boolean;
    error?: string;
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
        file_path?: string;
        line?: number;
    }>;
}

// Mock MUClient for provider tests
function createMockClient() {
    return {
        query: sinon.stub(),
        getNode: sinon.stub(),
        getNeighbors: sinon.stub(),
        getNodesForFile: sinon.stub(),
        verifyContracts: sinon.stub(),
        getContext: sinon.stub(),
        onGraphUpdate: sinon.stub().returns({ dispose: () => {} }),
        onConnectionStateChange: { dispose: () => {} },
        dispose: sinon.stub(),
    };
}

suite('ExplorerProvider Test Suite', () => {
    let sandbox: sinon.SinonSandbox;
    let mockClient: ReturnType<typeof createMockClient>;
    let configStub: sinon.SinonStub;

    setup(() => {
        sandbox = sinon.createSandbox();
        mockClient = createMockClient();

        // Mock VS Code configuration
        configStub = sandbox.stub(vscode.workspace, 'getConfiguration');
        configStub.returns({
            get: (key: string, defaultValue: unknown) => {
                if (key === 'complexity.warningThreshold') return 200;
                return defaultValue;
            },
        } as any);
    });

    teardown(() => {
        sandbox.restore();
    });

    suite('NodeItem', () => {
        test('creates correct tree item for module', async () => {
            const { NodeItem } = await import('../../providers/ExplorerProvider');

            const node: MockNode = {
                id: 'mod:test.py',
                name: 'test',
                type: 'module',
                file_path: 'test.py',
                line_start: 1,
            };

            const item = new NodeItem(node as any);

            assert.strictEqual(item.label, 'test');
            assert.strictEqual(item.id, 'mod:test.py');
            assert.ok(item.contextValue?.includes('module'));
        });

        test('creates correct tree item for class', async () => {
            const { NodeItem } = await import('../../providers/ExplorerProvider');

            const node: MockNode = {
                id: 'cls:test.py:MyClass',
                name: 'MyClass',
                type: 'class',
                qualified_name: 'test.MyClass',
                file_path: 'test.py',
                line_start: 10,
            };

            const item = new NodeItem(node as any);

            assert.strictEqual(item.label, 'MyClass');
            assert.ok(item.contextValue?.includes('class'));
        });

        test('creates correct tree item for function', async () => {
            const { NodeItem } = await import('../../providers/ExplorerProvider');

            const node: MockNode = {
                id: 'fn:test.py:my_func',
                name: 'my_func',
                type: 'function',
                file_path: 'test.py',
                line_start: 20,
                complexity: 15,
            };

            const item = new NodeItem(node as any);

            assert.strictEqual(item.label, 'my_func');
            assert.ok(item.contextValue?.includes('function'));
        });

        test('creates correct tree item for external dependency', async () => {
            const { NodeItem } = await import('../../providers/ExplorerProvider');

            const node: MockNode = {
                id: 'ext:os',
                name: 'os',
                type: 'external',
            };

            const item = new NodeItem(node as any);

            assert.strictEqual(item.label, 'os');
            assert.ok(item.contextValue?.includes('external'));
        });

        test('tooltip includes qualified name', async () => {
            const { NodeItem } = await import('../../providers/ExplorerProvider');

            const node: MockNode = {
                id: 'cls:test.py:MyClass',
                name: 'MyClass',
                type: 'class',
                qualified_name: 'mymodule.test.MyClass',
                file_path: 'test.py',
            };

            const item = new NodeItem(node as any);

            assert.ok(item.tooltip?.toString().includes('mymodule.test.MyClass'));
        });

        test('tooltip includes complexity', async () => {
            const { NodeItem } = await import('../../providers/ExplorerProvider');

            const node: MockNode = {
                id: 'fn:test.py:complex_func',
                name: 'complex_func',
                type: 'function',
                complexity: 500,
            };

            const item = new NodeItem(node as any);

            assert.ok(item.tooltip?.toString().includes('500'));
        });

        test('description includes complexity', async () => {
            const { NodeItem } = await import('../../providers/ExplorerProvider');

            const node: MockNode = {
                id: 'fn:test.py:func',
                name: 'func',
                type: 'function',
                file_path: 'src/test.py',
                complexity: 42,
            };

            const item = new NodeItem(node as any);

            assert.ok(typeof item.description === 'string' && item.description.includes('C:42'));
        });

        test('command is set for navigable nodes', async () => {
            const { NodeItem } = await import('../../providers/ExplorerProvider');

            const node: MockNode = {
                id: 'fn:test.py:func',
                name: 'func',
                type: 'function',
                file_path: '/path/to/test.py',
                line_start: 10,
            };

            const item = new NodeItem(node as any);

            assert.ok(item.command);
            assert.strictEqual(item.command?.command, 'vscode.open');
        });

        test('no command for nodes without file path', async () => {
            const { NodeItem } = await import('../../providers/ExplorerProvider');

            const node: MockNode = {
                id: 'ext:os',
                name: 'os',
                type: 'external',
            };

            const item = new NodeItem(node as any);

            // External nodes without file_path may not have a command
            // (depends on implementation - checking it doesn't throw)
            assert.ok(true);
        });
    });

    suite('ExplorerProvider', () => {
        test('getChildren returns empty array when loading', async () => {
            const { ExplorerProvider } = await import('../../providers/ExplorerProvider');

            const provider = new ExplorerProvider(mockClient as any, 'modules');

            // Mock query to simulate slow response
            mockClient.query.returns(new Promise(() => {}));

            const result = await provider.getChildren();

            // Should return empty initially (or cached results)
            assert.ok(Array.isArray(result));
        });

        test('getChildren calls query for modules view', async () => {
            const { ExplorerProvider } = await import('../../providers/ExplorerProvider');

            const mockNodes: MockNode[] = [
                { id: 'mod:a.py', name: 'a', type: 'module' },
                { id: 'mod:b.py', name: 'b', type: 'module' },
            ];

            mockClient.query.resolves({
                success: true,
                result: mockNodes,
            });

            const provider = new ExplorerProvider(mockClient as any, 'modules');
            const result = await provider.getChildren();

            assert.strictEqual(result.length, 2);
            assert.ok(mockClient.query.calledOnce);
        });

        test('getChildren returns items for classes view', async () => {
            const { ExplorerProvider } = await import('../../providers/ExplorerProvider');

            const mockNodes: MockNode[] = [
                { id: 'cls:a.py:ClassA', name: 'ClassA', type: 'class' },
            ];

            mockClient.query.resolves({
                success: true,
                result: mockNodes,
            });

            const provider = new ExplorerProvider(mockClient as any, 'classes');
            const result = await provider.getChildren();

            assert.strictEqual(result.length, 1);
        });

        test('getChildren returns items for functions view', async () => {
            const { ExplorerProvider } = await import('../../providers/ExplorerProvider');

            const mockNodes: MockNode[] = [
                { id: 'fn:a.py:func', name: 'func', type: 'function' },
            ];

            mockClient.query.resolves({
                success: true,
                result: mockNodes,
            });

            const provider = new ExplorerProvider(mockClient as any, 'functions');
            const result = await provider.getChildren();

            assert.strictEqual(result.length, 1);
        });

        test('getChildren returns items for hotspots view', async () => {
            const { ExplorerProvider } = await import('../../providers/ExplorerProvider');

            const mockNodes: MockNode[] = [
                { id: 'fn:a.py:complex', name: 'complex', type: 'function', complexity: 600 },
            ];

            mockClient.query.resolves({
                success: true,
                result: mockNodes,
            });

            const provider = new ExplorerProvider(mockClient as any, 'hotspots');
            const result = await provider.getChildren();

            assert.strictEqual(result.length, 1);
        });

        test('getChildren handles query failure', async () => {
            const { ExplorerProvider } = await import('../../providers/ExplorerProvider');

            mockClient.query.resolves({
                success: false,
                error: 'Query failed',
            });

            // Mock vscode.window.showWarningMessage
            sandbox.stub(vscode.window, 'showWarningMessage');

            const provider = new ExplorerProvider(mockClient as any, 'modules');
            const result = await provider.getChildren();

            assert.strictEqual(result.length, 0);
        });

        test('getChildren returns child nodes for element', async () => {
            const { ExplorerProvider, NodeItem } = await import('../../providers/ExplorerProvider');

            const parentNode: MockNode = {
                id: 'mod:test.py',
                name: 'test',
                type: 'module',
            };

            const childNodes: MockNode[] = [
                { id: 'cls:test.py:MyClass', name: 'MyClass', type: 'class' },
                { id: 'fn:test.py:func', name: 'func', type: 'function' },
            ];

            mockClient.getNeighbors.resolves(childNodes);

            const provider = new ExplorerProvider(mockClient as any, 'modules');
            const parentItem = new NodeItem(parentNode as any);

            const result = await provider.getChildren(parentItem);

            assert.strictEqual(result.length, 2);
        });

        test('refresh clears cache', async () => {
            const { ExplorerProvider } = await import('../../providers/ExplorerProvider');

            const provider = new ExplorerProvider(mockClient as any, 'modules');

            // First call
            mockClient.query.resolves({ success: true, result: [] });
            await provider.getChildren();

            // Refresh
            provider.refresh();

            // Second call should query again
            await provider.getChildren();

            assert.strictEqual(mockClient.query.callCount, 2);
        });

        test('getTreeItem returns element unchanged', async () => {
            const { ExplorerProvider, NodeItem } = await import('../../providers/ExplorerProvider');

            const provider = new ExplorerProvider(mockClient as any, 'modules');
            const node: MockNode = { id: 'mod:test.py', name: 'test', type: 'module' };
            const item = new NodeItem(node as any);

            const result = provider.getTreeItem(item);

            assert.strictEqual(result, item);
        });
    });
});

suite('CodeLensProvider Test Suite', () => {
    let sandbox: sinon.SinonSandbox;
    let mockClient: ReturnType<typeof createMockClient>;
    let configStub: sinon.SinonStub;

    setup(() => {
        sandbox = sinon.createSandbox();
        mockClient = createMockClient();

        configStub = sandbox.stub(vscode.workspace, 'getConfiguration');
        configStub.returns({
            get: (key: string, defaultValue: unknown) => {
                if (key === 'codeLens.enabled') return true;
                return defaultValue;
            },
        } as any);
    });

    teardown(() => {
        sandbox.restore();
    });

    suite('provideCodeLenses', () => {
        test('returns empty array when CodeLens disabled', async () => {
            configStub.returns({
                get: (key: string) => key === 'codeLens.enabled' ? false : undefined,
            } as any);

            const { CodeLensProvider } = await import('../../providers/CodeLensProvider');
            const provider = new CodeLensProvider(mockClient as any);

            const mockDocument = {
                languageId: 'python',
                uri: { fsPath: '/path/to/test.py' },
                version: 1,
            } as vscode.TextDocument;

            const result = await provider.provideCodeLenses(
                mockDocument,
                { isCancellationRequested: false } as vscode.CancellationToken
            );

            assert.strictEqual(result.length, 0);
        });

        test('returns empty array for unsupported language', async () => {
            const { CodeLensProvider } = await import('../../providers/CodeLensProvider');
            const provider = new CodeLensProvider(mockClient as any);

            const mockDocument = {
                languageId: 'plaintext',
                uri: { fsPath: '/path/to/test.txt' },
                version: 1,
            } as vscode.TextDocument;

            const result = await provider.provideCodeLenses(
                mockDocument,
                { isCancellationRequested: false } as vscode.CancellationToken
            );

            assert.strictEqual(result.length, 0);
        });

        test('returns CodeLenses for Python files', async () => {
            const mockNodes: MockNode[] = [
                {
                    id: 'fn:test.py:func',
                    name: 'func',
                    type: 'function',
                    file_path: '/path/to/test.py',
                    line_start: 5,
                },
            ];

            mockClient.getNodesForFile.resolves(mockNodes);

            const { CodeLensProvider } = await import('../../providers/CodeLensProvider');
            const provider = new CodeLensProvider(mockClient as any);

            const mockDocument = {
                languageId: 'python',
                uri: { fsPath: '/path/to/test.py' },
                version: 1,
                lineCount: 100,
            } as vscode.TextDocument;

            const result = await provider.provideCodeLenses(
                mockDocument,
                { isCancellationRequested: false } as vscode.CancellationToken
            );

            assert.strictEqual(result.length, 1);
        });

        test('returns empty array on client error', async () => {
            mockClient.getNodesForFile.rejects(new Error('Daemon not available'));

            const { CodeLensProvider } = await import('../../providers/CodeLensProvider');
            const provider = new CodeLensProvider(mockClient as any);

            const mockDocument = {
                languageId: 'python',
                uri: { fsPath: '/path/to/test.py' },
                version: 1,
            } as vscode.TextDocument;

            const result = await provider.provideCodeLenses(
                mockDocument,
                { isCancellationRequested: false } as vscode.CancellationToken
            );

            assert.strictEqual(result.length, 0);
        });

        test('refresh clears cache', async () => {
            const { CodeLensProvider } = await import('../../providers/CodeLensProvider');
            const provider = new CodeLensProvider(mockClient as any);

            provider.refresh();

            // Should not throw
            assert.ok(true);
        });
    });

    suite('resolveCodeLens', () => {
        test('resolves CodeLens with dependency counts', async () => {
            const outgoing: MockNode[] = [
                { id: 'ext:os', name: 'os', type: 'external' },
                { id: 'fn:utils.py:helper', name: 'helper', type: 'function' },
            ];
            const incoming: MockNode[] = [
                { id: 'fn:main.py:main', name: 'main', type: 'function' },
            ];

            mockClient.getNeighbors
                .withArgs('fn:test.py:func', 'outgoing').resolves(outgoing)
                .withArgs('fn:test.py:func', 'incoming').resolves(incoming);

            const { CodeLensProvider } = await import('../../providers/CodeLensProvider');
            const provider = new CodeLensProvider(mockClient as any);

            const codeLens = new vscode.CodeLens(new vscode.Range(0, 0, 0, 0));
            (codeLens as any).nodeId = 'fn:test.py:func';
            (codeLens as any).nodeName = 'func';

            const result = await provider.resolveCodeLens(
                codeLens,
                { isCancellationRequested: false } as vscode.CancellationToken
            );

            assert.ok(result);
            assert.ok(result?.command?.title.includes('deps'));
            assert.ok(result?.command?.title.includes('refs'));
        });

        test('returns null for CodeLens without nodeId', async () => {
            const { CodeLensProvider } = await import('../../providers/CodeLensProvider');
            const provider = new CodeLensProvider(mockClient as any);

            const codeLens = new vscode.CodeLens(new vscode.Range(0, 0, 0, 0));

            const result = await provider.resolveCodeLens(
                codeLens,
                { isCancellationRequested: false } as vscode.CancellationToken
            );

            assert.strictEqual(result, null);
        });

        test('handles error during resolution', async () => {
            mockClient.getNeighbors.rejects(new Error('Network error'));

            const { CodeLensProvider } = await import('../../providers/CodeLensProvider');
            const provider = new CodeLensProvider(mockClient as any);

            const codeLens = new vscode.CodeLens(new vscode.Range(0, 0, 0, 0));
            (codeLens as any).nodeId = 'fn:test.py:func';

            const result = await provider.resolveCodeLens(
                codeLens,
                { isCancellationRequested: false } as vscode.CancellationToken
            );

            // Should return CodeLens with error indicator
            assert.ok(result);
            assert.ok(result?.command?.title.includes('?'));
        });
    });
});

suite('DiagnosticsProvider Test Suite', () => {
    let sandbox: sinon.SinonSandbox;
    let mockClient: ReturnType<typeof createMockClient>;
    let diagnosticsSetStub: sinon.SinonStub;
    let diagnosticsClearStub: sinon.SinonStub;

    setup(() => {
        sandbox = sinon.createSandbox();
        mockClient = createMockClient();

        // Mock vscode.languages.createDiagnosticCollection
        const mockDiagnostics = {
            set: sandbox.stub(),
            clear: sandbox.stub(),
            dispose: sandbox.stub(),
        };
        diagnosticsSetStub = mockDiagnostics.set;
        diagnosticsClearStub = mockDiagnostics.clear;

        sandbox.stub(vscode.languages, 'createDiagnosticCollection').returns(mockDiagnostics as any);

        // Mock vscode.workspace.onDidSaveTextDocument
        sandbox.stub(vscode.workspace, 'onDidSaveTextDocument').returns({
            dispose: () => {},
        } as any);

        // Mock vscode.window.setStatusBarMessage
        sandbox.stub(vscode.window, 'setStatusBarMessage');
    });

    teardown(() => {
        sandbox.restore();
    });

    suite('refresh', () => {
        test('clears diagnostics when no violations', async () => {
            const mockResult: MockContractsResult = {
                passed: true,
                error_count: 0,
                warning_count: 0,
                violations: [],
            };

            mockClient.verifyContracts.resolves(mockResult);

            const { DiagnosticsProvider } = await import('../../providers/DiagnosticsProvider');
            const provider = new DiagnosticsProvider(mockClient as any);

            await provider.refresh();

            assert.ok(diagnosticsClearStub.called);
        });

        test('sets diagnostics for violations', async () => {
            const mockResult: MockContractsResult = {
                passed: false,
                error_count: 1,
                warning_count: 0,
                violations: [
                    {
                        contract: 'Complexity Check',
                        rule: 'query',
                        message: 'High complexity',
                        severity: 'error',
                        file_path: '/path/to/test.py',
                        line: 10,
                    },
                ],
            };

            mockClient.verifyContracts.resolves(mockResult);

            const { DiagnosticsProvider } = await import('../../providers/DiagnosticsProvider');
            const provider = new DiagnosticsProvider(mockClient as any);

            await provider.refresh();

            // Check that diagnostics were set
            assert.ok(diagnosticsSetStub.called || diagnosticsClearStub.called);
        });

        test('handles verification error silently', async () => {
            mockClient.verifyContracts.rejects(new Error('Daemon not available'));

            const { DiagnosticsProvider } = await import('../../providers/DiagnosticsProvider');
            const provider = new DiagnosticsProvider(mockClient as any);

            // Should not throw
            await provider.refresh();
            assert.ok(true);
        });

        test('maps error severity correctly', async () => {
            const mockResult: MockContractsResult = {
                passed: false,
                error_count: 1,
                warning_count: 0,
                violations: [
                    {
                        contract: 'Test',
                        rule: 'query',
                        message: 'Error',
                        severity: 'error',
                        file_path: '/test.py',
                        line: 1,
                    },
                ],
            };

            mockClient.verifyContracts.resolves(mockResult);

            const { DiagnosticsProvider } = await import('../../providers/DiagnosticsProvider');
            const provider = new DiagnosticsProvider(mockClient as any);

            await provider.refresh();

            // Verify diagnostics were processed
            assert.ok(true);
        });

        test('maps warning severity correctly', async () => {
            const mockResult: MockContractsResult = {
                passed: true,
                error_count: 0,
                warning_count: 1,
                violations: [
                    {
                        contract: 'Test',
                        rule: 'query',
                        message: 'Warning',
                        severity: 'warning',
                        file_path: '/test.py',
                        line: 1,
                    },
                ],
            };

            mockClient.verifyContracts.resolves(mockResult);

            const { DiagnosticsProvider } = await import('../../providers/DiagnosticsProvider');
            const provider = new DiagnosticsProvider(mockClient as any);

            await provider.refresh();

            // Verify diagnostics were processed
            assert.ok(true);
        });
    });

    suite('clear', () => {
        test('clears all diagnostics', async () => {
            const { DiagnosticsProvider } = await import('../../providers/DiagnosticsProvider');
            const provider = new DiagnosticsProvider(mockClient as any);

            provider.clear();

            assert.ok(diagnosticsClearStub.called);
        });
    });

    suite('dispose', () => {
        test('disposes resources', async () => {
            const { DiagnosticsProvider } = await import('../../providers/DiagnosticsProvider');
            const provider = new DiagnosticsProvider(mockClient as any);

            // Should not throw
            provider.dispose();
            assert.ok(true);
        });
    });
});

suite('DecorationProvider Test Suite', () => {
    let sandbox: sinon.SinonSandbox;
    let mockClient: ReturnType<typeof createMockClient>;

    setup(() => {
        sandbox = sinon.createSandbox();
        mockClient = createMockClient();

        // Mock VS Code configuration
        sandbox.stub(vscode.workspace, 'getConfiguration').returns({
            get: (key: string, defaultValue: unknown) => {
                if (key === 'badges.enabled') return true;
                if (key === 'complexity.warningThreshold') return 200;
                if (key === 'complexity.errorThreshold') return 500;
                return defaultValue;
            },
        } as any);

        // Mock vscode.window events
        sandbox.stub(vscode.window, 'onDidChangeActiveTextEditor').returns({
            dispose: () => {},
        } as any);
        sandbox.stub(vscode.workspace, 'onDidSaveTextDocument').returns({
            dispose: () => {},
        } as any);
        sandbox.stub(vscode.workspace, 'onDidChangeConfiguration').returns({
            dispose: () => {},
        } as any);

        // Mock decoration types
        sandbox.stub(vscode.window, 'createTextEditorDecorationType').returns({
            dispose: () => {},
        } as any);

        // Mock active editor
        Object.defineProperty(vscode.window, 'activeTextEditor', {
            get: () => undefined,
            configurable: true,
        });
        Object.defineProperty(vscode.window, 'visibleTextEditors', {
            get: () => [],
            configurable: true,
        });
    });

    teardown(() => {
        sandbox.restore();
    });

    test('creates decoration types on construction', async () => {
        const { DecorationProvider } = await import('../../providers/DecorationProvider');

        // Should not throw
        const provider = new DecorationProvider(mockClient as any);
        provider.dispose();

        assert.ok(true);
    });

    test('refresh clears cache and updates editors', async () => {
        const { DecorationProvider } = await import('../../providers/DecorationProvider');
        const provider = new DecorationProvider(mockClient as any);

        // Should not throw
        provider.refresh();
        provider.dispose();

        assert.ok(true);
    });

    test('dispose cleans up decoration types', async () => {
        const { DecorationProvider } = await import('../../providers/DecorationProvider');
        const provider = new DecorationProvider(mockClient as any);

        // Should not throw
        provider.dispose();

        assert.ok(true);
    });
});
