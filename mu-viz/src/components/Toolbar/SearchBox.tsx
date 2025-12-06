import { useEffect, useRef, useState, useCallback } from 'react';
import Fuse from 'fuse.js';
import { Search, X, ArrowUp, ArrowDown } from 'lucide-react';
import { useGraphStore } from '../../store/graphStore';
import { useUIStore } from '../../store/uiStore';

export function SearchBox() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [localQuery, setLocalQuery] = useState('');
  const [fuse, setFuse] = useState<Fuse<{ id: string; label: string }> | null>(null);

  const { elements, setSelectedNode } = useGraphStore();
  const {
    searchResults,
    searchFocusedIndex,
    setSearchQuery,
    setSearchResults,
    setSearchFocusedIndex,
    clearSearch,
  } = useUIStore();

  // Build Fuse index when elements change
  useEffect(() => {
    if (!elements) {
      setFuse(null);
      return;
    }

    const items = elements.nodes.map((n) => ({
      id: n.data.id,
      label: n.data.label,
      type: n.data.type,
      file_path: n.data.file_path || '',
    }));

    const fuseInstance = new Fuse(items, {
      keys: ['label', 'file_path'],
      threshold: 0.3,
      includeScore: true,
    });

    setFuse(fuseInstance);
  }, [elements]);

  // Search when query changes
  useEffect(() => {
    if (!fuse || !localQuery.trim()) {
      setSearchResults([]);
      return;
    }

    const results = fuse.search(localQuery, { limit: 20 });
    const ids = results.map((r) => r.item.id);
    setSearchResults(ids);
    setSearchQuery(localQuery);
    setSearchFocusedIndex(ids.length > 0 ? 0 : -1);
  }, [localQuery, fuse, setSearchResults, setSearchQuery, setSearchFocusedIndex]);

  // Keyboard navigation
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (searchResults.length === 0) return;

      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          setSearchFocusedIndex(
            Math.min(searchFocusedIndex + 1, searchResults.length - 1)
          );
          break;
        case 'ArrowUp':
          e.preventDefault();
          setSearchFocusedIndex(Math.max(searchFocusedIndex - 1, 0));
          break;
        case 'Enter':
          e.preventDefault();
          if (searchFocusedIndex >= 0) {
            setSelectedNode(searchResults[searchFocusedIndex]);
          }
          break;
        case 'Escape':
          e.preventDefault();
          handleClear();
          break;
      }
    },
    [searchResults, searchFocusedIndex, setSearchFocusedIndex, setSelectedNode]
  );

  const handleClear = () => {
    setLocalQuery('');
    clearSearch();
    inputRef.current?.focus();
  };

  const handleResultClick = (id: string) => {
    setSelectedNode(id);
  };

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

  return (
    <div className="relative">
      {/* Search Input */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-bauhaus-black/50" />
        <input
          ref={inputRef}
          type="text"
          placeholder="Search nodes... (⌘K)"
          value={localQuery}
          onChange={(e) => setLocalQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          className="
            w-full pl-10 pr-10 py-2
            bg-bauhaus-white
            border-2 border-bauhaus-black
            text-bauhaus-black font-medium
            placeholder:text-bauhaus-black/40
            focus:outline-none focus:ring-2 focus:ring-bauhaus-yellow focus:ring-offset-2
          "
        />
        {localQuery && (
          <button
            onClick={handleClear}
            className="absolute right-3 top-1/2 -translate-y-1/2 p-1 hover:bg-bauhaus-muted transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Search Results Dropdown */}
      {searchResults.length > 0 && (
        <div className="absolute top-full left-0 right-0 mt-2 bg-bauhaus-white border-4 border-bauhaus-black shadow-bauhaus-lg z-50 max-h-64 overflow-y-auto">
          {/* Results count */}
          <div className="px-3 py-2 bg-bauhaus-muted border-b-2 border-bauhaus-black">
            <span className="font-bauhaus-label text-bauhaus-black/60">
              {searchResults.length} results
            </span>
          </div>

          {/* Result items */}
          {searchResults.map((id, index) => {
            const node = elements?.nodes.find((n) => n.data.id === id);
            if (!node) return null;

            const isFocused = index === searchFocusedIndex;

            return (
              <button
                key={id}
                onClick={() => handleResultClick(id)}
                className={`
                  w-full px-3 py-2 text-left
                  flex items-center gap-3
                  border-b border-bauhaus-muted last:border-b-0
                  transition-colors
                  ${isFocused ? 'bg-bauhaus-yellow' : 'hover:bg-bauhaus-muted'}
                `}
              >
                {/* Type indicator */}
                <TypeIndicator type={node.data.type} />

                {/* Node info */}
                <div className="flex-1 min-w-0">
                  <div className="font-bold text-bauhaus-black truncate">
                    {node.data.label}
                  </div>
                  {node.data.file_path && (
                    <div className="text-xs text-bauhaus-black/60 truncate">
                      {node.data.file_path}
                    </div>
                  )}
                </div>

                {/* Keyboard hint */}
                {isFocused && (
                  <span className="text-xs font-bold text-bauhaus-black/60">
                    ↵
                  </span>
                )}
              </button>
            );
          })}

          {/* Keyboard navigation hint */}
          <div className="px-3 py-2 bg-bauhaus-muted border-t-2 border-bauhaus-black flex items-center gap-4 text-xs text-bauhaus-black/60">
            <span className="flex items-center gap-1">
              <ArrowUp className="w-3 h-3" />
              <ArrowDown className="w-3 h-3" />
              navigate
            </span>
            <span>↵ select</span>
            <span>esc close</span>
          </div>
        </div>
      )}

      {/* No results */}
      {localQuery && searchResults.length === 0 && (
        <div className="absolute top-full left-0 right-0 mt-2 bg-bauhaus-white border-4 border-bauhaus-black shadow-bauhaus-lg px-4 py-6 text-center">
          <div className="font-bauhaus-heading text-bauhaus-black/60 mb-2">
            No Results
          </div>
          <p className="text-sm text-bauhaus-black/40">
            No nodes match "{localQuery}"
          </p>
        </div>
      )}
    </div>
  );
}

function TypeIndicator({ type }: { type: string }) {
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

  return (
    <div
      className={`w-4 h-4 border border-bauhaus-black ${colors[type] || 'bg-bauhaus-muted'} ${shapes[type] || ''}`}
    />
  );
}
