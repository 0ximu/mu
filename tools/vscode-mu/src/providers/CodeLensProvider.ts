/**
 * CodeLens Provider
 *
 * Shows "X deps, Y refs" above functions and classes.
 * Clicking opens a quick pick to navigate to dependencies.
 */

import * as vscode from 'vscode';
import { MUClient, Node } from '../client';

/** Cached CodeLens data for a file */
interface FileCache {
    lenses: vscode.CodeLens[];
    version: number;
}

/**
 * Provides dependency CodeLens for functions and classes
 */
export class CodeLensProvider implements vscode.CodeLensProvider {
    private _onDidChangeCodeLenses = new vscode.EventEmitter<void>();
    readonly onDidChangeCodeLenses = this._onDidChangeCodeLenses.event;

    private readonly cache = new Map<string, FileCache>();
    private readonly nodeCache = new Map<string, Node[]>();

    constructor(private readonly client: MUClient) {}

    /**
     * Refresh CodeLenses
     */
    refresh(): void {
        this.cache.clear();
        this.nodeCache.clear();
        this._onDidChangeCodeLenses.fire();
    }

    async provideCodeLenses(
        document: vscode.TextDocument,
        token: vscode.CancellationToken
    ): Promise<vscode.CodeLens[]> {
        const config = vscode.workspace.getConfiguration('mu');

        // Check if CodeLens is enabled
        if (!config.get<boolean>('codeLens.enabled', true)) {
            return [];
        }

        // Only apply to supported languages
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

        if (!supportedLanguages.includes(document.languageId)) {
            return [];
        }

        const filePath = document.uri.fsPath;
        const documentVersion = document.version;

        // Check cache
        const cached = this.cache.get(filePath);
        if (cached && cached.version === documentVersion) {
            return cached.lenses;
        }

        // Get nodes for this file
        let nodes: Node[];
        try {
            nodes = await this.client.getNodesForFile(filePath);
            this.nodeCache.set(filePath, nodes);
        } catch (err) {
            // Daemon not available
            return [];
        }

        if (token.isCancellationRequested) {
            return [];
        }

        const lenses: vscode.CodeLens[] = [];

        // Create CodeLens for each node
        for (const node of nodes) {
            if (!node.line_start) {
                continue;
            }

            const line = node.line_start - 1;
            if (line < 0 || line >= document.lineCount) {
                continue;
            }

            const range = new vscode.Range(line, 0, line, 0);

            // Create a placeholder lens that will be resolved later
            const lens = new vscode.CodeLens(range, {
                title: 'Loading...',
                command: 'mu.showDependencies',
                arguments: [node.id],
            });
            (lens as any).nodeId = node.id;
            (lens as any).nodeName = node.name;

            lenses.push(lens);
        }

        // Cache the lenses
        this.cache.set(filePath, { lenses, version: documentVersion });

        return lenses;
    }

    async resolveCodeLens(
        codeLens: vscode.CodeLens,
        token: vscode.CancellationToken
    ): Promise<vscode.CodeLens | null> {
        const nodeId = (codeLens as any).nodeId as string | undefined;
        const nodeName = (codeLens as any).nodeName as string | undefined;

        if (!nodeId) {
            return null;
        }

        try {
            // Get dependency counts
            const [deps, refs] = await Promise.all([
                this.client.getNeighbors(nodeId, 'outgoing'),
                this.client.getNeighbors(nodeId, 'incoming'),
            ]);

            if (token.isCancellationRequested) {
                return null;
            }

            // Filter out external dependencies for display count
            const internalDeps = deps.filter((n) => n.type !== 'external');
            const externalDeps = deps.filter((n) => n.type === 'external');

            let title: string;
            if (externalDeps.length > 0) {
                title = `${internalDeps.length} deps (+${externalDeps.length} ext), ${refs.length} refs`;
            } else {
                title = `${deps.length} deps, ${refs.length} refs`;
            }

            codeLens.command = {
                title,
                command: 'mu.showDependencies',
                arguments: [nodeId, nodeName],
            };

            return codeLens;
        } catch (err) {
            // Daemon error - show basic info
            codeLens.command = {
                title: '? deps, ? refs',
                command: 'mu.showDependencies',
                arguments: [nodeId, nodeName],
            };
            return codeLens;
        }
    }
}
