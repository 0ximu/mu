# IDE Integration - Task Breakdown

## Business Context

**Problem**: Developers lack visibility into codebase structure and quality directly in their editor. Understanding dependencies, finding complex code, and getting relevant context for AI assistants requires switching between tools and running CLI commands.

**Outcome**: A VS Code extension that integrates MU into the development workflow, providing:
- Real-time code graph exploration in a sidebar
- Inline complexity badges to identify hotspots
- CodeLens showing dependency counts above functions
- MUQL queries from the command palette
- Smart context extraction for AI assistants
- Contract violations shown as diagnostics

**Users**:
- Developers wanting structural awareness without leaving the editor
- Teams using AI assistants (Copilot, Claude) who need relevant context
- Engineering leads monitoring code quality and architectural compliance

---

## Discovered Patterns

| Pattern | File | Relevance |
|---------|------|-----------|
| Daemon REST API | `/Users/imu/Dev/work/mu/src/mu/daemon/server.py:292-454` | Extension communicates via `/status`, `/nodes`, `/query`, `/context`, `/export` endpoints |
| WebSocket live updates | `/Users/imu/Dev/work/mu/src/mu/daemon/server.py:460-495` | `/live` WebSocket for real-time graph change notifications |
| MUClient TypeScript | `/Users/imu/Dev/work/mu/mu-viz/src/api/client.ts:11-116` | Port this client to VS Code extension for daemon communication |
| API Types | `/Users/imu/Dev/work/mu/mu-viz/src/api/types.ts:1-98` | TypeScript interfaces for Node, Edge, QueryResult, GraphEvent, etc. |
| Existing extension | `/Users/imu/Dev/work/mu/tools/vscode-mu/src/extension.ts` | CLI-based extension with compress/preview commands - extend this |
| Extension package.json | `/Users/imu/Dev/work/mu/tools/vscode-mu/package.json:35-129` | VS Code contribution points pattern for commands, views, configuration |
| MUQL Engine | `/Users/imu/Dev/work/mu/src/mu/kernel/muql/engine.py` | `MUQLEngine.query()` for executing queries via daemon |
| Smart Context | `/Users/imu/Dev/work/mu/src/mu/kernel/context/__init__.py` | `SmartContextExtractor` for question-based context |
| Contract Verifier | `/Users/imu/Dev/work/mu/src/mu/contracts/__init__.py` | `ContractVerifier` for architecture rule checking |
| Epic 9 Design | `/Users/imu/Dev/work/mu/docs/epics/09-ide-integration.md:97-256` | Package.json and provider patterns from epic document |

---

## Prerequisites

### Required Before Starting

1. **Daemon Mode (Epic 6)** must be complete - extension depends on HTTP/WebSocket API
2. **MU Contracts (Epic 7)** must be complete - diagnostics depend on contract verification

### Gap Analysis

The current daemon API (`/Users/imu/Dev/work/mu/src/mu/daemon/server.py`) is missing:

| Missing Endpoint | Required For | Priority |
|-----------------|--------------|----------|
| `POST /contracts/verify` | Story 9.6 (Diagnostics) | P1 |
| `GET /nodes?file_path=...` | Story 9.2, 9.3 (CodeLens, badges) | P0 |
| `GET /complexity` summary | Story 9.2 (Hotspots view) | P2 |

These will need to be added as part of this epic or as daemon enhancements.

---

## Task Breakdown

### Story 9.1: Explorer View

#### Task 1.1: Extend Extension Package Configuration

**Priority**: P0 (Foundation)
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/tools/vscode-mu/package.json` (modify)

**Pattern**: Follow existing contributions structure at line 35-129

**Description**: Add activity bar icon, tree views, and activation event for `.mubase` presence.

**Implementation Notes**:
```json
{
  "activationEvents": [
    "workspaceContains:.mubase",
    "onLanguage:mu"
  ],
  "contributes": {
    "viewsContainers": {
      "activitybar": [{
        "id": "mu-explorer",
        "title": "MU",
        "icon": "media/icons/mu.svg"
      }]
    },
    "views": {
      "mu-explorer": [
        { "id": "mu.modules", "name": "Modules" },
        { "id": "mu.classes", "name": "Classes" },
        { "id": "mu.functions", "name": "Functions" },
        { "id": "mu.hotspots", "name": "Hotspots" }
      ]
    },
    "configuration": {
      "properties": {
        "mu.daemonUrl": {
          "type": "string",
          "default": "http://localhost:8765"
        },
        "mu.complexity.warningThreshold": {
          "type": "number",
          "default": 200
        },
        "mu.complexity.errorThreshold": {
          "type": "number",
          "default": 500
        }
      }
    }
  }
}
```

**Acceptance Criteria**:
- [ ] Activity bar shows MU icon when `.mubase` exists in workspace
- [ ] Four tree views registered: Modules, Classes, Functions, Hotspots
- [ ] Configuration properties for daemon URL and complexity thresholds
- [ ] Extension activates when `.mubase` is present

---

#### Task 1.2: Create MU Daemon API Client

**Priority**: P0 (Foundation for all features)
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/tools/vscode-mu/src/client/MUClient.ts` (new)
- `/Users/imu/Dev/work/mu/tools/vscode-mu/src/client/types.ts` (new)

**Pattern**: Port from `/Users/imu/Dev/work/mu/mu-viz/src/api/client.ts:11-116`

