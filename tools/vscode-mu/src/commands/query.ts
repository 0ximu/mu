/**
 * Query Commands
 *
 * Commands for running MUQL queries and finding paths between nodes.
 */

import * as vscode from 'vscode';
import { MUClient } from '../client';

/** Query history for quick recall */
const queryHistory: string[] = [];
const MAX_HISTORY = 20;

/** Output channel for query results */
let outputChannel: vscode.OutputChannel | undefined;

function getOutputChannel(): vscode.OutputChannel {
    if (!outputChannel) {
        outputChannel = vscode.window.createOutputChannel('MU Query');
    }
    return outputChannel;
}

/**
 * Run a MUQL query from user input
 */
export async function runQuery(client: MUClient): Promise<void> {
    // Show quick pick with history if available
    let query: string | undefined;

    if (queryHistory.length > 0) {
        const historyItems = queryHistory.map((q, i) => ({
            label: q,
            description: i === 0 ? '(most recent)' : '',
        }));

        const selected = await vscode.window.showQuickPick(
            [
                { label: '$(add) New query...', description: 'Enter a new MUQL query' },
                ...historyItems,
            ],
            {
                title: 'MUQL Query',
                placeHolder: 'Select a previous query or enter a new one',
            }
        );

        if (!selected) {
            return;
        }

        if (selected.label === '$(add) New query...') {
            query = await vscode.window.showInputBox({
                prompt: 'Enter MUQL query',
                placeHolder: "SELECT * FROM nodes WHERE type = 'function' AND complexity > 500",
            });
        } else {
            query = selected.label;
        }
    } else {
        query = await vscode.window.showInputBox({
            prompt: 'Enter MUQL query',
            placeHolder: "SELECT * FROM nodes WHERE type = 'function' AND complexity > 500",
            value: queryHistory[0] || '',
        });
    }

    if (!query) {
        return;
    }

    // Add to history
    const existingIndex = queryHistory.indexOf(query);
    if (existingIndex >= 0) {
        queryHistory.splice(existingIndex, 1);
    }
    queryHistory.unshift(query);
    if (queryHistory.length > MAX_HISTORY) {
        queryHistory.pop();
    }

    // Execute query
    const channel = getOutputChannel();
    channel.clear();
    channel.appendLine(`Query: ${query}`);
    channel.appendLine('---');
    channel.show();

    try {
        const startTime = Date.now();
        const result = await client.query(query);
        const elapsed = Date.now() - startTime;

        if (!result.success) {
            channel.appendLine(`Error: ${result.error}`);
            vscode.window.showErrorMessage(`MU Query error: ${result.error}`);
            return;
        }

        // Format and display results
        const resultData = result.result;

        if (Array.isArray(resultData)) {
            channel.appendLine(`Results: ${resultData.length} rows (${elapsed}ms)`);
            channel.appendLine('');

            if (resultData.length === 0) {
                channel.appendLine('(no results)');
            } else {
                // Format as table if objects with consistent keys
                const firstRow = resultData[0];
                if (typeof firstRow === 'object' && firstRow !== null) {
                    const keys = Object.keys(firstRow as Record<string, unknown>);
                    channel.appendLine(keys.join('\t'));
                    channel.appendLine('-'.repeat(keys.length * 12));

                    for (const row of resultData) {
                        const values = keys.map((k) => {
                            const v = (row as Record<string, unknown>)[k];
                            if (v === null || v === undefined) return '';
                            if (typeof v === 'string') return v;
                            return JSON.stringify(v);
                        });
                        channel.appendLine(values.join('\t'));
                    }
                } else {
                    // Simple array
                    for (const item of resultData) {
                        channel.appendLine(JSON.stringify(item, null, 2));
                    }
                }
            }
        } else {
            channel.appendLine(`Result (${elapsed}ms):`);
            channel.appendLine(JSON.stringify(resultData, null, 2));
        }

        vscode.window.showInformationMessage(
            `MU: Query completed in ${elapsed}ms`
        );
    } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        channel.appendLine(`Error: ${message}`);
        vscode.window.showErrorMessage(`MU Query failed: ${message}`);
    }
}

