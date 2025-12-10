# Epic 9: IDE Integration

**Priority**: P4 - VS Code extension for in-editor experience
**Dependencies**: Daemon Mode (Epic 6), Smart Context (Epic 3)
**Estimated Complexity**: High
**PRD Reference**: Section 3.3

---

## Overview

Build a VS Code extension that integrates MU into the development workflow. Show dependency info inline, provide smart context for AI assistants, and enable MUQL queries from the editor.

## Goals

1. MUbase explorer sidebar
2. Inline complexity badges
3. CodeLens for dependencies
4. MUQL query palette
5. Smart context for Copilot/Claude

---

## User Stories

### Story 9.1: Explorer View
**As a** developer
**I want** a sidebar showing the code graph
**So that** I can navigate by structure

**Acceptance Criteria**:
- [ ] Tree view of modules/classes/functions
- [ ] Sort by complexity, name, or file
- [ ] Filter by type
- [ ] Click to navigate to code
- [ ] Refresh on file changes

### Story 9.2: Complexity Badges
**As a** developer
**I want** complexity shown in the editor
**So that** I can identify hot spots

**Acceptance Criteria**:
- [ ] Inline badges for functions/classes
- [ ] Color-coded by severity
- [ ] Hover for details
- [ ] Configurable thresholds

### Story 9.3: Dependency CodeLens
**As a** developer
**I want** dependency info above functions
**So that** I can see connections

**Acceptance Criteria**:
- [ ] Show "X dependencies, Y dependents" above functions
- [ ] Click to show full list
- [ ] Quick navigation to related code
- [ ] Update on file changes

### Story 9.4: MUQL Commands
**As a** developer
**I want** to run MUQL from VS Code
**So that** I can query without leaving editor

**Acceptance Criteria**:
- [ ] Command palette: "MU: Query"
- [ ] MUQL input box with history
- [ ] Results in output panel
- [ ] Quick actions on results

### Story 9.5: Smart Context
**As a** developer
**I want** AI context from MU
**So that** I get better AI suggestions

**Acceptance Criteria**:
- [ ] Command: "MU: Get Context for Question"
- [ ] Auto-context for Copilot Chat
- [ ] Copy context to clipboard
- [ ] Token budget configuration

### Story 9.6: Diagnostics
**As a** developer
**I want** contract violations shown
**So that** I fix issues early

**Acceptance Criteria**:
- [ ] Show violations as problems
- [ ] Inline squiggles for issues
- [ ] Quick fixes where applicable
- [ ] Refresh on save

---

## Technical Design

### Extension Architecture

```
mu-vscode/
├── package.json
├── tsconfig.json
├── webpack.config.js
├── src/
│   ├── extension.ts          # Entry point
│   ├── client/
│   │   ├── MUClient.ts       # Daemon API client
│   │   └── WebSocketClient.ts
│   ├── providers/
│   │   ├── ExplorerProvider.ts
│   │   ├── CodeLensProvider.ts
│   │   ├── DiagnosticsProvider.ts
│   │   ├── DecorationProvider.ts
│   │   └── HoverProvider.ts
│   ├── commands/
│   │   ├── query.ts
│   │   ├── context.ts
│   │   ├── navigate.ts
│   │   └── refresh.ts
│   ├── views/
│   │   ├── ExplorerView.ts
│   │   └── ResultsView.ts
│   └── utils/
│       ├── config.ts
│       └── cache.ts
├── media/
│   ├── icons/
│   └── styles/
└── test/
    └── suite/
```

### Package.json

