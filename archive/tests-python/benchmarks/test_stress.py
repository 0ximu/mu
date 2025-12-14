"""Stress tests for MU at scale.

Tests MU performance and stability under heavy load:
- Large codebase simulation (10k+ files)
- Memory usage under load
- Query performance at scale
- Parser throughput

Run with: pytest tests/benchmarks/test_stress.py -v -s
Mark slow tests: pytest tests/benchmarks/test_stress.py -v -s -m stress
"""

from __future__ import annotations

import gc
import os
import resource
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

from mu.kernel import Edge, EdgeType, MUbase, Node, NodeType
from mu.kernel.muql import MUQLEngine
from mu.parser import parse_file


# =============================================================================
# Markers
# =============================================================================


pytestmark = pytest.mark.stress


# =============================================================================
# Utilities
# =============================================================================


def get_memory_usage_mb() -> float:
    """Get current memory usage in MB."""
    if sys.platform == "darwin" or sys.platform.startswith("linux"):
        # macOS and Linux
        usage = resource.getrusage(resource.RUSAGE_SELF)
        return usage.ru_maxrss / (1024 * 1024)  # Convert to MB
    else:
        # Fallback for Windows
        import psutil
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / (1024 * 1024)


def create_large_codebase(tmp_path: Path, num_modules: int = 1000) -> MUbase:
    """Create a large MUbase for stress testing.

    Creates a realistic codebase structure with:
    - num_modules modules
    - ~10 functions per module
    - ~3 classes per module
    - Import relationships between modules

    Total nodes: ~14 * num_modules
    Total edges: ~15 * num_modules
    """
    db = MUbase(tmp_path / "large.mubase")

    # Create modules
    for i in range(num_modules):
        package = f"pkg_{i // 100}"
        module_name = f"module_{i}"
        file_path = f"src/{package}/{module_name}.py"

        db.add_node(
            Node(
                id=f"mod:{file_path}",
                type=NodeType.MODULE,
                name=module_name,
                qualified_name=f"{package}.{module_name}",
                file_path=file_path,
                line_start=1,
                line_end=500,
                complexity=0,
            )
        )

        # Create functions for this module
        for j in range(10):
            func_id = f"fn:{file_path}:func_{j}"
            db.add_node(
                Node(
                    id=func_id,
                    type=NodeType.FUNCTION,
                    name=f"func_{j}",
                    qualified_name=f"{package}.{module_name}.func_{j}",
                    file_path=file_path,
                    line_start=10 + j * 30,
                    line_end=35 + j * 30,
                    complexity=(i + j) % 20 + 1,
                    properties={
                        "is_async": j % 3 == 0,
                        "parameters": [
                            {"name": "x", "type_annotation": "int"},
                            {"name": "y", "type_annotation": "str"},
                        ],
                        "return_type": "bool",
                    },
                )
            )
            # Contains edge
            db.add_edge(
                Edge(
                    id=f"edge:contains:fn:{i}:{j}",
                    source_id=f"mod:{file_path}",
                    target_id=func_id,
                    type=EdgeType.CONTAINS,
                )
            )

        # Create classes for this module
        for k in range(3):
            class_id = f"cls:{file_path}:Class_{k}"
            db.add_node(
                Node(
                    id=class_id,
                    type=NodeType.CLASS,
                    name=f"Class_{k}",
                    qualified_name=f"{package}.{module_name}.Class_{k}",
                    file_path=file_path,
                    line_start=350 + k * 50,
                    line_end=400 + k * 50,
                    complexity=5,
                    properties={
                        "bases": ["BaseClass"] if k > 0 else [],
                        "decorators": ["dataclass"] if k == 0 else [],
                    },
                )
            )
            # Contains edge
            db.add_edge(
                Edge(
                    id=f"edge:contains:cls:{i}:{k}",
                    source_id=f"mod:{file_path}",
                    target_id=class_id,
                    type=EdgeType.CONTAINS,
                )
            )

        # Create import edges (each module imports ~5 other modules)
        for target_idx in range((i + 1) % num_modules, (i + 6) % num_modules):
            if target_idx != i:
                target_package = f"pkg_{target_idx // 100}"
                target_module = f"module_{target_idx}"
                target_path = f"src/{target_package}/{target_module}.py"
                db.add_edge(
                    Edge(
                        id=f"edge:import:{i}:{target_idx}",
                        source_id=f"mod:{file_path}",
                        target_id=f"mod:{target_path}",
                        type=EdgeType.IMPORTS,
                    )
                )

    return db


