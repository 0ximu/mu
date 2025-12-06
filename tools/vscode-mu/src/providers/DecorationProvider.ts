/**
 * Decoration Provider
 *
 * Shows complexity badges at the end of function/class definition lines.
 * Color-coded based on configurable thresholds.
 */

import * as vscode from 'vscode';
import { MUClient, Node } from '../client';

/** Cached node data for a file */
interface FileCache {
    nodes: Node[];
    version: number;
}

/**
 * Provides inline complexity decorations
 */
export class DecorationProvider implements vscode.Disposable {
    private readonly infoDecoration: vscode.TextEditorDecorationType;
    private readonly warningDecoration: vscode.TextEditorDecorationType;
    private readonly errorDecoration: vscode.TextEditorDecorationType;

    private readonly cache = new Map<string, FileCache>();
    private readonly disposables: vscode.Disposable[] = [];

    constructor(private readonly client: MUClient) {
        // Create decoration types with different colors
        this.infoDecoration = vscode.window.createTextEditorDecorationType({
            after: {
                margin: '0 0 0 1em',
                color: new vscode.ThemeColor('editorInfo.foreground'),
                fontStyle: 'italic',
            },
            isWholeLine: false,
        });

        this.warningDecoration = vscode.window.createTextEditorDecorationType({
            after: {
                margin: '0 0 0 1em',
                color: new vscode.ThemeColor('editorWarning.foreground'),
                fontStyle: 'italic',
            },
            isWholeLine: false,
        });

        this.errorDecoration = vscode.window.createTextEditorDecorationType({
            after: {
                margin: '0 0 0 1em',
                color: new vscode.ThemeColor('editorError.foreground'),
                fontWeight: 'bold',
            },
            isWholeLine: false,
        });

        // Listen for active editor changes
        this.disposables.push(
            vscode.window.onDidChangeActiveTextEditor((editor) => {
                if (editor) {
                    this.updateDecorations(editor);
                }
            })
        );

        // Listen for document saves
        this.disposables.push(
            vscode.workspace.onDidSaveTextDocument((doc) => {
                // Clear cache for this file and update if visible
                this.cache.delete(doc.uri.fsPath);
                const editor = vscode.window.visibleTextEditors.find(
                    (e) => e.document.uri.fsPath === doc.uri.fsPath
                );
                if (editor) {
                    this.updateDecorations(editor);
                }
            })
        );

        // Listen for configuration changes
        this.disposables.push(
            vscode.workspace.onDidChangeConfiguration((e) => {
                if (
                    e.affectsConfiguration('mu.badges') ||
                    e.affectsConfiguration('mu.complexity')
                ) {
                    // Refresh all visible editors
                    for (const editor of vscode.window.visibleTextEditors) {
                        this.updateDecorations(editor);
                    }
                }
            })
        );

        // Initial update for active editor
        if (vscode.window.activeTextEditor) {
            this.updateDecorations(vscode.window.activeTextEditor);
        }
    }

    /**
     * Clear all decorations from an editor
     */
    clearDecorations(editor: vscode.TextEditor): void {
        editor.setDecorations(this.infoDecoration, []);
        editor.setDecorations(this.warningDecoration, []);
        editor.setDecorations(this.errorDecoration, []);
    }

    /**
     * Update decorations for an editor
     */
    async updateDecorations(editor: vscode.TextEditor): Promise<void> {
        const config = vscode.workspace.getConfiguration('mu');

        // Check if badges are enabled
        if (!config.get<boolean>('badges.enabled', true)) {
            this.clearDecorations(editor);
            return;
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

        if (!supportedLanguages.includes(editor.document.languageId)) {
            return;
        }

        const filePath = editor.document.uri.fsPath;
        const documentVersion = editor.document.version;

        // Check cache
        const cached = this.cache.get(filePath);
        let nodes: Node[];

        if (cached && cached.version === documentVersion) {
            nodes = cached.nodes;
        } else {
            try {
                nodes = await this.client.getNodesForFile(filePath);
                this.cache.set(filePath, { nodes, version: documentVersion });
            } catch (err) {
                // Daemon not available, clear decorations
                this.clearDecorations(editor);
                return;
            }
        }

        // Get thresholds
        const warningThreshold = config.get<number>('complexity.warningThreshold', 200);
        const errorThreshold = config.get<number>('complexity.errorThreshold', 500);

        // Group decorations by severity
        const infoRanges: vscode.DecorationOptions[] = [];
        const warningRanges: vscode.DecorationOptions[] = [];
        const errorRanges: vscode.DecorationOptions[] = [];

        for (const node of nodes) {
            if (!node.line_start || !node.complexity || node.complexity === 0) {
                continue;
            }

            const line = node.line_start - 1; // VS Code uses 0-based lines
            if (line < 0 || line >= editor.document.lineCount) {
                continue;
            }

            const lineText = editor.document.lineAt(line);
            const range = new vscode.Range(
                line,
                lineText.text.length,
                line,
                lineText.text.length
            );

            const decoration: vscode.DecorationOptions = {
                range,
                renderOptions: {
                    after: {
                        contentText: ` [C:${node.complexity}]`,
                    },
                },
            };

            if (node.complexity >= errorThreshold) {
                errorRanges.push(decoration);
            } else if (node.complexity >= warningThreshold) {
                warningRanges.push(decoration);
            } else if (node.complexity > 0) {
                infoRanges.push(decoration);
            }
        }

        // Apply decorations
        editor.setDecorations(this.infoDecoration, infoRanges);
        editor.setDecorations(this.warningDecoration, warningRanges);
        editor.setDecorations(this.errorDecoration, errorRanges);
    }

    /**
     * Refresh decorations for all visible editors
     */
    refresh(): void {
        this.cache.clear();
        for (const editor of vscode.window.visibleTextEditors) {
            this.updateDecorations(editor);
        }
    }

    dispose(): void {
        this.infoDecoration.dispose();
        this.warningDecoration.dispose();
        this.errorDecoration.dispose();
        for (const d of this.disposables) {
            d.dispose();
        }
    }
}