```json
{
  "name": "mu-vscode",
  "displayName": "MU - Code Graph",
  "description": "Semantic code understanding and navigation",
  "version": "1.0.0",
  "publisher": "moesia",
  "engines": {
    "vscode": "^1.85.0"
  },
  "categories": ["Other", "Visualization"],
  "activationEvents": [
    "workspaceContains:.mubase"
  ],
  "main": "./dist/extension.js",
  "contributes": {
    "configuration": {
      "title": "MU",
      "properties": {
        "mu.daemonUrl": {
          "type": "string",
          "default": "http://localhost:8765",
          "description": "MU daemon URL"
        },
        "mu.complexity.warningThreshold": {
          "type": "number",
          "default": 200,
          "description": "Complexity threshold for warning badges"
        },
        "mu.complexity.errorThreshold": {
          "type": "number",
          "default": 500,
          "description": "Complexity threshold for error badges"
        },
        "mu.codeLens.enabled": {
          "type": "boolean",
          "default": true,
          "description": "Show dependency CodeLens"
        },
        "mu.badges.enabled": {
          "type": "boolean",
          "default": true,
          "description": "Show complexity badges"
        }
      }
    },
    "commands": [
      {
        "command": "mu.query",
        "title": "MU: Run Query"
      },
      {
        "command": "mu.getContext",
        "title": "MU: Get Context for Question"
      },
      {
        "command": "mu.showDependencies",
        "title": "MU: Show Dependencies"
      },
      {
        "command": "mu.showDependents",
        "title": "MU: Show Dependents"
      },
      {
        "command": "mu.findPath",
        "title": "MU: Find Path To..."
      },
      {
        "command": "mu.refresh",
        "title": "MU: Refresh Graph"
      },
      {
        "command": "mu.openVisualization",
        "title": "MU: Open Visualization"
      }
    ],
    "viewsContainers": {
      "activitybar": [
        {
          "id": "mu-explorer",
          "title": "MU",
          "icon": "media/icons/mu.svg"
        }
      ]
    },
    "views": {
      "mu-explorer": [
        {
          "id": "mu.modules",
          "name": "Modules"
        },
        {
          "id": "mu.classes",
          "name": "Classes"
        },
        {
          "id": "mu.functions",
          "name": "Functions"
        },
        {
          "id": "mu.hotspots",
          "name": "Hotspots"
        }
      ]
    },
    "menus": {
      "editor/context": [
        {
          "command": "mu.showDependencies",
          "group": "mu",
          "when": "resourceLangId in mu.supportedLanguages"
        },
        {
          "command": "mu.showDependents",
          "group": "mu",
          "when": "resourceLangId in mu.supportedLanguages"
        }
      ]
    }
  }
}
```

### Extension Entry Point

```typescript
// src/extension.ts
import * as vscode from 'vscode';
import { MUClient } from './client/MUClient';
import { ExplorerProvider } from './providers/ExplorerProvider';
import { CodeLensProvider } from './providers/CodeLensProvider';
import { DiagnosticsProvider } from './providers/DiagnosticsProvider';
import { DecorationProvider } from './providers/DecorationProvider';
import { HoverProvider } from './providers/HoverProvider';
import { registerCommands } from './commands';

let client: MUClient;

export async function activate(context: vscode.ExtensionContext) {
  // Initialize client
  const config = vscode.workspace.getConfiguration('mu');
  const daemonUrl = config.get<string>('daemonUrl', 'http://localhost:8765');

  client = new MUClient(daemonUrl);

  // Check daemon connection
  try {
    await client.getStatus();
    vscode.window.showInformationMessage('MU: Connected to daemon');
  } catch (e) {
    vscode.window.showWarningMessage(
      'MU: Daemon not running. Start with `mu daemon start`'
    );
  }

  // Register providers
  const explorerProvider = new ExplorerProvider(client);
  const codeLensProvider = new CodeLensProvider(client);
  const diagnosticsProvider = new DiagnosticsProvider(client);
  const decorationProvider = new DecorationProvider(client);
  const hoverProvider = new HoverProvider(client);

  // Register tree views
  context.subscriptions.push(
    vscode.window.registerTreeDataProvider('mu.modules', explorerProvider),
    vscode.window.registerTreeDataProvider('mu.classes', explorerProvider),
    vscode.window.registerTreeDataProvider('mu.functions', explorerProvider),
    vscode.window.registerTreeDataProvider('mu.hotspots', explorerProvider)
  );

  // Register CodeLens
  const selector = { scheme: 'file', pattern: '**/*.{py,ts,js,go,java,rs,cs}' };
  context.subscriptions.push(
    vscode.languages.registerCodeLensProvider(selector, codeLensProvider)
  );

  // Register Hover
  context.subscriptions.push(
    vscode.languages.registerHoverProvider(selector, hoverProvider)
  );

  // Register diagnostics
  const diagnostics = vscode.languages.createDiagnosticCollection('mu');
  context.subscriptions.push(diagnostics);
  diagnosticsProvider.setDiagnostics(diagnostics);

  // Register decorations
  decorationProvider.activate(context);

  // Register commands
  registerCommands(context, client);

  // Watch for file changes
  const watcher = vscode.workspace.createFileSystemWatcher('**/*.{py,ts,js,go,java,rs,cs}');
  watcher.onDidChange(() => {
    codeLensProvider.refresh();
    decorationProvider.refresh();
  });
  context.subscriptions.push(watcher);

  // WebSocket for live updates
  client.onGraphUpdate((event) => {
    codeLensProvider.refresh();
    decorationProvider.refresh();
    explorerProvider.refresh();
    diagnosticsProvider.refresh();
  });
}

export function deactivate() {
  client?.disconnect();
}
```