def generate_python_file(size: str = "medium") -> str:
    """Generate a Python file of specified size.

    Args:
        size: 'small' (~50 lines), 'medium' (~200 lines), 'large' (~1000 lines)
    """
    if size == "small":
        func_count, class_count = 3, 1
    elif size == "medium":
        func_count, class_count = 10, 3
    else:  # large
        func_count, class_count = 50, 10

    lines = ['"""Generated module for stress testing."""', "", "from typing import Any, List, Optional", ""]

    for i in range(func_count):
        lines.extend([
            f"def function_{i}(x: int, y: str, z: Optional[List[Any]] = None) -> bool:",
            f'    """Function {i} docstring."""',
            f"    if x > {i}:",
            f"        for item in (z or []):",
            f"            if item:",
            f"                return True",
            f"    return False",
            "",
        ])

    for i in range(class_count):
        lines.extend([
            f"class TestClass_{i}:",
            f'    """Class {i} docstring."""',
            "",
            f"    def __init__(self, value: int) -> None:",
            f"        self.value = value",
            "",
            f"    def method_a(self) -> int:",
            f"        return self.value * 2",
            "",
            f"    def method_b(self, x: int) -> int:",
            f"        if x > 0:",
            f"            return self.value + x",
            f"        return self.value",
            "",
            f"    @staticmethod",
            f"    def static_method(a: int, b: int) -> int:",
            f"        return a + b",
            "",
        ])

    return "\n".join(lines)


# =============================================================================
# TestLargeCodebaseSimulation
# =============================================================================


