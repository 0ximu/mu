import { useState, useCallback } from 'react';
import { RefreshCcw, AlertTriangle, CheckCircle, ChevronRight, ChevronDown, X } from 'lucide-react';
import { muClient } from '../../api/client';
import { useGraphStore } from '../../store/graphStore';
import { Button, Badge } from '../common';
import type { CyclesResult, EdgeType } from '../../api/types';

interface CycleDetectorProps {
  onNodeClick: (nodeId: string) => void;
  onClose?: () => void;
}

const EDGE_TYPE_OPTIONS: { value: EdgeType; label: string }[] = [
  { value: 'imports', label: 'Imports' },
  { value: 'inherits', label: 'Inherits' },
  { value: 'contains', label: 'Contains' },
];

export function CycleDetector({ onNodeClick, onClose }: CycleDetectorProps) {
  const { elements, setHighlightedPath } = useGraphStore();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CyclesResult | null>(null);
  const [selectedEdgeTypes, setSelectedEdgeTypes] = useState<EdgeType[]>(['imports']);
  const [expandedCycles, setExpandedCycles] = useState<Set<number>>(new Set());
  const [selectedCycleIndex, setSelectedCycleIndex] = useState<number | null>(null);

  const getNodeLabel = (id: string) => {
    const node = elements?.nodes.find((n) => n.data.id === id);
    return node?.data.label || id.split(':').pop() || id;
  };

  const handleDetectCycles = useCallback(async () => {
    setLoading(true);
    setError(null);
    setExpandedCycles(new Set());
    setSelectedCycleIndex(null);
    setHighlightedPath([]);

    try {
      const cyclesResult = await muClient.getCycles(
        selectedEdgeTypes.length > 0 ? selectedEdgeTypes : undefined
      );
      setResult(cyclesResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to detect cycles');
    } finally {
      setLoading(false);
    }
  }, [selectedEdgeTypes, setHighlightedPath]);

  const toggleCycleExpanded = (index: number) => {
    setExpandedCycles((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  };

  const handleSelectCycle = (index: number, cycle: string[]) => {
    if (selectedCycleIndex === index) {
      // Deselect
      setSelectedCycleIndex(null);
      setHighlightedPath([]);
    } else {
      // Select and highlight
      setSelectedCycleIndex(index);
      setHighlightedPath(cycle);
    }
  };

  const toggleEdgeType = (edgeType: EdgeType) => {
    setSelectedEdgeTypes((prev) =>
      prev.includes(edgeType)
        ? prev.filter((t) => t !== edgeType)
        : [...prev, edgeType]
    );
  };

  const handleClear = () => {
    setResult(null);
    setError(null);
    setSelectedCycleIndex(null);
    setHighlightedPath([]);
  };

  return (
    <div className="bg-bauhaus-white border-4 border-bauhaus-black shadow-bauhaus-lg overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 bg-bauhaus-yellow text-bauhaus-black font-bold uppercase tracking-wider text-sm border-b-4 border-bauhaus-black flex items-center justify-between">
        <div className="flex items-center gap-2">
          <RefreshCcw className="w-4 h-4" />
          Cycle Detector
          <span className="text-bauhaus-black/60 text-xs font-normal normal-case">
            Find circular dependencies
          </span>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="p-1 hover:bg-bauhaus-black/10 rounded transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      <div className="p-4 space-y-4">
        {/* Edge Type Filters */}
        <div>
          <label className="text-xs font-bold uppercase tracking-wider text-bauhaus-black/60 mb-2 block">
            Edge Types to Check
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
          </div>
        </div>

        {/* Detect Button */}
        <Button
          variant="yellow"
          onClick={handleDetectCycles}
          disabled={loading}
          className="w-full"
        >
          <RefreshCcw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          {loading ? 'Detecting...' : 'Detect Cycles'}
        </Button>

        {/* Error */}
        {error && (
          <div className="flex items-center gap-2 px-3 py-2 bg-bauhaus-red/10 border-2 border-bauhaus-red text-bauhaus-red text-sm">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
            {error}
          </div>
        )}

        {/* Results */}
        {result && (
          <div className="border-t-2 border-bauhaus-black pt-4">
            {/* Summary */}
            <div className="flex items-center justify-between mb-3">
              {result.cycle_count === 0 ? (
                <div className="flex items-center gap-2 text-green-600">
                  <CheckCircle className="w-5 h-5" />
                  <span className="font-bold">No cycles detected!</span>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <AlertTriangle className="w-5 h-5 text-bauhaus-red" />
                  <span className="font-bold text-bauhaus-black">
                    Found {result.cycle_count} cycle{result.cycle_count !== 1 ? 's' : ''}
                  </span>
                  <Badge variant="red">{result.total_nodes_in_cycles} nodes</Badge>
                </div>
              )}
              {result.cycle_count > 0 && (
                <button
                  onClick={handleClear}
                  className="text-xs text-bauhaus-black/60 hover:text-bauhaus-black"
                >
                  Clear
                </button>
              )}
            </div>

            {/* Cycles List */}
            {result.cycles.length > 0 && (
              <div className="max-h-64 overflow-y-auto border-2 border-bauhaus-black">
                {result.cycles.map((cycle, index) => (
                  <div
                    key={index}
                    className={`border-b border-bauhaus-muted last:border-b-0 ${
                      selectedCycleIndex === index ? 'bg-bauhaus-yellow/20' : ''
                    }`}
                  >
                    {/* Cycle Header */}
                    <button
                      onClick={() => {
                        toggleCycleExpanded(index);
                        handleSelectCycle(index, cycle);
                      }}
                      className="w-full px-3 py-2 flex items-center gap-2 hover:bg-bauhaus-muted/50 transition-colors"
                    >
                      {expandedCycles.has(index) ? (
                        <ChevronDown className="w-4 h-4 text-bauhaus-black/60" />
                      ) : (
                        <ChevronRight className="w-4 h-4 text-bauhaus-black/60" />
                      )}
                      <span
                        className={`w-3 h-3 rounded-full ${
                          selectedCycleIndex === index ? 'bg-bauhaus-yellow' : 'bg-bauhaus-red'
                        }`}
                      />
                      <span className="flex-1 text-left text-sm font-medium text-bauhaus-black">
                        Cycle {index + 1}
                      </span>
                      <Badge variant="gray">{cycle.length} nodes</Badge>
                    </button>

                    {/* Expanded Cycle Details */}
                    {expandedCycles.has(index) && (
                      <div className="px-3 pb-2 pl-9 space-y-1">
                        <div className="flex flex-wrap items-center gap-1 text-xs">
                          {cycle.map((nodeId, nodeIndex) => (
                            <div key={nodeId} className="flex items-center gap-1">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  onNodeClick(nodeId);
                                }}
                                className="px-2 py-0.5 bg-bauhaus-white border border-bauhaus-black hover:bg-bauhaus-muted transition-colors font-medium truncate max-w-[120px]"
                                title={nodeId}
                              >
                                {getNodeLabel(nodeId)}
                              </button>
                              {nodeIndex < cycle.length - 1 && (
                                <span className="text-bauhaus-black/40">→</span>
                              )}
                            </div>
                          ))}
                          <span className="text-bauhaus-black/40">→ (back to start)</span>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {result.cycle_count === 0 && (
              <p className="text-bauhaus-black/60 text-sm">
                Your codebase has no circular dependencies for the selected edge types.
                This is good for maintainability!
              </p>
            )}
          </div>
        )}

        {/* Help Text */}
        {!result && !loading && (
          <p className="text-xs text-bauhaus-black/50">
            Circular dependencies can make code harder to understand and maintain.
            Use this tool to find and fix dependency cycles.
          </p>
        )}
      </div>
    </div>
  );
}