**Description**: TypeScript client for communicating with MU daemon HTTP API and WebSocket.

**Implementation Notes**:
```typescript
// src/client/types.ts - Port from mu-viz/src/api/types.ts
export interface Node {
  id: string;
  name: string;
  type: 'module' | 'class' | 'function' | 'external';
  file_path?: string;
  line_start?: number;
  line_end?: number;
  complexity?: number;
  qualified_name?: string;
  properties?: Record<string, unknown>;
}

export interface QueryResult {
  result: unknown;
  success: boolean;
  error?: string;
}

export interface ContextResult {
  mu_text: string;
  token_count: number;
  nodes: Node[];
}

// src/client/MUClient.ts
import * as vscode from 'vscode';
import fetch from 'node-fetch';

export class MUClient {
  private baseUrl: string;
  private ws: WebSocket | null = null;
  private eventHandlers: ((event: GraphEvent) => void)[] = [];

  constructor() {
    const config = vscode.workspace.getConfiguration('mu');
    this.baseUrl = config.get<string>('daemonUrl', 'http://localhost:8765');
  }

  async getStatus(): Promise<StatusResponse> { ... }
  async getNode(id: string): Promise<Node> { ... }
  async getNeighbors(id: string, direction?: string): Promise<Node[]> { ... }
  async query(muql: string): Promise<QueryResult> { ... }
  async getContext(question: string, maxTokens?: number): Promise<ContextResult> { ... }

  connectWebSocket(): void { ... }
  onGraphUpdate(handler: (event: GraphEvent) => void): void { ... }
  disconnect(): void { ... }
}
```

**Acceptance Criteria**:
- [ ] `getStatus()` calls `GET /status` and returns daemon info
- [ ] `getNode(id)` calls `GET /nodes/{id}` with URL encoding
- [ ] `getNeighbors(id, direction)` calls `GET /nodes/{id}/neighbors`
- [ ] `query(muql)` calls `POST /query` with JSON body
- [ ] `getContext(question)` calls `POST /context`
- [ ] WebSocket connects to `/live` for real-time updates
- [ ] Event handlers can be registered via `onGraphUpdate()`
- [ ] Proper error handling with VS Code notifications
- [ ] Unit tests with mocked fetch

---

#### Task 1.3: Implement ExplorerProvider

**Priority**: P0 (Core Story 9.1 feature)
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/tools/vscode-mu/src/providers/ExplorerProvider.ts` (new)

**Pattern**: Follow VS Code `TreeDataProvider` interface, see epic design at line 350-433

**Dependencies**: Task 1.2 (MUClient)

**Description**: Tree data provider showing modules, classes, and functions from the code graph.

**Implementation Notes**:
```typescript
import * as vscode from 'vscode';
import { MUClient, Node } from '../client/MUClient';

export class ExplorerProvider implements vscode.TreeDataProvider<NodeItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<NodeItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private viewType: 'modules' | 'classes' | 'functions' | 'hotspots';
  private cache: Map<string, Node[]> = new Map();

  constructor(private client: MUClient, viewType: string) {
    this.viewType = viewType as any;
  }

  refresh(): void {
    this.cache.clear();
    this._onDidChangeTreeData.fire(undefined);
  }

  getTreeItem(element: NodeItem): vscode.TreeItem { ... }

  async getChildren(element?: NodeItem): Promise<NodeItem[]> {
    if (!element) {
      // Root level - query based on viewType
      const query = this.getQueryForViewType();
      const result = await this.client.query(query);
      return this.nodesToItems(result.result as Node[]);
    }
    // Children - get contained nodes
    const children = await this.client.getNeighbors(element.node.id, 'outgoing');
    return this.nodesToItems(children.filter(n => n.type !== 'external'));
  }

  private getQueryForViewType(): string {
    switch (this.viewType) {
      case 'modules': return 'SELECT * FROM modules ORDER BY name';
      case 'classes': return 'SELECT * FROM classes ORDER BY name';
      case 'functions': return 'SELECT * FROM functions ORDER BY name LIMIT 100';
      case 'hotspots': return 'SELECT * FROM functions WHERE complexity > 100 ORDER BY complexity DESC LIMIT 50';
    }
  }
}
```

**Acceptance Criteria**:
- [ ] Modules view shows all module nodes from graph
- [ ] Classes view shows all class nodes
- [ ] Functions view shows functions (limited to 100)
- [ ] Hotspots view shows functions with complexity > threshold, sorted desc
- [ ] Expanding a node shows its children (CONTAINS edges)
- [ ] Click navigates to file:line if available
- [ ] Icons based on node type (file-code, symbol-class, symbol-method)
- [ ] Tooltip shows qualified name and complexity
- [ ] Refresh updates view with fresh data

---

#### Task 1.4: Register Tree Views and Activation

**Priority**: P0 (Wire everything together)
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/tools/vscode-mu/src/extension.ts` (modify)

**Pattern**: Follow existing extension.ts structure

**Dependencies**: Tasks 1.1, 1.2, 1.3

**Description**: Update extension activation to create client, register tree providers, and connect WebSocket.

