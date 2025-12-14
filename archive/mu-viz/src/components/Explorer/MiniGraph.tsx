import { useMemo } from 'react';
import type { CytoscapeData, NodeType } from '../../api/types';

interface MiniGraphProps {
  data: CytoscapeData;
  centerNodeId: string;
  onNodeClick: (nodeId: string) => void;
}

interface PositionedNode {
  id: string;
  label: string;
  type: NodeType;
  x: number;
  y: number;
  isCenter: boolean;
}

interface PositionedEdge {
  source: string;
  target: string;
  sourceX: number;
  sourceY: number;
  targetX: number;
  targetY: number;
}

const NODE_COLORS: Record<NodeType, string> = {
  module: '#1040C0',
  class: '#D02020',
  function: '#F0C020',
  external: '#808080',
};

const NODE_WIDTH = 120;
const NODE_HEIGHT = 36;
const PADDING = 40;

export function MiniGraph({ data, centerNodeId, onNodeClick }: MiniGraphProps) {
  const layout = useMemo(() => {
    if (data.nodes.length === 0) {
      return { nodes: [], edges: [], width: 0, height: 0 };
    }

    // Separate nodes into center, dependencies (left), and usedBy (right)
    const centerNode = data.nodes.find((n) => n.data.id === centerNodeId);
    const dependencies = data.edges
      .filter((e) => e.data.source === centerNodeId)
      .map((e) => data.nodes.find((n) => n.data.id === e.data.target))
      .filter(Boolean);
    const usedBy = data.edges
      .filter((e) => e.data.target === centerNodeId)
      .map((e) => data.nodes.find((n) => n.data.id === e.data.source))
      .filter(Boolean);

    // Calculate dimensions
    const maxSideNodes = Math.max(dependencies.length, usedBy.length, 1);
    const height = Math.max(maxSideNodes * (NODE_HEIGHT + 20) + PADDING * 2, 200);
    const width = NODE_WIDTH * 3 + PADDING * 4;

    // Position center node
    const nodes: PositionedNode[] = [];
    const centerX = width / 2;
    const centerY = height / 2;

    if (centerNode) {
      nodes.push({
        id: centerNode.data.id,
        label: centerNode.data.label,
        type: centerNode.data.type,
        x: centerX,
        y: centerY,
        isCenter: true,
      });
    }

    // Position dependencies on the left
    const depStartY = (height - (dependencies.length - 1) * (NODE_HEIGHT + 20)) / 2;
    dependencies.forEach((node, i) => {
      if (node) {
        nodes.push({
          id: node.data.id,
          label: node.data.label,
          type: node.data.type,
          x: PADDING + NODE_WIDTH / 2,
          y: depStartY + i * (NODE_HEIGHT + 20),
          isCenter: false,
        });
      }
    });

    // Position usedBy on the right
    const usedByStartY = (height - (usedBy.length - 1) * (NODE_HEIGHT + 20)) / 2;
    usedBy.forEach((node, i) => {
      if (node) {
        nodes.push({
          id: node.data.id,
          label: node.data.label,
          type: node.data.type,
          x: width - PADDING - NODE_WIDTH / 2,
          y: usedByStartY + i * (NODE_HEIGHT + 20),
          isCenter: false,
        });
      }
    });

    // Create positioned edges
    const nodePositions = Object.fromEntries(nodes.map((n) => [n.id, { x: n.x, y: n.y }]));
    const edges: PositionedEdge[] = data.edges
      .filter((e) => nodePositions[e.data.source] && nodePositions[e.data.target])
      .map((e) => ({
        source: e.data.source,
        target: e.data.target,
        sourceX: nodePositions[e.data.source].x,
        sourceY: nodePositions[e.data.source].y,
        targetX: nodePositions[e.data.target].x,
        targetY: nodePositions[e.data.target].y,
      }));

    return { nodes, edges, width, height };
  }, [data, centerNodeId]);

  if (layout.nodes.length === 0) {
    return (
      <div className="w-full h-full flex items-center justify-center text-bauhaus-black/40">
        No connections to display
      </div>
    );
  }

  return (
    <div className="w-full h-full overflow-hidden">
      <svg width="100%" height="100%" viewBox={`0 0 ${layout.width} ${layout.height}`}>
        {/* Grid pattern background */}
        <defs>
          <pattern id="mini-grid" width="20" height="20" patternUnits="userSpaceOnUse">
            <circle cx="1" cy="1" r="1" fill="#E0E0E0" />
          </pattern>
          {/* Arrow marker */}
          <marker
            id="mini-arrowhead"
            markerWidth="10"
            markerHeight="7"
            refX="9"
            refY="3.5"
            orient="auto"
          >
            <polygon points="0 0, 10 3.5, 0 7" fill="#121212" />
          </marker>
        </defs>
        <rect width="100%" height="100%" fill="url(#mini-grid)" />

        {/* Edges */}
        {layout.edges.map((edge, i) => {
          // Calculate edge endpoints to stop at node borders
          const dx = edge.targetX - edge.sourceX;
          const dy = edge.targetY - edge.sourceY;
          const len = Math.sqrt(dx * dx + dy * dy);
          if (len === 0) return null;

          const ux = dx / len;
          const uy = dy / len;

          // Offset from center of node to border
          const sourceOffset = NODE_WIDTH / 2 + 5;
          const targetOffset = NODE_WIDTH / 2 + 10;

          const x1 = edge.sourceX + ux * sourceOffset;
          const y1 = edge.sourceY + uy * sourceOffset;
          const x2 = edge.targetX - ux * targetOffset;
          const y2 = edge.targetY - uy * targetOffset;

          return (
            <line
              key={`${edge.source}-${edge.target}-${i}`}
              x1={x1}
              y1={y1}
              x2={x2}
              y2={y2}
              stroke="#121212"
              strokeWidth="2"
              markerEnd="url(#mini-arrowhead)"
            />
          );
        })}

        {/* Nodes */}
        {layout.nodes.map((node) => (
          <g
            key={node.id}
            transform={`translate(${node.x - NODE_WIDTH / 2}, ${node.y - NODE_HEIGHT / 2})`}
            className="cursor-pointer"
            onClick={() => !node.isCenter && onNodeClick(node.id)}
          >
            {/* Node background */}
            <rect
              width={NODE_WIDTH}
              height={NODE_HEIGHT}
              rx={node.type === 'function' ? NODE_HEIGHT / 2 : 0}
              ry={node.type === 'function' ? NODE_HEIGHT / 2 : 0}
              fill={NODE_COLORS[node.type]}
              stroke="#121212"
              strokeWidth={node.isCenter ? 4 : 2}
            />
            {/* Center marker */}
            {node.isCenter && (
              <text
                x={NODE_WIDTH / 2}
                y={-8}
                textAnchor="middle"
                fontSize="10"
                fontWeight="bold"
                fill="#121212"
              >
                YOU ARE HERE
              </text>
            )}
            {/* Node label */}
            <text
              x={NODE_WIDTH / 2}
              y={NODE_HEIGHT / 2 + 4}
              textAnchor="middle"
              fontSize="11"
              fontWeight="600"
              fill={node.type === 'function' ? '#121212' : '#FFFFFF'}
            >
              {truncateLabel(node.label, 14)}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

function truncateLabel(label: string, maxLength: number): string {
  if (label.length <= maxLength) return label;
  return label.slice(0, maxLength - 2) + '...';
}
