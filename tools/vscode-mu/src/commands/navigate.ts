/**
 * Navigation Commands
 *
 * Commands for navigating dependencies and dependents in the code graph.
 */

import * as vscode from 'vscode';
import { MUClient, Node } from '../client';

/**
 * Navigate to a node's source location
 */
async function navigateToNode(node: Node): Promise<void> {
    if (!node.file_path) {
        vscode.window.showInformationMessage(
            `${node.name} is an external dependency and has no source location.`
        );
        return;
    }

    try {
        const uri = vscode.Uri.file(node.file_path);
        const doc = await vscode.workspace.openTextDocument(uri);
        const editor = await vscode.window.showTextDocument(doc);

        if (node.line_start) {
            const line = node.line_start - 1;
            const range = new vscode.Range(line, 0, line, 0);
            editor.selection = new vscode.Selection(range.start, range.start);
            editor.revealRange(range, vscode.TextEditorRevealType.InCenter);
        }
    } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        vscode.window.showErrorMessage(`Failed to open file: ${message}`);
    }
}

/**
 * Show quick pick for a list of nodes
 */
async function showNodePicker(
    nodes: Node[],
    title: string,
    emptyMessage: string
): Promise<void> {
    if (nodes.length === 0) {
        vscode.window.showInformationMessage(emptyMessage);
        return;
    }

    // Sort: internal first, then by type, then by name
    const sorted = [...nodes].sort((a, b) => {
        // External dependencies last
        if (a.type === 'external' && b.type !== 'external') return 1;
        if (a.type !== 'external' && b.type === 'external') return -1;

        // Then by type: modules, classes, functions
        const typeOrder = { module: 0, class: 1, function: 2, external: 3 };
        const aOrder = typeOrder[a.type] ?? 4;
        const bOrder = typeOrder[b.type] ?? 4;
        if (aOrder !== bOrder) return aOrder - bOrder;

        // Then by name
        return a.name.localeCompare(b.name);
    });

    const items = sorted.map((n) => ({
        label: getNodeIcon(n.type) + ' ' + n.name,
        description: n.qualified_name !== n.name ? n.qualified_name : undefined,
        detail: n.file_path
            ? `${n.file_path}${n.line_start ? `:${n.line_start}` : ''}`
            : n.type === 'external'
              ? '(external dependency)'
              : undefined,
        node: n,
    }));

    const selected = await vscode.window.showQuickPick(items, {
        title,
        placeHolder: 'Select to navigate to source',
        matchOnDescription: true,
        matchOnDetail: true,
    });

    if (selected) {
        await navigateToNode(selected.node);
    }
}

function getNodeIcon(type: string): string {
    switch (type) {
        case 'module':
            return '$(file-code)';
        case 'class':
            return '$(symbol-class)';
        case 'function':
            return '$(symbol-method)';
        case 'external':
            return '$(package)';
        default:
            return '$(circle-outline)';
    }
}

/**
 * Get node at current cursor position
 */
async function getNodeAtCursor(client: MUClient): Promise<Node | undefined> {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        return undefined;
    }

    const filePath = editor.document.uri.fsPath;
    const line = editor.selection.active.line + 1; // 1-based

    try {
        const nodes = await client.getNodesForFile(filePath);
        // Find the most specific node containing this line
        // (prefer smaller spans, i.e., functions over modules)
        const containingNodes = nodes.filter(
            (n) => n.line_start && n.line_end && line >= n.line_start && line <= n.line_end
        );

        if (containingNodes.length === 0) {
            return undefined;
        }

        // Sort by span size (smallest first)
        containingNodes.sort((a, b) => {
            const aSpan = (a.line_end || 0) - (a.line_start || 0);
            const bSpan = (b.line_end || 0) - (b.line_start || 0);
            return aSpan - bSpan;
        });

        return containingNodes[0];
    } catch {
        return undefined;
    }
}

/**
 * Show dependencies for a node
 */
export async function showDependencies(
    client: MUClient,
    nodeId?: string,
    nodeName?: string
): Promise<void> {
    // If no nodeId provided, get node at cursor
    if (!nodeId) {
        const node = await getNodeAtCursor(client);
        if (!node) {
            vscode.window.showWarningMessage(
                'MU: No function or class at cursor position.'
            );
            return;
        }
        nodeId = node.id;
        nodeName = node.name;
    }

    try {
        const deps = await client.getNeighbors(nodeId, 'outgoing');
        await showNodePicker(
            deps,
            `Dependencies of ${nodeName || nodeId}`,
            `${nodeName || nodeId} has no dependencies.`
        );
    } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        vscode.window.showErrorMessage(`MU: Failed to get dependencies - ${message}`);
    }
}

/**
 * Show dependents for a node
 */
export async function showDependents(
    client: MUClient,
    nodeId?: string,
    nodeName?: string
): Promise<void> {
    // If no nodeId provided, get node at cursor
    if (!nodeId) {
        const node = await getNodeAtCursor(client);
        if (!node) {
            vscode.window.showWarningMessage(
                'MU: No function or class at cursor position.'
            );
            return;
        }
        nodeId = node.id;
        nodeName = node.name;
    }

    try {
        const dependents = await client.getNeighbors(nodeId, 'incoming');
        await showNodePicker(
            dependents,
            `Dependents of ${nodeName || nodeId}`,
            `${nodeName || nodeId} has no dependents.`
        );
    } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        vscode.window.showErrorMessage(`MU: Failed to get dependents - ${message}`);
    }
}
