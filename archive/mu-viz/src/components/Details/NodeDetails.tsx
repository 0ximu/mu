import { useEffect, useState, useCallback } from 'react';
import {
  X,
  FileCode,
  Copy,
  Check,
  ExternalLink,
  GitBranch,
  Layers,
  Zap,
  ChevronRight,
  AlertTriangle,
} from 'lucide-react';
import { useGraphStore } from '../../store/graphStore';
import { useUIStore } from '../../store/uiStore';
import { muClient } from '../../api/client';
import type { Node, ImpactResult, AncestorsResult } from '../../api/types';
import { Button, Badge, Panel } from '../common';

export function NodeDetails() {
  const { selectedNode, setSelectedNode, elements, setHighlightedPath } = useGraphStore();
  const { setDetailsPanelOpen } = useUIStore();
  const [node, setNode] = useState<Node | null>(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  // Graph reasoning state
  const [impactResult, setImpactResult] = useState<ImpactResult | null>(null);
  const [ancestorsResult, setAncestorsResult] = useState<AncestorsResult | null>(null);
  const [reasoningLoading, setReasoningLoading] = useState<'impact' | 'ancestors' | null>(null);
  const [reasoningError, setReasoningError] = useState<string | null>(null);

  // Fetch full node details when selected
  useEffect(() => {
    if (!selectedNode) {
      setNode(null);
      return;
    }

    // Reset reasoning state when node changes
    setImpactResult(null);
    setAncestorsResult(null);
    setReasoningError(null);
    setHighlightedPath([]);

    setLoading(true);
    muClient
      .getNode(selectedNode)
      .then(setNode)
      .catch((err) => {
        console.error('Failed to fetch node:', err);
        // Fallback to elements data
        const elemNode = elements?.nodes.find((n) => n.data.id === selectedNode);
        if (elemNode) {
          setNode({
            id: elemNode.data.id,
            name: elemNode.data.label,
            type: elemNode.data.type,
            file_path: elemNode.data.file_path,
            line_start: elemNode.data.line_start,
            line_end: elemNode.data.line_end,
            complexity: elemNode.data.complexity,
          });
        }
      })
      .finally(() => setLoading(false));
  }, [selectedNode, elements, setHighlightedPath]);

  // Impact analysis handler
  const handleImpact = useCallback(async () => {
    if (!selectedNode) return;
    setReasoningLoading('impact');
    setReasoningError(null);
    setAncestorsResult(null);

    try {
      const result = await muClient.getImpact(selectedNode, ['imports']);
      setImpactResult(result);
      if (result.impacted_nodes.length > 0) {
        setHighlightedPath([selectedNode, ...result.impacted_nodes]);
      }
    } catch (err) {
      setReasoningError(err instanceof Error ? err.message : 'Impact analysis failed');
    } finally {
      setReasoningLoading(null);
    }
  }, [selectedNode, setHighlightedPath]);

  // Ancestors analysis handler
  const handleAncestors = useCallback(async () => {
    if (!selectedNode) return;
    setReasoningLoading('ancestors');
    setReasoningError(null);
    setImpactResult(null);

    try {
      const result = await muClient.getAncestors(selectedNode, ['imports']);
      setAncestorsResult(result);
      if (result.ancestor_nodes.length > 0) {
        setHighlightedPath([...result.ancestor_nodes, selectedNode]);
      }
    } catch (err) {
      setReasoningError(err instanceof Error ? err.message : 'Ancestors analysis failed');
    } finally {
      setReasoningLoading(null);
    }
  }, [selectedNode, setHighlightedPath]);

  // Clear reasoning results
  const handleClearReasoning = useCallback(() => {
    setImpactResult(null);
    setAncestorsResult(null);
    setReasoningError(null);
    setHighlightedPath([]);
  }, [setHighlightedPath]);

  const handleClose = () => {
    setSelectedNode(null);
    setDetailsPanelOpen(false);
  };

  const handleCopyMU = async () => {
    if (!node?.mu_representation) return;
    await navigator.clipboard.writeText(node.mu_representation);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Get connections from graph
  const connections = {
    incoming: elements?.edges.filter((e) => e.data.target === selectedNode) || [],
    outgoing: elements?.edges.filter((e) => e.data.source === selectedNode) || [],
  };

  if (!selectedNode) {
    return (
      <div className="h-full flex flex-col">
        {/* Header */}
        <div className="p-3 border-b-4 border-bauhaus-black bg-bauhaus-red">
          <span className="font-bold uppercase tracking-wider text-white">
            Details
          </span>
        </div>

        {/* Empty state */}
        <div className="flex-1 flex flex-col items-center justify-center p-6 text-center">
          <div className="w-16 h-16 mb-4 relative">
            <div className="absolute inset-0 bg-bauhaus-blue rounded-full opacity-20" />
            <div className="absolute inset-2 bg-bauhaus-red rotate-45" />
            <div className="absolute inset-4 bg-bauhaus-yellow rounded-full" />
          </div>
          <p className="font-bauhaus-heading text-bauhaus-black/60 mb-2">
            No Node Selected
          </p>
          <p className="text-sm text-bauhaus-black/40">
            Click on a node in the graph to view its details
          </p>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="h-full flex flex-col">
        <div className="p-3 border-b-4 border-bauhaus-black bg-bauhaus-red">
          <span className="font-bold uppercase tracking-wider text-white">
            Details
          </span>
        </div>
        <div className="flex-1 flex items-center justify-center">
          <div className="w-8 h-8 border-4 border-bauhaus-yellow border-t-transparent rounded-full animate-spin" />
        </div>
      </div>
    );
  }

  if (!node) {
    return (
      <div className="h-full flex flex-col">
        <div className="p-3 border-b-4 border-bauhaus-black bg-bauhaus-red">
          <span className="font-bold uppercase tracking-wider text-white">
            Details
          </span>
        </div>
        <div className="flex-1 flex items-center justify-center p-6">
          <p className="text-bauhaus-black/60">Node not found</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="p-3 border-b-4 border-bauhaus-black bg-bauhaus-red flex items-center justify-between">
        <span className="font-bold uppercase tracking-wider text-white">
          Details
        </span>
        <button
          onClick={handleClose}
          className="p-1 hover:bg-white/20 transition-colors"
        >
          <X className="w-5 h-5 text-white" />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Node Name & Type */}
        <div>
          <div className="flex items-start gap-2 mb-2">
            <TypeIndicator type={node.type} />
            <div className="flex-1 min-w-0">
              <h2 className="font-bold text-lg text-bauhaus-black break-words">
                {node.name}
              </h2>
              <Badge variant={getTypeVariant(node.type)}>{node.type}</Badge>
            </div>
          </div>
        </div>

        {/* Quick Stats */}
        <div className="grid grid-cols-2 gap-2">
          {node.complexity !== undefined && (
            <StatBox
              label="Complexity"
              value={node.complexity}
              color={node.complexity > 100 ? 'red' : 'blue'}
            />
          )}
          {node.line_start && node.line_end && (
            <StatBox
              label="Lines"
              value={`${node.line_end - node.line_start + 1}`}
              color="yellow"
            />
          )}
        </div>

        {/* File Location */}
        {node.file_path && (
          <Panel variant="default" decoration="square" className="p-3">
            <div className="flex items-center gap-2 mb-2">
              <FileCode className="w-4 h-4 text-bauhaus-black/60" />
              <span className="font-bauhaus-label text-bauhaus-black/60">
                Location
              </span>
            </div>
            <p className="text-sm font-mono break-all text-bauhaus-black">
              {node.file_path}
              {node.line_start && `:${node.line_start}`}
              {node.line_end && node.line_end !== node.line_start && `-${node.line_end}`}
            </p>
          </Panel>
        )}

        {/* Connections */}
        <div className="space-y-3">
          <h3 className="font-bauhaus-label text-bauhaus-black flex items-center gap-2">
            <GitBranch className="w-4 h-4" />
            Connections
          </h3>

          {/* Incoming */}
          {connections.incoming.length > 0 && (
            <div>
              <span className="text-xs font-bold uppercase text-bauhaus-black/60">
                Incoming ({connections.incoming.length})
              </span>
              <div className="mt-1 space-y-1">
                {connections.incoming.slice(0, 5).map((edge) => (
                  <ConnectionItem
                    key={edge.data.id}
                    nodeId={edge.data.source}
                    edgeType={edge.data.type}
                    elements={elements}
                    onClick={() => setSelectedNode(edge.data.source)}
                  />
                ))}
                {connections.incoming.length > 5 && (
                  <span className="text-xs text-bauhaus-black/40">
                    +{connections.incoming.length - 5} more
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Outgoing */}
          {connections.outgoing.length > 0 && (
            <div>
              <span className="text-xs font-bold uppercase text-bauhaus-black/60">
                Outgoing ({connections.outgoing.length})
              </span>
              <div className="mt-1 space-y-1">
                {connections.outgoing.slice(0, 5).map((edge) => (
                  <ConnectionItem
                    key={edge.data.id}
                    nodeId={edge.data.target}
                    edgeType={edge.data.type}
                    elements={elements}
                    onClick={() => setSelectedNode(edge.data.target)}
                  />
                ))}
                {connections.outgoing.length > 5 && (
                  <span className="text-xs text-bauhaus-black/40">
                    +{connections.outgoing.length - 5} more
                  </span>
                )}
              </div>
            </div>
          )}

          {connections.incoming.length === 0 && connections.outgoing.length === 0 && (
            <p className="text-sm text-bauhaus-black/40">No connections</p>
          )}
        </div>

        {/* Graph Reasoning - Impact & Ancestors */}
        <div className="space-y-3 pt-2 border-t-2 border-bauhaus-black">
          <h3 className="font-bauhaus-label text-bauhaus-black flex items-center gap-2">
            <Zap className="w-4 h-4" />
            Graph Reasoning
          </h3>

          {/* Action Buttons */}
          <div className="flex gap-2">
            <Button
              variant="red"
              onClick={handleImpact}
              disabled={reasoningLoading !== null}
              className="flex-1 text-xs px-2 py-1.5"
            >
              {reasoningLoading === 'impact' ? '...' : 'Impact'}
            </Button>
            <Button
              variant="blue"
              onClick={handleAncestors}
              disabled={reasoningLoading !== null}
              className="flex-1 text-xs px-2 py-1.5"
            >
              {reasoningLoading === 'ancestors' ? '...' : 'Ancestors'}
            </Button>
          </div>

          {/* Error */}
          {reasoningError && (
            <div className="flex items-center gap-1 text-xs text-bauhaus-red">
              <AlertTriangle className="w-3 h-3" />
              {reasoningError}
            </div>
          )}

          {/* Impact Results */}
          {impactResult && (
            <div className="bg-bauhaus-red/10 border-2 border-bauhaus-red p-2">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-bold text-bauhaus-red">
                  Impact: {impactResult.count} nodes
                </span>
                <button
                  onClick={handleClearReasoning}
                  className="text-xs text-bauhaus-black/40 hover:text-bauhaus-black"
                >
                  Clear
                </button>
              </div>
              {impactResult.count > 0 ? (
                <div className="max-h-32 overflow-y-auto space-y-1">
                  {impactResult.impacted_nodes.slice(0, 10).map((id) => {
                    const n = elements?.nodes.find((x) => x.data.id === id);
                    return (
                      <button
                        key={id}
                        onClick={() => setSelectedNode(id)}
                        className="w-full flex items-center gap-1 px-1 py-0.5 text-xs bg-white hover:bg-bauhaus-muted transition-colors text-left"
                      >
                        <span className="w-1.5 h-1.5 bg-bauhaus-red rounded-full" />
                        <span className="truncate flex-1">{n?.data.label || id.split('/').pop()}</span>
                        <ChevronRight className="w-3 h-3 text-bauhaus-black/40" />
                      </button>
                    );
                  })}
                  {impactResult.count > 10 && (
                    <span className="text-xs text-bauhaus-black/40">
                      +{impactResult.count - 10} more
                    </span>
                  )}
                </div>
              ) : (
                <p className="text-xs text-bauhaus-black/60">No downstream impact</p>
              )}
            </div>
          )}

          {/* Ancestors Results */}
          {ancestorsResult && (
            <div className="bg-bauhaus-blue/10 border-2 border-bauhaus-blue p-2">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-bold text-bauhaus-blue">
                  Ancestors: {ancestorsResult.count} nodes
                </span>
                <button
                  onClick={handleClearReasoning}
                  className="text-xs text-bauhaus-black/40 hover:text-bauhaus-black"
                >
                  Clear
                </button>
              </div>
              {ancestorsResult.count > 0 ? (
                <div className="max-h-32 overflow-y-auto space-y-1">
                  {ancestorsResult.ancestor_nodes.slice(0, 10).map((id) => {
                    const n = elements?.nodes.find((x) => x.data.id === id);
                    return (
                      <button
                        key={id}
                        onClick={() => setSelectedNode(id)}
                        className="w-full flex items-center gap-1 px-1 py-0.5 text-xs bg-white hover:bg-bauhaus-muted transition-colors text-left"
                      >
                        <span className="w-1.5 h-1.5 bg-bauhaus-blue rounded-full" />
                        <span className="truncate flex-1">{n?.data.label || id.split('/').pop()}</span>
                        <ChevronRight className="w-3 h-3 text-bauhaus-black/40" />
                      </button>
                    );
                  })}
                  {ancestorsResult.count > 10 && (
                    <span className="text-xs text-bauhaus-black/40">
                      +{ancestorsResult.count - 10} more
                    </span>
                  )}
                </div>
              ) : (
                <p className="text-xs text-bauhaus-black/60">No upstream dependencies</p>
              )}
            </div>
          )}
        </div>

        {/* Properties */}
        {node.properties && Object.keys(node.properties).length > 0 && (
          <div>
            <h3 className="font-bauhaus-label text-bauhaus-black flex items-center gap-2 mb-2">
              <Layers className="w-4 h-4" />
              Properties
            </h3>
            <pre className="text-xs bg-bauhaus-muted border-2 border-bauhaus-black p-3 overflow-auto max-h-40 font-mono">
              {JSON.stringify(node.properties, null, 2)}
            </pre>
          </div>
        )}

        {/* MU Representation */}
        {node.mu_representation && (
          <div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="font-bauhaus-label text-bauhaus-black">
                MU Format
              </h3>
              <Button
                variant="outline"
                onClick={handleCopyMU}
                className="text-xs px-2 py-1"
              >
                {copied ? (
                  <Check className="w-3 h-3 text-green-600" />
                ) : (
                  <Copy className="w-3 h-3" />
                )}
                {copied ? 'Copied!' : 'Copy'}
              </Button>
            </div>
            <pre className="text-xs bg-bauhaus-black text-bauhaus-yellow border-2 border-bauhaus-black p-3 overflow-auto max-h-40 font-mono">
              {node.mu_representation}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

// Helper Components

function TypeIndicator({ type }: { type: string }) {
  const colors: Record<string, string> = {
    module: 'bg-node-module',
    class: 'bg-node-class',
    function: 'bg-node-function',
    external: 'bg-node-external',
  };

  return (
    <div
      className={`w-6 h-6 border-2 border-bauhaus-black ${colors[type] || 'bg-bauhaus-muted'}`}
    />
  );
}

function getTypeVariant(type: string): 'red' | 'blue' | 'yellow' | 'gray' {
  const variants: Record<string, 'red' | 'blue' | 'yellow' | 'gray'> = {
    module: 'blue',
    class: 'red',
    function: 'yellow',
    external: 'gray',
  };
  return variants[type] || 'gray';
}

function StatBox({
  label,
  value,
  color,
}: {
  label: string;
  value: string | number;
  color: 'red' | 'blue' | 'yellow';
}) {
  const bgColors = {
    red: 'bg-bauhaus-red',
    blue: 'bg-bauhaus-blue',
    yellow: 'bg-bauhaus-yellow',
  };

  const textColors = {
    red: 'text-white',
    blue: 'text-white',
    yellow: 'text-bauhaus-black',
  };

  return (
    <div className={`${bgColors[color]} ${textColors[color]} border-2 border-bauhaus-black p-2 text-center`}>
      <div className="text-lg font-bold">{value}</div>
      <div className="text-xs uppercase tracking-wider opacity-80">{label}</div>
    </div>
  );
}

function ConnectionItem({
  nodeId,
  edgeType,
  elements,
  onClick,
}: {
  nodeId: string;
  edgeType: string;
  elements: ReturnType<typeof useGraphStore.getState>['elements'];
  onClick: () => void;
}) {
  const node = elements?.nodes.find((n) => n.data.id === nodeId);
  const label = node?.data.label || nodeId;

  const edgeColors: Record<string, string> = {
    IMPORTS: 'text-node-module',
    INHERITS: 'text-node-class',
    CALLS: 'text-node-function',
    CONTAINS: 'text-bauhaus-black/40',
  };

  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-2 px-2 py-1 bg-bauhaus-white border border-bauhaus-black hover:bg-bauhaus-muted transition-colors text-left"
    >
      <span className={`text-xs font-bold ${edgeColors[edgeType] || 'text-bauhaus-black/60'}`}>
        {edgeType}
      </span>
      <span className="flex-1 truncate text-sm">{label}</span>
      <ExternalLink className="w-3 h-3 text-bauhaus-black/40" />
    </button>
  );
}
