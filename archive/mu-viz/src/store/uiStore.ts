import { create } from 'zustand';
import { persist } from 'zustand/middleware';

type ExplorerView = 'search' | 'detail' | 'graph' | 'settings';

interface UIState {
  // Explorer mode
  explorerView: ExplorerView;
  selectedNodeId: string | null;
  recentNodes: string[];
  settingsOpen: boolean;

  // Panel visibility
  sidebarOpen: boolean;
  detailsPanelOpen: boolean;
  timelineOpen: boolean;

  // Search
  searchQuery: string;
  searchResults: string[];
  searchFocusedIndex: number;

  // Path finding
  pathFindingMode: boolean;
  pathSource: string | null;
  pathTarget: string | null;

  // Export
  exportModalOpen: boolean;

  // Explorer Actions
  setExplorerView: (view: ExplorerView) => void;
  setSelectedNodeId: (nodeId: string | null) => void;
  addRecentNode: (nodeId: string) => void;
  clearRecentNodes: () => void;
  setSettingsOpen: (open: boolean) => void;

  // Actions
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  toggleDetailsPanel: () => void;
  setDetailsPanelOpen: (open: boolean) => void;
  toggleTimeline: () => void;
  setTimelineOpen: (open: boolean) => void;

  setSearchQuery: (query: string) => void;
  setSearchResults: (results: string[]) => void;
  setSearchFocusedIndex: (index: number) => void;
  clearSearch: () => void;

  setPathFindingMode: (enabled: boolean) => void;
  setPathSource: (nodeId: string | null) => void;
  setPathTarget: (nodeId: string | null) => void;
  clearPathFinding: () => void;

  setExportModalOpen: (open: boolean) => void;
}

const MAX_RECENT_NODES = 10;

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      // Initial state - Explorer
      explorerView: 'search' as ExplorerView,
      selectedNodeId: null,
      recentNodes: [],
      settingsOpen: false,

      // Initial state - Panels
      sidebarOpen: true,
      detailsPanelOpen: false,
      timelineOpen: false,
      searchQuery: '',
      searchResults: [],
      searchFocusedIndex: -1,
      pathFindingMode: false,
      pathSource: null,
      pathTarget: null,
      exportModalOpen: false,

      // Explorer Actions
      setExplorerView: (view) => set({ explorerView: view }),
      setSelectedNodeId: (nodeId) => set({ selectedNodeId: nodeId }),
      addRecentNode: (nodeId) =>
        set((s) => {
          const filtered = s.recentNodes.filter((id) => id !== nodeId);
          return {
            recentNodes: [nodeId, ...filtered].slice(0, MAX_RECENT_NODES),
          };
        }),
      clearRecentNodes: () => set({ recentNodes: [] }),
      setSettingsOpen: (open) => set({ settingsOpen: open }),

      // Actions
      toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
      setSidebarOpen: (open) => set({ sidebarOpen: open }),

      toggleDetailsPanel: () => set((s) => ({ detailsPanelOpen: !s.detailsPanelOpen })),
      setDetailsPanelOpen: (open) => set({ detailsPanelOpen: open }),

      toggleTimeline: () => set((s) => ({ timelineOpen: !s.timelineOpen })),
      setTimelineOpen: (open) => set({ timelineOpen: open }),

      setSearchQuery: (query) => set({ searchQuery: query }),
      setSearchResults: (results) => set({ searchResults: results }),
      setSearchFocusedIndex: (index) => set({ searchFocusedIndex: index }),
      clearSearch: () => set({ searchQuery: '', searchResults: [], searchFocusedIndex: -1 }),

      setPathFindingMode: (enabled) => set({ pathFindingMode: enabled }),
      setPathSource: (nodeId) => set({ pathSource: nodeId }),
      setPathTarget: (nodeId) => set({ pathTarget: nodeId }),
      clearPathFinding: () =>
        set({ pathFindingMode: false, pathSource: null, pathTarget: null }),

      setExportModalOpen: (open) => set({ exportModalOpen: open }),
    }),
    {
      name: 'mu-explorer-ui',
      partialize: (state) => ({
        recentNodes: state.recentNodes,
      }),
    }
  )
);
