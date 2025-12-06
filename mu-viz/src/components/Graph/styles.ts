// eslint-disable-next-line @typescript-eslint/no-explicit-any
type CytoscapeStylesheet = any;

// Bauhaus color palette
const COLORS = {
  red: '#D02020',
  blue: '#1040C0',
  yellow: '#F0C020',
  black: '#121212',
  white: '#FFFFFF',
  gray: '#808080',
  muted: '#E0E0E0',
};

// Node type to Bauhaus color mapping
const NODE_COLORS: Record<string, string> = {
  module: COLORS.blue,
  class: COLORS.red,
  function: COLORS.yellow,
  external: COLORS.gray,
};

// Node type to shape mapping (Bauhaus geometric forms)
const NODE_SHAPES: Record<string, string> = {
  module: 'round-rectangle', // Foundational, architectural
  class: 'rectangle',        // Solid, structured
  function: 'ellipse',       // Dynamic, circular
  external: 'hexagon',       // External, unusual
};

// Edge type colors
const EDGE_COLORS: Record<string, string> = {
  imports: COLORS.blue,
  inherits: COLORS.red,
  contains: COLORS.gray,
};

export const cytoscapeStyles: CytoscapeStylesheet[] = [
  // ========================================
  // BASE NODE STYLE - Bauhaus Principles
  // ========================================
  {
    selector: 'node',
    style: {
      // Label
      'label': 'data(label)',
      'text-valign': 'center',
      'text-halign': 'center',
      'font-family': 'Outfit, system-ui, sans-serif',
      'font-size': '11px',
      'font-weight': 700,
      'color': COLORS.white,
      'text-outline-color': COLORS.black,
      'text-outline-width': 2,
      'text-max-width': '80px',
      'text-wrap': 'ellipsis',

      // Geometry
      'width': 50,
      'height': 50,
      'background-color': COLORS.blue,
      'shape': 'rectangle',

      // Bauhaus border style
      'border-width': 3,
      'border-color': COLORS.black,

      // Transition for interactions
      'transition-property': 'background-color, border-color, width, height',
      'transition-duration': '200ms',
    },
  },

  // ========================================
  // NODE TYPE VARIANTS
  // ========================================
  {
    selector: 'node[type="module"]',
    style: {
      'background-color': NODE_COLORS.module,
      'shape': NODE_SHAPES.module,
      'width': 70,
      'height': 35,
    },
  },
  {
    selector: 'node[type="class"]',
    style: {
      'background-color': NODE_COLORS.class,
      'shape': NODE_SHAPES.class,
      'width': 55,
      'height': 55,
    },
  },
  {
    selector: 'node[type="function"]',
    style: {
      'background-color': NODE_COLORS.function,
      'shape': NODE_SHAPES.function,
      'color': COLORS.black,
      'text-outline-color': COLORS.yellow,
    },
  },
  {
    selector: 'node[type="external"]',
    style: {
      'background-color': NODE_COLORS.external,
      'shape': NODE_SHAPES.external,
      'opacity': 0.7,
    },
  },

  // ========================================
  // COMPLEXITY-BASED SIZING (Bauhaus scale)
  // ========================================
  {
    selector: 'node[complexity > 50]',
    style: {
      'width': 60,
      'height': 60,
    },
  },
  {
    selector: 'node[complexity > 100]',
    style: {
      'width': 70,
      'height': 70,
    },
  },
  {
    selector: 'node[complexity > 250]',
    style: {
      'width': 80,
      'height': 80,
      'border-width': 4,
    },
  },
  {
    selector: 'node[complexity > 500]',
    style: {
      'width': 90,
      'height': 90,
      'border-width': 5,
      'border-color': COLORS.red,
    },
  },

  // ========================================
  // BASE EDGE STYLE
  // ========================================
  {
    selector: 'edge',
    style: {
      'width': 2,
      'line-color': COLORS.gray,
      'target-arrow-color': COLORS.gray,
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      'arrow-scale': 1,
      'opacity': 0.8,
      'transition-property': 'line-color, target-arrow-color, width, opacity',
      'transition-duration': '200ms',
    },
  },

  // ========================================
  // EDGE TYPE VARIANTS
  // ========================================
  {
    selector: 'edge[type="imports"]',
    style: {
      'line-color': EDGE_COLORS.imports,
      'target-arrow-color': EDGE_COLORS.imports,
      'width': 2,
    },
  },
  {
    selector: 'edge[type="inherits"]',
    style: {
      'line-color': EDGE_COLORS.inherits,
      'target-arrow-color': EDGE_COLORS.inherits,
      'width': 3,
      'target-arrow-shape': 'triangle-tee',
    },
  },
  {
    selector: 'edge[type="contains"]',
    style: {
      'line-color': EDGE_COLORS.contains,
      'target-arrow-color': EDGE_COLORS.contains,
      'line-style': 'dashed',
      'opacity': 0.5,
    },
  },

  // ========================================
  // SELECTION STATE - Bauhaus Yellow highlight
  // ========================================
  {
    selector: 'node:selected',
    style: {
      'border-width': 5,
      'border-color': COLORS.yellow,
      'background-opacity': 1,
    },
  },
  {
    selector: 'node:active',
    style: {
      'overlay-color': COLORS.yellow,
      'overlay-padding': 8,
      'overlay-opacity': 0.3,
    },
  },

  // ========================================
  // HIGHLIGHTED PATH - Yellow trace
  // ========================================
  {
    selector: '.highlighted',
    style: {
      'background-color': COLORS.yellow,
      'line-color': COLORS.yellow,
      'target-arrow-color': COLORS.yellow,
      'color': COLORS.black,
      'text-outline-color': COLORS.yellow,
      'border-color': COLORS.black,
      'width': 4,
      'z-index': 999,
    },
  },
  {
    selector: 'node.highlighted',
    style: {
      'border-width': 5,
    },
  },

  // ========================================
  // DIMMED STATE (when path is highlighted)
  // ========================================
  {
    selector: '.dimmed',
    style: {
      'opacity': 0.2,
    },
  },

  // ========================================
  // SEARCH MATCH
  // ========================================
  {
    selector: '.search-match',
    style: {
      'border-width': 4,
      'border-color': COLORS.red,
      'border-style': 'double',
    },
  },

  // ========================================
  // HOVER STATES
  // ========================================
  {
    selector: 'node:grabbable',
    style: {
      'cursor': 'grab',
    },
  },
  {
    selector: 'node:grabbed',
    style: {
      'cursor': 'grabbing',
    },
  },
];

export { COLORS, NODE_COLORS, EDGE_COLORS };
