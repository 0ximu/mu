/**
 * Diagnostics Provider
 *
 * Shows contract violations as VS Code diagnostics in the Problems panel.
 * Updates on file save and can be manually refreshed.
 */

import * as vscode from 'vscode';
import { MUClient, ContractViolation } from '../client';

/**
 * Provides diagnostics for MU contract violations
 */
export class DiagnosticsProvider implements vscode.Disposable {
    private readonly diagnostics: vscode.DiagnosticCollection;
    private readonly disposables: vscode.Disposable[] = [];
    private isRefreshing = false;

    constructor(private readonly client: MUClient) {
        this.diagnostics = vscode.languages.createDiagnosticCollection('mu-contracts');

        // Listen for document saves
        this.disposables.push(
            vscode.workspace.onDidSaveTextDocument(() => {
                // Debounce - don't refresh on every save in quick succession
                this.refresh();
            })
        );

        // Initial refresh
        this.refresh();
    }

    /**
     * Refresh diagnostics from contract verification
     */
    async refresh(): Promise<void> {
        if (this.isRefreshing) {
            return;
        }

        this.isRefreshing = true;

        try {
            // Clear existing diagnostics
            this.diagnostics.clear();

            // Verify contracts
            const result = await this.client.verifyContracts();

            if (result.violations.length === 0) {
                // No violations - we're done
                return;
            }

            // Group violations by file
            const byFile = new Map<string, vscode.Diagnostic[]>();

            for (const violation of result.violations) {
                const diagnostic = this.violationToDiagnostic(violation);
                const filePath = violation.file_path || 'unknown';

                const existing = byFile.get(filePath) || [];
                existing.push(diagnostic);
                byFile.set(filePath, existing);
            }

            // Apply diagnostics to each file
            for (const [filePath, diagnostics] of byFile) {
                if (filePath !== 'unknown') {
                    try {
                        const uri = vscode.Uri.file(filePath);
                        this.diagnostics.set(uri, diagnostics);
                    } catch {
                        // File path invalid - skip
                    }
                }
            }

            // Show status bar notification if there are errors
            if (result.error_count > 0) {
                vscode.window.setStatusBarMessage(
                    `MU: ${result.error_count} contract violation(s)`,
                    5000
                );
            }
        } catch (err) {
            // Daemon not available or contracts endpoint not implemented
            // Silently fail - this is expected when daemon is not running
            console.debug('MU: Contract verification failed:', err);
        } finally {
            this.isRefreshing = false;
        }
    }

    private violationToDiagnostic(violation: ContractViolation): vscode.Diagnostic {
        // Determine line range
        const line = (violation.line || 1) - 1; // VS Code uses 0-based lines
        const range = new vscode.Range(line, 0, line, Number.MAX_SAFE_INTEGER);

        // Build message
        const message = `[${violation.contract}] ${violation.message}`;

        // Map severity
        const severity =
            violation.severity === 'error'
                ? vscode.DiagnosticSeverity.Error
                : vscode.DiagnosticSeverity.Warning;

        const diagnostic = new vscode.Diagnostic(range, message, severity);
        diagnostic.source = 'MU Contracts';
        diagnostic.code = violation.rule;

        return diagnostic;
    }

    /**
     * Clear all diagnostics
     */
    clear(): void {
        this.diagnostics.clear();
    }

    dispose(): void {
        this.diagnostics.dispose();
        for (const d of this.disposables) {
            d.dispose();
        }
    }
}
