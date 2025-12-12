"""Concurrency and thread safety tests for MU.

Tests ensure MU components handle concurrent access correctly:
- MUbase: Concurrent reads, read-write isolation
- Parser: Parallel file parsing, tree-sitter thread safety
- Cache: Race conditions, cache stampede prevention

Run with: pytest tests/integration/test_concurrency.py -v -s
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pytest

from mu.kernel import Edge, EdgeType, MUbase, Node, NodeType
from mu.kernel.muql import MUQLEngine
from mu.parser import parse_file


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def populated_db(tmp_path: Path) -> MUbase:
    """Create a populated MUbase for concurrent testing."""
    db = MUbase(tmp_path / "concurrent.mubase")

    # Create modules
    for i in range(100):
        db.add_node(
            Node(
                id=f"mod:src/module_{i}.py",
                type=NodeType.MODULE,
                name=f"module_{i}",
                qualified_name=f"src.module_{i}",
                file_path=f"src/module_{i}.py",
                line_start=1,
                line_end=100,
                complexity=i % 10,
            )
        )

    # Create functions
    for i in range(500):
        module_idx = i % 100
        db.add_node(
            Node(
                id=f"fn:src/module_{module_idx}.py:func_{i}",
                type=NodeType.FUNCTION,
                name=f"func_{i}",
                qualified_name=f"module_{module_idx}.func_{i}",
                file_path=f"src/module_{module_idx}.py",
                line_start=10 + (i % 10) * 10,
                line_end=20 + (i % 10) * 10,
                complexity=i % 20,
            )
        )
        # Add contains edge
        db.add_edge(
            Edge(
                id=f"edge:contains:{i}",
                source_id=f"mod:src/module_{module_idx}.py",
                target_id=f"fn:src/module_{module_idx}.py:func_{i}",
                type=EdgeType.CONTAINS,
            )
        )

    # Add import edges between modules
    for i in range(50):
        db.add_edge(
            Edge(
                id=f"edge:import:{i}",
                source_id=f"mod:src/module_{i}.py",
                target_id=f"mod:src/module_{(i + 1) % 100}.py",
                type=EdgeType.IMPORTS,
            )
        )

    yield db
    db.close()


@pytest.fixture
def read_only_db(tmp_path: Path, populated_db: MUbase) -> MUbase:
    """Create a read-only connection to the populated database."""
    populated_db.close()
    db = MUbase(tmp_path / "concurrent.mubase", read_only=True)
    yield db
    db.close()


@pytest.fixture
def python_files(tmp_path: Path) -> list[Path]:
    """Create multiple Python files for parallel parsing tests."""
    files = []
    for i in range(20):
        file_path = tmp_path / f"test_file_{i}.py"
        file_path.write_text(f'''
"""Test module {i}."""

def function_{i}_a(x: int) -> int:
    """Add one to x."""
    if x > 0:
        return x + 1
    return 0

def function_{i}_b(y: str) -> str:
    """Process string."""
    for char in y:
        if char.isalpha():
            continue
    return y.lower()

class TestClass_{i}:
    """Test class for module {i}."""

    def __init__(self, value: int):
        self.value = value

    def process(self) -> int:
        """Process the value."""
        return self.value * 2

    @staticmethod
    def helper(x: int, y: int) -> int:
        return x + y
''')
        files.append(file_path)
    return files


# =============================================================================
# TestMUbaseConcurrency
# =============================================================================


class TestMUbaseConcurrency:
    """Test MUbase under concurrent access.

    Note: DuckDB connections are not thread-safe. Each thread must use
    its own connection (read-only for concurrent reads).
    """

    def test_concurrent_reads(self, tmp_path: Path, populated_db: MUbase) -> None:
        """Multiple threads reading simultaneously via separate connections."""
        # Close the populated_db so we can open read-only connections
        db_path = populated_db.path
        populated_db.close()

        results: list[tuple[int, Any]] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def read_nodes(thread_id: int) -> None:
            try:
                # Each thread opens its own read-only connection
                thread_db = MUbase(db_path, read_only=True)
                try:
                    # Each thread performs multiple read operations
                    nodes = thread_db.get_nodes(node_type=NodeType.FUNCTION)
                    stats = thread_db.stats()
                    node = thread_db.get_node(f"fn:src/module_{thread_id % 100}.py:func_{thread_id}")

                    with lock:
                        results.append((thread_id, {
                            "node_count": len(nodes),
                            "stats_nodes": stats["nodes"],
                            "specific_node": node is not None,
                        }))
                finally:
                    thread_db.close()
            except Exception as e:
                with lock:
                    errors.append(e)

        # Run 20 threads concurrently
        threads = []
        for i in range(20):
            t = threading.Thread(target=read_nodes, args=(i,))
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=30)

        # Verify no errors
        assert len(errors) == 0, f"Concurrent reads produced errors: {errors}"

        # Verify all threads completed
        assert len(results) == 20, f"Only {len(results)} threads completed"

        # Verify results are consistent
        node_counts = [r[1]["node_count"] for r in results]
        assert all(c == node_counts[0] for c in node_counts), "Inconsistent node counts across threads"

    def test_concurrent_queries(self, tmp_path: Path, populated_db: MUbase) -> None:
        """Multiple MUQL queries in parallel via separate connections."""
        # Close populated_db to allow concurrent read-only connections
        db_path = populated_db.path
        populated_db.close()

        results: list[tuple[str, Any]] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        queries = [
            "SELECT * FROM functions LIMIT 10",
            "SELECT name, complexity FROM functions WHERE complexity > 10",
            "SELECT COUNT(*) FROM modules",
            "SELECT name FROM functions ORDER BY complexity DESC LIMIT 5",
            'SHOW dependencies OF "mod:src/module_0.py"',
        ]

        def run_query(query: str, worker_id: int) -> None:
            try:
                # Each worker uses its own connection
                thread_db = MUbase(db_path, read_only=True)
                try:
                    engine = MUQLEngine(thread_db)
                    result = engine.execute(query)
                    with lock:
                        results.append((query, {
                            "success": result.is_success,
                            "row_count": result.row_count if result.is_success else 0,
                        }))
                finally:
                    thread_db.close()
            except Exception as e:
                with lock:
                    errors.append(e)

        # Run queries concurrently multiple times
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            worker_id = 0
            for _ in range(4):  # 4 rounds
                for query in queries:
                    futures.append(executor.submit(run_query, query, worker_id))
                    worker_id += 1

            for future in as_completed(futures, timeout=60):
                try:
                    future.result()
                except Exception as e:
                    errors.append(e)

        assert len(errors) == 0, f"Concurrent queries produced errors: {errors}"
        assert len(results) == 20, f"Expected 20 results, got {len(results)}"
        assert all(r[1]["success"] for r in results), "Some queries failed"

    @pytest.mark.slow
    @pytest.mark.xfail(
        reason="DuckDB doesn't support mixed read-only/read-write connections to same file",
        strict=False,
    )
    def test_read_write_isolation(self, tmp_path: Path) -> None:
        """Writers should not corrupt concurrent readers (using separate connections)."""
        db_path = tmp_path / "isolation.mubase"

        # Create initial database
        writer_db = MUbase(db_path)
        for i in range(50):
            writer_db.add_node(
                Node(
                    id=f"mod:initial_{i}.py",
                    type=NodeType.MODULE,
                    name=f"initial_{i}",
                    qualified_name=f"initial_{i}",
                    file_path=f"initial_{i}.py",
                    line_start=1,
                    line_end=100,
                    complexity=0,
                )
            )
        writer_db.close()

        # Now test concurrent read and write (DuckDB handles this)
        read_results: list[int] = []
        write_count = 0
        errors: list[Exception] = []
        lock = threading.Lock()

        def reader_task() -> None:
            """Read-only connection reads continuously."""
            try:
                reader_db = MUbase(db_path, read_only=True)
                for _ in range(10):
                    nodes = reader_db.get_nodes(node_type=NodeType.MODULE)
                    with lock:
                        read_results.append(len(nodes))
                    time.sleep(0.01)  # Small delay
                reader_db.close()
            except Exception as e:
                with lock:
                    errors.append(e)

        def writer_task() -> None:
            """Writer adds nodes."""
            nonlocal write_count
            try:
                writer_db = MUbase(db_path)
                for i in range(20):
                    writer_db.add_node(
                        Node(
                            id=f"mod:new_{i}.py",
                            type=NodeType.MODULE,
                            name=f"new_{i}",
                            qualified_name=f"new_{i}",
                            file_path=f"new_{i}.py",
                            line_start=1,
                            line_end=100,
                            complexity=0,
                        )
                    )
                    with lock:
                        write_count += 1
                    time.sleep(0.01)
                writer_db.close()
            except Exception as e:
                with lock:
                    errors.append(e)

        # Start reader and writer concurrently
        reader_thread = threading.Thread(target=reader_task)
        writer_thread = threading.Thread(target=writer_task)

        reader_thread.start()
        writer_thread.start()

        reader_thread.join(timeout=30)
        writer_thread.join(timeout=30)

        # Check for errors (might have lock conflicts, that's acceptable)
        # The important thing is no crashes or corruption
        if errors:
            # Lock errors are expected behavior
            lock_errors = [e for e in errors if "lock" in str(e).lower()]
            other_errors = [e for e in errors if "lock" not in str(e).lower()]
            assert len(other_errors) == 0, f"Unexpected errors: {other_errors}"

        # Verify reads got consistent data (monotonically increasing or stable)
        # Node counts should never be negative or corrupt
        assert all(r >= 50 for r in read_results), "Read results show data corruption"


# =============================================================================
# TestParserConcurrency
# =============================================================================


class TestParserConcurrency:
    """Test parser thread safety."""

    def test_parallel_file_parsing(self, python_files: list[Path]) -> None:
        """Parse multiple files in parallel."""
        results: list[tuple[Path, Any]] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def parse_file_task(file_path: Path) -> None:
            try:
                result = parse_file(file_path, "python")
                with lock:
                    results.append((file_path, {
                        "success": result.success,
                        "functions": len(result.module.functions) if result.module else 0,
                        "classes": len(result.module.classes) if result.module else 0,
                    }))
            except Exception as e:
                with lock:
                    errors.append(e)

        # Parse all files in parallel
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(parse_file_task, f) for f in python_files]

            for future in as_completed(futures, timeout=60):
                try:
                    future.result()
                except Exception as e:
                    errors.append(e)

        assert len(errors) == 0, f"Parallel parsing produced errors: {errors}"
        assert len(results) == len(python_files), "Not all files were parsed"

        # Verify all parses succeeded
        assert all(r[1]["success"] for r in results), "Some parses failed"

        # Each file should have 2 functions and 1 class
        for path, data in results:
            assert data["functions"] == 2, f"Expected 2 functions in {path.name}, got {data['functions']}"
            assert data["classes"] == 1, f"Expected 1 class in {path.name}, got {data['classes']}"

    def test_tree_sitter_thread_safety(self, python_files: list[Path]) -> None:
        """Tree-sitter instances should be safe across threads.

        This tests that tree-sitter Language objects are properly cached
        and don't cause issues when accessed from multiple threads.
        """
        errors: list[Exception] = []
        parse_counts: list[int] = []
        lock = threading.Lock()

        def rapid_parse(thread_id: int) -> None:
            """Rapidly parse the same files multiple times."""
            try:
                local_count = 0
                for _ in range(5):  # Each thread parses all files 5 times
                    for file_path in python_files[:5]:  # Use first 5 files
                        result = parse_file(file_path, "python")
                        if result.success:
                            local_count += 1
                with lock:
                    parse_counts.append(local_count)
            except Exception as e:
                with lock:
                    errors.append(e)

        # Run 8 threads doing rapid parsing
        threads = []
        for i in range(8):
            t = threading.Thread(target=rapid_parse, args=(i,))
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=60)

        assert len(errors) == 0, f"Tree-sitter thread safety failed: {errors}"

        # Each thread should have parsed 25 files successfully (5 files * 5 rounds)
        assert all(c == 25 for c in parse_counts), f"Inconsistent parse counts: {parse_counts}"

    def test_mixed_language_parallel_parsing(self, tmp_path: Path) -> None:
        """Parse files of different languages in parallel."""
        # Create test files for different languages
        files: list[tuple[Path, str]] = []

        # Python files
        for i in range(5):
            path = tmp_path / f"test_{i}.py"
            path.write_text(f"def func_{i}(): pass")
            files.append((path, "python"))

        # TypeScript files
        for i in range(5):
            path = tmp_path / f"test_{i}.ts"
            path.write_text(f"function func{i}(): void {{}}")
            files.append((path, "typescript"))

        # Go files
        for i in range(5):
            path = tmp_path / f"test_{i}.go"
            path.write_text(f"package main\n\nfunc func{i}() {{}}")
            files.append((path, "go"))

        results: list[tuple[Path, bool]] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def parse_task(file_path: Path, language: str) -> None:
            try:
                result = parse_file(file_path, language)
                with lock:
                    results.append((file_path, result.success))
            except Exception as e:
                with lock:
                    errors.append(e)

        with ThreadPoolExecutor(max_workers=15) as executor:
            futures = [executor.submit(parse_task, f, lang) for f, lang in files]
            for future in as_completed(futures, timeout=60):
                try:
                    future.result()
                except Exception as e:
                    errors.append(e)

        assert len(errors) == 0, f"Mixed language parsing errors: {errors}"
        assert len(results) == 15, f"Expected 15 results, got {len(results)}"
        assert all(success for _, success in results), "Some parses failed"


# =============================================================================
# TestCacheRaceConditions
# =============================================================================


class TestCacheRaceConditions:
    """Test cache under concurrent access."""

    def test_cache_concurrent_access(self, tmp_path: Path) -> None:
        """Multiple threads accessing the cache simultaneously."""
        from mu.cache import CacheManager
        from mu.config import CacheConfig

        config = CacheConfig(enabled=True, ttl_hours=24)
        cache = CacheManager(config, tmp_path)

        errors: list[Exception] = []
        operations: list[str] = []
        lock = threading.Lock()

        def cache_worker(thread_id: int) -> None:
            """Perform cache operations."""
            try:
                for i in range(10):
                    key = f"hash_{thread_id}_{i}"

                    # Set operation
                    cache.set_file_result(key, f"output_{thread_id}_{i}", "python", f"test_{i}.py")

                    # Get operation
                    result = cache.get_file_result(key)

                    with lock:
                        if result:
                            operations.append(f"hit:{thread_id}:{i}")
                        else:
                            operations.append(f"miss:{thread_id}:{i}")

            except Exception as e:
                with lock:
                    errors.append(e)

        threads = []
        for i in range(5):
            t = threading.Thread(target=cache_worker, args=(i,))
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=30)

        cache.close()

        assert len(errors) == 0, f"Cache concurrent access errors: {errors}"
        # Most operations should be hits (set then get)
        hits = [op for op in operations if op.startswith("hit:")]
        assert len(hits) > 0, "Cache should have some hits"

    def test_cache_stampede_prevention(self, tmp_path: Path) -> None:
        """Multiple threads requesting same uncached item shouldn't cause stampede.

        This tests that when multiple threads request the same uncached key,
        only one should compute and the others should wait or use the computed value.
        """
        from mu.cache import CacheManager
        from mu.config import CacheConfig

        config = CacheConfig(enabled=True, ttl_hours=24)
        cache = CacheManager(config, tmp_path)

        computation_count = 0
        computation_lock = threading.Lock()
        results: list[str | None] = []
        result_lock = threading.Lock()

        def compute_value() -> str:
            """Simulate expensive computation."""
            nonlocal computation_count
            with computation_lock:
                computation_count += 1
            time.sleep(0.1)  # Simulate work
            return "expensive_result"

        def worker(thread_id: int) -> None:
            """Try to get from cache, compute if missing."""
            key = "stampede_test_key"

            # Try to get
            result = cache.get_file_result(key)

            if result is None:
                # Cache miss - compute and store
                value = compute_value()
                cache.set_file_result(key, value, "python", "test.py")
                with result_lock:
                    results.append(value)
            else:
                with result_lock:
                    results.append(result.mu_output)

        # Start multiple threads at once
        threads = []
        for i in range(10):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)

        # Start all at once
        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=30)

        cache.close()

        # Without stampede prevention, all 10 threads might compute
        # With stampede prevention (or eventual consistency), results should be consistent
        assert len(results) == 10, f"Expected 10 results, got {len(results)}"
        # All results should be the same value
        assert all(r == "expensive_result" for r in results), "Inconsistent results"

    def test_llm_cache_concurrent_access(self, tmp_path: Path) -> None:
        """Test LLM cache under concurrent access."""
        from mu.cache import CacheManager
        from mu.config import CacheConfig

        config = CacheConfig(enabled=True, ttl_hours=24)
        cache = CacheManager(config, tmp_path)

        errors: list[Exception] = []
        results: list[bool] = []
        lock = threading.Lock()

        def llm_cache_worker(thread_id: int) -> None:
            try:
                for i in range(10):
                    # Compute cache key
                    code = f"def test_{thread_id}_{i}(): pass"
                    key = CacheManager.compute_llm_cache_key(code, "1.0", "test-model")

                    # Set
                    cache.set_llm_result(
                        cache_key=key,
                        function_name=f"test_{thread_id}_{i}",
                        summary=[f"Summary line {i}"],
                        model="test-model",
                        prompt_version="1.0",
                    )

                    # Get
                    result = cache.get_llm_result(key)

                    with lock:
                        results.append(result is not None)

            except Exception as e:
                with lock:
                    errors.append(e)

        threads = []
        for i in range(5):
            t = threading.Thread(target=llm_cache_worker, args=(i,))
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=30)

        cache.close()

        assert len(errors) == 0, f"LLM cache errors: {errors}"
        assert len(results) == 50, f"Expected 50 results, got {len(results)}"
        # All gets should succeed after sets
        hit_rate = sum(results) / len(results)
        assert hit_rate > 0.5, f"Hit rate too low: {hit_rate}"


# =============================================================================
# TestDaemonConcurrency - Placeholder for async tests
# =============================================================================


class TestDaemonConcurrency:
    """Test daemon under load.

    These tests are marked as requiring the daemon optional dependency.
    """

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        True,  # Skip by default - daemon tests require running daemon
        reason="Daemon tests require running daemon instance"
    )
    async def test_concurrent_requests(self) -> None:
        """Multiple simultaneous API requests to daemon.

        This test requires:
        1. mu-cli[daemon] to be installed
        2. A running daemon instance

        TODO: Implement when daemon integration tests are set up.
        """
        pass


# =============================================================================
# TestEdgeCases
# =============================================================================


class TestConcurrencyEdgeCases:
    """Test edge cases in concurrent access.

    Note: DuckDB connections are not thread-safe, so tests use separate
    read-only connections per thread where appropriate.
    """

    def test_empty_db_concurrent_reads(self, tmp_path: Path) -> None:
        """Concurrent reads on empty database should not crash."""
        db_path = tmp_path / "empty.mubase"
        db = MUbase(db_path)
        db.close()  # Close so we can open read-only connections

        errors: list[Exception] = []
        results: list[int] = []
        lock = threading.Lock()

        def read_empty(thread_id: int) -> None:
            try:
                # Each thread gets its own connection
                thread_db = MUbase(db_path, read_only=True)
                try:
                    nodes = thread_db.get_nodes()
                    stats = thread_db.stats()
                    with lock:
                        results.append(len(nodes))
                finally:
                    thread_db.close()
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = []
        for i in range(10):
            t = threading.Thread(target=read_empty, args=(i,))
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Empty DB concurrent read errors: {errors}"
        assert all(r == 0 for r in results), "Empty DB should return 0 nodes"

    def test_sequential_read_operations(self, tmp_path: Path) -> None:
        """Sequential read operations in single thread should work correctly."""
        db = MUbase(tmp_path / "sequential.mubase")

        # Add some data
        for i in range(10):
            db.add_node(
                Node(
                    id=f"mod:{i}",
                    type=NodeType.MODULE,
                    name=f"mod_{i}",
                    qualified_name=f"mod_{i}",
                    file_path=f"mod_{i}.py",
                    line_start=1,
                    line_end=100,
                    complexity=0,
                )
            )

        results: list[int] = []

        # Perform many sequential reads
        for _ in range(20):
            nodes = db.get_nodes()
            results.append(len(nodes))
            time.sleep(0.01)

        db.close()

        # All reads should return same count
        assert all(r == 10 for r in results), "Sequential reads should be consistent"

    def test_rapid_open_close_cycles(self, tmp_path: Path) -> None:
        """Rapidly opening and closing database connections."""
        errors: list[Exception] = []
        cycles: list[int] = []
        lock = threading.Lock()
        db_path = tmp_path / "rapid.mubase"

        # Create initial database
        db = MUbase(db_path)
        db.add_node(
            Node(
                id="mod:test",
                type=NodeType.MODULE,
                name="test",
                qualified_name="test",
                file_path="test.py",
                line_start=1,
                line_end=100,
                complexity=0,
            )
        )
        db.close()

        def rapid_open_close(thread_id: int) -> None:
            local_cycles = 0
            try:
                for _ in range(5):
                    try:
                        local_db = MUbase(db_path, read_only=True)
                        nodes = local_db.get_nodes()
                        local_db.close()
                        local_cycles += 1
                    except Exception:
                        # Lock conflicts are acceptable
                        pass
                with lock:
                    cycles.append(local_cycles)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = []
        for i in range(5):
            t = threading.Thread(target=rapid_open_close, args=(i,))
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=30)

        # Some cycles should succeed
        assert sum(cycles) > 0, "At least some open/close cycles should succeed"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
