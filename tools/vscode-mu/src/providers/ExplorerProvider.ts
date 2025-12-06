/**
 * Explorer Provider
 *
 * Tree data provider for the MU Explorer sidebar views.
 * Shows modules, classes, functions, and hotspots from the code graph.
 */

import * as vscode from 'vscode';
import { MUClient, Node, NodeType } from '../client';

/** View types for the explorer */
export type ViewType = 'modules' | 'classes' | 'functions' | 'hotspots';

/**
 * Tree item representing a node in the code graph
 */
export class NodeItem extends vscode.TreeItem {
    constructor(
        public readonly node: Node,
        public readonly collapsibleState: vscode.TreeItemCollapsibleState = vscode.TreeItemCollapsibleState.None
    ) {
        super(node.name, collapsibleState);

        // Set item properties based on node type
        this.id = node.id;
        this.tooltip = this.buildTooltip();
        this.description = this.buildDescription();
        this.iconPath = this.getIcon();
        this.contextValue = `mu.node.${node.type}`;

        // Make it clickable to navigate to source
        if (node.file_path && node.line_start) {
            this.command = {
                command: 'vscode.open',
                title: 'Go to Definition',
                arguments: [
                    vscode.Uri.file(node.file_path),
                    {
                        selection: new vscode.Range(
                            node.line_start - 1,
                            0,
                            node.line_start - 1,
                            0
                        ),
                    },
                ],
            };
        }
    }

    private buildTooltip(): string {
        const parts: string[] = [];

        if (this.node.qualified_name) {
            parts.push(this.node.qualified_name);
        } else {
            parts.push(this.node.name);
        }

        parts.push(`Type: ${this.node.type}`);

        if (this.node.complexity !== undefined && this.node.complexity > 0) {
            parts.push(`Complexity: ${this.node.complexity}`);
        }

        if (this.node.file_path) {
            parts.push(`File: ${this.node.file_path}`);
            if (this.node.line_start) {
                parts.push(`Line: ${this.node.line_start}`);
            }
        }

        return parts.join('\n');
    }

    private buildDescription(): string {
        const parts: string[] = [];

        if (this.node.complexity !== undefined && this.node.complexity > 0) {
            parts.push(`C:${this.node.complexity}`);
        }

        if (this.node.file_path) {
            // Show just the filename
            const fileName = this.node.file_path.split('/').pop() || '';
            parts.push(fileName);
        }

        return parts.join(' | ');
    }

    private getIcon(): vscode.ThemeIcon {
        switch (this.node.type) {
            case 'module':
                return new vscode.ThemeIcon('file-code');
            case 'class':
                return new vscode.ThemeIcon('symbol-class');
            case 'function':
                return new vscode.ThemeIcon('symbol-method');
            case 'external':
                return new vscode.ThemeIcon('package');
            default:
                return new vscode.ThemeIcon('circle-outline');
        }
    }
}

/**
 * Tree data provider for MU Explorer views
 */
export class ExplorerProvider implements vscode.TreeDataProvider<NodeItem> {
    private _onDidChangeTreeData = new vscode.EventEmitter<NodeItem | undefined | void>();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

    private cache: Map<string, Node[]> = new Map();
    private isLoading = false;

    constructor(
        private readonly client: MUClient,
        private readonly viewType: ViewType
    ) {}

    /**
     * Refresh the tree view
     */
    refresh(): void {
        this.cache.clear();
        this._onDidChangeTreeData.fire();
    }

    getTreeItem(element: NodeItem): vscode.TreeItem {
        return element;
    }

    async getChildren(element?: NodeItem): Promise<NodeItem[]> {
        if (this.isLoading) {
            return [];
        }

        try {
            if (!element) {
                // Root level - query based on view type
                return await this.getRootNodes();
            } else {
                // Children - get contained nodes
                return await this.getChildNodes(element.node.id);
            }
        } catch (err) {
            console.error(`MU Explorer (${this.viewType}): Failed to get children:`, err);
            return [];
        }
    }

    private async getRootNodes(): Promise<NodeItem[]> {
        const cacheKey = `root:${this.viewType}`;
        const cached = this.cache.get(cacheKey);
        if (cached) {
            return this.nodesToItems(cached, true);
        }

        this.isLoading = true;
        try {
            const query = this.getQueryForViewType();
            const result = await this.client.query(query);

            if (!result.success) {
                vscode.window.showWarningMessage(`MU: Query failed - ${result.error}`);
                return [];
            }

            const nodes = (result.result as Node[]) || [];
            this.cache.set(cacheKey, nodes);
            return this.nodesToItems(nodes, true);
        } finally {
            this.isLoading = false;
        }
    }

    private async getChildNodes(parentId: string): Promise<NodeItem[]> {
        const cacheKey = `children:${parentId}`;
        const cached = this.cache.get(cacheKey);
        if (cached) {
            return this.nodesToItems(cached, false);
        }

        try {
            const neighbors = await this.client.getNeighbors(parentId, 'outgoing');
            // Filter to only include non-external contained nodes
            const children = neighbors.filter(
                (n) => n.type !== 'external' && this.isContainedType(n.type)
            );
            this.cache.set(cacheKey, children);
            return this.nodesToItems(children, false);
        } catch (err) {
            console.error(`MU Explorer: Failed to get children for ${parentId}:`, err);
            return [];
        }
    }

    private getQueryForViewType(): string {
        switch (this.viewType) {
            case 'modules':
                return "SELECT * FROM nodes WHERE type = 'module' ORDER BY name";
            case 'classes':
                return "SELECT * FROM nodes WHERE type = 'class' ORDER BY name LIMIT 200";
            case 'functions':
                return "SELECT * FROM nodes WHERE type = 'function' ORDER BY name LIMIT 100";
            case 'hotspots':
                return this.getHotspotsQuery();
            default:
                return "SELECT * FROM nodes WHERE type = 'module'";
        }
    }

    private getHotspotsQuery(): string {
        const config = vscode.workspace.getConfiguration('mu');
        const warningThreshold = config.get<number>('complexity.warningThreshold', 200);
        return `SELECT * FROM nodes WHERE type = 'function' AND complexity > ${warningThreshold} ORDER BY complexity DESC LIMIT 50`;
    }

    private isContainedType(type: NodeType): boolean {
        // Classes can contain functions (methods)
        // Modules can contain classes and functions
        return type === 'class' || type === 'function';
    }

    private nodesToItems(nodes: Node[], isRoot: boolean): NodeItem[] {
        return nodes.map((node) => {
            // Modules and classes can be expanded to show children
            const canExpand =
                isRoot && (node.type === 'module' || node.type === 'class');
            const state = canExpand
                ? vscode.TreeItemCollapsibleState.Collapsed
                : vscode.TreeItemCollapsibleState.None;
            return new NodeItem(node, state);
        });
    }
}
