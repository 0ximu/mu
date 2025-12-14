import { useState, useCallback } from 'react';
import { Zap, GitBranch, RefreshCcw, AlertTriangle, ChevronRight, X } from 'lucide-react';
import { muClient } from '../../api/client';
import { useGraphStore } from '../../store/graphStore';
import { Button, Badge } from '../common';
import type { ImpactResult, AncestorsResult, EdgeType } from '../../api/types';

type ReasoningMode = 'impact' | 'ancestors' | null;

interface GraphReasoningProps {
  nodeId: string;
  onNodeClick: (nodeId: string) => void;
}

const EDGE_TYPE_OPTIONS: { value: EdgeType; label: string }[] = [
  { value: 'imports', label: 'Imports' },
  { value: 'inherits', label: 'Inherits' },
  { value: 'contains', label: 'Contains' },
];

export function GraphReasoning({ nodeId, onNodeClick }: GraphReasoningProps) {
  const { elements, setHighlightedPath } = useGraphStore();
  const [mode, setMode] = useState<ReasoningMode>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [impactResult, setImpactResult] = useState<ImpactResult | null>(null);
  const [ancestorsResult, setAncestorsResult] = useState<AncestorsResult | null>(null);
  const [selectedEdgeTypes, setSelectedEdgeTypes] = useState<EdgeType[]>([]);

  const getNodeLabel = (id: string) => {
    const node = elements?.nodes.find((n) => n.data.id === id);
    return node?.data.label || id.split(':').pop() || id;
  };

  const handleAnalyzeImpact = useCallback(async () => {
    setLoading(true);
    setError(null);
    setMode('impact');

    try {
      const result = await muClient.getImpact(
        nodeId,
        selectedEdgeTypes.length > 0 ? selectedEdgeTypes : undefined
      );
      setImpactResult(result);
      setAncestorsResult(null);

      // Highlight impacted nodes in graph
      if (result.impacted_nodes.length > 0) {
        setHighlightedPath([nodeId, ...result.impacted_nodes]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to analyze impact');
    } finally {
      setLoading(false);
    }
  }, [nodeId, selectedEdgeTypes, setHighlightedPath]);

  const handleAnalyzeAncestors = useCallback(async () => {
    setLoading(true);
    setError(null);
    setMode('ancestors');

    try {
      const result = await muClient.getAncestors(
        nodeId,
        selectedEdgeTypes.length > 0 ? selectedEdgeTypes : undefined
      );
      setAncestorsResult(result);
      setImpactResult(null);

      // Highlight ancestor nodes in graph
      if (result.ancestor_nodes.length > 0) {
        setHighlightedPath([...result.ancestor_nodes, nodeId]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to analyze ancestors');
    } finally {
      setLoading(false);
    }
  }, [nodeId, selectedEdgeTypes, setHighlightedPath]);

  const handleClear = () => {
    setMode(null);
    setImpactResult(null);
    setAncestorsResult(null);
    setError(null);
    setHighlightedPath([]);
  };

  const toggleEdgeType = (edgeType: EdgeType) => {
    setSelectedEdgeTypes((prev) =>
      prev.includes(edgeType)
        ? prev.filter((t) => t !== edgeType)
        : [...prev, edgeType]
    );
  };

  const resultNodes = mode === 'impact' ? impactResult?.impacted_nodes : ancestorsResult?.ancestor_nodes;
  const resultCount = mode === 'impact' ? impactResult?.count : ancestorsResult?.count;

  return (
    <div className="bg-bauhaus-white border-4 border-bauhaus-black shadow-bauhaus-lg overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 bg-gradient-to-r from-bauhaus-blue to-bauhaus-red text-white font-bold uppercase tracking-wider text-sm border-b-4 border-bauhaus-black flex items-center gap-2">
        <Zap className="w-4 h-4" />
        Graph Reasoning
        <span className="text-white/60 text-xs font-normal normal-case ml-2">
          Powered by Rust petgraph
        </span>
      </div>

      <div className="p-4 space-y-4">
        {/* Edge Type Filters */}
        <div>
          <label className="text-xs font-bold uppercase tracking-wider text-bauhaus-black/60 mb-2 block">
            Edge Types (optional)
          </label>
          <div className="flex flex-wrap gap-2">
            {EDGE_TYPE_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => toggleEdgeType(opt.value)}
                className={`px-3 py-1 text-xs font-bold uppercase border-2 border-bauhaus-black transition-colors ${
                  selectedEdgeTypes.includes(opt.value)
                    ? 'bg-bauhaus-black text-white'
                    : 'bg-bauhaus-white text-bauhaus-black hover:bg-bauhaus-muted'
                }`}
              >
                {opt.label}
              </button>
            ))}
            {selectedEdgeTypes.length > 0 && (
              <button
                onClick={() => setSelectedEdgeTypes([])}
                className="px-2 py-1 text-xs text-bauhaus-black/60 hover:text-bauhaus-black"
              >
                Clear
              </button>
            )}
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex gap-2">
          <Button
            variant="red"
            onClick={handleAnalyzeImpact}
            disabled={loading}
            className="flex-1"
          >
            <Zap className="w-4 h-4" />
            {loading && mode === 'impact' ? 'Analyzing...' : 'Impact Analysis'}
          </Button>
          <Button
            variant="blue"
            onClick={handleAnalyzeAncestors}
            disabled={loading}
            className="flex-1"
          >
            <GitBranch className="w-4 h-4" />
            {loading && mode === 'ancestors' ? 'Analyzing...' : 'Find Ancestors'}
          </Button>
        </div>

        {/* Error */}
        {error && (
          <div className="flex items-center gap-2 px-3 py-2 bg-bauhaus-red/10 border-2 border-bauhaus-red text-bauhaus-red text-sm">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
            {error}
          </div>
        )}

        {/* Results */}
        {mode && resultNodes && (
          <div className="border-t-2 border-bauhaus-black pt-4">
            <div className="flex items-center justify-between mb-3">
              <h4 className="font-bold uppercase text-sm text-bauhaus-black flex items-center gap-2">
                {mode === 'impact' ? (
                  <>
                    <Zap className="w-4 h-4 text-bauhaus-red" />
                    Impact Analysis
                  </>
                ) : (
                  <>
                    <GitBranch className="w-4 h-4 text-bauhaus-blue" />
                    Ancestors
                  </>
                )}
                <Badge variant={mode === 'impact' ? 'red' : 'blue'}>{resultCount}</Badge>
              </h4>
              <button
                onClick={handleClear}
                className="p-1 hover:bg-bauhaus-muted rounded transition-colors"
              >
                <X className="w-4 h-4 text-bauhaus-black/60" />
              </button>
            </div>

            {resultNodes.length === 0 ? (
              <p className="text-bauhaus-black/60 text-sm">
                {mode === 'impact'
                  ? 'No downstream dependencies found. Changes to this node won\'t affect others.'
                  : 'No upstream dependencies found. This node is independent.'}
              </p>
            ) : (
              <>
                <p className="text-bauhaus-black/60 text-sm mb-3">
                  {mode === 'impact'
                    ? `Changing this node may affect ${resultCount} other node${resultCount !== 1 ? 's' : ''}:`
                    : `This node depends on ${resultCount} other node${resultCount !== 1 ? 's' : ''}:`}
                </p>
                <div className="max-h-48 overflow-y-auto border-2 border-bauhaus-black">
                  {resultNodes.slice(0, 50).map((id) => (
                    <button
                      key={id}
                      onClick={() => onNodeClick(id)}
                      className="w-full px-3 py-2 flex items-center gap-2 hover:bg-bauhaus-muted transition-colors border-b border-bauhaus-muted last:border-b-0 group"
                    >
                      <span
                        className={`w-2 h-2 rounded-full ${
                          mode === 'impact' ? 'bg-bauhaus-red' : 'bg-bauhaus-blue'
                        }`}
                      />
                      <span className="flex-1 text-left text-sm font-medium text-bauhaus-black truncate">
                        {getNodeLabel(id)}
                      </span>
                      <ChevronRight className="w-4 h-4 text-bauhaus-black/40 group-hover:text-bauhaus-black transition-colors" />
                    </button>
                  ))}
                  {resultNodes.length > 50 && (
                    <div className="px-3 py-2 text-sm text-bauhaus-black/60 bg-bauhaus-muted">
                      +{resultNodes.length - 50} more nodes...
                    </div>
                  )}
                </div>
              </>
            )}

            {/* Refresh */}
            <Button
              variant="outline"
              onClick={mode === 'impact' ? handleAnalyzeImpact : handleAnalyzeAncestors}
              className="w-full mt-3"
              disabled={loading}
            >
              <RefreshCcw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