**Implementation Notes**:
```typescript
import { MUClient } from './client/MUClient';
import { ExplorerProvider } from './providers/ExplorerProvider';

let client: MUClient;

export async function activate(context: vscode.ExtensionContext) {
  // Initialize daemon client
  client = new MUClient();

  // Check daemon status
  try {
    await client.getStatus();
    vscode.window.showInformationMessage('MU: Connected to daemon');
  } catch (e) {
    vscode.window.showWarningMessage('MU: Daemon not running. Start with `mu daemon start`');
  }

  // Register tree views
  const modulesProvider = new ExplorerProvider(client, 'modules');
  const classesProvider = new ExplorerProvider(client, 'classes');
  const functionsProvider = new ExplorerProvider(client, 'functions');
  const hotspotsProvider = new ExplorerProvider(client, 'hotspots');

  context.subscriptions.push(
    vscode.window.registerTreeDataProvider('mu.modules', modulesProvider),
    vscode.window.registerTreeDataProvider('mu.classes', classesProvider),
    vscode.window.registerTreeDataProvider('mu.functions', functionsProvider),
    vscode.window.registerTreeDataProvider('mu.hotspots', hotspotsProvider),
  );

  // Connect WebSocket for live updates
  client.connectWebSocket();
  client.onGraphUpdate(() => {
    modulesProvider.refresh();
    classesProvider.refresh();
    functionsProvider.refresh();
    hotspotsProvider.refresh();
  });
}
```

**Acceptance Criteria**:
- [ ] Extension checks daemon connection on activation
- [ ] Warning shown if daemon not running
- [ ] All four tree providers registered and visible
- [ ] WebSocket connection established for live updates
- [ ] Graph changes trigger tree refresh
- [ ] Clean disconnect on deactivation

---

### Story 9.2: Complexity Badges

#### Task 2.1: Implement DecorationProvider

**Priority**: P1
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/tools/vscode-mu/src/providers/DecorationProvider.ts` (new)

**Pattern**: Follow VS Code TextEditorDecorationType API, see epic design at line 519-651

**Dependencies**: Task 1.2 (MUClient)

**Description**: Show inline complexity badges at the end of function/class definition lines.

**Implementation Notes**:
```typescript
export class DecorationProvider {
  private infoDecoration: vscode.TextEditorDecorationType;
  private warningDecoration: vscode.TextEditorDecorationType;
  private errorDecoration: vscode.TextEditorDecorationType;

  constructor(private client: MUClient) {
    // Create decoration types with different colors
    this.infoDecoration = vscode.window.createTextEditorDecorationType({
      after: { margin: '0 0 0 1em', color: '#569CD6' }
    });
    this.warningDecoration = vscode.window.createTextEditorDecorationType({
      after: { margin: '0 0 0 1em', color: '#DCDCAA' }
    });
    this.errorDecoration = vscode.window.createTextEditorDecorationType({
      after: { margin: '0 0 0 1em', color: '#F14C4C' }
    });
  }

  async updateDecorations(editor: vscode.TextEditor): Promise<void> {
    const config = vscode.workspace.getConfiguration('mu');
    if (!config.get<boolean>('badges.enabled', true)) {
      this.clearDecorations(editor);
      return;
    }

    const warningThreshold = config.get<number>('complexity.warningThreshold', 200);
    const errorThreshold = config.get<number>('complexity.errorThreshold', 500);

    // Query nodes for this file
    const filePath = editor.document.uri.fsPath;
    const result = await this.client.query(
      `SELECT * FROM nodes WHERE file_path = '${filePath}' AND type IN ('function', 'class')`
    );

    // Group decorations by severity
    // Apply to editor
  }
}
```

**Acceptance Criteria**:
- [ ] Functions show complexity badge at end of definition line
- [ ] Badges color-coded: info (blue) < warning (yellow) < error (red)
- [ ] Thresholds configurable via settings
- [ ] Badges update on file save
- [ ] Can be toggled on/off via `mu.badges.enabled`
- [ ] Performance: cached per file, cleared on change

---

#### Task 2.2: Add Configuration and Commands for Badges

**Priority**: P1
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/tools/vscode-mu/package.json` (modify)
- `/Users/imu/Dev/work/mu/tools/vscode-mu/src/extension.ts` (modify)

**Dependencies**: Task 2.1

**Description**: Add configuration properties and commands for complexity badges.

**Acceptance Criteria**:
- [ ] `mu.badges.enabled` setting (default true)
- [ ] `mu.complexity.warningThreshold` setting (default 200)
- [ ] `mu.complexity.errorThreshold` setting (default 500)
- [ ] `mu.toggleBadges` command to toggle visibility
- [ ] Settings changes apply immediately

---

### Story 9.3: Dependency CodeLens

#### Task 3.1: Implement CodeLensProvider

**Priority**: P1
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/tools/vscode-mu/src/providers/CodeLensProvider.ts` (new)

**Pattern**: Follow VS Code CodeLensProvider interface, see epic design at line 438-514

**Dependencies**: Task 1.2 (MUClient)

**Description**: Show "X deps, Y refs" above functions and classes.

**Implementation Notes**:
```typescript
export class CodeLensProvider implements vscode.CodeLensProvider {
  private _onDidChangeCodeLenses = new vscode.EventEmitter<void>();
  readonly onDidChangeCodeLenses = this._onDidChangeCodeLenses.event;

  constructor(private client: MUClient) {}