class TestLargeCodebaseSimulation:
    """Stress tests with large codebase simulation."""

    @pytest.mark.slow
    def test_10k_file_codebase_creation(self, tmp_path: Path) -> None:
        """Test creating a database with 10,000 file simulation.

        This tests the creation performance and memory usage when
        building a graph representing a large codebase.
        """
        initial_memory = get_memory_usage_mb()
        start_time = time.perf_counter()

        db = create_large_codebase(tmp_path, num_modules=10000)

        creation_time = time.perf_counter() - start_time
        stats = db.stats()
        db.close()

        final_memory = get_memory_usage_mb()
        memory_delta = final_memory - initial_memory

        print(f"\n{'=' * 60}")
        print("Large Codebase Creation (10k modules)")
        print(f"{'=' * 60}")
        print(f"  Nodes:        {stats['nodes']:,}")
        print(f"  Edges:        {stats['edges']:,}")
        print(f"  Creation:     {creation_time:.2f}s")
        print(f"  Memory delta: {memory_delta:.1f}MB")
        print(f"  DB size:      {stats['file_size_kb']:.1f}KB")
        print(f"{'=' * 60}")

        # Performance assertions
        assert creation_time < 120, f"Creation took too long: {creation_time:.2f}s"
        assert stats["nodes"] >= 140000, f"Expected ~140k nodes, got {stats['nodes']}"
        assert stats["edges"] >= 150000, f"Expected ~150k edges, got {stats['edges']}"

    @pytest.mark.slow
    def test_query_performance_at_scale(self, tmp_path: Path) -> None:
        """Test query performance on large database.

        Various query types should complete within acceptable time limits.
        """
        # Create large database
        db = create_large_codebase(tmp_path, num_modules=5000)
        engine = MUQLEngine(db)

        queries = [
            ("Simple SELECT", "SELECT * FROM functions LIMIT 100"),
            ("Complex WHERE", "SELECT name, complexity FROM functions WHERE complexity > 15"),
            ("ORDER BY", "SELECT name, complexity FROM functions ORDER BY complexity DESC LIMIT 50"),
            ("COUNT", "SELECT COUNT(*) FROM functions"),
            ("Show dependencies", 'SHOW dependencies OF "mod:src/pkg_0/module_0.py" DEPTH 2'),
        ]

        results: list[dict[str, Any]] = []

        for name, query in queries:
            times = []
            for _ in range(5):  # Run 5 times for averaging
                start = time.perf_counter()
                result = engine.execute(query)
                elapsed = (time.perf_counter() - start) * 1000
                times.append(elapsed)
                assert result.is_success, f"Query failed: {query}"

            results.append({
                "name": name,
                "mean_ms": statistics.mean(times),
                "median_ms": statistics.median(times),
                "max_ms": max(times),
            })

        db.close()

        print(f"\n{'=' * 60}")
        print("Query Performance at Scale (5k modules)")
        print(f"{'=' * 60}")
        for r in results:
            print(f"  {r['name']:20s}: mean={r['mean_ms']:.1f}ms, max={r['max_ms']:.1f}ms")
        print(f"{'=' * 60}")

        # Performance assertions - queries should be reasonably fast
        for r in results:
            assert r["mean_ms"] < 5000, f"{r['name']} too slow: {r['mean_ms']:.1f}ms"

    @pytest.mark.slow
    def test_dependency_traversal_at_scale(self, tmp_path: Path) -> None:
        """Test dependency traversal performance on deep graphs."""
        db = create_large_codebase(tmp_path, num_modules=2000)

        traversal_times: list[float] = []

        # Test various traversal depths
        for depth in [1, 2, 3, 5]:
            start = time.perf_counter()
            deps = db.get_dependencies(
                "mod:src/pkg_0/module_0.py",
                depth=depth,
                edge_types=[EdgeType.IMPORTS],
            )
            elapsed = (time.perf_counter() - start) * 1000
            traversal_times.append(elapsed)

            print(f"  Depth {depth}: {len(deps)} deps in {elapsed:.2f}ms")

        db.close()

        # Even deep traversals should complete quickly
        assert max(traversal_times) < 10000, "Deep traversal too slow"


# =============================================================================
# TestMemoryUsage
# =============================================================================


class TestMemoryUsage:
    """Test memory usage under various conditions."""

    @pytest.mark.slow
    def test_memory_growth_during_build(self, tmp_path: Path) -> None:
        """Track memory growth during database population."""
        db = MUbase(tmp_path / "memory.mubase")
        memory_samples: list[tuple[int, float]] = []

        gc.collect()
        initial = get_memory_usage_mb()

        for batch in range(100):
            # Add 100 nodes per batch
            for i in range(100):
                idx = batch * 100 + i
                db.add_node(
                    Node(
                        id=f"fn:test_{idx}",
                        type=NodeType.FUNCTION,
                        name=f"func_{idx}",
                        qualified_name=f"test.func_{idx}",
                        file_path="test.py",
                        line_start=idx,
                        line_end=idx + 10,
                        complexity=idx % 20,
                    )
                )

            if batch % 10 == 0:
                gc.collect()
                current = get_memory_usage_mb()
                memory_samples.append((batch * 100, current - initial))

        db.close()

        print(f"\n{'=' * 60}")
        print("Memory Growth During Build")
        print(f"{'=' * 60}")
        for nodes, delta in memory_samples:
            print(f"  {nodes:5d} nodes: +{delta:.1f}MB")
        print(f"{'=' * 60}")

        # Memory should grow sub-linearly with proper connection management
        # Final growth should be reasonable
        final_delta = memory_samples[-1][1]
        assert final_delta < 500, f"Excessive memory growth: {final_delta:.1f}MB"

    @pytest.mark.slow
    def test_memory_after_large_query(self, tmp_path: Path) -> None:
        """Ensure memory is released after large queries."""
        db = create_large_codebase(tmp_path, num_modules=1000)
        engine = MUQLEngine(db)

        gc.collect()
        before_query = get_memory_usage_mb()

        # Execute a large query
        result = engine.execute("SELECT * FROM functions")
        assert result.is_success
        assert result.row_count > 10000

        during_query = get_memory_usage_mb()

        # Clear result reference
        del result
        gc.collect()

        after_gc = get_memory_usage_mb()
        db.close()

        print(f"\n{'=' * 60}")
        print("Memory After Large Query")
        print(f"{'=' * 60}")
        print(f"  Before query: {before_query:.1f}MB")
        print(f"  During query: {during_query:.1f}MB")
        print(f"  After GC:     {after_gc:.1f}MB")
        print(f"{'=' * 60}")

        # Memory should be released after GC
        memory_released = during_query - after_gc
        assert memory_released > -50, "Memory not being released properly"


