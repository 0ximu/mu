import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import Fuse from 'fuse.js';
import {
  Search,
  X,
  ArrowUp,
  ArrowDown,
  Circle,
  Square,
  Clock,
  Activity,
  Settings,
} from 'lucide-react';
import { useGraphStore } from '../../store/graphStore';
import { useUIStore } from '../../store/uiStore';
import { Button, Badge } from '../common';
import type { CytoscapeNode, NodeType } from '../../api/types';

interface SearchResult {
  id: string;
  label: string;
  type: NodeType;
  file_path?: string;
  complexity?: number;
}

interface SearchViewProps {
  onResultSelect: (nodeId: string) => void;
  onSettingsClick: () => void;
}

const FILTER_PRESETS: Array<{ label: string; filter: (n: CytoscapeNode) => boolean }> = [
  { label: 'All Nodes', filter: () => true },
  { label: 'High Complexity', filter: (n) => (n.data.complexity || 0) >= 100 },
  { label: 'Classes', filter: (n) => n.data.type === 'class' },
  { label: 'Functions', filter: (n) => n.data.type === 'function' },
];

export function SearchView({ onResultSelect, onSettingsClick }: SearchViewProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [localQuery, setLocalQuery] = useState('');
  const [focusedIndex, setFocusedIndex] = useState(-1);
  const [activePreset, setActivePreset] = useState(0);

  const { elements, wsConnected, loading } = useGraphStore();
  const { recentNodes, addRecentNode } = useUIStore();

  // Build Fuse index when elements change
  const fuseInstance = useMemo(() => {
    if (!elements) return null;

    const items: SearchResult[] = elements.nodes.map((n) => ({
      id: n.data.id,
      label: n.data.label,
      type: n.data.type,
      file_path: n.data.file_path || '',
      complexity: n.data.complexity,
    }));

    return new Fuse(items, {
      keys: ['label', 'file_path'],
      threshold: 0.3,
      includeScore: true,
    });
  }, [elements]);

  // Compute search results from query - also compute a focused index
  const { results, initialFocusIndex } = useMemo(() => {
    if (!fuseInstance || !localQuery.trim()) {
      return { results: [], initialFocusIndex: -1 };
    }

    const searchResults = fuseInstance.search(localQuery, { limit: 20 });
    const preset = FILTER_PRESETS[activePreset];
    const filteredResults = searchResults
      .filter((r) => {
        const node = elements?.nodes.find((n) => n.data.id === r.item.id);
        return node ? preset.filter(node) : false;
      })
      .map((r) => r.item);
    return {
      results: filteredResults,
      initialFocusIndex: filteredResults.length > 0 ? 0 : -1,
    };
  }, [localQuery, fuseInstance, activePreset, elements]);

  // Derive the effective focused index - reset when results change
  // When focusedIndex hasn't been actively set by user navigation, use initial
  const effectiveFocusedIndex = useMemo(() => {
    if (results.length === 0) return -1;
    if (focusedIndex >= 0 && focusedIndex < results.length) return focusedIndex;
    return initialFocusIndex;
  }, [results.length, focusedIndex, initialFocusIndex]);

  const handleClear = useCallback(() => {
    setLocalQuery('');
    setFocusedIndex(-1);
    inputRef.current?.focus();
  }, []);

  const handleResultClick = useCallback(
    (id: string) => {
      addRecentNode(id);
      onResultSelect(id);
    },
    [addRecentNode, onResultSelect]
  );

  // Keyboard navigation
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (results.length === 0) return;

      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          setFocusedIndex((prev) => Math.min(prev + 1, results.length - 1));
          break;
        case 'ArrowUp':
          e.preventDefault();
          setFocusedIndex((prev) => Math.max(prev - 1, 0));
          break;
        case 'Enter':
          e.preventDefault();
          if (effectiveFocusedIndex >= 0) {
            handleResultClick(results[effectiveFocusedIndex].id);
          }
          break;
        case 'Escape':
          e.preventDefault();
          handleClear();
          break;
      }
    },
    [results, effectiveFocusedIndex, handleResultClick, handleClear]
  );

  // Global keyboard shortcut (Cmd/Ctrl + K)
  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };

    window.addEventListener('keydown', handleGlobalKeyDown);
    return () => window.removeEventListener('keydown', handleGlobalKeyDown);
  }, []);

  // Get recent nodes info
  const recentNodesInfo = recentNodes
    .slice(0, 5)
    .map((id) => {
      const node = elements?.nodes.find((n) => n.data.id === id);
      return node ? { id, label: node.data.label, type: node.data.type } : null;
    })
    .filter(Boolean) as Array<{ id: string; label: string; type: NodeType }>;

  const nodeCount = elements?.nodes.length || 0;
  const edgeCount = elements?.edges.length || 0;

  return (
    <div className="h-full flex flex-col bg-bauhaus-canvas">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 bg-bauhaus-black border-b-4 border-bauhaus-black">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1">
            <Circle className="w-4 h-4 text-bauhaus-red fill-bauhaus-red" />
            <Square className="w-4 h-4 text-bauhaus-blue fill-bauhaus-blue" />
            <div
              className="w-4 h-4 bg-bauhaus-yellow"
              style={{ clipPath: 'polygon(50% 0%, 0% 100%, 100% 100%)' }}
            />
          </div>
          <h1 className="text-xl font-black uppercase tracking-tight text-white">
            MU Explorer
          </h1>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div
              className={`w-2 h-2 rounded-full ${
                wsConnected ? 'bg-bauhaus-yellow' : 'bg-bauhaus-red'
              }`}
            />
            <span className="text-white/60 text-xs uppercase tracking-wider">
              {loading ? 'Loading' : wsConnected ? 'Live' : 'Offline'}
            </span>
          </div>
          <button
            onClick={onSettingsClick}
            className="p-2 text-white/60 hover:text-white hover:bg-white/10 transition-colors"
          >
            <Settings className="w-5 h-5" />
          </button>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 flex flex-col items-center justify-center p-8">
        <div className="w-full max-w-xl space-y-8">
          {/* Title */}
          <div className="text-center">
            <h2 className="font-bauhaus-heading text-2xl text-bauhaus-black mb-2">
              What code are you looking for?
            </h2>
            <p className="text-bauhaus-black/60 text-sm">
              Search for classes, functions, and modules
            </p>
          </div>

          {/* Search Input */}
          <div className="relative">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-bauhaus-black/40" />
            <input
              ref={inputRef}
              type="text"
              placeholder="Search nodes... (⌘K)"
              value={localQuery}
              onChange={(e) => setLocalQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              className="
                w-full pl-12 pr-12 py-4
                bg-bauhaus-white
                border-4 border-bauhaus-black
                shadow-bauhaus-lg
                text-lg text-bauhaus-black font-medium
                placeholder:text-bauhaus-black/30
                focus:outline-none focus:ring-4 focus:ring-bauhaus-yellow focus:ring-offset-2
              "
            />
            {localQuery && (
              <button
                onClick={handleClear}
                className="absolute right-4 top-1/2 -translate-y-1/2 p-1 hover:bg-bauhaus-muted transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            )}
          </div>

          {/* Search Results */}
          {results.length > 0 && (
            <div className="bg-bauhaus-white border-4 border-bauhaus-black shadow-bauhaus-lg max-h-80 overflow-y-auto">
              <div className="px-4 py-2 bg-bauhaus-muted border-b-2 border-bauhaus-black flex items-center justify-between">
                <span className="font-bauhaus-label text-bauhaus-black/60">
                  {results.length} results
                </span>
                <div className="flex items-center gap-1 text-xs text-bauhaus-black/40">
                  <ArrowUp className="w-3 h-3" />
                  <ArrowDown className="w-3 h-3" />
                  <span>navigate</span>
                  <span className="ml-2">↵ select</span>
                </div>
              </div>
              {results.map((result, index) => (
                <button
                  key={result.id}
                  onClick={() => handleResultClick(result.id)}
                  className={`
                    w-full px-4 py-3 text-left
                    flex items-center gap-3
                    border-b border-bauhaus-muted last:border-b-0
                    transition-colors
                    ${index === effectiveFocusedIndex ? 'bg-bauhaus-yellow' : 'hover:bg-bauhaus-muted'}
                  `}
                >
                  <TypeIcon type={result.type} />
                  <div className="flex-1 min-w-0">
                    <div className="font-bold text-bauhaus-black truncate">
                      {result.label}
                    </div>
                    {result.file_path && (
                      <div className="text-xs text-bauhaus-black/50 truncate">
                        {result.file_path}
                        {result.complexity !== undefined && (
                          <span className="ml-2 text-bauhaus-black/40">
                            Complexity: {result.complexity}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                  <Badge variant={getTypeVariant(result.type)}>{result.type}</Badge>
                </button>
              ))}
            </div>
          )}

          {/* No Results */}
          {localQuery && results.length === 0 && (
            <div className="bg-bauhaus-white border-4 border-bauhaus-black shadow-bauhaus-lg px-6 py-8 text-center">
              <div className="font-bauhaus-heading text-bauhaus-black/60 mb-2">
                No Results
              </div>
              <p className="text-sm text-bauhaus-black/40">
                No nodes match "{localQuery}"
              </p>
            </div>
          )}

          {/* Recent & Quick Filters (shown when no search) */}
          {!localQuery && (
            <>
              {/* Recent Nodes */}
              {recentNodesInfo.length > 0 && (
                <div>
                  <h3 className="font-bauhaus-label text-bauhaus-black/60 mb-3 flex items-center gap-2">
                    <Clock className="w-4 h-4" />
                    Recent
                  </h3>
                  <div className="space-y-2">
                    {recentNodesInfo.map((node) => (
                      <button
                        key={node.id}
                        onClick={() => handleResultClick(node.id)}
                        className="
                          w-full px-4 py-2 text-left
                          flex items-center gap-3
                          bg-bauhaus-white border-2 border-bauhaus-black
                          hover:bg-bauhaus-muted transition-colors
                        "
                      >
                        <TypeIcon type={node.type} size="sm" />
                        <span className="font-medium text-bauhaus-black">{node.label}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Quick Filters */}
              <div>
                <h3 className="font-bauhaus-label text-bauhaus-black/60 mb-3">
                  Quick filters
                </h3>
                <div className="flex flex-wrap gap-2">
                  {FILTER_PRESETS.map((preset, index) => (
                    <Button
                      key={preset.label}
                      variant={activePreset === index ? 'blue' : 'outline'}
                      onClick={() => {
                        setActivePreset(index);
                        inputRef.current?.focus();
                      }}
                      className="text-xs"
                    >
                      {preset.label}
                    </Button>
                  ))}
                </div>
              </div>
            </>
          )}

          {/* Stats Footer */}
          <div className="flex items-center justify-center gap-4 text-sm text-bauhaus-black/40">
            <span className="flex items-center gap-1">
              <Activity className="w-4 h-4" />
              {nodeCount.toLocaleString()} nodes
            </span>
            <span>•</span>
            <span>{edgeCount.toLocaleString()} edges</span>
          </div>
        </div>
      </main>
    </div>
  );
}

function TypeIcon({ type, size = 'md' }: { type: NodeType; size?: 'sm' | 'md' }) {
  const colors: Record<NodeType, string> = {
    module: 'bg-node-module',
    class: 'bg-node-class',
    function: 'bg-node-function',
    external: 'bg-node-external',
  };

  const shapes: Record<NodeType, string> = {
    module: '',
    class: '',
    function: 'rounded-full',
    external: '',
  };

  const sizeClass = size === 'sm' ? 'w-3 h-3' : 'w-4 h-4';

  return (
    <div
      className={`${sizeClass} border border-bauhaus-black ${colors[type]} ${shapes[type]}`}
    />
  );
}

function getTypeVariant(type: NodeType): 'red' | 'blue' | 'yellow' | 'gray' {
  const variants: Record<NodeType, 'red' | 'blue' | 'yellow' | 'gray'> = {
    module: 'blue',
    class: 'red',
    function: 'yellow',
    external: 'gray',
  };
  return variants[type];
}
