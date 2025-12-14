import { useEffect, useState } from 'react';
import {
  Clock,
  GitCommit,
  User,
  Plus,
  Minus,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  X,
} from 'lucide-react';
import { useGraphStore } from '../../store/graphStore';
import { useUIStore } from '../../store/uiStore';
import { Button } from '../common';
import type { Snapshot } from '../../api/types';

export function Timeline() {
  const {
    snapshots,
    currentSnapshot,
    loadSnapshots,
    loadGraph,
    loadGraphAtSnapshot,
  } = useGraphStore();
  const { setTimelineOpen } = useUIStore();

  const [selectedIndex, setSelectedIndex] = useState<number>(-1);

  // Load snapshots on mount
  useEffect(() => {
    loadSnapshots();
  }, [loadSnapshots]);

  // Sync selected index with current snapshot
  useEffect(() => {
    if (!currentSnapshot) {
      setSelectedIndex(-1);
      return;
    }

    const index = snapshots.findIndex((s) => s.commit_hash === currentSnapshot);
    setSelectedIndex(index);
  }, [currentSnapshot, snapshots]);

  const handleSliderChange = (index: number) => {
    setSelectedIndex(index);
    if (index >= 0 && index < snapshots.length) {
      loadGraphAtSnapshot(snapshots[index].commit_hash);
    }
  };

  const handleLiveMode = () => {
    setSelectedIndex(-1);
    loadGraph();
  };

  const handlePrev = () => {
    if (selectedIndex < snapshots.length - 1) {
      handleSliderChange(selectedIndex + 1);
    }
  };

  const handleNext = () => {
    if (selectedIndex > 0) {
      handleSliderChange(selectedIndex - 1);
    } else if (selectedIndex === -1 && snapshots.length > 0) {
      handleSliderChange(0);
    }
  };

  const current: Snapshot | null = selectedIndex >= 0 ? snapshots[selectedIndex] : null;

  if (snapshots.length === 0) {
    return (
      <div className="px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3 text-white">
          <Clock className="w-5 h-5" />
          <span className="font-medium">No history available</span>
        </div>
        <button
          onClick={() => setTimelineOpen(false)}
          className="p-1 hover:bg-white/10 transition-colors"
        >
          <X className="w-5 h-5 text-white" />
        </button>
      </div>
    );
  }

  return (
    <div className="px-4 py-3">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3 text-white">
          <Clock className="w-5 h-5" />
          <span className="font-bold uppercase tracking-wider">Time Travel</span>
          {current && (
            <span className="text-white/60 text-sm">
              Viewing snapshot from {formatDate(current.commit_date)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant={currentSnapshot ? 'yellow' : 'ghost'}
            onClick={handleLiveMode}
            className={`text-xs ${!currentSnapshot ? 'text-white hover:bg-white/10' : ''}`}
          >
            <RefreshCw className="w-4 h-4" />
            Live
          </Button>
          <button
            onClick={() => setTimelineOpen(false)}
            className="p-1 hover:bg-white/10 transition-colors"
          >
            <X className="w-5 h-5 text-white" />
          </button>
        </div>
      </div>

      {/* Timeline Controls */}
      <div className="flex items-center gap-4">
        {/* Navigation buttons */}
        <Button
          variant="outline"
          onClick={handlePrev}
          disabled={selectedIndex >= snapshots.length - 1}
          className="p-2"
        >
          <ChevronLeft className="w-4 h-4" />
        </Button>

        {/* Slider */}
        <div className="flex-1">
          <input
            type="range"
            min={0}
            max={snapshots.length - 1}
            value={selectedIndex >= 0 ? selectedIndex : 0}
            onChange={(e) => handleSliderChange(Number(e.target.value))}
            className="
              w-full h-3
              bg-white/20
              border-2 border-white
              appearance-none
              cursor-pointer
              [&::-webkit-slider-thumb]:appearance-none
              [&::-webkit-slider-thumb]:w-5
              [&::-webkit-slider-thumb]:h-5
              [&::-webkit-slider-thumb]:bg-bauhaus-yellow
              [&::-webkit-slider-thumb]:border-2
              [&::-webkit-slider-thumb]:border-white
              [&::-webkit-slider-thumb]:cursor-pointer
              [&::-moz-range-thumb]:w-5
              [&::-moz-range-thumb]:h-5
              [&::-moz-range-thumb]:bg-bauhaus-yellow
              [&::-moz-range-thumb]:border-2
              [&::-moz-range-thumb]:border-white
              [&::-moz-range-thumb]:cursor-pointer
            "
          />
          {/* Tick marks */}
          <div className="flex justify-between mt-1 px-2">
            <span className="text-xs text-white/40">Oldest</span>
            <span className="text-xs text-white/40">Newest</span>
          </div>
        </div>

        {/* Navigation buttons */}
        <Button
          variant="outline"
          onClick={handleNext}
          disabled={selectedIndex === 0}
          className="p-2"
        >
          <ChevronRight className="w-4 h-4" />
        </Button>
      </div>

      {/* Commit Info */}
      {current && (
        <div className="mt-3 flex items-start gap-4 bg-white/10 border-2 border-white/20 p-3">
          {/* Commit hash */}
          <div className="flex items-center gap-2">
            <GitCommit className="w-4 h-4 text-white/60" />
            <code className="text-sm font-mono text-white">
              {current.commit_hash.slice(0, 8)}
            </code>
          </div>

          {/* Message */}
          <div className="flex-1 min-w-0">
            <p className="text-white truncate">{current.commit_message}</p>
          </div>

          {/* Author & Date */}
          <div className="text-right text-sm">
            <div className="flex items-center gap-1 text-white/60">
              <User className="w-3 h-3" />
              {current.commit_author}
            </div>
            <div className="text-white/40">{formatDate(current.commit_date)}</div>
          </div>

          {/* Stats */}
          <div className="flex items-center gap-3 text-sm">
            <span className="flex items-center gap-1 text-green-400">
              <Plus className="w-3 h-3" />
              {current.nodes_added}
            </span>
            <span className="flex items-center gap-1 text-red-400">
              <Minus className="w-3 h-3" />
              {current.nodes_removed}
            </span>
            <span className="flex items-center gap-1 text-yellow-400">
              <RefreshCw className="w-3 h-3" />
              {current.nodes_modified}
            </span>
          </div>
        </div>
      )}

      {/* Live mode indicator */}
      {!current && (
        <div className="mt-3 flex items-center justify-center gap-2 bg-bauhaus-yellow/20 border-2 border-bauhaus-yellow p-2">
          <div className="w-2 h-2 bg-bauhaus-yellow rounded-full animate-pulse" />
          <span className="text-white font-medium">Viewing Live Graph</span>
        </div>
      )}
    </div>
  );
}

function formatDate(dateStr: string): string {
  try {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return dateStr;
  }
}
