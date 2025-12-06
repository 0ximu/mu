"""Tests for MU scanner."""

import pytest
import tempfile
from pathlib import Path

from mu.config import MUConfig
from mu.scanner import (
    detect_language,
    should_ignore,
    scan_codebase,
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
