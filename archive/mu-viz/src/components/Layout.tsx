import { type ReactNode } from 'react';
import {
  Circle,
  Square,
  Triangle,
  PanelLeftClose,
  PanelLeftOpen,
  Clock,
  Download,
} from 'lucide-react';
import { Button } from './common';
import { useUIStore } from '../store/uiStore';
import { useGraphStore } from '../store/graphStore';

interface LayoutProps {
  sidebar: ReactNode;
  main: ReactNode;
  details?: ReactNode;
  timeline?: ReactNode;
}

export function Layout({ sidebar, main, details, timeline }: LayoutProps) {
  const {
    sidebarOpen,
    toggleSidebar,
    timelineOpen,
    toggleTimeline,
    setExportModalOpen,
  } = useUIStore();

  const { wsConnected, loading } = useGraphStore();

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-bauhaus-canvas">
      {/* Navigation Bar */}
      <nav className="flex items-center justify-between px-4 py-3 bg-bauhaus-black border-b-4 border-bauhaus-black">
        {/* Logo - Bauhaus geometric composition */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1">
            <Circle className="w-5 h-5 text-bauhaus-red fill-bauhaus-red" />
            <Square className="w-5 h-5 text-bauhaus-blue fill-bauhaus-blue" />
            <Triangle className="w-5 h-5 text-bauhaus-yellow fill-bauhaus-yellow" />
          </div>
          <h1 className="text-xl font-black uppercase tracking-tight text-white">
            MU Visualizer
          </h1>
        </div>

        {/* Nav Actions */}
        <div className="flex items-center gap-2">
          {/* Connection Status */}
          <div className="flex items-center gap-2 mr-4">
            <div
              className={`w-3 h-3 rounded-full border-2 border-white ${
                wsConnected ? 'bg-bauhaus-yellow' : 'bg-bauhaus-red'
              }`}
            />
            <span className="text-white text-sm font-medium uppercase tracking-wider">
              {loading ? 'Loading...' : wsConnected ? 'Live' : 'Offline'}
            </span>
          </div>

          <Button
            variant="ghost"
            onClick={toggleTimeline}
            className="text-white hover:bg-white/10"
          >
            <Clock className="w-5 h-5" />
            <span className="hidden sm:inline">Timeline</span>
          </Button>

          <Button
            variant="ghost"
            onClick={() => setExportModalOpen(true)}
            className="text-white hover:bg-white/10"
          >
            <Download className="w-5 h-5" />
            <span className="hidden sm:inline">Export</span>
          </Button>
        </div>
      </nav>

      {/* Main Content Area */}
      <div className="flex-1 flex overflow-hidden">
        {/* Sidebar */}
        <aside
          className={`
            flex flex-col
            bg-bauhaus-white
            border-r-4 border-bauhaus-black
            transition-all duration-300 ease-out
            ${sidebarOpen ? 'w-72' : 'w-0'}
            overflow-hidden
          `}
        >
          {/* Sidebar Header */}
          <div className="flex items-center justify-between p-3 border-b-4 border-bauhaus-black bg-bauhaus-yellow">
            <span className="font-bold uppercase tracking-wider text-bauhaus-black">
              Filters
            </span>
            <button
              onClick={toggleSidebar}
              className="p-1 hover:bg-bauhaus-black/10 transition-colors"
            >
              <PanelLeftClose className="w-5 h-5" />
            </button>
          </div>

          {/* Sidebar Content */}
          <div className="flex-1 overflow-y-auto p-4">{sidebar}</div>
        </aside>

        {/* Sidebar Toggle (when closed) */}
        {!sidebarOpen && (
          <button
            onClick={toggleSidebar}
            className="
              absolute left-0 top-1/2 -translate-y-1/2 z-10
              bg-bauhaus-yellow
              border-2 border-l-0 border-bauhaus-black
              p-2
              hover:bg-bauhaus-yellow/80
              transition-colors
            "
          >
            <PanelLeftOpen className="w-5 h-5" />
          </button>
        )}

        {/* Graph Container */}
        <main className="flex-1 flex flex-col overflow-hidden relative">
          {/* Timeline (collapsible) */}
          {timelineOpen && timeline && (
            <div className="border-b-4 border-bauhaus-black bg-bauhaus-blue">
              {timeline}
            </div>
          )}

          {/* Graph Area */}
          <div className="flex-1 overflow-hidden relative">{main}</div>
        </main>

        {/* Details Panel */}
        {details && (
          <aside className="w-80 bg-bauhaus-white border-l-4 border-bauhaus-black overflow-hidden">
            {details}
          </aside>
        )}
      </div>

      {/* Footer Stats Bar */}
      <footer className="flex items-center justify-between px-4 py-2 bg-bauhaus-black border-t-4 border-bauhaus-black">
        <div className="flex items-center gap-4">
          <Stat label="Nodes" color="blue" />
          <Stat label="Edges" color="red" />
          <Stat label="Modules" color="yellow" />
        </div>
        <span className="text-white/60 text-xs uppercase tracking-wider">
          MU Visualization Engine v1.0
        </span>
      </footer>
    </div>
  );
}

function Stat({ label, color }: { label: string; color: 'red' | 'blue' | 'yellow' }) {
  const { elements } = useGraphStore();

  const colorClass = {
    red: 'bg-bauhaus-red',
    blue: 'bg-bauhaus-blue',
    yellow: 'bg-bauhaus-yellow text-bauhaus-black',
  }[color];

  const getValue = () => {
    if (!elements) return '—';
    if (label === 'Nodes') return elements.nodes.length;
    if (label === 'Edges') return elements.edges.length;
    if (label === 'Modules') {
      return elements.nodes.filter((n) => n.data.type === 'module').length;
    }
    return '—';
  };

  return (
    <div className="flex items-center gap-2">
      <div className={`w-3 h-3 ${colorClass}`} />
      <span className="text-white text-sm">
        <span className="font-bold">{getValue()}</span>{' '}
        <span className="opacity-60 uppercase text-xs tracking-wider">{label}</span>
      </span>
    </div>
  );
}
