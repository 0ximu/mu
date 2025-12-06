/**
 * MU VS Code Extension
 *
 * Provides IDE integration for MU (Machine Understanding) semantic compression.
 *
 * Features:
 * - MU language syntax highlighting
 * - Code graph explorer in sidebar
 * - Complexity badges on functions
 * - Dependency CodeLens
 * - MUQL queries from command palette
 * - Smart context extraction for AI assistants
 * - Contract violation diagnostics
 */

import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';

import { MUClient } from './client';
import {
    ExplorerProvider,
    DecorationProvider,
    CodeLensProvider,
    DiagnosticsProvider,
} from './providers';
import {
    runQuery,
    findPath,
    getContext,
    getContextForSelection,
    showDependencies,
    showDependents,
    disposeQueryChannel,
} from './commands';

let outputChannel: vscode.OutputChannel;
let client: MUClient;
let statusBarItem: vscode.StatusBarItem;

// Providers
let decorationProvider: DecorationProvider;
let codeLensProvider: CodeLensProvider;
let diagnosticsProvider: DiagnosticsProvider;
let modulesProvider: ExplorerProvider;
let classesProvider: ExplorerProvider;
let functionsProvider: ExplorerProvider;
let hotspotsProvider: ExplorerProvider;

export async function activate(context: vscode.ExtensionContext) {
    outputChannel = vscode.window.createOutputChannel('MU');
    outputChannel.appendLine('MU extension activating...');

    // Initialize daemon client
    client = new MUClient();

    // Create status bar item
    statusBarItem = vscode.window.createStatusBarItem(
        vscode.StatusBarAlignment.Right,
        100
    );
    statusBarItem.command = 'mu.reconnect';
    context.subscriptions.push(statusBarItem);

    // Listen for connection state changes
    client.onConnectionStateChange((state) => {
        updateStatusBar(state);
    });

    // Check daemon status and connect WebSocket
    await checkDaemonAndConnect();

    // Register tree view providers
    modulesProvider = new ExplorerProvider(client, 'modules');
    classesProvider = new ExplorerProvider(client, 'classes');
    functionsProvider = new ExplorerProvider(client, 'functions');
    hotspotsProvider = new ExplorerProvider(client, 'hotspots');

    context.subscriptions.push(
        vscode.window.registerTreeDataProvider('mu.modules', modulesProvider),
        vscode.window.registerTreeDataProvider('mu.classes', classesProvider),
        vscode.window.registerTreeDataProvider('mu.functions', functionsProvider),
        vscode.window.registerTreeDataProvider('mu.hotspots', hotspotsProvider)
    );

    // Register decoration provider
    decorationProvider = new DecorationProvider(client);
    context.subscriptions.push(decorationProvider);

    // Register CodeLens provider
    codeLensProvider = new CodeLensProvider(client);
    const supportedLanguages = [
        'python',
        'typescript',
        'javascript',
        'typescriptreact',
        'javascriptreact',
        'go',
        'java',
        'rust',
        'csharp',
    ];

    context.subscriptions.push(
        vscode.languages.registerCodeLensProvider(
            supportedLanguages.map((lang) => ({ language: lang })),
            codeLensProvider
        )
    );

    // Register diagnostics provider
    diagnosticsProvider = new DiagnosticsProvider(client);
    context.subscriptions.push(diagnosticsProvider);

    // Subscribe to WebSocket updates to refresh providers
    context.subscriptions.push(
        client.onGraphUpdate(() => {
            modulesProvider.refresh();
            classesProvider.refresh();
            functionsProvider.refresh();
            hotspotsProvider.refresh();
            decorationProvider.refresh();
            codeLensProvider.refresh();
            diagnosticsProvider.refresh();
        })
    );

    // Register hover provider for MU files
    context.subscriptions.push(
        vscode.languages.registerHoverProvider('mu', new MuHoverProvider())
    );

    // Register all commands
    context.subscriptions.push(
        // Existing CLI commands
        vscode.commands.registerCommand('mu.compress', compressCommand),
        vscode.commands.registerCommand('mu.compressFile', compressFileCommand),
        vscode.commands.registerCommand('mu.compressWorkspace', compressWorkspaceCommand),
        vscode.commands.registerCommand('mu.preview', previewCommand),
        vscode.commands.registerCommand('mu.diff', diffCommand),

        // New daemon-based commands
        vscode.commands.registerCommand('mu.query', () => runQuery(client)),
        vscode.commands.registerCommand('mu.findPath', () => findPath(client)),
        vscode.commands.registerCommand('mu.getContext', () => getContext(client)),
        vscode.commands.registerCommand('mu.getContextForSelection', () =>
            getContextForSelection(client)
        ),
        vscode.commands.registerCommand('mu.showDependencies', (nodeId?: string, nodeName?: string) =>
            showDependencies(client, nodeId, nodeName)
        ),
        vscode.commands.registerCommand('mu.showDependents', (nodeId?: string, nodeName?: string) =>
            showDependents(client, nodeId, nodeName)
        ),

        // Utility commands
        vscode.commands.registerCommand('mu.refresh', () => {
            modulesProvider.refresh();
            classesProvider.refresh();
            functionsProvider.refresh();
            hotspotsProvider.refresh();
            decorationProvider.refresh();
            codeLensProvider.refresh();
        }),
        vscode.commands.registerCommand('mu.reconnect', () => checkDaemonAndConnect()),
        vscode.commands.registerCommand('mu.toggleBadges', () => {
            const config = vscode.workspace.getConfiguration('mu');
            const current = config.get<boolean>('badges.enabled', true);
            config.update('badges.enabled', !current, vscode.ConfigurationTarget.Workspace);
        }),
        vscode.commands.registerCommand('mu.refreshDiagnostics', () => {
            diagnosticsProvider.refresh();
        }),
        vscode.commands.registerCommand('mu.openVisualization', openVisualization)
    );

    outputChannel.appendLine('MU extension activated');
}

