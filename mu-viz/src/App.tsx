import { useEffect } from 'react';
import { Explorer } from './components/Explorer';
import { useGraphStore } from './store/graphStore';
import { useWebSocket } from './hooks';

function App() {
  const { loadGraph, error } = useGraphStore();

  // Connect WebSocket for live updates
  useWebSocket();

  // Load graph on mount
  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-bauhaus-canvas">
      <Explorer />

      {/* Global Error Toast */}
      {error && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50">
          <div className="bg-bauhaus-red text-white border-4 border-bauhaus-black shadow-bauhaus-xl px-6 py-3 flex items-center gap-4">
            <span className="font-bold">{error}</span>
            <button
              onClick={() => useGraphStore.setState({ error: null })}
              className="text-white/80 hover:text-white"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