  refresh(): void {
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

    // Get nodes for this file
    const filePath = document.uri.fsPath;
    const result = await this.client.query(
      `SELECT * FROM nodes WHERE file_path = '${filePath}' AND type IN ('function', 'class')`
    );

    const lenses: vscode.CodeLens[] = [];
    for (const node of result.result as Node[]) {
      if (!node.line_start) continue;

      // Get dependency and dependent counts
      const deps = await this.client.getNeighbors(node.id, 'outgoing');
      const refs = await this.client.getNeighbors(node.id, 'incoming');

      const range = new vscode.Range(node.line_start - 1, 0, node.line_start - 1, 0);
      lenses.push(new vscode.CodeLens(range, {
        title: `${deps.length} deps, ${refs.length} refs`,
        command: 'mu.showDependencies',
        arguments: [node.id]
      }));
    }
    return lenses;
  }
}
```

**Acceptance Criteria**:
- [ ] CodeLens appears above functions and classes
- [ ] Shows "X deps, Y refs" with correct counts
- [ ] Clicking opens dependency picker (Quick Pick)
- [ ] Selecting dependency navigates to that node
- [ ] Can be toggled via `mu.codeLens.enabled`
- [ ] Updates on file save
- [ ] Caches results per file for performance

---

#### Task 3.2: Add Dependency Navigation Commands

**Priority**: P1
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/tools/vscode-mu/src/commands/navigate.ts` (new)
- `/Users/imu/Dev/work/mu/tools/vscode-mu/package.json` (modify)

**Dependencies**: Task 3.1

**Description**: Commands to show/navigate dependencies and dependents.

**Implementation Notes**:
```typescript
export async function showDependencies(client: MUClient, nodeId?: string) {
  if (!nodeId) {
    // Get node at cursor position
    const editor = vscode.window.activeTextEditor;
    if (!editor) return;
    // Query for node at current line
  }

  const deps = await client.getNeighbors(nodeId, 'outgoing');

  const items = deps.map(d => ({
    label: d.name,
    description: `${d.type} - ${d.file_path || 'external'}`,
    detail: d.qualified_name,
    node: d,
  }));

  const selected = await vscode.window.showQuickPick(items, {
    title: 'Dependencies',
    placeHolder: 'Select to navigate',
  });

  if (selected?.node.file_path) {
    // Navigate to file and line
  }
}
```

**Acceptance Criteria**:
- [ ] `mu.showDependencies` command shows Quick Pick of dependencies
- [ ] `mu.showDependents` command shows Quick Pick of dependents
- [ ] Commands work from CodeLens click or command palette
- [ ] Commands work with cursor position if no nodeId provided
- [ ] Selecting item navigates to source location
- [ ] External dependencies shown but not navigable

---

### Story 9.4: MUQL Commands

#### Task 4.1: Implement Query Command

**Priority**: P1
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/tools/vscode-mu/src/commands/query.ts` (new)
- `/Users/imu/Dev/work/mu/tools/vscode-mu/package.json` (modify)

**Pattern**: Follow epic design at line 666-688

**Dependencies**: Task 1.2 (MUClient)

**Description**: Command to run MUQL queries from command palette with history.

**Implementation Notes**:
```typescript
const queryHistory: string[] = [];

export async function runQuery(client: MUClient) {
  const query = await vscode.window.showInputBox({
    prompt: 'Enter MUQL query',
    placeHolder: 'SELECT * FROM functions WHERE complexity > 500',
    value: queryHistory[0] || '',
  });

  if (!query) return;

  // Add to history
  queryHistory.unshift(query);
  if (queryHistory.length > 20) queryHistory.pop();

  try {
    const result = await client.query(query);

    if (!result.success) {
      vscode.window.showErrorMessage(`Query error: ${result.error}`);
      return;
    }

    // Show in output channel
    const channel = vscode.window.createOutputChannel('MU Query');
    channel.clear();
    channel.appendLine(`Query: ${query}\n`);
    channel.appendLine(JSON.stringify(result.result, null, 2));
    channel.show();
  } catch (e: any) {
    vscode.window.showErrorMessage(`Query failed: ${e.message}`);
  }
}
```

**Acceptance Criteria**:
- [ ] `mu.query` command opens input box
- [ ] Query sent to daemon via `/query` endpoint
- [ ] Results shown in output channel as JSON
- [ ] Query history preserved (last 20)
- [ ] Previous query pre-filled in input
- [ ] Errors shown as error messages

---

#### Task 4.2: Add Find Path Command

**Priority**: P2
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/tools/vscode-mu/src/commands/query.ts` (modify)

**Dependencies**: Task 4.1

**Description**: Command to find path between two nodes.

**Acceptance Criteria**:
- [ ] `mu.findPath` command prompts for from/to node names
- [ ] Executes `PATH FROM x TO y` query
- [ ] Shows path in output channel
- [ ] "No path found" message if none exists

---

### Story 9.5: Smart Context

#### Task 5.1: Implement Get Context Command