# =============================================================================
# TestParserThroughput
# =============================================================================


class TestParserThroughput:
    """Test parser throughput at scale."""

    @pytest.mark.slow
    def test_parsing_throughput(self, tmp_path: Path) -> None:
        """Measure files parsed per second."""
        # Create test files
        files: list[Path] = []
        for i in range(100):
            file_path = tmp_path / f"test_{i}.py"
            file_path.write_text(generate_python_file("medium"))
            files.append(file_path)

        # Measure parsing throughput
        start = time.perf_counter()
        total_functions = 0
        total_classes = 0

        for file_path in files:
            result = parse_file(file_path, "python")
            if result.success and result.module:
                total_functions += len(result.module.functions)
                total_classes += len(result.module.classes)

        elapsed = time.perf_counter() - start
        files_per_second = len(files) / elapsed

        print(f"\n{'=' * 60}")
        print("Parser Throughput")
        print(f"{'=' * 60}")
        print(f"  Files:            {len(files)}")
        print(f"  Functions found:  {total_functions}")
        print(f"  Classes found:    {total_classes}")
        print(f"  Time:             {elapsed:.2f}s")
        print(f"  Throughput:       {files_per_second:.1f} files/s")
        print(f"{'=' * 60}")

        # Should parse at least 10 files per second
        assert files_per_second > 10, f"Parsing too slow: {files_per_second:.1f} files/s"

    @pytest.mark.slow
    def test_large_file_parsing(self, tmp_path: Path) -> None:
        """Test parsing very large files."""
        sizes = ["small", "medium", "large"]
        results: list[dict[str, Any]] = []

        for size in sizes:
            file_path = tmp_path / f"test_{size}.py"
            content = generate_python_file(size)
            file_path.write_text(content)

            times = []
            for _ in range(3):
                start = time.perf_counter()
                result = parse_file(file_path, "python")
                elapsed = (time.perf_counter() - start) * 1000
                times.append(elapsed)

            results.append({
                "size": size,
                "lines": len(content.split("\n")),
                "mean_ms": statistics.mean(times),
                "functions": len(result.module.functions) if result.module else 0,
                "classes": len(result.module.classes) if result.module else 0,
            })

        print(f"\n{'=' * 60}")
        print("Large File Parsing")
        print(f"{'=' * 60}")
        for r in results:
            print(
                f"  {r['size']:8s}: {r['lines']:4d} lines, "
                f"{r['functions']:2d} funcs, {r['classes']:2d} classes, "
                f"{r['mean_ms']:.1f}ms"
            )
        print(f"{'=' * 60}")

        # Large files should still parse reasonably fast
        large_result = [r for r in results if r["size"] == "large"][0]
        assert large_result["mean_ms"] < 5000, "Large file parsing too slow"


# =============================================================================
# TestDatabaseStress
# =============================================================================


