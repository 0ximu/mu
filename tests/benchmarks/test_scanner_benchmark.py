"""Benchmark tests comparing Python vs Rust scanner performance.

Run with: pytest tests/benchmarks/test_scanner_benchmark.py -v -s
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path

import pytest

from mu.config import MUConfig
from mu.scanner import (
    _HAS_RUST_SCANNER,
    _USE_RUST_SCANNER,
    scan_codebase,
    scan_codebase_auto,
)

# Get the MU repo root for realistic benchmarking
MU_ROOT = Path(__file__).parent.parent.parent


def time_scan(scan_fn, root: Path, config: MUConfig, iterations: int = 5) -> dict:
    """Time a scan function over multiple iterations.

    Returns:
        dict with min, max, mean, median times in ms
    """
    times = []
    result = None

    for _ in range(iterations):
        start = time.perf_counter()
        result = scan_fn(root, config)
        elapsed = (time.perf_counter() - start) * 1000  # ms
        times.append(elapsed)

    return {
        "min_ms": min(times),
        "max_ms": max(times),
        "mean_ms": statistics.mean(times),
        "median_ms": statistics.median(times),
        "times": times,
        "result": result,
    }


class TestScannerBenchmark:
    """Benchmark tests for scanner performance."""

    @pytest.fixture
    def config(self) -> MUConfig:
        """Get default MU config."""
        return MUConfig()

    def test_python_scanner_baseline(self, config: MUConfig) -> None:
        """Measure Python scanner performance as baseline."""
        stats = time_scan(scan_codebase, MU_ROOT, config, iterations=3)

        print(f"\n{'='*60}")
        print("Python Scanner Performance (baseline)")
        print(f"{'='*60}")
        print(f"  Min:    {stats['min_ms']:.2f}ms")
        print(f"  Max:    {stats['max_ms']:.2f}ms")
        print(f"  Mean:   {stats['mean_ms']:.2f}ms")
        print(f"  Median: {stats['median_ms']:.2f}ms")
        print(f"  Files:  {stats['result'].stats.total_files}")
        print(f"  Lines:  {stats['result'].stats.total_lines}")

        # Baseline assertion - Python should complete within 5 seconds
        assert stats["mean_ms"] < 5000, "Python scanner too slow"

    @pytest.mark.skipif(not _HAS_RUST_SCANNER, reason="Rust scanner not available")
    def test_rust_scanner_performance(self, config: MUConfig) -> None:
        """Measure Rust scanner performance."""
        # Force Rust scanner by using scan_codebase_auto with Rust enabled
        stats = time_scan(scan_codebase_auto, MU_ROOT, config, iterations=5)

        print(f"\n{'='*60}")
        print("Rust Scanner Performance")
        print(f"{'='*60}")
        print(f"  Min:    {stats['min_ms']:.2f}ms")
        print(f"  Max:    {stats['max_ms']:.2f}ms")
        print(f"  Mean:   {stats['mean_ms']:.2f}ms")
        print(f"  Median: {stats['median_ms']:.2f}ms")
        print(f"  Files:  {stats['result'].stats.total_files}")
        print(f"  Lines:  {stats['result'].stats.total_lines}")

        # Target: < 150ms with Rust scanner (relaxed for CI variance and machine load)
        assert stats["mean_ms"] < 150, f"Rust scanner should be < 150ms, got {stats['mean_ms']:.2f}ms"

    @pytest.mark.skipif(not _HAS_RUST_SCANNER, reason="Rust scanner not available")
    def test_scanner_comparison(self, config: MUConfig) -> None:
        """Compare Python vs Rust scanner performance side-by-side."""
        iterations = 5

        # Measure Python
        python_stats = time_scan(scan_codebase, MU_ROOT, config, iterations=iterations)

        # Measure Rust
        rust_stats = time_scan(scan_codebase_auto, MU_ROOT, config, iterations=iterations)

        # Calculate speedup
        speedup = python_stats["mean_ms"] / rust_stats["mean_ms"]

        print(f"\n{'='*60}")
        print("Scanner Performance Comparison")
        print(f"{'='*60}")
        print(f"  Python mean: {python_stats['mean_ms']:.2f}ms")
        print(f"  Rust mean:   {rust_stats['mean_ms']:.2f}ms")
        print(f"  Speedup:     {speedup:.1f}x faster")
        print(f"{'='*60}")

        # Verify results are consistent
        assert python_stats["result"].stats.total_files > 0
        assert rust_stats["result"].stats.total_files > 0

        # Rust should be faster (relaxed threshold for CI variance and machine load)
        assert speedup >= 1.3, f"Expected at least 1.3x speedup, got {speedup:.1f}x"

    @pytest.mark.skipif(not _HAS_RUST_SCANNER, reason="Rust scanner not available")
    def test_auto_scanner_selects_rust(self, config: MUConfig) -> None:
        """Verify scan_codebase_auto uses Rust when available."""
        # Run auto scanner and check timing
        start = time.perf_counter()
        result = scan_codebase_auto(MU_ROOT, config)
        elapsed_ms = (time.perf_counter() - start) * 1000

        print(f"\n{'='*60}")
        print("Auto Scanner Selection Test")
        print(f"{'='*60}")
        print(f"  Time:   {elapsed_ms:.2f}ms")
        print(f"  Files:  {result.stats.total_files}")

        # If Rust is available and enabled, should be fast
        if _USE_RUST_SCANNER:
            assert elapsed_ms < 100, f"Auto scanner should use fast Rust path, got {elapsed_ms:.2f}ms"

    @pytest.mark.xfail(reason="Rust and Python scanners use different ignore patterns - known issue")
    def test_scanner_result_consistency(self, config: MUConfig) -> None:
        """Verify Python and Rust scanners return consistent results."""
        if not _HAS_RUST_SCANNER:
            pytest.skip("Rust scanner not available")

        python_result = scan_codebase(MU_ROOT, config)
        rust_result = scan_codebase_auto(MU_ROOT, config)

        # File counts should be close (may differ slightly due to race conditions)
        file_diff = abs(python_result.stats.total_files - rust_result.stats.total_files)
        assert file_diff <= 5, f"File count mismatch: Python={python_result.stats.total_files}, Rust={rust_result.stats.total_files}"

        # Languages should match
        python_langs = set(python_result.stats.languages.keys())
        rust_langs = set(rust_result.stats.languages.keys())
        assert python_langs == rust_langs, f"Language mismatch: {python_langs.symmetric_difference(rust_langs)}"

        print(f"\n{'='*60}")
        print("Result Consistency Check")
        print(f"{'='*60}")
        print(f"  Python files: {python_result.stats.total_files}")
        print(f"  Rust files:   {rust_result.stats.total_files}")
        print(f"  Languages:    {sorted(python_langs)}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
