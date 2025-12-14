import { useState, useCallback } from 'react';
import { Route, X, ArrowRight, Trash2 } from 'lucide-react';
import { useGraphStore } from '../../store/graphStore';
import { useUIStore } from '../../store/uiStore';
import { muClient } from '../../api/client';
import { Button } from '../common';

export function PathFinder() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { elements, highlightedPath, setHighlightedPath } = useGraphStore();
  const {
    pathFindingMode,
    pathSource,
    pathTarget,
    setPathFindingMode,
    setPathSource,
    setPathTarget,
    clearPathFinding,
  } = useUIStore();

  const getNodeLabel = (id: string | null) => {
    if (!id || !elements) return null;
    const node = elements.nodes.find((n) => n.data.id === id);
    return node?.data.label || id;
  };

  const handleFindPath = useCallback(async () => {
    if (!pathSource || !pathTarget) return;

    setLoading(true);
    setError(null);

    try {
      const path = await muClient.findPath(pathSource, pathTarget);
      if (path.length === 0) {
        setError('No path found between these nodes');
        setHighlightedPath([]);
      } else {
        setHighlightedPath(path);
        setPathFindingMode(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to find path');
      setHighlightedPath([]);
    } finally {
      setLoading(false);
    }
  }, [pathSource, pathTarget, setHighlightedPath, setPathFindingMode]);

  const handleClearPath = () => {
    setHighlightedPath([]);
    clearPathFinding();
    setError(null);
  };

  const handleStartPathFinding = () => {
    setPathFindingMode(true);
    setPathSource(null);
    setPathTarget(null);
    setHighlightedPath([]);
    setError(null);
  };

  return (
    <div className="border-t-4 border-bauhaus-black mt-4 pt-4">
      <h3 className="font-bauhaus-label text-bauhaus-black mb-3 flex items-center gap-2">
        <Route className="w-4 h-4" />
        Path Finder
      </h3>

      {/* Path Finding Mode Toggle */}
      {!pathFindingMode && highlightedPath.length === 0 && (
        <Button
          variant="red"
          onClick={handleStartPathFinding}
          className="w-full"
        >
          Find Path Between Nodes
        </Button>
      )}

      {/* Path Selection UI */}
      {pathFindingMode && (
        <div className="space-y-3">
          {/* Source Node */}
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-bauhaus-blue border-2 border-bauhaus-black flex items-center justify-center">
              <span className="text-white font-bold text-sm">A</span>
            </div>
            <div className="flex-1">
              {pathSource ? (
                <div className="flex items-center justify-between bg-bauhaus-white border-2 border-bauhaus-black px-3 py-1.5">
                  <span className="font-medium truncate">{getNodeLabel(pathSource)}</span>
                  <button
                    onClick={() => setPathSource(null)}
                    className="ml-2 p-0.5 hover:bg-bauhaus-muted"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ) : (
                <div className="px-3 py-1.5 bg-bauhaus-muted border-2 border-dashed border-bauhaus-black text-bauhaus-black/50 text-sm">
                  Click a node to select source
                </div>
              )}
            </div>
          </div>

          {/* Arrow */}
          <div className="flex justify-center">
            <ArrowRight className="w-6 h-6 text-bauhaus-black" />
          </div>

          {/* Target Node */}
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-bauhaus-red border-2 border-bauhaus-black flex items-center justify-center">
              <span className="text-white font-bold text-sm">B</span>
            </div>
            <div className="flex-1">
              {pathTarget ? (
                <div className="flex items-center justify-between bg-bauhaus-white border-2 border-bauhaus-black px-3 py-1.5">
                  <span className="font-medium truncate">{getNodeLabel(pathTarget)}</span>
                  <button
                    onClick={() => setPathTarget(null)}
                    className="ml-2 p-0.5 hover:bg-bauhaus-muted"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ) : (
                <div className="px-3 py-1.5 bg-bauhaus-muted border-2 border-dashed border-bauhaus-black text-bauhaus-black/50 text-sm">
                  Click a node to select target
                </div>
              )}
            </div>
          </div>

          {/* Error */}
          {error && (
            <div className="bg-bauhaus-red/10 border-2 border-bauhaus-red px-3 py-2 text-bauhaus-red text-sm">
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-2 pt-2">
            <Button
              variant="yellow"
              onClick={handleFindPath}
              disabled={!pathSource || !pathTarget || loading}
              className="flex-1"
            >
              {loading ? 'Finding...' : 'Find Path'}
            </Button>
            <Button variant="outline" onClick={handleClearPath}>
              <Trash2 className="w-4 h-4" />
            </Button>
          </div>
        </div>
      )}

      {/* Path Result */}
      {highlightedPath.length > 0 && (
        <div className="space-y-3">
          {/* Path visualization */}
          <div className="bg-bauhaus-yellow/20 border-2 border-bauhaus-yellow p-3">
            <div className="font-bauhaus-label text-bauhaus-black/60 mb-2">
              Path Found ({highlightedPath.length} nodes)
            </div>
            <div className="flex flex-wrap items-center gap-1">
              {highlightedPath.map((id, index) => (
                <div key={id} className="flex items-center gap-1">
                  <span className="px-2 py-0.5 bg-bauhaus-white border border-bauhaus-black text-xs font-bold truncate max-w-[100px]">
                    {getNodeLabel(id)}
                  </span>
                  {index < highlightedPath.length - 1 && (
                    <ArrowRight className="w-3 h-3 text-bauhaus-black/40" />
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Clear button */}
          <Button variant="outline" onClick={handleClearPath} className="w-full">
            <Trash2 className="w-4 h-4" />
            Clear Path
          </Button>
        </div>
      )}
    </div>
  );
}
