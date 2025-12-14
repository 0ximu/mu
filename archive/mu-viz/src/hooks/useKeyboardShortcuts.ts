import { useEffect } from 'react';
import { useUIStore } from '../store/uiStore';
import { useGraphStore } from '../store/graphStore';

export function useKeyboardShortcuts() {
  const {
    toggleSidebar,
    toggleTimeline,
    setExportModalOpen,
    clearSearch,
    clearPathFinding,
  } = useUIStore();

  const { setSelectedNode, setHighlightedPath, loadGraph } = useGraphStore();

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't trigger shortcuts when typing in inputs
      const target = e.target as HTMLElement;
      if (
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable
      ) {
        // Only handle Escape in inputs
        if (e.key === 'Escape') {
          (target as HTMLInputElement).blur();
        }
        return;
      }

      const isMod = e.metaKey || e.ctrlKey;

      // Global shortcuts
      switch (e.key) {
        // Toggle sidebar: Cmd/Ctrl + B
        case 'b':
          if (isMod) {
            e.preventDefault();
            toggleSidebar();
          }
          break;

        // Toggle timeline: Cmd/Ctrl + T
        case 't':
          if (isMod) {
            e.preventDefault();
            toggleTimeline();
          }
          break;

        // Export: Cmd/Ctrl + E
        case 'e':
          if (isMod) {
            e.preventDefault();
            setExportModalOpen(true);
          }
          break;

        // Refresh graph: Cmd/Ctrl + R
        case 'r':
          if (isMod) {
            e.preventDefault();
            loadGraph();
          }
          break;

        // Clear selection: Escape
        case 'Escape':
          setSelectedNode(null);
          setHighlightedPath([]);
          clearSearch();
          clearPathFinding();
          setExportModalOpen(false);
          break;

        // Focus search: /
        case '/':
          if (!isMod) {
            e.preventDefault();
            const searchInput = document.querySelector(
              'input[placeholder*="Search"]'
            ) as HTMLInputElement | null;
            searchInput?.focus();
          }
          break;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    toggleSidebar,
    toggleTimeline,
    setExportModalOpen,
    clearSearch,
    clearPathFinding,
    setSelectedNode,
    setHighlightedPath,
    loadGraph,
  ]);
}
