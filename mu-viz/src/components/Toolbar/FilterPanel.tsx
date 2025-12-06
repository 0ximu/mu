import { useGraphStore, type Filters } from '../../store/graphStore';
import { Button, Input, Select, Slider } from '../common';
import { LAYOUT_OPTIONS } from '../Graph/layouts';
import type { NodeType } from '../../api/types';
import { Circle, Square, Hexagon, RotateCcw } from 'lucide-react';

const NODE_TYPES: Array<{ type: NodeType; label: string; icon: typeof Circle; color: string }> = [
  { type: 'module', label: 'Module', icon: Square, color: 'bg-node-module' },
  { type: 'class', label: 'Class', icon: Square, color: 'bg-node-class' },
  { type: 'function', label: 'Function', icon: Circle, color: 'bg-node-function' },
  { type: 'external', label: 'External', icon: Hexagon, color: 'bg-node-external' },
];

const FILTER_PRESETS: Array<{ label: string; filters: Partial<Filters> }> = [
  {
    label: 'All Nodes',
    filters: {
      types: ['module', 'class', 'function', 'external'],
      minComplexity: 0,
      pathPattern: '',
    },
  },
  {
    label: 'High Complexity',
    filters: {
      types: ['module', 'class', 'function', 'external'],
      minComplexity: 100,
      pathPattern: '',
    },
  },
  {
    label: 'Classes Only',
    filters: {
      types: ['class'],
      minComplexity: 0,
      pathPattern: '',
    },
  },
  {
    label: 'Functions Only',
    filters: {
      types: ['function'],
      minComplexity: 0,
      pathPattern: '',
    },
  },
];

export function FilterPanel() {
  const { filters, setFilters, resetFilters, loadGraph } = useGraphStore();

  const toggleType = (type: NodeType) => {
    const current = filters.types || [];
    const updated = current.includes(type)
      ? current.filter((t) => t !== type)
      : [...current, type];
    setFilters({ types: updated });
  };

  const applyPreset = (preset: Partial<Filters>) => {
    setFilters(preset);
  };

  return (
    <div className="space-y-6">
      {/* Filter Presets */}
      <div>
        <h3 className="font-bauhaus-label text-bauhaus-black mb-3">Presets</h3>
        <div className="flex flex-wrap gap-2">
          {FILTER_PRESETS.map((preset) => (
            <Button
              key={preset.label}
              variant="outline"
              onClick={() => applyPreset(preset.filters)}
              className="text-xs px-2 py-1"
            >
              {preset.label}
            </Button>
          ))}
        </div>
      </div>

      {/* Node Types */}
      <div>
        <h3 className="font-bauhaus-label text-bauhaus-black mb-3">Node Types</h3>
        <div className="space-y-2">
          {NODE_TYPES.map(({ type, label, icon: Icon, color }) => {
            const isActive = filters.types?.includes(type) ?? true;
            return (
              <button
                key={type}
                onClick={() => toggleType(type)}
                className={`
                  w-full flex items-center gap-3 px-3 py-2
                  border-2 border-bauhaus-black
                  transition-all duration-200
                  ${isActive
                    ? `${color} text-white shadow-bauhaus-sm`
                    : 'bg-bauhaus-muted text-bauhaus-black/50'
                  }
                `}
              >
                <Icon className="w-4 h-4" />
                <span className="font-medium uppercase tracking-wider text-sm">
                  {label}
                </span>
                <span className="ml-auto font-bold">
                  {isActive ? 'ON' : 'OFF'}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Complexity Filter */}
      <div>
        <Slider
          label="Min Complexity"
          min={0}
          max={500}
          step={10}
          value={filters.minComplexity || 0}
          onChange={(e) => setFilters({ minComplexity: Number(e.target.value) })}
        />
      </div>

      {/* Path Filter */}
      <div>
        <Input
          label="Path Pattern"
          placeholder="e.g., src/services/*"
          value={filters.pathPattern || ''}
          onChange={(e) => setFilters({ pathPattern: e.target.value })}
        />
        <p className="text-xs text-bauhaus-black/60 mt-1">
          Regex pattern to filter by file path
        </p>
      </div>

      {/* Layout Selection */}
      <div>
        <Select
          label="Layout"
          value={filters.layout || 'cose'}
          onChange={(e) => setFilters({ layout: e.target.value })}
          options={LAYOUT_OPTIONS.map((l) => ({
            value: l.name,
            label: l.label,
          }))}
        />
      </div>

      {/* Action Buttons */}
      <div className="flex gap-2 pt-4 border-t-2 border-bauhaus-black">
        <Button variant="blue" onClick={loadGraph} className="flex-1">
          Apply
        </Button>
        <Button variant="outline" onClick={resetFilters}>
          <RotateCcw className="w-4 h-4" />
        </Button>
      </div>

      {/* Decorative Bauhaus element */}
      <div className="flex justify-center gap-2 pt-4">
        <div className="w-4 h-4 bg-bauhaus-red" />
        <div className="w-4 h-4 bg-bauhaus-blue rounded-full" />
        <div
          className="w-4 h-4 bg-bauhaus-yellow"
          style={{
            clipPath: 'polygon(50% 0%, 0% 100%, 100% 100%)',
          }}
        />
      </div>
    </div>
  );
}
