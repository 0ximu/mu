"""Tests for MU scanner."""

import pytest
import tempfile
from pathlib import Path

from mu.config import MUConfig
from mu.scanner import (
    detect_language,
    should_ignore,
    scan_codebase,
    scan_codebase_auto,
    SUPPORTED_LANGUAGES,
)


class TestLanguageDetection:
    """Test language detection from file extensions."""

    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("main.py", "python"),
            ("app.ts", "typescript"),
            ("component.tsx", "tsx"),
            ("component.jsx", "jsx"),
            ("service.cs", "csharp"),
            ("index.js", "javascript"),
            ("config.yaml", "yaml"),
            ("data.json", "json"),
            ("unknown.xyz", None),
        ],
    )
    def test_detect_language(self, filename, expected):
        """Test language detection for various extensions."""
        result = detect_language(Path(filename))
        assert result == expected

    def test_case_insensitive(self):
        """Test that extension matching is case insensitive."""
        assert detect_language(Path("Main.PY")) == "python"
        assert detect_language(Path("App.TS")) == "typescript"


class TestIgnorePatterns:
    """Test ignore pattern matching."""

    def test_directory_pattern(self):
        """Test directory ignore patterns."""
        root = Path("/project")
        patterns = ["node_modules/"]

        assert should_ignore(
            Path("/project/node_modules/foo.js"), patterns, root
        ) == "ignore_pattern"
        assert should_ignore(
            Path("/project/src/app.js"), patterns, root
        ) is None

    def test_glob_pattern(self):
        """Test glob ignore patterns."""
        root = Path("/project")
        patterns = ["*.pyc", "*.min.js"]

        assert should_ignore(
            Path("/project/cache.pyc"), patterns, root
        ) == "ignore_pattern"
        assert should_ignore(
            Path("/project/bundle.min.js"), patterns, root
        ) == "ignore_pattern"
        assert should_ignore(
            Path("/project/app.py"), patterns, root
        ) is None


