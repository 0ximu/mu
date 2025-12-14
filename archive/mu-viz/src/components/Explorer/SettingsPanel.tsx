import { X, RotateCcw, Circle, Square, Hexagon } from 'lucide-react';
import { useGraphStore, type Filters } from '../../store/graphStore';
import { Button, Input, Select, Slider } from '../common';
import { LAYOUT_OPTIONS } from '../Graph/layouts';
import type { NodeType } from '../../api/types';

interface SettingsPanelProps {
  onClose: () => void;
}

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

export function SettingsPanel({ onClose }: SettingsPanelProps) {
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

  const handleApply = () => {
    loadGraph();
    onClose();
  };

  return (
    <div className="h-full flex flex-col bg-bauhaus-canvas">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 bg-bauhaus-black border-b-4 border-bauhaus-black">
        <h1 className="text-xl font-black uppercase tracking-tight text-white">Settings</h1>
        <button
          onClick={onClose}
          className="p-2 text-white/60 hover:text-white hover:bg-white/10 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>
      </header>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-xl mx-auto space-y-8">
          {/* Filter Presets */}
          <section>
            <h2 className="font-bauhaus-heading text-bauhaus-black mb-4">Quick Presets</h2>
            <div className="flex flex-wrap gap-2">
              {FILTER_PRESETS.map((preset) => (
                <Button
                  key={preset.label}
                  variant="outline"
                  onClick={() => applyPreset(preset.filters)}
                  className="text-sm"
                >
                  {preset.label}
                </Button>
              ))}
            </div>
          </section>

          {/* Node Types */}
          <section>
            <h2 className="font-bauhaus-heading text-bauhaus-black mb-4">Node Types</h2>
            <div className="space-y-2">
              {NODE_TYPES.map(({ type, label, icon: Icon, color }) => {
                const isActive = filters.types?.includes(type) ?? true;
                return (
                  <button
                    key={type}
                    onClick={() => toggleType(type)}
                    className={`
                      w-full flex items-center gap-3 px-4 py-3
                      border-4 border-bauhaus-black
                      transition-all duration-200
                      ${
                        isActive
                          ? `${color} text-white shadow-bauhaus-md`
                          : 'bg-bauhaus-muted text-bauhaus-black/50'
                      }
                    `}
                  >
                    <Icon className="w-5 h-5" />
                    <span className="font-bold uppercase tracking-wider">{label}</span>
                    <span className="ml-auto font-bold">{isActive ? 'ON' : 'OFF'}</span>
                  </button>
                );
              })}
            </div>
          </section>

          {/* Complexity Filter */}
          <section>
            <h2 className="font-bauhaus-heading text-bauhaus-black mb-4">Complexity Threshold</h2>
            <div className="bg-bauhaus-white border-4 border-bauhaus-black p-4 shadow-bauhaus-md">
              <Slider
                label="Minimum Complexity"
                min={0}
                max={500}
                step={10}
                value={filters.minComplexity || 0}
                onChange={(e) => setFilters({ minComplexity: Number(e.target.value) })}
              />
              <p className="text-sm text-bauhaus-black/60 mt-2">
                Only show nodes with complexity &ge; {filters.minComplexity || 0}
              </p>
            </div>
          </section>

          {/* Path Filter */}
          <section>
            <h2 className="font-bauhaus-heading text-bauhaus-black mb-4">Path Pattern</h2>
            <div className="bg-bauhaus-white border-4 border-bauhaus-black p-4 shadow-bauhaus-md">
              <Input
                label="Regex Pattern"
                placeholder="e.g., src/services/*"
                value={filters.pathPattern || ''}
                onChange={(e) => setFilters({ pathPattern: e.target.value })}
              />
              <p className="text-sm text-bauhaus-black/60 mt-2">
                Filter nodes by file path using regex
              </p>
            </div>
          </section>

          {/* Layout Selection */}
          <section>
            <h2 className="font-bauhaus-heading text-bauhaus-black mb-4">Graph Layout</h2>
            <div className="bg-bauhaus-white border-4 border-bauhaus-black p-4 shadow-bauhaus-md">
              <Select
                label="Layout Algorithm"
                value={filters.layout || 'cose'}
                onChange={(e) => setFilters({ layout: e.target.value })}
                options={LAYOUT_OPTIONS.map((l) => ({
                  value: l.name,
                  label: l.label,
                }))}
              />
              <p className="text-sm text-bauhaus-black/60 mt-2">
                Controls how nodes are arranged in full graph view
              </p>
            </div>
          </section>
        </div>
      </div>

      {/* Footer Actions */}
      <footer className="flex items-center justify-between px-6 py-4 bg-bauhaus-white border-t-4 border-bauhaus-black">
        <Button variant="ghost" onClick={resetFilters} className="flex items-center gap-2">
          <RotateCcw className="w-4 h-4" />
          Reset All
        </Button>
        <div className="flex gap-3">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="blue" onClick={handleApply}>
            Apply & Close
          </Button>
        </div>
      </footer>
    </div>
  );
}