export function deactivate() {
    if (client) {
        client.dispose();
    }
    disposeQueryChannel();
    if (outputChannel) {
        outputChannel.dispose();
    }
}

/**
 * Check if daemon is running and connect WebSocket
 */
async function checkDaemonAndConnect(): Promise<void> {
    updateStatusBar('connecting');

    try {
        const status = await client.getStatus();
        outputChannel.appendLine(`MU: Connected to daemon at ${status.mubase_path}`);
        outputChannel.appendLine(`MU: Graph has ${status.stats.nodes} nodes, ${status.stats.edges} edges`);

        // Connect WebSocket for live updates
        client.connectWebSocket();

        vscode.window.showInformationMessage(
            `MU: Connected to daemon (${status.stats.nodes} nodes)`
        );
    } catch (err) {
        outputChannel.appendLine('MU: Daemon not running');
        updateStatusBar('disconnected');

        vscode.window
            .showWarningMessage(
                'MU: Daemon not running. Start with `mu daemon start .`',
                'Start Daemon'
            )
            .then((selection) => {
                if (selection === 'Start Daemon') {
                    startDaemon();
                }
            });
    }
}

/**
 * Update status bar based on connection state
 */
function updateStatusBar(state: string): void {
    switch (state) {
        case 'connected':
            statusBarItem.text = '$(check) MU';
            statusBarItem.tooltip = 'MU: Connected to daemon (click to reconnect)';
            statusBarItem.backgroundColor = undefined;
            break;
        case 'connecting':
            statusBarItem.text = '$(sync~spin) MU';
            statusBarItem.tooltip = 'MU: Connecting to daemon...';
            statusBarItem.backgroundColor = undefined;
            break;
        case 'disconnected':
        default:
            statusBarItem.text = '$(warning) MU';
            statusBarItem.tooltip = 'MU: Disconnected (click to reconnect)';
            statusBarItem.backgroundColor = new vscode.ThemeColor(
                'statusBarItem.warningBackground'
            );
            break;
    }
    statusBarItem.show();
}

/**
 * Start the MU daemon
 */