### Explorer Provider

```typescript
// src/providers/ExplorerProvider.ts
import * as vscode from 'vscode';
import { MUClient, Node } from '../client/MUClient';

export class ExplorerProvider implements vscode.TreeDataProvider<NodeItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<NodeItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private cache: Map<string, Node[]> = new Map();

  constructor(private client: MUClient) {}

  refresh(): void {
    this.cache.clear();
    this._onDidChangeTreeData.fire(undefined);
  }

  getTreeItem(element: NodeItem): vscode.TreeItem {
    return element;
  }

  async getChildren(element?: NodeItem): Promise<NodeItem[]> {
    if (!element) {
      // Root level - show modules
      const nodes = await this.client.query(
        'SELECT * FROM modules ORDER BY name'
      );
      return nodes.rows.map((n) => new NodeItem(n, vscode.TreeItemCollapsibleState.Collapsed));
    }

    // Show children of the node
    const children = await this.client.getNeighbors(element.node.id, 'outgoing', 'CONTAINS');
    return children.map((n) => {
      const hasChildren = n.type === 'CLASS' || n.type === 'MODULE';
      const state = hasChildren
        ? vscode.TreeItemCollapsibleState.Collapsed
        : vscode.TreeItemCollapsibleState.None;
      return new NodeItem(n, state);
    });
  }
}

class NodeItem extends vscode.TreeItem {
  constructor(
    public readonly node: Node,
    public readonly collapsibleState: vscode.TreeItemCollapsibleState
  ) {
    super(node.name, collapsibleState);

    this.tooltip = `${node.qualified_name || node.name}\nComplexity: ${node.complexity || 'N/A'}`;
    this.description = node.type;

    // Icon based on type
    this.iconPath = new vscode.ThemeIcon(getIconForType(node.type));

    // Click to navigate
    if (node.file_path && node.line_start) {
      this.command = {
        command: 'vscode.open',
        title: 'Open',
        arguments: [
          vscode.Uri.file(node.file_path),
          { selection: new vscode.Range(node.line_start - 1, 0, node.line_start - 1, 0) }
        ]
      };
    }

    // Context value for menus
    this.contextValue = `mu-node-${node.type.toLowerCase()}`;
  }
}

function getIconForType(type: string): string {
  const icons: Record<string, string> = {
    MODULE: 'file-code',
    CLASS: 'symbol-class',
    FUNCTION: 'symbol-method',
    ENTITY: 'database',
    EXTERNAL: 'package',
  };
  return icons[type] || 'symbol-misc';
}
```

### CodeLens Provider

