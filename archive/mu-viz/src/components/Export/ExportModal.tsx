import { useState, useCallback } from 'react';
import {
  X,
  Image,
  FileCode,
  Link2,
  Download,
  Check,
  Copy,
} from 'lucide-react';
import { useUIStore } from '../../store/uiStore';
import { useGraphStore } from '../../store/graphStore';
import { Button, Panel } from '../common';

type ExportFormat = 'png' | 'svg' | 'json' | 'link';

interface ExportOption {
  format: ExportFormat;
  label: string;
  description: string;
  icon: typeof Image;
}

const EXPORT_OPTIONS: ExportOption[] = [
  {
    format: 'png',
    label: 'PNG Image',
    description: 'Rasterized image for presentations',
    icon: Image,
  },
  {
    format: 'svg',
    label: 'SVG Vector',
    description: 'Scalable vector for editing',
    icon: FileCode,
  },
  {
    format: 'json',
    label: 'JSON Data',
    description: 'Raw graph data for processing',
    icon: FileCode,
  },
  {
    format: 'link',
    label: 'Share Link',
    description: 'Link with current view state',
    icon: Link2,
  },
];

export function ExportModal() {
  const { exportModalOpen, setExportModalOpen } = useUIStore();
  const { elements, filters, selectedNode, highlightedPath } = useGraphStore();

  const [selectedFormat, setSelectedFormat] = useState<ExportFormat>('png');
  const [exporting, setExporting] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleExport = useCallback(async () => {
    if (!elements) return;

    setExporting(true);

    try {
      switch (selectedFormat) {
        case 'png':
        case 'svg': {
          // Get Cytoscape instance and export
          // Note: This would normally access the cy instance via ref
          // For now, we'll create a blob from the elements
          const mimeType = selectedFormat === 'png' ? 'image/png' : 'image/svg+xml';
          const extension = selectedFormat;

          // Placeholder - actual implementation would use cy.png() or cy.svg()
          const dataUrl = `data:${mimeType};base64,${btoa('Export placeholder')}`;

          // Trigger download
          const link = document.createElement('a');
          link.href = dataUrl;
          link.download = `mu-graph-${Date.now()}.${extension}`;
          link.click();
          break;
        }

        case 'json': {
          const data = {
            exported_at: new Date().toISOString(),
            nodes: elements.nodes,
            edges: elements.edges,
            filters,
            view_state: {
              selectedNode,
              highlightedPath,
            },
          };

          const blob = new Blob([JSON.stringify(data, null, 2)], {
            type: 'application/json',
          });
          const url = URL.createObjectURL(blob);

          const link = document.createElement('a');
          link.href = url;
          link.download = `mu-graph-${Date.now()}.json`;
          link.click();

          // Cleanup
          setTimeout(() => URL.revokeObjectURL(url), 1000);
          break;
        }

        case 'link': {
          // Generate shareable link with state
          const state = {
            filters,
            selectedNode,
            highlightedPath,
          };

          const stateParam = btoa(JSON.stringify(state));
          const shareUrl = `${window.location.origin}${window.location.pathname}?state=${stateParam}`;

          await navigator.clipboard.writeText(shareUrl);
          setCopied(true);
          setTimeout(() => setCopied(false), 3000);
          break;
        }
      }
    } catch (err) {
      console.error('Export failed:', err);
    } finally {
      setExporting(false);
    }
  }, [elements, selectedFormat, filters, selectedNode, highlightedPath]);

  if (!exportModalOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-bauhaus-black/60"
        onClick={() => setExportModalOpen(false)}
      />

      {/* Modal */}
      <Panel
        variant="default"
        decoration="circle"
        className="relative z-10 w-full max-w-md"
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b-4 border-bauhaus-black bg-bauhaus-yellow">
          <h2 className="font-bauhaus-heading text-bauhaus-black">
            Export Graph
          </h2>
          <button
            onClick={() => setExportModalOpen(false)}
            className="p-1 hover:bg-bauhaus-black/10 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4 space-y-4">
          {/* Format Selection */}
          <div className="space-y-2">
            {EXPORT_OPTIONS.map((option) => {
              const isSelected = selectedFormat === option.format;
              const Icon = option.icon;

              return (
                <button
                  key={option.format}
                  onClick={() => setSelectedFormat(option.format)}
                  className={`
                    w-full flex items-center gap-4 p-3
                    border-2 border-bauhaus-black
                    transition-all duration-200
                    ${isSelected
                      ? 'bg-bauhaus-blue text-white shadow-bauhaus-md'
                      : 'bg-bauhaus-white hover:bg-bauhaus-muted'
                    }
                  `}
                >
                  <Icon className="w-6 h-6" />
                  <div className="flex-1 text-left">
                    <div className="font-bold uppercase tracking-wider text-sm">
                      {option.label}
                    </div>
                    <div className={`text-xs ${isSelected ? 'text-white/70' : 'text-bauhaus-black/60'}`}>
                      {option.description}
                    </div>
                  </div>
                  {isSelected && (
                    <div className="w-4 h-4 bg-bauhaus-yellow" />
                  )}
                </button>
              );
            })}
          </div>

          {/* Graph Stats */}
          <div className="bg-bauhaus-muted border-2 border-bauhaus-black p-3">
            <div className="font-bauhaus-label text-bauhaus-black/60 mb-2">
              Export Contains
            </div>
            <div className="grid grid-cols-3 gap-2 text-center">
              <div>
                <div className="font-bold text-lg">{elements?.nodes.length || 0}</div>
                <div className="text-xs text-bauhaus-black/60 uppercase">Nodes</div>
              </div>
              <div>
                <div className="font-bold text-lg">{elements?.edges.length || 0}</div>
                <div className="text-xs text-bauhaus-black/60 uppercase">Edges</div>
              </div>
              <div>
                <div className="font-bold text-lg">
                  {highlightedPath.length > 0 ? 'Yes' : 'No'}
                </div>
                <div className="text-xs text-bauhaus-black/60 uppercase">Path</div>
              </div>
            </div>
          </div>

          {/* Success message for link copy */}
          {copied && selectedFormat === 'link' && (
            <div className="flex items-center gap-2 bg-green-100 border-2 border-green-600 p-3 text-green-800">
              <Check className="w-5 h-5" />
              <span className="font-bold">Link copied to clipboard!</span>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t-4 border-bauhaus-black bg-bauhaus-muted flex justify-end gap-2">
          <Button variant="outline" onClick={() => setExportModalOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="red"
            onClick={handleExport}
            disabled={exporting || !elements}
          >
            {exporting ? (
              'Exporting...'
            ) : selectedFormat === 'link' ? (
              <>
                <Copy className="w-4 h-4" />
                Copy Link
              </>
            ) : (
              <>
                <Download className="w-4 h-4" />
                Download
              </>
            )}
          </Button>
        </div>
      </Panel>
    </div>
  );
}