class TestDatabaseStress:
    """Stress tests for database operations."""

    @pytest.mark.slow
    def test_rapid_insert_update_cycles(self, tmp_path: Path) -> None:
        """Test rapid insert/update cycles."""
        db = MUbase(tmp_path / "rapid.mubase")

        start = time.perf_counter()
        operations = 0

        for cycle in range(100):
            # Insert batch
            for i in range(100):
                idx = cycle * 100 + i
                db.add_node(
                    Node(
                        id=f"fn:cycle_{idx}",
                        type=NodeType.FUNCTION,
                        name=f"func_{idx}",
                        qualified_name=f"test.func_{idx}",
                        file_path="test.py",
                        line_start=idx,
                        line_end=idx + 10,
                        complexity=idx % 20,
                    )
                )
                operations += 1

            # Update some existing
            for i in range(0, 100, 10):
                idx = cycle * 100 + i
                db.add_node(
                    Node(
                        id=f"fn:cycle_{idx}",
                        type=NodeType.FUNCTION,
                        name=f"func_{idx}_updated",
                        qualified_name=f"test.func_{idx}",
                        file_path="test.py",
                        line_start=idx,
                        line_end=idx + 20,
                        complexity=(idx % 20) + 5,
                    )
                )
                operations += 1

        elapsed = time.perf_counter() - start
        ops_per_second = operations / elapsed

        stats = db.stats()
        db.close()

        print(f"\n{'=' * 60}")
        print("Rapid Insert/Update Cycles")
        print(f"{'=' * 60}")
        print(f"  Operations:     {operations:,}")
        print(f"  Time:           {elapsed:.2f}s")
        print(f"  Ops/second:     {ops_per_second:.1f}")
        print(f"  Final nodes:    {stats['nodes']:,}")
        print(f"{'=' * 60}")

        # Should handle at least 1000 ops per second
        assert ops_per_second > 1000, f"Operations too slow: {ops_per_second:.1f} ops/s"

    @pytest.mark.slow
    def test_concurrent_read_heavy_load(self, tmp_path: Path) -> None:
        """Test database under heavy read load."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        db = create_large_codebase(tmp_path, num_modules=500)

        read_count = 0
        start = time.perf_counter()

        def read_task(task_id: int) -> int:
            count = 0
            for _ in range(50):
                nodes = db.get_nodes(node_type=NodeType.FUNCTION)
                count += 1
            return count

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(read_task, i) for i in range(8)]
            for future in as_completed(futures, timeout=120):
                read_count += future.result()

        elapsed = time.perf_counter() - start
        reads_per_second = read_count / elapsed

        db.close()

        print(f"\n{'=' * 60}")
        print("Concurrent Read Heavy Load")
        print(f"{'=' * 60}")
        print(f"  Read operations: {read_count}")
        print(f"  Time:            {elapsed:.2f}s")
        print(f"  Reads/second:    {reads_per_second:.1f}")
        print(f"{'=' * 60}")

        # Should handle concurrent reads efficiently
        assert reads_per_second > 1, f"Reads too slow: {reads_per_second:.1f}/s"


# =============================================================================
# TestExportStress
# =============================================================================


class TestExportStress:
    """Stress tests for export operations."""

    @pytest.mark.slow
    def test_export_large_codebase(self, tmp_path: Path) -> None:
        """Test exporting a large codebase to various formats."""
        from mu.kernel.export.lisp import LispExporter
        from mu.kernel.export.mu_text import MUTextExporter

        db = create_large_codebase(tmp_path, num_modules=500)

        exporters = [
            ("MU Text", MUTextExporter()),
            ("Lisp", LispExporter()),
        ]

        results: list[dict[str, Any]] = []

        for name, exporter in exporters:
            start = time.perf_counter()
            result = exporter.export(db)
            elapsed = (time.perf_counter() - start) * 1000

            results.append({
                "name": name,
                "time_ms": elapsed,
                "output_len": len(result.output),
                "node_count": result.node_count,
            })

        db.close()

        print(f"\n{'=' * 60}")
        print("Export Large Codebase")
        print(f"{'=' * 60}")
        for r in results:
            print(
                f"  {r['name']:10s}: {r['time_ms']:.1f}ms, "
                f"{r['output_len']:,} chars, {r['node_count']:,} nodes"
            )
        print(f"{'=' * 60}")

        # Exports should complete in reasonable time
        for r in results:
            assert r["time_ms"] < 30000, f"{r['name']} export too slow"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