```typescript
// src/providers/CodeLensProvider.ts
import * as vscode from 'vscode';
import { MUClient, Node } from '../client/MUClient';

export class CodeLensProvider implements vscode.CodeLensProvider {
  private _onDidChangeCodeLenses = new vscode.EventEmitter<void>();
  readonly onDidChangeCodeLenses = this._onDidChangeCodeLenses.event;

  private cache: Map<string, Node[]> = new Map();

  constructor(private client: MUClient) {}

  refresh(): void {
    this.cache.clear();
    this._onDidChangeCodeLenses.fire();
  }

  async provideCodeLenses(
    document: vscode.TextDocument,
    token: vscode.CancellationToken
  ): Promise<vscode.CodeLens[]> {
    const config = vscode.workspace.getConfiguration('mu');
    if (!config.get<boolean>('codeLens.enabled', true)) {
      return [];
    }

    const filePath = document.uri.fsPath;
    const lenses: vscode.CodeLens[] = [];

    try {
      // Get nodes for this file
      const nodes = await this.getNodesForFile(filePath);

      for (const node of nodes) {
        if (node.type !== 'FUNCTION' && node.type !== 'CLASS') continue;
        if (!node.line_start) continue;

        const range = new vscode.Range(
          node.line_start - 1, 0,
          node.line_start - 1, 0
        );

        // Get dependency counts
        const deps = await this.client.getNeighbors(node.id, 'outgoing');
        const depCount = deps.filter(d => d.id !== node.id).length;

        const dependents = await this.client.getNeighbors(node.id, 'incoming');
        const depByCount = dependents.filter(d => d.id !== node.id).length;

        // Create CodeLens
        lenses.push(new vscode.CodeLens(range, {
          title: `${depCount} deps, ${depByCount} refs`,
          command: 'mu.showDependencies',
          arguments: [node.id]
        }));
      }
    } catch (e) {
      console.error('MU CodeLens error:', e);
    }

    return lenses;
  }

  private async getNodesForFile(filePath: string): Promise<Node[]> {
    if (this.cache.has(filePath)) {
      return this.cache.get(filePath)!;
    }

    const result = await this.client.query(
      `SELECT * FROM nodes WHERE file_path = '${filePath}'`
    );
    const nodes = result.rows as Node[];
    this.cache.set(filePath, nodes);
    return nodes;
  }
}
```

### Decoration Provider (Complexity Badges)

```typescript
// src/providers/DecorationProvider.ts
import * as vscode from 'vscode';
import { MUClient, Node } from '../client/MUClient';

export class DecorationProvider {
  private infoDecoration: vscode.TextEditorDecorationType;
  private warningDecoration: vscode.TextEditorDecorationType;
  private errorDecoration: vscode.TextEditorDecorationType;

  private cache: Map<string, Node[]> = new Map();

  constructor(private client: MUClient) {
    this.infoDecoration = vscode.window.createTextEditorDecorationType({
      after: {
        contentText: '',
        margin: '0 0 0 1em',
        color: new vscode.ThemeColor('editorInfo.foreground'),
      }
    });

    this.warningDecoration = vscode.window.createTextEditorDecorationType({
      after: {
        margin: '0 0 0 1em',
        color: new vscode.ThemeColor('editorWarning.foreground'),
      }
    });

    this.errorDecoration = vscode.window.createTextEditorDecorationType({
      after: {
        margin: '0 0 0 1em',
        color: new vscode.ThemeColor('editorError.foreground'),
      }
    });
  }

  activate(context: vscode.ExtensionContext) {
    // Update decorations on active editor change
    vscode.window.onDidChangeActiveTextEditor(
      (editor) => this.updateDecorations(editor),
      null,
      context.subscriptions
    );

    // Update on document change
    vscode.workspace.onDidChangeTextDocument(
      (event) => {
        const editor = vscode.window.activeTextEditor;
        if (editor && event.document === editor.document) {
          this.updateDecorations(editor);
        }
      },
      null,
      context.subscriptions
    );

    // Initial update
    this.updateDecorations(vscode.window.activeTextEditor);
  }

  refresh(): void {
    this.cache.clear();
    this.updateDecorations(vscode.window.activeTextEditor);
  }

  private async updateDecorations(editor: vscode.TextEditor | undefined) {
    if (!editor) return;

    const config = vscode.workspace.getConfiguration('mu');
    if (!config.get<boolean>('badges.enabled', true)) {
      return;
    }

    const warningThreshold = config.get<number>('complexity.warningThreshold', 200);
    const errorThreshold = config.get<number>('complexity.errorThreshold', 500);

    const filePath = editor.document.uri.fsPath;

    try {
      const nodes = await this.getNodesForFile(filePath);

      const infoDecorations: vscode.DecorationOptions[] = [];
      const warningDecorations: vscode.DecorationOptions[] = [];
      const errorDecorations: vscode.DecorationOptions[] = [];

      for (const node of nodes) {
        if (node.type !== 'FUNCTION' || !node.line_start || !node.complexity) {
          continue;
        }

        const line = node.line_start - 1;
        const lineLength = editor.document.lineAt(line).text.length;
        const range = new vscode.Range(line, lineLength, line, lineLength);

        const decoration: vscode.DecorationOptions = {
          range,
          renderOptions: {
            after: {
              contentText: ` complexity: ${node.complexity}`,
            }
          }
        };

        if (node.complexity >= errorThreshold) {
          errorDecorations.push(decoration);
        } else if (node.complexity >= warningThreshold) {
          warningDecorations.push(decoration);
        } else {
          infoDecorations.push(decoration);
        }
      }

      editor.setDecorations(this.infoDecoration, infoDecorations);
      editor.setDecorations(this.warningDecoration, warningDecorations);
      editor.setDecorations(this.errorDecoration, errorDecorations);
    } catch (e) {
      console.error('MU decorations error:', e);
    }
  }

  private async getNodesForFile(filePath: string): Promise<Node[]> {
    if (this.cache.has(filePath)) {
      return this.cache.get(filePath)!;
    }

    const result = await this.client.query(
      `SELECT * FROM nodes WHERE file_path = '${filePath}'`
    );
    const nodes = result.rows as Node[];
    this.cache.set(filePath, nodes);
    return nodes;
  }
}
```