async function startDaemon(): Promise<void> {
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (!workspaceFolders || workspaceFolders.length === 0) {
        vscode.window.showWarningMessage('MU: No workspace folder open');
        return;
    }

    const cwd = workspaceFolders[0].uri.fsPath;
    const config = vscode.workspace.getConfiguration('mu');
    const muPath = config.get<string>('executablePath', 'mu');

    try {
        // Start daemon in background
        const child = cp.spawn(muPath, ['daemon', 'start', '.'], {
            cwd,
            detached: true,
            stdio: 'ignore',
        });
        child.unref();

        // Wait a moment for daemon to start
        await new Promise((resolve) => setTimeout(resolve, 2000));

        // Try to connect
        await checkDaemonAndConnect();
    } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        vscode.window.showErrorMessage(`MU: Failed to start daemon - ${message}`);
    }
}

/**
 * Open the MU visualization in browser
 */
function openVisualization(): void {
    const config = vscode.workspace.getConfiguration('mu');
    const daemonUrl = config.get<string>('daemonUrl', 'http://localhost:8765');

    // Assume mu-viz is served on the same host
    const vizUrl = daemonUrl.replace(/:\d+$/, ':3000');

    vscode.env.openExternal(vscode.Uri.parse(vizUrl));
}

// =============================================================================
// CLI-based commands (existing functionality)
// =============================================================================

/**
 * Run mu compress on a selected directory
 */
async function compressCommand() {
    const folderUri = await vscode.window.showOpenDialog({
        canSelectFiles: false,
        canSelectFolders: true,
        canSelectMany: false,
        openLabel: 'Select folder to compress',
    });

    if (!folderUri || folderUri.length === 0) {
        return;
    }

    const folder = folderUri[0].fsPath;
    await runMuCompress(folder);
}

/**
 * Run mu compress on the current file's directory
 */
async function compressFileCommand() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showWarningMessage('No active file');
        return;
    }

    const filePath = editor.document.uri.fsPath;
    const dirPath = path.dirname(filePath);
    await runMuCompress(dirPath);
}

/**
 * Run mu compress on the workspace root
 */
async function compressWorkspaceCommand() {
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (!workspaceFolders || workspaceFolders.length === 0) {
        vscode.window.showWarningMessage('No workspace folder open');
        return;
    }

    const folder = workspaceFolders[0].uri.fsPath;
    await runMuCompress(folder);
}

/**
 * Preview MU output for the current file or directory
 */
async function previewCommand() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showWarningMessage('No active file');
        return;
    }

    const filePath = editor.document.uri.fsPath;
    const dirPath = path.dirname(filePath);

    const result = await runMuCommand(['compress', dirPath, '--format', 'mu']);
    if (result) {
        const doc = await vscode.workspace.openTextDocument({
            content: result,
            language: 'mu',
        });
        await vscode.window.showTextDocument(doc, vscode.ViewColumn.Beside);
    }
}

/**
 * Run mu diff between two git refs
 */
async function diffCommand() {
    const baseRef = await vscode.window.showInputBox({
        prompt: 'Enter base git ref (e.g., main, HEAD~1)',
        value: 'main',
    });

    if (!baseRef) {
        return;
    }

    const headRef = await vscode.window.showInputBox({
        prompt: 'Enter head git ref (e.g., HEAD, feature-branch)',
        value: 'HEAD',
    });

    if (!headRef) {
        return;
    }

    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (!workspaceFolders || workspaceFolders.length === 0) {
        vscode.window.showWarningMessage('No workspace folder open');
        return;
    }

    const cwd = workspaceFolders[0].uri.fsPath;
    const result = await runMuCommand(
        ['diff', baseRef, headRef, '--format', 'markdown'],
        cwd
    );

    if (result) {
        const doc = await vscode.workspace.openTextDocument({
            content: result,
            language: 'markdown',
        });
        await vscode.window.showTextDocument(doc, vscode.ViewColumn.Beside);
    }
}

/**
 * Run mu compress and handle output
 */
async function runMuCompress(folder: string) {
    const outputPath = await vscode.window.showInputBox({
        prompt: 'Output file path (leave empty for stdout)',
        placeHolder: 'output.mu',
    });

    const args = ['compress', folder];
    if (outputPath) {
        args.push('-o', outputPath);
    }

    const result = await runMuCommand(args);

    if (result) {
        if (outputPath) {
            vscode.window.showInformationMessage(`MU output saved to ${outputPath}`);
            const doc = await vscode.workspace.openTextDocument(outputPath);
            await vscode.window.showTextDocument(doc);
        } else {
            const doc = await vscode.workspace.openTextDocument({
                content: result,
                language: 'mu',
            });
            await vscode.window.showTextDocument(doc, vscode.ViewColumn.Beside);
        }
    }
}