class TestScanCodebase:
    """Test codebase scanning."""

    def test_scan_empty_directory(self):
        """Test scanning an empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = MUConfig()
            result = scan_codebase(Path(tmpdir), config)

            assert result.stats.total_files == 0
            assert result.stats.total_lines == 0

    def test_scan_with_python_files(self):
        """Test scanning a directory with Python files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            (Path(tmpdir) / "main.py").write_text("print('hello')\n")
            (Path(tmpdir) / "utils.py").write_text("def foo():\n    pass\n")

            config = MUConfig()
            result = scan_codebase(Path(tmpdir), config)

            assert result.stats.total_files == 2
            assert result.stats.languages.get("python") == 2
            assert result.stats.total_lines == 3

    def test_scan_ignores_node_modules(self):
        """Test that node_modules is ignored by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create node_modules directory with files
            nm_dir = Path(tmpdir) / "node_modules"
            nm_dir.mkdir()
            (nm_dir / "package.js").write_text("module.exports = {}")

            # Create regular file
            (Path(tmpdir) / "app.js").write_text("console.log('hi')")

            config = MUConfig()
            result = scan_codebase(Path(tmpdir), config)

            # Should only find app.js
            assert result.stats.total_files == 1
            assert any(s.path == "node_modules" for s in result.skipped)

    def test_scan_respects_max_file_size(self):
        """Test that large files are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file larger than max size
            large_file = Path(tmpdir) / "large.py"
            large_file.write_text("x" * (1024 * 1024 + 1))  # > 1MB

            config = MUConfig()
            config.scanner.max_file_size_kb = 1  # 1KB limit
            result = scan_codebase(Path(tmpdir), config)

            assert result.stats.total_files == 0
            assert any(s.reason == "file_too_large" for s in result.skipped)

    def test_scan_result_has_file_hashes(self):
        """Test that scanned files have hashes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.py").write_text("x = 1")

            config = MUConfig()
            result = scan_codebase(Path(tmpdir), config)

            assert len(result.files) == 1
            assert result.files[0].hash.startswith("sha256:")


class TestRustScanner:
    """Tests for Rust scanner integration."""

    def test_rust_scanner_available(self):
        """Test that Rust scanner is available."""
        from mu.scanner import _HAS_RUST_SCANNER, _USE_RUST_SCANNER

        # Rust scanner should be available if mu._core is installed
        try:
            from mu import _core

            has_scan = hasattr(_core, "scan_directory")
            assert _HAS_RUST_SCANNER == has_scan
        except ImportError:
            assert not _HAS_RUST_SCANNER

    @pytest.mark.skipif(
        not __import__("mu.scanner", fromlist=["_HAS_RUST_SCANNER"])._HAS_RUST_SCANNER,
        reason="Rust scanner not available",
    )
    def test_rust_scan_directory_basic(self):
        """Test basic Rust scanner functionality."""
        from mu import _core

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            (Path(tmpdir) / "main.py").write_text("print('hello')\n")
            (Path(tmpdir) / "utils.ts").write_text("export const x = 1;\n")

            result = _core.scan_directory(str(tmpdir))

            # Should find both files
            assert len(result.files) >= 2
            assert result.error_count == 0
            assert result.duration_ms >= 0

    @pytest.mark.skipif(
        not __import__("mu.scanner", fromlist=["_HAS_RUST_SCANNER"])._HAS_RUST_SCANNER,
        reason="Rust scanner not available",
    )
    def test_rust_scan_with_extension_filter(self):
        """Test Rust scanner with extension filtering."""
        from mu import _core

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "main.py").write_text("print('hello')")
            (Path(tmpdir) / "utils.ts").write_text("export const x = 1;")
            (Path(tmpdir) / "readme.md").write_text("# Hello")

            result = _core.scan_directory(str(tmpdir), extensions=["py"])

            # Should only find Python file
            assert len(result.files) == 1
            assert result.files[0].language == "python"

    @pytest.mark.skipif(
        not __import__("mu.scanner", fromlist=["_HAS_RUST_SCANNER"])._HAS_RUST_SCANNER,
        reason="Rust scanner not available",
    )
    def test_rust_scan_with_hashes(self):
        """Test Rust scanner computes file hashes."""
        from mu import _core

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.py").write_text("x = 1")

            result = _core.scan_directory(
                str(tmpdir), extensions=["py"], compute_hashes=True
            )

            assert len(result.files) == 1
            assert result.files[0].hash is not None
            assert result.files[0].hash.startswith("xxh3:")

    @pytest.mark.skipif(
        not __import__("mu.scanner", fromlist=["_HAS_RUST_SCANNER"])._HAS_RUST_SCANNER,
        reason="Rust scanner not available",
    )
    def test_rust_scan_with_line_count(self):
        """Test Rust scanner counts lines."""
        from mu import _core

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.py").write_text("line1\nline2\nline3\n")

            result = _core.scan_directory(
                str(tmpdir), extensions=["py"], count_lines_flag=True
            )

            assert len(result.files) == 1
            assert result.files[0].lines == 3

    @pytest.mark.skipif(
        not __import__("mu.scanner", fromlist=["_HAS_RUST_SCANNER"])._HAS_RUST_SCANNER,
        reason="Rust scanner not available",
    )
    def test_rust_scan_respects_gitignore(self):
        """Test Rust scanner respects .gitignore."""
        import subprocess
        from mu import _core

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            # Initialize git repo for .gitignore to be respected
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            (tmppath / "main.py").write_text("print('hello')")
            (tmppath / "ignored.py").write_text("print('ignored')")
            (tmppath / ".gitignore").write_text("ignored.py\n")

            result = _core.scan_directory(str(tmpdir), extensions=["py"])

            paths = [f.path for f in result.files]
            assert "main.py" in paths
            assert "ignored.py" not in paths

    @pytest.mark.skipif(
        not __import__("mu.scanner", fromlist=["_HAS_RUST_SCANNER"])._HAS_RUST_SCANNER,
        reason="Rust scanner not available",
    )
    def test_rust_scan_auto_function(self):
        """Test scan_codebase_auto uses Rust when available."""
        from mu.scanner import scan_codebase_auto, _USE_RUST_SCANNER

        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "test.py").write_text("x = 1")

            config = MUConfig()
            result = scan_codebase_auto(Path(tmpdir), config)

            assert result.stats.total_files == 1
            # Hash format depends on which scanner was used
            if _USE_RUST_SCANNER:
                assert result.files[0].hash.startswith("xxh3:")
            else:
                assert result.files[0].hash.startswith("sha256:")