### Commands

```typescript
// src/commands/index.ts
import * as vscode from 'vscode';
import { MUClient } from '../client/MUClient';

export function registerCommands(
  context: vscode.ExtensionContext,
  client: MUClient
) {
  // Query command
  context.subscriptions.push(
    vscode.commands.registerCommand('mu.query', async () => {
      const query = await vscode.window.showInputBox({
        prompt: 'Enter MUQL query',
        placeHolder: 'SELECT * FROM functions WHERE complexity > 500',
      });

      if (!query) return;

      try {
        const result = await client.query(query);

        // Show in output channel
        const channel = vscode.window.createOutputChannel('MU Query');
        channel.clear();
        channel.appendLine(`Query: ${query}\n`);
        channel.appendLine(`Results (${result.rows.length}):\n`);
        channel.appendLine(JSON.stringify(result.rows, null, 2));
        channel.show();
      } catch (e: any) {
        vscode.window.showErrorMessage(`Query error: ${e.message}`);
      }
    })
  );

  // Get context command
  context.subscriptions.push(
    vscode.commands.registerCommand('mu.getContext', async () => {
      const question = await vscode.window.showInputBox({
        prompt: 'What do you want to understand?',
        placeHolder: 'How does authentication work?',
      });

      if (!question) return;

      try {
        const result = await client.getContext(question);

        // Copy to clipboard
        await vscode.env.clipboard.writeText(result.mu_text);

        vscode.window.showInformationMessage(
          `Context copied! ${result.token_count} tokens, ${result.nodes.length} nodes`
        );
      } catch (e: any) {
        vscode.window.showErrorMessage(`Context error: ${e.message}`);
      }
    })
  );

  // Show dependencies command
  context.subscriptions.push(
    vscode.commands.registerCommand('mu.showDependencies', async (nodeId?: string) => {
      if (!nodeId) {
        // Get from current cursor position
        const editor = vscode.window.activeTextEditor;
        if (!editor) return;

        const position = editor.selection.active;
        const nodes = await client.query(
          `SELECT * FROM nodes WHERE file_path = '${editor.document.uri.fsPath}'
           AND line_start <= ${position.line + 1}
           AND line_end >= ${position.line + 1}`
        );

        if (nodes.rows.length === 0) {
          vscode.window.showWarningMessage('No node found at cursor');
          return;
        }

        nodeId = nodes.rows[0].id;
      }

      const deps = await client.getNeighbors(nodeId, 'outgoing');

      const items = deps.map((d) => ({
        label: d.name,
        description: `${d.type} - ${d.file_path || 'external'}`,
        detail: d.qualified_name,
        node: d,
      }));

      const selected = await vscode.window.showQuickPick(items, {
        title: 'Dependencies',
        placeHolder: 'Select to navigate',
      });

      if (selected && selected.node.file_path) {
        const doc = await vscode.workspace.openTextDocument(selected.node.file_path);
        await vscode.window.showTextDocument(doc, {
          selection: new vscode.Range(
            selected.node.line_start - 1, 0,
            selected.node.line_start - 1, 0
          )
        });
      }
    })
  );

  // Show dependents command
  context.subscriptions.push(
    vscode.commands.registerCommand('mu.showDependents', async (nodeId?: string) => {
      // Similar to showDependencies but with 'incoming' direction
      // ...
    })
  );

  // Find path command
  context.subscriptions.push(
    vscode.commands.registerCommand('mu.findPath', async () => {
      const from = await vscode.window.showInputBox({
        prompt: 'From node name',
      });
      if (!from) return;

      const to = await vscode.window.showInputBox({
        prompt: 'To node name',
      });
      if (!to) return;

      try {
        const result = await client.query(`PATH FROM ${from} TO ${to}`);

        if (result.rows.length === 0) {
          vscode.window.showInformationMessage('No path found');
          return;
        }

        const path = result.rows[0].path;
        const channel = vscode.window.createOutputChannel('MU Path');
        channel.clear();
        channel.appendLine(`Path from ${from} to ${to}:\n`);
        channel.appendLine(path.join(' → '));
        channel.show();
      } catch (e: any) {
        vscode.window.showErrorMessage(`Path error: ${e.message}`);
      }
    })
  );

  // Refresh command
  context.subscriptions.push(
    vscode.commands.registerCommand('mu.refresh', async () => {
      // Trigger refresh on all providers
      vscode.commands.executeCommand('mu.internal.refresh');
      vscode.window.showInformationMessage('MU: Graph refreshed');
    })
  );

  // Open visualization command
  context.subscriptions.push(
    vscode.commands.registerCommand('mu.openVisualization', async () => {
      const config = vscode.workspace.getConfiguration('mu');
      const daemonUrl = config.get<string>('daemonUrl', 'http://localhost:8765');
      const vizUrl = daemonUrl.replace(/:\d+$/, ':3000'); // Assuming viz on port 3000

      vscode.env.openExternal(vscode.Uri.parse(vizUrl));
    })
  );
}
```

