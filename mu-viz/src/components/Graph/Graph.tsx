import { useEffect, useRef, useCallback } from 'react';
import cytoscape, { type Core, type NodeSingular } from 'cytoscape';
import dagre from 'cytoscape-dagre';
import { useGraphStore } from '../../store/graphStore';
import { useUIStore } from '../../store/uiStore';
import { cytoscapeStyles } from './styles';
import { getLayout, type LayoutName } from './layouts';
import { ZoomIn, ZoomOut, Maximize2, RefreshCw } from 'lucide-react';
import { Button } from '../common';

// Register dagre layout
cytoscape.use(dagre);

export function Graph() {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  const {
    elements,
    selectedNode,
    highlightedPath,
    filters,
    loading,
    setSelectedNode,
  } = useGraphStore();

  const {
    searchResults,
    pathFindingMode,
    pathSource,
    setPathSource,
    setPathTarget,
  } = useUIStore();

  // Initialize Cytoscape
  useEffect(() => {
    if (!containerRef.current) return;

    const cy = cytoscape({
      container: containerRef.current,
      elements: [],
      style: cytoscapeStyles,
      layout: { name: 'preset' },
      wheelSensitivity: 0.3,
      minZoom: 0.1,
      maxZoom: 3,
      // Performance optimizations for large graphs
      textureOnViewport: true,
      hideEdgesOnViewport: true,
      hideLabelsOnViewport: true,
      pixelRatio: 1, // Use device pixel ratio of 1 for performance
    });

    // Event handlers
    cy.on('tap', 'node', (evt) => {
      const node = evt.target as NodeSingular;
      const nodeId = node.id();

      if (pathFindingMode) {
        if (!pathSource) {
          setPathSource(nodeId);
        } else {
          setPathTarget(nodeId);
        }
      } else {
        setSelectedNode(nodeId);
      }
    });

    cy.on('tap', (evt) => {
      if (evt.target === cy) {
        setSelectedNode(null);
      }
    });

    // Double-click to focus
    cy.on('dbltap', 'node', (evt) => {
      const node = evt.target as NodeSingular;
      cy.animate({
        center: { eles: node },
        zoom: 1.5,
        duration: 300,
      });
    });

    cyRef.current = cy;

    return () => {
      cy.destroy();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Update elements when data changes
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !elements) return;

    cy.elements().remove();
    cy.add([
      ...elements.nodes.map((n) => ({ group: 'nodes' as const, ...n })),
      ...elements.edges.map((e) => ({ group: 'edges' as const, ...e })),
    ]);

    // Apply layout
    const layout = getLayout(filters.layout as LayoutName);
    cy.layout(layout).run();
  }, [elements, filters.layout]);

  // Apply type filters
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    cy.nodes().forEach((node) => {
      const data = node.data();
      let visible = true;

      // Type filter
      if (filters.types && !filters.types.includes(data.type)) {
        visible = false;
      }

      // Complexity filter
      if (filters.minComplexity && (data.complexity || 0) < filters.minComplexity) {
        visible = false;
      }

      // Path filter
      if (filters.pathPattern) {
        try {
          const regex = new RegExp(filters.pathPattern, 'i');
          if (!data.file_path?.match(regex)) {
            visible = false;
          }
        } catch {
          // Invalid regex, ignore filter
        }
      }

      node.style('display', visible ? 'element' : 'none');
    });

    // Hide edges connected to hidden nodes
    cy.edges().forEach((edge) => {
      const source = edge.source();
      const target = edge.target();
      const visible =
        source.style('display') === 'element' && target.style('display') === 'element';
      edge.style('display', visible ? 'element' : 'none');
    });
  }, [filters.types, filters.minComplexity, filters.pathPattern]);

  // Highlight path
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    // Reset all highlights
    cy.elements().removeClass('highlighted dimmed');

    if (highlightedPath && highlightedPath.length > 0) {
      // Dim all elements
      cy.elements().addClass('dimmed');

      // Highlight path nodes and edges
      for (let i = 0; i < highlightedPath.length; i++) {
        const nodeId = highlightedPath[i];
        const node = cy.getElementById(nodeId);
        node.removeClass('dimmed').addClass('highlighted');

        if (i < highlightedPath.length - 1) {
          const nextId = highlightedPath[i + 1];
          cy.edges(`[source = "${nodeId}"][target = "${nextId}"]`)
            .removeClass('dimmed')
            .addClass('highlighted');
          cy.edges(`[source = "${nextId}"][target = "${nodeId}"]`)
            .removeClass('dimmed')
            .addClass('highlighted');
        }
      }
    }
  }, [highlightedPath]);

  // Center on selected node
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !selectedNode) return;

    const node = cy.getElementById(selectedNode);
    if (node.length > 0) {
      cy.animate({
        center: { eles: node },
        duration: 300,
      });
    }
  }, [selectedNode]);

  // Highlight search results
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    cy.nodes().removeClass('search-match');

    if (searchResults.length > 0) {
      searchResults.forEach((id) => {
        cy.getElementById(id).addClass('search-match');
      });
    }
  }, [searchResults]);

  // Control functions
  const handleZoomIn = useCallback(() => {
    cyRef.current?.zoom({
      level: (cyRef.current.zoom() || 1) * 1.3,
      renderedPosition: {
        x: containerRef.current!.clientWidth / 2,
        y: containerRef.current!.clientHeight / 2,
      },
    });
  }, []);

  const handleZoomOut = useCallback(() => {
    cyRef.current?.zoom({
      level: (cyRef.current.zoom() || 1) * 0.7,
      renderedPosition: {
        x: containerRef.current!.clientWidth / 2,
        y: containerRef.current!.clientHeight / 2,
      },
    });
  }, []);

  const handleFit = useCallback(() => {
    cyRef.current?.fit(undefined, 50);
  }, []);

  const handleRelayout = useCallback(() => {
    if (!cyRef.current) return;
    const layout = getLayout(filters.layout as LayoutName);
    cyRef.current.layout(layout).run();
  }, [filters.layout]);

  return (
    <div className="relative w-full h-full">
      {/* Graph container with Bauhaus pattern background */}
      <div
        ref={containerRef}
        className="w-full h-full bg-bauhaus-canvas pattern-dots"
        style={{
          backgroundImage: 'radial-gradient(#E0E0E0 1.5px, transparent 1.5px)',
          backgroundSize: '20px 20px',
        }}
      />

      {/* Loading overlay */}
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-bauhaus-canvas/80">
          <div className="flex flex-col items-center gap-4">
            {/* Bauhaus loading animation - rotating shapes */}
            <div className="relative w-20 h-20">
              <div className="absolute inset-0 w-10 h-10 bg-bauhaus-red animate-spin" style={{ animationDuration: '2s' }} />
              <div className="absolute inset-0 w-12 h-12 rounded-full bg-bauhaus-blue animate-ping opacity-30" />
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="w-6 h-6 bg-bauhaus-yellow rotate-45" />
              </div>
            </div>
            <span className="font-bauhaus-heading text-bauhaus-black">Loading Graph...</span>
          </div>
        </div>
      )}

      {/* Zoom controls - Bauhaus styled */}
      <div className="absolute bottom-4 right-4 flex flex-col gap-2">
        <Button variant="outline" onClick={handleZoomIn} className="p-2">
          <ZoomIn className="w-5 h-5" />
        </Button>
        <Button variant="outline" onClick={handleZoomOut} className="p-2">
          <ZoomOut className="w-5 h-5" />
        </Button>
        <Button variant="outline" onClick={handleFit} className="p-2">
          <Maximize2 className="w-5 h-5" />
        </Button>
        <Button variant="outline" onClick={handleRelayout} className="p-2">
          <RefreshCw className="w-5 h-5" />
        </Button>
      </div>

      {/* Path finding mode indicator */}
      {pathFindingMode && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 bg-bauhaus-yellow border-4 border-bauhaus-black shadow-bauhaus-lg px-6 py-3">
          <span className="font-bauhaus-heading text-bauhaus-black">
            {!pathSource
              ? 'Click source node'
              : 'Click target node'}
          </span>
        </div>
      )}

      {/* Legend */}
      <div className="absolute bottom-4 left-4 bg-bauhaus-white border-2 border-bauhaus-black p-3 shadow-bauhaus-md">
        <div className="font-bauhaus-label mb-2">Legend</div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          <div className="flex items-center gap-2">
            <div className="w-4 h-3 bg-node-module border border-bauhaus-black" />
            <span>Module</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 bg-node-class border border-bauhaus-black" />
            <span>Class</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 rounded-full bg-node-function border border-bauhaus-black" />
            <span>Function</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 rotate-45 bg-node-entity border border-bauhaus-black" />
            <span>Entity</span>
          </div>
        </div>
      </div>
    </div>
  );
}
