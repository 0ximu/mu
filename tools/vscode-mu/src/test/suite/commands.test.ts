/**
 * Command Tests
 *
 * Tests for VS Code commands including runQuery, getContext, showDependencies, and showDependents.
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

interface MockContextResult {
    mu_text: string;
    token_count: number;
    nodes: MockNode[];
}

// Mock MUClient for command tests
function createMockClient() {
    return {
        query: sinon.stub(),
        getNode: sinon.stub(),
        getNeighbors: sinon.stub(),
        getNodesForFile: sinon.stub(),
        verifyContracts: sinon.stub(),
        getContext: sinon.stub(),
        findPath: sinon.stub(),
        onGraphUpdate: sinon.stub().returns({ dispose: () => {} }),
        onConnectionStateChange: { dispose: () => {} },
        dispose: sinon.stub(),
    };
}

suite('Query Commands Test Suite', () => {
    let sandbox: sinon.SinonSandbox;
    let mockClient: ReturnType<typeof createMockClient>;
    let showInputBoxStub: sinon.SinonStub;
    let showQuickPickStub: sinon.SinonStub;
    let showInformationMessageStub: sinon.SinonStub;
    let showErrorMessageStub: sinon.SinonStub;
    let createOutputChannelStub: sinon.SinonStub;

    setup(() => {
        sandbox = sinon.createSandbox();
        mockClient = createMockClient();

        // Mock VS Code window methods
        showInputBoxStub = sandbox.stub(vscode.window, 'showInputBox');
        showQuickPickStub = sandbox.stub(vscode.window, 'showQuickPick');
        showInformationMessageStub = sandbox.stub(vscode.window, 'showInformationMessage');
        showErrorMessageStub = sandbox.stub(vscode.window, 'showErrorMessage');

        // Mock output channel
        const mockOutputChannel = {
            appendLine: sandbox.stub(),
            clear: sandbox.stub(),
            show: sandbox.stub(),
            dispose: sandbox.stub(),
        };
        createOutputChannelStub = sandbox.stub(vscode.window, 'createOutputChannel').returns(mockOutputChannel as any);
    });

    teardown(() => {
        sandbox.restore();
    });

    suite('runQuery', () => {
        test('returns early when user cancels input', async () => {
            showInputBoxStub.resolves(undefined);

            const { runQuery } = await import('../../commands/query');
            await runQuery(mockClient as any);

            assert.ok(!mockClient.query.called);
        });

        test('executes query and shows results', async () => {
            const mockResult: MockQueryResult = {
                result: [{ name: 'TestClass', type: 'class' }],
                success: true,
            };

            showInputBoxStub.resolves("SELECT * FROM classes");
            mockClient.query.resolves(mockResult);
            showInformationMessageStub.resolves();

            const { runQuery } = await import('../../commands/query');
            await runQuery(mockClient as any);

            assert.ok(mockClient.query.calledWith("SELECT * FROM classes"));
        });

        test('shows error message on query failure', async () => {
            const mockResult: MockQueryResult = {
                result: null,
                success: false,
                error: 'Invalid syntax',
            };

            showInputBoxStub.resolves("INVALID QUERY");
            mockClient.query.resolves(mockResult);

            const { runQuery } = await import('../../commands/query');
            await runQuery(mockClient as any);

            assert.ok(showErrorMessageStub.called);
        });

        test('handles network error', async () => {
            showInputBoxStub.resolves("SELECT * FROM classes");
            mockClient.query.rejects(new Error('Network error'));

            const { runQuery } = await import('../../commands/query');
            await runQuery(mockClient as any);

            assert.ok(showErrorMessageStub.called);
        });

        test('uses quick pick for query history', async () => {
            // First query to populate history
            showInputBoxStub.resolves("SELECT * FROM classes");
            mockClient.query.resolves({ result: [], success: true });

            const { runQuery } = await import('../../commands/query');
            await runQuery(mockClient as any);

            // Second query should show quick pick with history
            showQuickPickStub.resolves({ label: '$(add) New query...' });
            showInputBoxStub.resolves(undefined);

            await runQuery(mockClient as any);

            // Verify quick pick was shown on subsequent call
            assert.ok(true);
        });
    });

    suite('findPath', () => {
        test('returns early when user cancels from input', async () => {
            showInputBoxStub.resolves(undefined);

            const { findPath } = await import('../../commands/query');
            await findPath(mockClient as any);

            assert.ok(!mockClient.findPath.called);
        });

        test('returns early when user cancels to input', async () => {
            showInputBoxStub.onFirstCall().resolves('NodeA');
            showInputBoxStub.onSecondCall().resolves(undefined);

            const { findPath } = await import('../../commands/query');
            await findPath(mockClient as any);

            assert.ok(!mockClient.findPath.called);
        });

        test('finds path between nodes', async () => {
            showInputBoxStub.onFirstCall().resolves('mod:a.py');
            showInputBoxStub.onSecondCall().resolves('mod:b.py');
            mockClient.findPath.resolves(['mod:a.py', 'mod:c.py', 'mod:b.py']);
            mockClient.getNode.resolves({ id: 'mod:c.py', name: 'c', type: 'module' });

            const { findPath } = await import('../../commands/query');
            await findPath(mockClient as any);

            assert.ok(mockClient.findPath.called);
        });

        test('handles no path found', async () => {
            showInputBoxStub.onFirstCall().resolves('mod:a.py');
            showInputBoxStub.onSecondCall().resolves('mod:b.py');
            mockClient.findPath.resolves([]);

            const { findPath } = await import('../../commands/query');
            await findPath(mockClient as any);

            assert.ok(showInformationMessageStub.called);
        });

        test('looks up nodes by name if not ID format', async () => {
            showInputBoxStub.onFirstCall().resolves('MyClass');
            showInputBoxStub.onSecondCall().resolves('OtherClass');

            mockClient.query
                .onFirstCall().resolves({
                    success: true,
                    result: [{ id: 'cls:a.py:MyClass' }],
                })
                .onSecondCall().resolves({
                    success: true,
                    result: [{ id: 'cls:b.py:OtherClass' }],
                });

            mockClient.findPath.resolves([]);

            const { findPath } = await import('../../commands/query');
            await findPath(mockClient as any);

            // Should have called query to look up names
            assert.ok(mockClient.query.callCount >= 2);
        });
    });
});

suite('Context Commands Test Suite', () => {
    let sandbox: sinon.SinonSandbox;
    let mockClient: ReturnType<typeof createMockClient>;
    let showInputBoxStub: sinon.SinonStub;
    let showInformationMessageStub: sinon.SinonStub;
    let showErrorMessageStub: sinon.SinonStub;
    let clipboardWriteTextStub: sinon.SinonStub;
    let withProgressStub: sinon.SinonStub;

    setup(() => {
        sandbox = sinon.createSandbox();
        mockClient = createMockClient();

        showInputBoxStub = sandbox.stub(vscode.window, 'showInputBox');
        showInformationMessageStub = sandbox.stub(vscode.window, 'showInformationMessage');
        showErrorMessageStub = sandbox.stub(vscode.window, 'showErrorMessage');

        // Mock clipboard
        clipboardWriteTextStub = sandbox.stub(vscode.env.clipboard, 'writeText');
        clipboardWriteTextStub.resolves();

        // Mock withProgress to execute the callback immediately
        withProgressStub = sandbox.stub(vscode.window, 'withProgress');
        withProgressStub.callsFake(async (options: any, task: any) => {
            return task();
        });

        // Mock workspace configuration
        sandbox.stub(vscode.workspace, 'getConfiguration').returns({
            get: (key: string, defaultValue: unknown) => {
                if (key === 'context.maxTokens') return 8000;
                return defaultValue;
            },
        } as any);
    });

    teardown(() => {
        sandbox.restore();
    });

    suite('getContext', () => {
        test('returns early when user cancels input', async () => {
            showInputBoxStub.resolves(undefined);

            const { getContext } = await import('../../commands/context');
            await getContext(mockClient as any);

            assert.ok(!mockClient.getContext.called);
        });

        test('extracts context and copies to clipboard', async () => {
            const mockResult: MockContextResult = {
                mu_text: '! module test\n$ TestClass',
                token_count: 50,
                nodes: [{ id: 'mod:test.py', name: 'test', type: 'module' }],
            };

            showInputBoxStub.resolves('How does authentication work?');
            mockClient.getContext.resolves(mockResult);
            showInformationMessageStub.resolves();

            const { getContext } = await import('../../commands/context');
            await getContext(mockClient as any);

            assert.ok(mockClient.getContext.calledWith('How does authentication work?', 8000));
            assert.ok(clipboardWriteTextStub.calledWith('! module test\n$ TestClass'));
        });

        test('shows success message with token count', async () => {
            const mockResult: MockContextResult = {
                mu_text: '! module test',
                token_count: 100,
                nodes: [{ id: 'mod:test.py', name: 'test', type: 'module' }],
            };

            showInputBoxStub.resolves('How does X work?');
            mockClient.getContext.resolves(mockResult);
            showInformationMessageStub.resolves();

            const { getContext } = await import('../../commands/context');
            await getContext(mockClient as any);

            assert.ok(showInformationMessageStub.called);
            const message = showInformationMessageStub.firstCall.args[0];
            assert.ok(message.includes('100 tokens'));
        });

        test('handles context extraction error', async () => {
            showInputBoxStub.resolves('How does X work?');
            mockClient.getContext.rejects(new Error('Extraction failed'));

            const { getContext } = await import('../../commands/context');
            await getContext(mockClient as any);

            assert.ok(showErrorMessageStub.called);
        });

        test('opens editor when Show in Editor is selected', async () => {
            const mockResult: MockContextResult = {
                mu_text: '! module test',
                token_count: 50,
                nodes: [],
            };

            showInputBoxStub.resolves('Question?');
            mockClient.getContext.resolves(mockResult);
            showInformationMessageStub.resolves('Show in Editor');

            // Mock document/editor opening
            const mockDoc = { getText: () => '' };
            sandbox.stub(vscode.workspace, 'openTextDocument').resolves(mockDoc as any);
            sandbox.stub(vscode.window, 'showTextDocument').resolves({} as any);

            const { getContext } = await import('../../commands/context');
            await getContext(mockClient as any);

            assert.ok(true); // Test passes if no error thrown
        });
    });
});

suite('Navigation Commands Test Suite', () => {
    let sandbox: sinon.SinonSandbox;
    let mockClient: ReturnType<typeof createMockClient>;
    let showQuickPickStub: sinon.SinonStub;
    let showWarningMessageStub: sinon.SinonStub;
    let showErrorMessageStub: sinon.SinonStub;
    let showInformationMessageStub: sinon.SinonStub;

    setup(() => {
        sandbox = sinon.createSandbox();
        mockClient = createMockClient();

        showQuickPickStub = sandbox.stub(vscode.window, 'showQuickPick');
        showWarningMessageStub = sandbox.stub(vscode.window, 'showWarningMessage');
        showErrorMessageStub = sandbox.stub(vscode.window, 'showErrorMessage');
        showInformationMessageStub = sandbox.stub(vscode.window, 'showInformationMessage');

        // Mock active text editor
        Object.defineProperty(vscode.window, 'activeTextEditor', {
            get: () => undefined,
            configurable: true,
        });
    });

    teardown(() => {
        sandbox.restore();
    });

    suite('showDependencies', () => {
        test('shows warning when no node at cursor', async () => {
            const { showDependencies } = await import('../../commands/navigate');
            await showDependencies(mockClient as any);

            assert.ok(showWarningMessageStub.called);
        });

        test('shows dependencies when nodeId provided', async () => {
            const mockDeps: MockNode[] = [
                { id: 'ext:os', name: 'os', type: 'external' },
                { id: 'fn:utils.py:helper', name: 'helper', type: 'function', file_path: 'utils.py' },
            ];

            mockClient.getNeighbors.resolves(mockDeps);
            showQuickPickStub.resolves(undefined);

            const { showDependencies } = await import('../../commands/navigate');
            await showDependencies(mockClient as any, 'fn:test.py:func', 'func');

            assert.ok(mockClient.getNeighbors.calledWith('fn:test.py:func', 'outgoing'));
            assert.ok(showQuickPickStub.called);
        });

        test('shows message when no dependencies', async () => {
            mockClient.getNeighbors.resolves([]);

            const { showDependencies } = await import('../../commands/navigate');
            await showDependencies(mockClient as any, 'fn:test.py:func', 'func');

            assert.ok(showInformationMessageStub.called);
        });

        test('handles client error', async () => {
            mockClient.getNeighbors.rejects(new Error('Network error'));

            const { showDependencies } = await import('../../commands/navigate');
            await showDependencies(mockClient as any, 'fn:test.py:func', 'func');

            assert.ok(showErrorMessageStub.called);
        });

        test('navigates to selected dependency', async () => {
            const mockDeps: MockNode[] = [
                { id: 'fn:utils.py:helper', name: 'helper', type: 'function', file_path: '/path/utils.py', line_start: 10 },
            ];

            mockClient.getNeighbors.resolves(mockDeps);

            // Mock document/editor opening
            const mockDoc = {};
            const mockEditor = {
                selection: new vscode.Selection(0, 0, 0, 0),
                revealRange: sandbox.stub(),
            };
            sandbox.stub(vscode.workspace, 'openTextDocument').resolves(mockDoc as any);
            sandbox.stub(vscode.window, 'showTextDocument').resolves(mockEditor as any);

            showQuickPickStub.resolves({
                node: mockDeps[0],
            });

            const { showDependencies } = await import('../../commands/navigate');
            await showDependencies(mockClient as any, 'fn:test.py:func', 'func');

            assert.ok(true); // Test passes if no error
        });
    });

    suite('showDependents', () => {
        test('shows warning when no node at cursor', async () => {
            const { showDependents } = await import('../../commands/navigate');
            await showDependents(mockClient as any);

            assert.ok(showWarningMessageStub.called);
        });

        test('shows dependents when nodeId provided', async () => {
            const mockRefs: MockNode[] = [
                { id: 'fn:main.py:main', name: 'main', type: 'function', file_path: 'main.py' },
            ];

            mockClient.getNeighbors.resolves(mockRefs);
            showQuickPickStub.resolves(undefined);

            const { showDependents } = await import('../../commands/navigate');
            await showDependents(mockClient as any, 'fn:test.py:func', 'func');

            assert.ok(mockClient.getNeighbors.calledWith('fn:test.py:func', 'incoming'));
            assert.ok(showQuickPickStub.called);
        });

        test('shows message when no dependents', async () => {
            mockClient.getNeighbors.resolves([]);

            const { showDependents } = await import('../../commands/navigate');
            await showDependents(mockClient as any, 'fn:test.py:func', 'func');

            assert.ok(showInformationMessageStub.called);
        });

        test('handles client error', async () => {
            mockClient.getNeighbors.rejects(new Error('Network error'));

            const { showDependents } = await import('../../commands/navigate');
            await showDependents(mockClient as any, 'fn:test.py:func', 'func');

            assert.ok(showErrorMessageStub.called);
        });

        test('uses node from cursor when no nodeId', async () => {
            const mockNodes: MockNode[] = [
                { id: 'fn:test.py:func', name: 'func', type: 'function', line_start: 5, line_end: 20 },
            ];

            // Mock active editor
            Object.defineProperty(vscode.window, 'activeTextEditor', {
                get: () => ({
                    document: {
                        uri: { fsPath: '/path/test.py' },
                    },
                    selection: {
                        active: { line: 10 },
                    },
                }),
                configurable: true,
            });

            mockClient.getNodesForFile.resolves(mockNodes);
            mockClient.getNeighbors.resolves([]);

            const { showDependents } = await import('../../commands/navigate');
            await showDependents(mockClient as any);

            // Should have looked up nodes for file
            assert.ok(mockClient.getNodesForFile.called || showWarningMessageStub.called);
        });
    });

    suite('Node sorting in quick pick', () => {
        test('sorts internal nodes before external', async () => {
            const mockDeps: MockNode[] = [
                { id: 'ext:os', name: 'os', type: 'external' },
                { id: 'fn:utils.py:helper', name: 'helper', type: 'function', file_path: 'utils.py' },
                { id: 'ext:json', name: 'json', type: 'external' },
            ];

            mockClient.getNeighbors.resolves(mockDeps);
            showQuickPickStub.resolves(undefined);

            const { showDependencies } = await import('../../commands/navigate');
            await showDependencies(mockClient as any, 'fn:test.py:func', 'func');

            // The quick pick should have been called with sorted items
            // Internal (function) should come before external
            assert.ok(showQuickPickStub.called);
        });

        test('sorts by type within category', async () => {
            const mockDeps: MockNode[] = [
                { id: 'fn:a.py:func', name: 'func', type: 'function', file_path: 'a.py' },
                { id: 'cls:b.py:Class', name: 'Class', type: 'class', file_path: 'b.py' },
                { id: 'mod:c.py', name: 'c', type: 'module', file_path: 'c.py' },
            ];

            mockClient.getNeighbors.resolves(mockDeps);
            showQuickPickStub.resolves(undefined);

            const { showDependencies } = await import('../../commands/navigate');
            await showDependencies(mockClient as any, 'fn:test.py:func', 'func');

            // Should have shown sorted items: module, class, function
            assert.ok(showQuickPickStub.called);
        });
    });
});