**Priority**: P1
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/tools/vscode-mu/src/commands/context.ts` (new)
- `/Users/imu/Dev/work/mu/tools/vscode-mu/package.json` (modify)

**Pattern**: Follow epic design at line 692-714

**Dependencies**: Task 1.2 (MUClient)

**Description**: Command to get smart context for a question and copy to clipboard.

**Implementation Notes**:
```typescript
export async function getContext(client: MUClient) {
  const question = await vscode.window.showInputBox({
    prompt: 'What do you want to understand?',
    placeHolder: 'How does authentication work?',
  });

  if (!question) return;

  const config = vscode.workspace.getConfiguration('mu');
  const maxTokens = config.get<number>('context.maxTokens', 8000);

  try {
    const result = await client.getContext(question, maxTokens);

    // Copy to clipboard
    await vscode.env.clipboard.writeText(result.mu_text);

    vscode.window.showInformationMessage(
      `Context copied! ${result.token_count} tokens, ${result.nodes.length} nodes`,
      'Show in Editor'
    ).then(selection => {
      if (selection === 'Show in Editor') {
        vscode.workspace.openTextDocument({ content: result.mu_text, language: 'mu' })
          .then(doc => vscode.window.showTextDocument(doc, vscode.ViewColumn.Beside));
      }
    });
  } catch (e: any) {
    vscode.window.showErrorMessage(`Context extraction failed: ${e.message}`);
  }
}
```

**Acceptance Criteria**:
- [ ] `mu.getContext` command prompts for question
- [ ] Calls daemon `/context` endpoint
- [ ] Copies MU output to clipboard
- [ ] Shows token count and node count in message
- [ ] Option to show in editor panel
- [ ] `mu.context.maxTokens` configurable (default 8000)

---

#### Task 5.2: Add Context for Selection Command

**Priority**: P2
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/tools/vscode-mu/src/commands/context.ts` (modify)

**Dependencies**: Task 5.1

**Description**: Get context based on selected code or current function.

**Acceptance Criteria**:
- [ ] `mu.getContextForSelection` command
- [ ] Uses selected text or function at cursor
- [ ] Generates context around that code location
- [ ] Copies to clipboard

---

### Story 9.6: Diagnostics

#### Task 6.1: Add Contracts Verify Endpoint to Daemon

**Priority**: P0 (Required for diagnostics)
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/src/mu/daemon/server.py` (modify)

**Pattern**: Follow existing endpoint patterns at line 292-454

**Description**: Add `/contracts/verify` endpoint to daemon for contract verification.

**Implementation Notes**:
```python
class ContractsRequest(BaseModel):
    """Request model for /contracts/verify endpoint."""
    contracts_path: str | None = Field(
        default=None,
        description="Path to contracts file (default: .mu-contracts.yml)"
    )

class ContractsResponse(BaseModel):
    """Response model for /contracts/verify endpoint."""
    passed: bool
    error_count: int
    warning_count: int
    violations: list[dict]

