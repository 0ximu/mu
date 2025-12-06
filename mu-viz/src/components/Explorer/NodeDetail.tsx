import { useEffect, useState } from 'react';
import {
  ArrowLeft,
  FileCode,
  Copy,
  Check,
  ArrowRight,
  ArrowDown,
  Network,
  ChevronRight,
} from 'lucide-react';
import { useGraphStore } from '../../store/graphStore';
import { useUIStore } from '../../store/uiStore';
import { muClient } from '../../api/client';
import type { Node, CytoscapeData, NodeType } from '../../api/types';
import { Button, Badge } from '../common';
import { MiniGraph } from './MiniGraph';

interface NodeDetailProps {
  nodeId: string;
  onBack: () => void;
  onNodeClick: (nodeId: string) => void;
  onGraphView: () => void;
}

export function NodeDetail({ nodeId, onBack, onNodeClick, onGraphView }: NodeDetailProps) {
  const { elements } = useGraphStore();
  const { addRecentNode } = useUIStore();

  const [node, setNode] = useState<Node | null>(null);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);
  const [showAllDeps, setShowAllDeps] = useState(false);
  const [showAllUsedBy, setShowAllUsedBy] = useState(false);

  // Fetch full node details
  useEffect(() => {
    let cancelled = false;

    const fetchNode = async () => {
      try {
        const fetchedNode = await muClient.getNode(nodeId);
        if (!cancelled) {
          setNode(fetchedNode);
          setLoading(false);
        }
      } catch (err) {
        console.error('Failed to fetch node:', err);
        // Fallback to elements data
        if (!cancelled) {
          const elemNode = elements?.nodes.find((n) => n.data.id === nodeId);
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
          setLoading(false);
        }
      }
    };

    fetchNode();

    return () => {
      cancelled = true;
    };
  }, [nodeId, elements]);

  // Get connections
  const dependencies = elements?.edges
    .filter((e) => e.data.source === nodeId)
    .map((e) => {
      const targetNode = elements.nodes.find((n) => n.data.id === e.data.target);
      return {
        id: e.data.target,
        label: targetNode?.data.label || e.data.target,
        type: targetNode?.data.type as NodeType,
        edgeType: e.data.type,
      };
    }) || [];

  const usedBy = elements?.edges
    .filter((e) => e.data.target === nodeId)
    .map((e) => {
      const sourceNode = elements.nodes.find((n) => n.data.id === e.data.source);
      return {
        id: e.data.source,
        label: sourceNode?.data.label || e.data.source,
        type: sourceNode?.data.type as NodeType,
        edgeType: e.data.type,
      };
    }) || [];

  const handleCopyMU = async () => {
    if (!node?.mu_representation) return;
    await navigator.clipboard.writeText(node.mu_representation);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleNodeNavigate = (id: string) => {
    addRecentNode(id);
    onNodeClick(id);
  };

  // Prepare mini graph data
  const getMiniGraphData = (): CytoscapeData => {
    if (!elements) return { nodes: [], edges: [] };

    const connectedNodeIds = new Set([
      nodeId,
      ...dependencies.slice(0, 5).map((d) => d.id),
      ...usedBy.slice(0, 5).map((u) => u.id),
    ]);

    const nodes = elements.nodes.filter((n) => connectedNodeIds.has(n.data.id));
    const edges = elements.edges.filter(
      (e) => connectedNodeIds.has(e.data.source) && connectedNodeIds.has(e.data.target)
    );

    return { nodes, edges };
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center bg-bauhaus-canvas">
        <div className="w-12 h-12 border-4 border-bauhaus-yellow border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!node) {
    return (
      <div className="h-full flex flex-col bg-bauhaus-canvas">
        <Header onBack={onBack} title="Not Found" />
        <div className="flex-1 flex items-center justify-center">
          <p className="text-bauhaus-black/60">Node not found</p>
        </div>
      </div>
    );
  }

  const DISPLAY_LIMIT = 5;
  const displayedDeps = showAllDeps ? dependencies : dependencies.slice(0, DISPLAY_LIMIT);
  const displayedUsedBy = showAllUsedBy ? usedBy : usedBy.slice(0, DISPLAY_LIMIT);

  return (
    <div className="h-full flex flex-col bg-bauhaus-canvas">
      {/* Header */}
      <Header
        onBack={onBack}
        title={node.name}
        rightAction={
          <Button variant="outline" onClick={onGraphView} className="text-sm px-3 py-1">
            <Network className="w-4 h-4" />
            Graph View
          </Button>
        }
      />

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto p-6 space-y-6">
          {/* Node Info Card */}
          <div className="bg-bauhaus-white border-4 border-bauhaus-black shadow-bauhaus-lg p-6">
            <div className="flex items-start gap-4">
              <TypeIndicator type={node.type} size="lg" />
              <div className="flex-1 min-w-0">
                <h2 className="text-2xl font-bold text-bauhaus-black break-words mb-2">
                  {node.name}
                </h2>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={getTypeVariant(node.type)}>{node.type}</Badge>
                  {node.complexity !== undefined && (
                    <Badge variant={node.complexity > 100 ? 'red' : 'gray'}>
                      Complexity: {node.complexity}
                    </Badge>
                  )}
                  {node.line_start && node.line_end && (
                    <Badge variant="gray">
                      {node.line_end - node.line_start + 1} lines
                    </Badge>
                  )}
                </div>
              </div>
            </div>

            {/* Location */}
            {node.file_path && (
              <div className="mt-4 px-4 py-3 bg-bauhaus-muted border-2 border-bauhaus-black">
                <div className="flex items-center gap-2 text-bauhaus-black/60 mb-1">
                  <FileCode className="w-4 h-4" />
                  <span className="text-xs font-bold uppercase tracking-wider">Location</span>
                </div>
                <p className="font-mono text-sm text-bauhaus-black break-all">
                  {node.file_path}
                  {node.line_start && `:${node.line_start}`}
                  {node.line_end && node.line_end !== node.line_start && `-${node.line_end}`}
                </p>
              </div>
            )}
          </div>

          {/* Visual Context - Mini Graph */}
          {(dependencies.length > 0 || usedBy.length > 0) && (
            <div className="bg-bauhaus-white border-4 border-bauhaus-black shadow-bauhaus-lg overflow-hidden">
              <div className="px-4 py-3 bg-bauhaus-blue text-white font-bold uppercase tracking-wider text-sm border-b-4 border-bauhaus-black">
                Visual Context
              </div>
              <div className="h-64 bg-bauhaus-canvas">
                <MiniGraph
                  data={getMiniGraphData()}
                  centerNodeId={nodeId}
                  onNodeClick={handleNodeNavigate}
                />
              </div>
            </div>
          )}

          {/* Dependencies */}
          {dependencies.length > 0 && (
            <div className="bg-bauhaus-white border-4 border-bauhaus-black shadow-bauhaus-lg overflow-hidden">
              <div className="px-4 py-3 bg-bauhaus-red text-white font-bold uppercase tracking-wider text-sm border-b-4 border-bauhaus-black flex items-center gap-2">
                <ArrowRight className="w-4 h-4" />
                Dependencies ({dependencies.length})
                <span className="text-white/60 text-xs font-normal normal-case ml-2">
                  What this uses
                </span>
              </div>
              <div className="divide-y divide-bauhaus-muted">
                {displayedDeps.map((dep) => (
                  <ConnectionItem
                    key={dep.id}
                    label={dep.label}
                    type={dep.type}
                    edgeType={dep.edgeType}
                    onClick={() => handleNodeNavigate(dep.id)}
                  />
                ))}
                {dependencies.length > DISPLAY_LIMIT && (
                  <button
                    onClick={() => setShowAllDeps(!showAllDeps)}
                    className="w-full px-4 py-2 text-sm text-bauhaus-blue hover:bg-bauhaus-muted transition-colors text-left"
                  >
                    {showAllDeps
                      ? 'Show less'
                      : `Show ${dependencies.length - DISPLAY_LIMIT} more...`}
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Used By */}
          {usedBy.length > 0 && (
            <div className="bg-bauhaus-white border-4 border-bauhaus-black shadow-bauhaus-lg overflow-hidden">
              <div className="px-4 py-3 bg-bauhaus-yellow text-bauhaus-black font-bold uppercase tracking-wider text-sm border-b-4 border-bauhaus-black flex items-center gap-2">
                <ArrowDown className="w-4 h-4" />
                Used By ({usedBy.length})
                <span className="text-bauhaus-black/60 text-xs font-normal normal-case ml-2">
                  What uses this
                </span>
              </div>
              <div className="divide-y divide-bauhaus-muted">
                {displayedUsedBy.map((dep) => (
                  <ConnectionItem
                    key={dep.id}
                    label={dep.label}
                    type={dep.type}
                    edgeType={dep.edgeType}
                    onClick={() => handleNodeNavigate(dep.id)}
                  />
                ))}
                {usedBy.length > DISPLAY_LIMIT && (
                  <button
                    onClick={() => setShowAllUsedBy(!showAllUsedBy)}
                    className="w-full px-4 py-2 text-sm text-bauhaus-blue hover:bg-bauhaus-muted transition-colors text-left"
                  >
                    {showAllUsedBy ? 'Show less' : `Show ${usedBy.length - DISPLAY_LIMIT} more...`}
                  </button>
                )}
              </div>
            </div>
          )}

          {/* No Connections */}
          {dependencies.length === 0 && usedBy.length === 0 && (
            <div className="bg-bauhaus-white border-4 border-bauhaus-black shadow-bauhaus-lg p-6 text-center">
              <p className="text-bauhaus-black/60">No connections found</p>
            </div>
          )}

          {/* MU Representation */}
          {node.mu_representation && (
            <div className="bg-bauhaus-white border-4 border-bauhaus-black shadow-bauhaus-lg overflow-hidden">
              <div className="px-4 py-3 bg-bauhaus-black text-white font-bold uppercase tracking-wider text-sm flex items-center justify-between">
                <span>MU Format</span>
                <Button
                  variant="ghost"
                  onClick={handleCopyMU}
                  className="text-white/80 hover:text-white text-xs px-2 py-1"
                >
                  {copied ? (
                    <>
                      <Check className="w-3 h-3" />
                      Copied!
                    </>
                  ) : (
                    <>
                      <Copy className="w-3 h-3" />
                      Copy
                    </>
                  )}
                </Button>
              </div>
              <pre className="p-4 bg-bauhaus-black text-bauhaus-yellow font-mono text-sm overflow-x-auto">
                {node.mu_representation}
              </pre>
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-3">
            <Button variant="blue" onClick={onGraphView} className="flex-1">
              <Network className="w-4 h-4" />
              Show Full Graph
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

// Header Component
function Header({
  onBack,
  title,
  rightAction,
}: {
  onBack: () => void;
  title: string;
  rightAction?: React.ReactNode;
}) {
  return (
    <header className="flex items-center justify-between px-4 py-3 bg-bauhaus-black border-b-4 border-bauhaus-black">
      <button
        onClick={onBack}
        className="flex items-center gap-2 text-white hover:text-bauhaus-yellow transition-colors"
      >
        <ArrowLeft className="w-5 h-5" />
        <span className="font-bold uppercase tracking-wider text-sm">Back</span>
      </button>
      <h1 className="text-white font-bold truncate max-w-md">{title}</h1>
      <div>{rightAction}</div>
    </header>
  );
}

// Type Indicator
function TypeIndicator({ type, size = 'md' }: { type: string; size?: 'sm' | 'md' | 'lg' }) {
  const colors: Record<string, string> = {
    module: 'bg-node-module',
    class: 'bg-node-class',
    function: 'bg-node-function',
    external: 'bg-node-external',
  };

  const shapes: Record<string, string> = {
    module: '',
    class: '',
    function: 'rounded-full',
    external: '',
  };

  const sizeClass = {
    sm: 'w-4 h-4',
    md: 'w-6 h-6',
    lg: 'w-10 h-10',
  }[size];

  return (
    <div
      className={`${sizeClass} border-2 border-bauhaus-black ${colors[type] || 'bg-bauhaus-muted'} ${shapes[type] || ''}`}
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

// Connection Item
function ConnectionItem({
  label,
  type,
  edgeType,
  onClick,
}: {
  label: string;
  type?: NodeType;
  edgeType: string;
  onClick: () => void;
}) {
  const edgeColors: Record<string, string> = {
    imports: 'text-node-module',
    inherits: 'text-node-class',
    calls: 'text-node-function',
    contains: 'text-bauhaus-black/40',
  };

  return (
    <button
      onClick={onClick}
      className="w-full px-4 py-3 flex items-center gap-3 hover:bg-bauhaus-muted transition-colors group"
    >
      {type && <TypeIndicator type={type} size="sm" />}
      <span className={`text-xs font-bold uppercase ${edgeColors[edgeType] || 'text-bauhaus-black/60'}`}>
        {edgeType}
      </span>
      <span className="flex-1 text-left font-medium text-bauhaus-black truncate">{label}</span>
      <ChevronRight className="w-4 h-4 text-bauhaus-black/40 group-hover:text-bauhaus-black transition-colors" />
    </button>
  );
}