---

## Implementation Plan

### Phase 1: Project Setup (Day 1)
1. Initialize VS Code extension project
2. Configure TypeScript and webpack
3. Set up package.json with contributions
4. Create basic extension activation

### Phase 2: API Client (Day 1)
1. Port MUClient from visualization
2. Add VS Code-specific error handling
3. Add WebSocket support
4. Test connection to daemon

### Phase 3: Explorer View (Day 2)
1. Implement ExplorerProvider
2. Add tree views for modules/classes/functions
3. Implement navigation on click
4. Add refresh functionality

### Phase 4: CodeLens (Day 2-3)
1. Implement CodeLensProvider
2. Show dependency counts
3. Add click actions
4. Cache for performance

### Phase 5: Decorations (Day 3)
1. Implement DecorationProvider
2. Show complexity badges
3. Color-code by severity
4. Add configuration options

### Phase 6: Hover Provider (Day 3-4)
1. Implement HoverProvider
2. Show node details on hover
3. Show quick actions
4. Add Markdown formatting

### Phase 7: Commands (Day 4)
1. Implement query command
2. Implement context command
3. Implement navigation commands
4. Add command palette entries

### Phase 8: Diagnostics (Day 4-5)
1. Implement DiagnosticsProvider
2. Show contract violations
3. Add problem panel integration
4. Update on file save

### Phase 9: Polish (Day 5)
1. Add icons and theming
2. Improve error handling
3. Add status bar item
4. Write documentation

### Phase 10: Testing (Day 5)
1. Unit tests for providers
2. Integration tests with daemon
3. Manual testing workflow
4. Package for marketplace

---

## Testing Strategy

### Unit Tests
- Provider logic tests
- Command tests with mocked API
- Configuration tests

### Integration Tests
- Full extension activation
- Daemon connection
- Feature interactions

### Manual Testing
- Install in VS Code
- Test all features
- Performance profiling

---

## Success Criteria

- [ ] Extension activates when .mubase exists
- [ ] Explorer shows graph structure
- [ ] CodeLens shows dependency info
- [ ] Complexity badges display correctly
- [ ] MUQL queries work from palette
- [ ] Context extraction works
- [ ] WebSocket updates work
- [ ] Extension is < 1MB packaged

---

## Future Enhancements

1. **Copilot Chat integration**: MU as context provider
2. **Inline suggestions**: Show similar code patterns
3. **Refactoring support**: Safe rename with graph awareness
4. **Multi-root workspace**: Support multiple .mubase files
5. **Remote development**: Work with remote daemon
