import { useUIStore } from '../../store/uiStore';
import { SearchView } from './SearchView';
import { NodeDetail } from './NodeDetail';
import { GraphView } from './GraphView';
import { SettingsPanel } from './SettingsPanel';

export function Explorer() {
  const {
    explorerView,
    setExplorerView,
    selectedNodeId,
    setSelectedNodeId,
  } = useUIStore();

  // Handle search result selection
  const handleResultSelect = (nodeId: string) => {
    setSelectedNodeId(nodeId);
    setExplorerView('detail');
  };

  // Handle navigation back to search
  const handleBackToSearch = () => {
    setSelectedNodeId(null);
    setExplorerView('search');
  };

  // Handle opening settings
  const handleSettingsClick = () => {
    setExplorerView('settings');
  };

  // Handle closing settings
  const handleSettingsClose = () => {
    setExplorerView('search');
  };

  // Handle node navigation in detail view
  const handleNodeClick = (nodeId: string) => {
    setSelectedNodeId(nodeId);
    // Stay in detail view
  };

  // Handle graph view
  const handleGraphView = () => {
    setExplorerView('graph');
  };

  // Handle back from graph
  const handleBackFromGraph = () => {
    if (selectedNodeId) {
      setExplorerView('detail');
    } else {
      setExplorerView('search');
    }
  };

  // Render based on current view
  switch (explorerView) {
    case 'search':
      return (
        <SearchView
          onResultSelect={handleResultSelect}
          onSettingsClick={handleSettingsClick}
        />
      );

    case 'detail':
      if (!selectedNodeId) {
        // Fallback to search if no node selected
        return (
          <SearchView
            onResultSelect={handleResultSelect}
            onSettingsClick={handleSettingsClick}
          />
        );
      }
      return (
        <NodeDetail
          nodeId={selectedNodeId}
          onBack={handleBackToSearch}
          onNodeClick={handleNodeClick}
          onGraphView={handleGraphView}
        />
      );

    case 'graph':
      return (
        <GraphView
          onBack={handleBackFromGraph}
          focusNodeId={selectedNodeId}
        />
      );

    case 'settings':
      return <SettingsPanel onClose={handleSettingsClose} />;

    default:
      return (
        <SearchView
          onResultSelect={handleResultSelect}
          onSettingsClick={handleSettingsClick}
        />
      );
  }
}
