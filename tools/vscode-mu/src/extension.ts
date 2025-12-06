import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';

let outputChannel: vscode.OutputChannel;

export function activate(context: vscode.ExtensionContext) {
    outputChannel = vscode.window.createOutputChannel('MU');

    // Register commands
    context.subscriptions.push(
        vscode.commands.registerCommand('mu.compress', compressCommand),
        vscode.commands.registerCommand('mu.compressFile', compressFileCommand),
        vscode.commands.registerCommand('mu.compressWorkspace', compressWorkspaceCommand),
        vscode.commands.registerCommand('mu.preview', previewCommand),
        vscode.commands.registerCommand('mu.diff', diffCommand)
    );

    // Register hover provider for MU files
    context.subscriptions.push(
        vscode.languages.registerHoverProvider('mu', new MuHoverProvider())
    );

    outputChannel.appendLine('MU extension activated');
}

export function deactivate() {
    if (outputChannel) {
        outputChannel.dispose();
    }
}

/**
 * Run mu compress on a selected directory
 */
async function compressCommand() {
    const folderUri = await vscode.window.showOpenDialog({
        canSelectFiles: false,
        canSelectFolders: true,
        canSelectMany: false,
        openLabel: 'Select folder to compress'
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
            language: 'mu'
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
        value: 'main'
    });

    if (!baseRef) {
        return;
    }

    const headRef = await vscode.window.showInputBox({
        prompt: 'Enter head git ref (e.g., HEAD, feature-branch)',
        value: 'HEAD'
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
    const result = await runMuCommand(['diff', baseRef, headRef, '--format', 'markdown'], cwd);

    if (result) {
        const doc = await vscode.workspace.openTextDocument({
            content: result,
            language: 'markdown'
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
        placeHolder: 'output.mu'
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
                language: 'mu'
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
            env: { ...process.env }
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
                vscode.window.showErrorMessage(`MU command failed: ${stderr || 'Unknown error'}`);
                resolve(null);
            }
        });

        child.on('error', (err) => {
            outputChannel.appendLine(`Error: ${err.message}`);
            vscode.window.showErrorMessage(`Failed to run MU: ${err.message}. Is 'mu' installed and in PATH?`);
            resolve(null);
        });
    });
}

/**
 * Hover provider for MU files - shows info about sigils
 */
class MuHoverProvider implements vscode.HoverProvider {
    private sigilInfo: Record<string, string> = {
        '!': '**Module/Service** - Defines a module or service boundary',
        '§': '**Module** (Unicode) - Module namespace declaration',
        '$': '**Entity/Class** - Defines a class or data structure',
        'τ': '**Type** (Unicode) - Type or class definition',
        '#': '**Function/Method** - Function or method signature',
        'λ': '**Lambda/Function** (Unicode) - Function definition',
        '@': '**Metadata/Decorator** - Annotations, decorators, or metadata',
        '?': '**Conditional** - Branch or conditional logic',
        '::': '**Annotation/Invariant** - Guards, constraints, or notes',
        '∅': '**Empty** - Stripped or empty marker',
        '->': '**Data Flow** - Return type or data transformation',
        '→': '**Data Flow** (Unicode) - Return type or data transformation',
        '=>': '**State Mutation** - State change or assignment',
        '⟹': '**State Mutation** (Unicode) - State change or assignment',
        '|': '**Match/Switch** - Pattern matching branch',
        '~': '**Iteration** - Loop or iteration marker',
        '<': '**Inheritance** - Class extends another',
        '@attrs': '**Attributes** - List of class/struct attributes',
        '@deps': '**Dependencies** - External dependencies list'
    };

    provideHover(
        document: vscode.TextDocument,
        position: vscode.Position
    ): vscode.ProviderResult<vscode.Hover> {
        const line = document.lineAt(position.line).text;
        const wordRange = document.getWordRangeAtPosition(position, /[@#$!?§τλ∅⟹→]|::|->|=>|@attrs|@deps/);

        if (!wordRange) {
            return null;
        }

        const word = document.getText(wordRange);
        const info = this.sigilInfo[word];

        if (info) {
            return new vscode.Hover(new vscode.MarkdownString(info));
        }

        // Check for module definition
        if (line.startsWith('!module ') || line.startsWith('§')) {
            return new vscode.Hover(
                new vscode.MarkdownString('**Module Definition** - Top-level namespace boundary')
            );
        }

        return null;
    }
}