/**
 * Sanitize a string for safe use in MUQL queries.
 * Escapes single quotes, double quotes, and validates against injection patterns.
 */
function sanitizeForQuery(value: string): string {
    // Escape both single and double quotes
    return value.replace(/'/g, "''").replace(/"/g, '\\"');
}

/**
 * Validate that a node name/ID has safe characters.
 */
function isValidNodeInput(input: string): boolean {
    // Allow only alphanumeric, colons, dots, underscores, hyphens, forward slashes, and spaces
    return /^[a-zA-Z0-9:._\-/ ]+$/.test(input);
}

/**
 * Find path between two nodes
 */
export async function findPath(client: MUClient): Promise<void> {
    // Get "from" node
    const fromInput = await vscode.window.showInputBox({
        prompt: 'Enter starting node name or ID',
        placeHolder: 'e.g., UserService or mod:src/services/user.py',
    });

    if (!fromInput) {
        return;
    }

    // Get "to" node
    const toInput = await vscode.window.showInputBox({
        prompt: 'Enter destination node name or ID',
        placeHolder: 'e.g., DatabaseConnection or cls:Database',
    });

    if (!toInput) {
        return;
    }

    // Validate inputs to prevent injection
    if (!isValidNodeInput(fromInput) || !isValidNodeInput(toInput)) {
        vscode.window.showErrorMessage('MU: Invalid characters in node name/ID');
        return;
    }

    const channel = getOutputChannel();
    channel.clear();
    channel.appendLine(`Finding path from "${fromInput}" to "${toInput}"...`);
    channel.show();

    try {
        // First, try to find nodes by name if not already IDs
        let fromId = fromInput;
        let toId = toInput;

        // If input doesn't look like an ID (no : prefix), search by name
        if (!fromInput.includes(':')) {
            const result = await client.query(
                `SELECT * FROM nodes WHERE name = '${sanitizeForQuery(fromInput)}' LIMIT 1`
            );
            if (result.success && Array.isArray(result.result) && result.result.length > 0) {
                fromId = (result.result[0] as { id: string }).id;
            }
        }

        if (!toInput.includes(':')) {
            const result = await client.query(
                `SELECT * FROM nodes WHERE name = '${sanitizeForQuery(toInput)}' LIMIT 1`
            );
            if (result.success && Array.isArray(result.result) && result.result.length > 0) {
                toId = (result.result[0] as { id: string }).id;
            }
        }

        // Execute PATH query
        const path = await client.findPath(fromId, toId);

        if (path.length === 0) {
            channel.appendLine('');
            channel.appendLine('No path found between these nodes.');
            vscode.window.showInformationMessage(
                'MU: No path found between the specified nodes.'
            );
            return;
        }

        channel.appendLine('');
        channel.appendLine(`Path found (${path.length} nodes):`);
        channel.appendLine('');

        for (let i = 0; i < path.length; i++) {
            const nodeId = path[i];
            const prefix = i === 0 ? '  [START]' : i === path.length - 1 ? '  [END]' : '       ';
            const arrow = i < path.length - 1 ? ' ->' : '';

            try {
                const node = await client.getNode(nodeId);
                channel.appendLine(`${prefix} ${node.name} (${node.type})${arrow}`);
            } catch {
                channel.appendLine(`${prefix} ${nodeId}${arrow}`);
            }
        }

        vscode.window.showInformationMessage(
            `MU: Found path with ${path.length} nodes.`
        );
    } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        channel.appendLine(`Error: ${message}`);
        vscode.window.showErrorMessage(`MU Find Path failed: ${message}`);
    }
}

/**
 * Dispose the output channel
 */
export function disposeQueryChannel(): void {
    outputChannel?.dispose();
    outputChannel = undefined;
}