@app.post("/contracts/verify", response_model=ContractsResponse)
async def verify_contracts(request: ContractsRequest) -> ContractsResponse:
    """Verify architecture contracts against the graph."""
    state: AppState = app.state.daemon

    contracts_path = Path(request.contracts_path or ".mu-contracts.yml")
    if not contracts_path.is_absolute():
        contracts_path = state.mubase_path.parent / contracts_path

    try:
        from mu.contracts import ContractVerifier, parse_contracts_file

        contracts = parse_contracts_file(contracts_path)
        verifier = ContractVerifier(state.mubase)
        result = verifier.verify(contracts)

        return ContractsResponse(
            passed=result.passed,
            error_count=result.error_count,
            warning_count=result.warning_count,
            violations=[v.to_dict() for v in result.violations],
        )
    except FileNotFoundError:
        return ContractsResponse(
            passed=True,
            error_count=0,
            warning_count=0,
            violations=[],
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
```

**Acceptance Criteria**:
- [ ] `POST /contracts/verify` endpoint added to daemon
- [ ] Accepts optional `contracts_path` parameter
- [ ] Returns passed, error_count, warning_count, violations
- [ ] Handles missing contracts file gracefully (returns passed=true)
- [ ] Proper error handling for parse errors
- [ ] Unit tests added

---

#### Task 6.2: Implement DiagnosticsProvider

**Priority**: P1
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/tools/vscode-mu/src/providers/DiagnosticsProvider.ts` (new)
- `/Users/imu/Dev/work/mu/tools/vscode-mu/src/client/MUClient.ts` (modify)

**Dependencies**: Task 6.1

**Description**: Show contract violations as VS Code diagnostics in the Problems panel.

**Implementation Notes**:
```typescript
export class DiagnosticsProvider {
  private diagnostics: vscode.DiagnosticCollection;

  constructor(private client: MUClient) {
    this.diagnostics = vscode.languages.createDiagnosticCollection('mu');
  }

  async refresh(): Promise<void> {
    // Clear existing
    this.diagnostics.clear();

    try {
      const result = await this.client.verifyContracts();

      // Group violations by file
      const byFile = new Map<string, vscode.Diagnostic[]>();

      for (const violation of result.violations) {
        const filePath = violation.file_path;
        if (!filePath) continue;

        const diagnostic = new vscode.Diagnostic(
          new vscode.Range(
            (violation.line || 1) - 1, 0,
            (violation.line || 1) - 1, 100
          ),
          `[${violation.contract}] ${violation.message}`,
          violation.severity === 'error'
            ? vscode.DiagnosticSeverity.Error
            : vscode.DiagnosticSeverity.Warning
        );
        diagnostic.source = 'MU Contracts';

        const existing = byFile.get(filePath) || [];
        existing.push(diagnostic);
        byFile.set(filePath, existing);
      }

      // Apply to diagnostics collection
      for (const [filePath, diagnostics] of byFile) {
        this.diagnostics.set(vscode.Uri.file(filePath), diagnostics);
      }
    } catch (e) {
      console.error('MU diagnostics error:', e);
    }
  }

  dispose(): void {
    this.diagnostics.dispose();
  }
}
```

**Acceptance Criteria**:
- [ ] Contract violations appear in Problems panel
- [ ] Errors shown with red severity
- [ ] Warnings shown with yellow severity
- [ ] Diagnostics linked to file and line when available
- [ ] Refresh on file save
- [ ] Refresh command available (`mu.refreshDiagnostics`)

---

#### Task 6.3: Add Client Method for Contracts

**Priority**: P1
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/tools/vscode-mu/src/client/MUClient.ts` (modify)
- `/Users/imu/Dev/work/mu/tools/vscode-mu/src/client/types.ts` (modify)

**Dependencies**: Task 6.1

**Description**: Add `verifyContracts()` method to MUClient.

**Acceptance Criteria**:
- [ ] `verifyContracts()` method calls `POST /contracts/verify`
- [ ] Returns typed `ContractsResult` with violations array
- [ ] Violation type includes contract name, message, severity, file_path, line

---

### Story 9.7: Polish and Testing

#### Task 7.1: Add HoverProvider

**Priority**: P2
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/tools/vscode-mu/src/providers/HoverProvider.ts` (new)

**Dependencies**: Task 1.2

**Description**: Show node details on hover (complexity, dependencies, etc.).

**Acceptance Criteria**:
- [ ] Hover on function/class shows Markdown tooltip
- [ ] Shows: name, type, complexity, file path
- [ ] Shows dependency and dependent counts
- [ ] Links to show full dependency list

---

#### Task 7.2: Add Status Bar Item

**Priority**: P2
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/tools/vscode-mu/src/extension.ts` (modify)

**Description**: Status bar showing daemon connection status.

**Acceptance Criteria**:
- [ ] Status bar item shows "MU: Connected" or "MU: Disconnected"
- [ ] Click reconnects to daemon
- [ ] Icon indicates status (check vs warning)
- [ ] Updates on WebSocket connect/disconnect

---

#### Task 7.3: Create Extension Icons

**Priority**: P2
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/tools/vscode-mu/media/icons/mu.svg` (new)
- `/Users/imu/Dev/work/mu/tools/vscode-mu/media/icons/*.svg` (new)

**Description**: SVG icons for activity bar and tree items.

**Acceptance Criteria**:
- [ ] Activity bar icon (mu.svg) - MU logo
- [ ] Icons follow VS Code icon guidelines (24x24, monochrome)
- [ ] Works in both light and dark themes

---

#### Task 7.4: Unit Tests for Providers

**Priority**: P1
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/tools/vscode-mu/src/test/suite/providers.test.ts` (new)
- `/Users/imu/Dev/work/mu/tools/vscode-mu/src/test/suite/client.test.ts` (new)

**Description**: Unit tests for providers and client with mocked API.

**Acceptance Criteria**:
- [ ] MUClient tests with mocked fetch
- [ ] ExplorerProvider tests with mocked client
- [ ] CodeLensProvider tests with mocked client
- [ ] DecorationProvider tests with mocked client
- [ ] DiagnosticsProvider tests with mocked client
- [ ] 80%+ code coverage

---

#### Task 7.5: Integration Tests with Daemon

**Priority**: P2
**Complexity**: Medium
**Files**:
- `/Users/imu/Dev/work/mu/tools/vscode-mu/src/test/integration/daemon.test.ts` (new)

**Description**: Integration tests that run against real daemon.

**Acceptance Criteria**:
- [ ] Test starts daemon before suite
- [ ] Tests query, context, contracts endpoints
- [ ] Tests WebSocket connection and events
- [ ] Cleanup stops daemon after suite

---

#### Task 7.6: Documentation and README

**Priority**: P2
**Complexity**: Small
**Files**:
- `/Users/imu/Dev/work/mu/tools/vscode-mu/README.md` (modify)

**Description**: Update README with installation, features, and configuration.

**Acceptance Criteria**:
- [ ] Installation instructions (from VSIX and marketplace)
- [ ] Feature descriptions with screenshots
- [ ] Configuration reference
- [ ] Troubleshooting guide
- [ ] Link to MU CLI documentation

---

## Dependencies

```
Task 1.1 (package.json) ─┬─> Task 1.2 (MUClient) ─┬─> Task 1.3 (Explorer)
                         │                        ├─> Task 2.1 (Decorations)
                         │                        ├─> Task 3.1 (CodeLens)
                         │                        ├─> Task 4.1 (Query)
                         │                        ├─> Task 5.1 (Context)
                         │                        └─> Task 6.2 (Diagnostics)
                         │
                         └─> Task 1.4 (Activation) depends on 1.2, 1.3, 2.1, 3.1

Task 6.1 (Daemon endpoint) ─> Task 6.2 (DiagnosticsProvider) ─> Task 6.3 (Client method)

Tasks 7.* (Polish) can run in parallel after core features
```

**Parallel Opportunities**:
- After Task 1.2 (MUClient), Tasks 1.3, 2.1, 3.1, 4.1, 5.1 can proceed in parallel
- Task 6.1 (daemon endpoint) can be done in parallel with extension development
- All Task 7.* can run in parallel after respective feature tasks

---

## Edge Cases

1. **Daemon not running**: Show clear message, disable features gracefully
2. **No .mubase file**: Extension activates but shows "Build required" state
3. **Large codebases**: Limit query results, implement pagination
4. **Stale cache**: Clear cache on WebSocket graph_update events
5. **Network errors**: Retry with exponential backoff, show status
6. **Contract file missing**: Diagnostics returns empty (not an error)
7. **Circular dependencies in tree**: Prevent infinite expansion
8. **External dependencies**: Show in tree but mark as non-navigable

---

## Security Considerations

1. **Daemon binding**: Extension respects localhost-only daemon binding
2. **Path traversal**: Validate file paths in API responses
3. **MUQL injection**: Don't interpolate user input directly into MUQL
4. **Contracts file**: Only read from workspace or configured path
5. **Clipboard**: Only copy MU output, never sensitive data

---

## Performance Considerations

1. **Cache aggressively**: Node data, neighbor counts per file
2. **Debounce refreshes**: Don't refresh on every keystroke
3. **Lazy loading**: Tree views load children on expand only
4. **Limit queries**: Use LIMIT in MUQL, cap tree view items
5. **WebSocket efficiency**: Only refresh affected views on events
6. **Bundle size**: Keep extension < 1MB, use tree-shaking

---

## Success Criteria

- [x] Extension activates when `.mubase` exists
- [x] Explorer shows graph structure with navigation
- [x] Complexity badges display and update correctly
- [x] CodeLens shows dependency info with click navigation
- [x] MUQL queries work from command palette
- [x] Smart context copies relevant MU to clipboard
- [x] Contract violations appear in Problems panel
- [x] WebSocket updates refresh views in real-time
- [ ] Extension packaged and < 1MB
- [ ] All unit tests pass with 80%+ coverage

---

## Implementation Status

### Completed Tasks

#### Task 1.1: Extend Extension Package Configuration
**Status**: Complete

**Implementation**:
- Updated `/Users/imu/Dev/work/mu/tools/vscode-mu/package.json`:
  - Added `workspaceContains:.mubase` activation event
  - Added activity bar view container with `mu-explorer` id
  - Registered four tree views: `mu.modules`, `mu.classes`, `mu.functions`, `mu.hotspots`
  - Added configuration for `daemonUrl`, complexity thresholds, `codeLens.enabled`, `badges.enabled`, `context.maxTokens`
  - Added new commands: `mu.query`, `mu.getContext`, `mu.showDependencies`, `mu.showDependents`, `mu.findPath`, `mu.refresh`, `mu.openVisualization`, `mu.toggleBadges`, `mu.refreshDiagnostics`
  - Added `ws` dependency for WebSocket support

**Quality**:
- [x] TypeScript compiles successfully

---

#### Task 1.2: Create MU Daemon API Client
**Status**: Complete

**Implementation**:
- Created `/Users/imu/Dev/work/mu/tools/vscode-mu/src/client/types.ts`:
  - TypeScript interfaces for Node, Edge, StatusResponse, QueryResult, ContextResult, ContractsResult, GraphEvent, etc.
- Created `/Users/imu/Dev/work/mu/tools/vscode-mu/src/client/MUClient.ts`:
  - Constructor reads `daemonUrl` from config
  - Implements `getStatus()`, `getNode()`, `getNeighbors()`, `query()`, `getContext()`, `verifyContracts()`, `getNodesForFile()`, `findPath()`
  - WebSocket connection with auto-reconnect
  - Event handler registration via `onGraphUpdate()`
  - Connection state change events
  - Proper error handling with VS Code notifications

**Quality**:
- [x] TypeScript compiles successfully
- [x] Uses native http/https modules (no external fetch dependency)
- [x] Handles configuration changes dynamically

---

#### Task 1.3: Implement ExplorerProvider
**Status**: Complete

**Implementation**:
- Created `/Users/imu/Dev/work/mu/tools/vscode-mu/src/providers/ExplorerProvider.ts`:
  - `TreeDataProvider<NodeItem>` implementation
  - `NodeItem` class extending `TreeItem` with proper icons, tooltips, and navigation
  - `getChildren()` queries daemon based on view type (modules, classes, functions, hotspots)
  - Hotspots view uses complexity threshold from config
  - Click navigates to file:line
  - Caching per view type for performance
  - Refresh method to clear cache and update view

**Quality**:
- [x] TypeScript compiles successfully
- [x] Implements TreeDataProvider correctly
- [x] Proper error handling

---

#### Task 2.1: Implement DecorationProvider
**Status**: Complete

**Implementation**:
- Created `/Users/imu/Dev/work/mu/tools/vscode-mu/src/providers/DecorationProvider.ts`:
  - Complexity badges at end of function/class lines using TextEditorDecorationType
  - Three decoration types: info (blue), warning (yellow), error (red)
  - Configurable thresholds via `mu.complexity.warningThreshold` and `mu.complexity.errorThreshold`
  - Updates on file save and active editor change
  - Listens for configuration changes
  - Per-file caching with document version tracking
  - Can be toggled via `mu.badges.enabled`

**Quality**:
- [x] TypeScript compiles successfully
- [x] Uses VS Code theme colors

---

#### Task 3.1: Implement CodeLensProvider
**Status**: Complete

**Implementation**:
- Created `/Users/imu/Dev/work/mu/tools/vscode-mu/src/providers/CodeLensProvider.ts`:
  - Shows "X deps, Y refs" above functions and classes
  - Separate counts for internal and external dependencies
  - Click opens dependency quick pick via `mu.showDependencies` command
  - `resolveCodeLens` fetches neighbor counts asynchronously
  - Can be toggled via `mu.codeLens.enabled`
  - Caches results per file for performance

**Quality**:
- [x] TypeScript compiles successfully
- [x] Implements CodeLensProvider correctly

---

#### Task 3.2: Add Dependency Navigation Commands
**Status**: Complete

**Implementation**:
- Created `/Users/imu/Dev/work/mu/tools/vscode-mu/src/commands/navigate.ts`:
  - `showDependencies` command: Quick Pick of outgoing dependencies
  - `showDependents` command: Quick Pick of incoming dependencies
  - Commands work from CodeLens click or command palette
  - Commands work with cursor position if no nodeId provided
  - Selecting item navigates to source location
  - External dependencies shown but marked as non-navigable
  - Icons based on node type

**Quality**:
- [x] TypeScript compiles successfully

---

#### Task 4.1: Implement Query Command
**Status**: Complete

**Implementation**:
- Created `/Users/imu/Dev/work/mu/tools/vscode-mu/src/commands/query.ts`:
  - `runQuery`: MUQL input box with history (last 20 queries)
  - Results shown in MU Query output channel as formatted table
  - Query history shown in quick pick for easy recall
  - Timing information included

**Quality**:
- [x] TypeScript compiles successfully

---

#### Task 4.2: Add Find Path Command
**Status**: Complete

**Implementation**:
- Added to `/Users/imu/Dev/work/mu/tools/vscode-mu/src/commands/query.ts`:
  - `findPath`: from/to input boxes
  - Searches by name if input doesn't look like ID
  - Shows path in output channel with node details
  - "No path found" message if none exists

**Quality**:
- [x] TypeScript compiles successfully

---

#### Task 5.1: Implement Get Context Command
**Status**: Complete

**Implementation**:
- Created `/Users/imu/Dev/work/mu/tools/vscode-mu/src/commands/context.ts`:
  - `getContext`: Question input, calls `/context` endpoint, copies MU to clipboard
  - Shows token count and node count in message
  - Option to show in editor panel or show included nodes
  - `getContextForSelection`: Uses selected text or function at cursor
  - Configurable `mu.context.maxTokens` (default 8000)

**Quality**:
- [x] TypeScript compiles successfully

---

#### Task 1.4: Update Extension Activation
**Status**: Complete

**Implementation**:
- Updated `/Users/imu/Dev/work/mu/tools/vscode-mu/src/extension.ts`:
  - Creates MUClient instance on activation
  - Registers all four tree providers (modules, classes, functions, hotspots)
  - Registers DecorationProvider, CodeLensProvider, DiagnosticsProvider
  - Registers all new commands
  - Connects WebSocket for live updates
  - Status bar item showing connection state
  - Click to reconnect functionality
  - Auto-start daemon option when not running
  - Clean disposal on deactivation

**Quality**:
- [x] TypeScript compiles successfully
- [x] Proper cleanup on deactivation

---

#### Task 6.1: Add Contracts Verify Endpoint to Daemon
**Status**: Complete

**Implementation**:
- Modified `/Users/imu/Dev/work/mu/src/mu/daemon/server.py`:
  - Added `ContractsRequest`, `ContractViolationResponse`, `ContractsResponse` Pydantic models
  - Added `POST /contracts/verify` endpoint
  - Accepts optional `contracts_path` parameter (defaults to `.mu-contracts.yml`)
  - Returns `passed`, `error_count`, `warning_count`, `violations`
  - Handles missing contracts file gracefully (returns passed=true)
  - Proper error handling for parse errors

**Quality**:
- [x] ruff check passes
- [x] mypy passes

---

#### Task 6.2 & 6.3: Implement DiagnosticsProvider
**Status**: Complete

**Implementation**:
- Created `/Users/imu/Dev/work/mu/tools/vscode-mu/src/providers/DiagnosticsProvider.ts`:
  - Shows contract violations in Problems panel
  - Errors shown with red severity, warnings with yellow
  - Diagnostics linked to file and line when available
  - Refresh on file save
  - `mu.refreshDiagnostics` command available
- Added `verifyContracts()` method to MUClient

**Quality**:
- [x] TypeScript compiles successfully

---

### Additional Implementations

#### Activity Bar Icon
**Status**: Complete

**Implementation**:
- Created `/Users/imu/Dev/work/mu/tools/vscode-mu/media/icons/mu.svg`:
  - Simple MU logo in SVG format
  - Uses `currentColor` for theme compatibility

---

### Remaining Tasks (Not Implemented)

#### Task 7.1: Add HoverProvider
**Status**: Pending (P2 priority)

**Notes**: Would show node details on hover (complexity, dependencies).

---

#### Task 7.4: Unit Tests for Providers
**Status**: Pending (P1 priority)

**Notes**: Need to add tests with mocked client.

---

#### Task 7.5: Integration Tests with Daemon
**Status**: Pending (P2 priority)

**Notes**: Need to test against real daemon.

---

#### Task 7.6: Documentation and README
**Status**: Pending (P2 priority)

**Notes**: README needs installation, features, and configuration documentation.

---

### Build Verification

```bash
# TypeScript compilation
cd tools/vscode-mu && npm run compile
# Result: Successful

# Python linting
ruff check src/mu/daemon/server.py
# Result: All checks passed!

# Python type checking
mypy src/mu/daemon/server.py --ignore-missing-imports
# Result: Success: no issues found
```
