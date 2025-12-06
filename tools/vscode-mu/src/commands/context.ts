/**
 * Context Commands
 *
 * Commands for extracting smart context for AI assistants.
 */

import * as vscode from 'vscode';
import { MUClient } from '../client';

/**
 * Get smart context for a question and copy to clipboard
 */
export async function getContext(client: MUClient): Promise<void> {
    // Get the question
    const question = await vscode.window.showInputBox({
        prompt: 'What do you want to understand?',
        placeHolder: 'e.g., How does authentication work?',
        title: 'Smart Context',
    });

    if (!question) {
        return;
    }

    // Get max tokens from config
    const config = vscode.workspace.getConfiguration('mu');
    const maxTokens = config.get<number>('context.maxTokens', 8000);

    try {
        // Show progress
        await vscode.window.withProgress(
            {
                location: vscode.ProgressLocation.Notification,
                title: 'MU: Extracting context...',
                cancellable: false,
            },
            async () => {
                const result = await client.getContext(question, maxTokens);

                // Copy to clipboard
                await vscode.env.clipboard.writeText(result.mu_text);

                // Show success message with option to view
                const selection = await vscode.window.showInformationMessage(
                    `MU: Context copied! ${result.token_count} tokens, ${result.nodes.length} nodes`,
                    'Show in Editor',
                    'Show Nodes'
                );

                if (selection === 'Show in Editor') {
                    const doc = await vscode.workspace.openTextDocument({
                        content: result.mu_text,
                        language: 'mu',
                    });
                    await vscode.window.showTextDocument(doc, vscode.ViewColumn.Beside);
                } else if (selection === 'Show Nodes') {
                    // Show included nodes in a quick pick
                    const items = result.nodes.map((n) => ({
                        label: n.name,
                        description: `${n.type}${n.complexity ? ` [C:${n.complexity}]` : ''}`,
                        detail: n.file_path
                            ? `${n.file_path}:${n.line_start || '?'}`
                            : 'No file location',
                        node: n,
                    }));

                    const selected = await vscode.window.showQuickPick(items, {
                        title: 'Included Nodes',
                        placeHolder: 'Select to navigate to source',
                    });

                    if (selected?.node.file_path && selected.node.line_start) {
                        const uri = vscode.Uri.file(selected.node.file_path);
                        const doc = await vscode.workspace.openTextDocument(uri);
                        const editor = await vscode.window.showTextDocument(doc);
                        const line = selected.node.line_start - 1;
                        const range = new vscode.Range(line, 0, line, 0);
                        editor.selection = new vscode.Selection(range.start, range.start);
                        editor.revealRange(range, vscode.TextEditorRevealType.InCenter);
                    }
                }
            }
        );
    } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        vscode.window.showErrorMessage(`MU: Context extraction failed - ${message}`);
    }
}

/**
 * Get context based on current selection or function at cursor
 */
export async function getContextForSelection(client: MUClient): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showWarningMessage('MU: No active editor');
        return;
    }

    // Get selected text or current line
    let selection = editor.document.getText(editor.selection);

    if (!selection || selection.trim().length === 0) {
        // No selection - try to find function at cursor
        const line = editor.selection.active.line;
        const filePath = editor.document.uri.fsPath;

        try {
            const nodes = await client.getNodesForFile(filePath);
            const nodeAtLine = nodes.find(
                (n) =>
                    n.line_start &&
                    n.line_end &&
                    line + 1 >= n.line_start &&
                    line + 1 <= n.line_end
            );

            if (nodeAtLine) {
                selection = `Code around ${nodeAtLine.name} in ${filePath}`;
            } else {
                // Use current line content
                selection = editor.document.lineAt(line).text.trim();
            }
        } catch {
            // Fallback to current line
            selection = editor.document.lineAt(line).text.trim();
        }
    }

    if (!selection || selection.trim().length === 0) {
        vscode.window.showWarningMessage(
            'MU: No selection or code at cursor. Please select some code or position cursor in a function.'
        );
        return;
    }

    // Build context question
    const question = `What is the context and dependencies for: ${selection}`;

    // Get max tokens from config
    const config = vscode.workspace.getConfiguration('mu');
    const maxTokens = config.get<number>('context.maxTokens', 8000);

    try {
        await vscode.window.withProgress(
            {
                location: vscode.ProgressLocation.Notification,
                title: 'MU: Extracting context for selection...',
                cancellable: false,
            },
            async () => {
                const result = await client.getContext(question, maxTokens);

                // Copy to clipboard
                await vscode.env.clipboard.writeText(result.mu_text);

                const selection = await vscode.window.showInformationMessage(
                    `MU: Context copied! ${result.token_count} tokens, ${result.nodes.length} nodes`,
                    'Show in Editor'
                );

                if (selection === 'Show in Editor') {
                    const doc = await vscode.workspace.openTextDocument({
                        content: result.mu_text,
                        language: 'mu',
                    });
                    await vscode.window.showTextDocument(doc, vscode.ViewColumn.Beside);
                }
            }
        );
    } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        vscode.window.showErrorMessage(`MU: Context extraction failed - ${message}`);
    }
}
