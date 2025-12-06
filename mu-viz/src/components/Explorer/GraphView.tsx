import { ArrowLeft, Settings, Download, Clock } from 'lucide-react';
import { Graph } from '../Graph';
import { FilterPanel } from '../Toolbar/FilterPanel';
import { NodeDetails } from '../Details/NodeDetails';
import { Timeline } from '../Timeline/Timeline';
import { ExportModal } from '../Export/ExportModal';
import { useUIStore } from '../../store/uiStore';
import { useGraphStore } from '../../store/graphStore';
import { Button } from '../common';

interface GraphViewProps {
  onBack: () => void;
  focusNodeId?: string | null;
}

export function GraphView({ onBack, focusNodeId }: GraphViewProps) {
  const {
    sidebarOpen,
    toggleSidebar,
    timelineOpen,
    toggleTimeline,
    exportModalOpen,
    setExportModalOpen,
  } = useUIStore();

  const { selectedNode, setSelectedNode, wsConnected, loading } = useGraphStore();

  // If we have a focus node and it's not selected, select it
  if (focusNodeId && selectedNode !== focusNodeId) {
    setSelectedNode(focusNodeId);
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-3 bg-bauhaus-black border-b-4 border-bauhaus-black">
        <button
          onClick={onBack}
          className="flex items-center gap-2 text-white hover:text-bauhaus-yellow transition-colors"
        >
          <ArrowLeft className="w-5 h-5" />
          <span className="font-bold uppercase tracking-wider text-sm">Back to Explorer</span>
        </button>

        <div className="flex items-center gap-3">
          {/* Connection Status */}
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

          <Button
            variant="ghost"
            onClick={toggleTimeline}
            className="text-white/80 hover:text-white text-sm"
          >
            <Clock className="w-4 h-4" />
            Timeline
          </Button>

          <Button
            variant="ghost"
            onClick={() => setExportModalOpen(true)}
            className="text-white/80 hover:text-white text-sm"
          >
            <Download className="w-4 h-4" />
            Export
          </Button>

          <Button
            variant="ghost"
            onClick={toggleSidebar}
            className="text-white/80 hover:text-white text-sm"
          >
            <Settings className="w-4 h-4" />
            Filters
          </Button>
        </div>
      </header>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Sidebar */}
        {sidebarOpen && (
          <aside className="w-72 bg-bauhaus-white border-r-4 border-bauhaus-black overflow-y-auto">
            <div className="p-4 border-b-4 border-bauhaus-black bg-bauhaus-yellow">
              <span className="font-bold uppercase tracking-wider text-bauhaus-black">
                Filters
              </span>
            </div>
            <div className="p-4">
              <FilterPanel />
            </div>
          </aside>
        )}

        {/* Main Graph Area */}
        <main className="flex-1 flex flex-col overflow-hidden">
          {/* Timeline */}
          {timelineOpen && (
            <div className="border-b-4 border-bauhaus-black bg-bauhaus-blue">
              <Timeline />
            </div>
          )}

          {/* Graph */}
          <div className="flex-1 overflow-hidden relative">
            <Graph />
          </div>
        </main>

        {/* Details Panel */}
        {selectedNode && (
          <aside className="w-80 bg-bauhaus-white border-l-4 border-bauhaus-black overflow-hidden">
            <NodeDetails />
          </aside>
        )}
      </div>

      {/* Export Modal */}
      {exportModalOpen && <ExportModal />}
    </div>
  );
}