/**
 * Execute mu CLI command
 */
function runMuCommand(args: string[], cwd?: string): Promise<string | null> {
    return new Promise((resolve) => {
        const config = vscode.workspace.getConfiguration('mu');
        const muPath = config.get<string>('executablePath', 'mu');

        outputChannel.appendLine(`Running: ${muPath} ${args.join(' ')}`);

        const options: cp.SpawnOptions = {
            cwd: cwd || vscode.workspace.workspaceFolders?.[0]?.uri.fsPath,
            env: { ...process.env },
        };

        const child = cp.spawn(muPath, args, options);
        let stdout = '';
        let stderr = '';

        child.stdout?.on('data', (data) => {
            stdout += data.toString();
        });

        child.stderr?.on('data', (data) => {
            stderr += data.toString();
            outputChannel.appendLine(data.toString());
        });

        child.on('close', (code) => {
            if (code === 0) {
                outputChannel.appendLine('Command completed successfully');
                resolve(stdout);
            } else {
                outputChannel.appendLine(`Command failed with code ${code}`);
                vscode.window.showErrorMessage(
                    `MU command failed: ${stderr || 'Unknown error'}`
                );
                resolve(null);
            }
        });

        child.on('error', (err) => {
            outputChannel.appendLine(`Error: ${err.message}`);
            vscode.window.showErrorMessage(
                `Failed to run MU: ${err.message}. Is 'mu' installed and in PATH?`
            );
            resolve(null);
        });
    });
}

// =============================================================================
// Hover Provider
// =============================================================================

/**
 * Hover provider for MU files - shows info about sigils
 */
class MuHoverProvider implements vscode.HoverProvider {
    private sigilInfo: Record<string, string> = {
        '!': '**Module/Service** - Defines a module or service boundary',
        '\u00a7': '**Module** (Unicode) - Module namespace declaration',
        '$': '**Entity/Class** - Defines a class or data structure',
        '\u03c4': '**Type** (Unicode) - Type or class definition',
        '#': '**Function/Method** - Function or method signature',
        '\u03bb': '**Lambda/Function** (Unicode) - Function definition',
        '@': '**Metadata/Decorator** - Annotations, decorators, or metadata',
        '?': '**Conditional** - Branch or conditional logic',
        '::': '**Annotation/Invariant** - Guards, constraints, or notes',
        '\u2205': '**Empty** - Stripped or empty marker',
        '->': '**Data Flow** - Return type or data transformation',
        '\u2192': '**Data Flow** (Unicode) - Return type or data transformation',
        '=>': '**State Mutation** - State change or assignment',
        '\u27f9': '**State Mutation** (Unicode) - State change or assignment',
        '|': '**Match/Switch** - Pattern matching branch',
        '~': '**Iteration** - Loop or iteration marker',
        '<': '**Inheritance** - Class extends another',
        '@attrs': '**Attributes** - List of class/struct attributes',
        '@deps': '**Dependencies** - External dependencies list',
    };

    provideHover(
        document: vscode.TextDocument,
        position: vscode.Position
    ): vscode.ProviderResult<vscode.Hover> {
        const line = document.lineAt(position.line).text;
        const wordRange = document.getWordRangeAtPosition(
            position,
            /[@#$!?\u00a7\u03c4\u03bb\u2205\u27f9\u2192]|::|->|=>|@attrs|@deps/
        );

        if (!wordRange) {
            return null;
        }

        const word = document.getText(wordRange);
        const info = this.sigilInfo[word];

        if (info) {
            return new vscode.Hover(new vscode.MarkdownString(info));
        }

        // Check for module definition
        if (line.startsWith('!module ') || line.startsWith('\u00a7')) {
            return new vscode.Hover(
                new vscode.MarkdownString(
                    '**Module Definition** - Top-level namespace boundary'
                )
            );
        }

        return null;
    }
}
