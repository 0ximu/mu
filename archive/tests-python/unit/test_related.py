"""Tests for related files detection (Intelligence Layer F4)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mu.extras.intelligence import (
    RelatedFile,
    RelatedFilesDetector,
    RelatedFilesResult,
)
from mu.extras.intelligence.related import CONVENTION_PATTERNS, ConventionPattern


class TestRelatedFileModel:
    """Tests for RelatedFile data model."""

    def test_related_file_to_dict(self) -> None:
        """RelatedFile converts to dict correctly."""
        rf = RelatedFile(
            path="tests/unit/test_auth.py",
            exists=True,
            action="update",
            reason="Unit test file convention",
            confidence=0.9,
            source="convention",
            template=None,
        )
        d = rf.to_dict()
        assert d["path"] == "tests/unit/test_auth.py"
        assert d["exists"] is True
        assert d["action"] == "update"
        assert d["reason"] == "Unit test file convention"
        assert d["confidence"] == 0.9
        assert d["source"] == "convention"
        assert d["template"] is None

    def test_related_file_with_template(self) -> None:
        """RelatedFile can include template content."""
        rf = RelatedFile(
            path="tests/unit/test_new_feature.py",
            exists=False,
            action="create",
            reason="Python test file convention",
            confidence=0.9,
            source="convention",
            template="import pytest\n\ndef test_example():\n    pass",
        )
        d = rf.to_dict()
        assert d["template"] is not None
        assert "pytest" in d["template"]


class TestRelatedFilesResult:
    """Tests for RelatedFilesResult data model."""

    def test_result_to_dict(self) -> None:
        """RelatedFilesResult converts to dict correctly."""
        result = RelatedFilesResult(
            file_path="src/auth.py",
            change_type="modify",
            related_files=[
                RelatedFile(
                    path="tests/test_auth.py",
                    exists=True,
                    action="update",
                    reason="Test file",
                    confidence=0.9,
                    source="convention",
                )
            ],
            detection_time_ms=15.5,
        )
        d = result.to_dict()
        assert d["file_path"] == "src/auth.py"
        assert d["change_type"] == "modify"
        assert len(d["related_files"]) == 1
        assert d["detection_time_ms"] == 15.5

    def test_result_action_filters(self) -> None:
        """Result filters files by action correctly."""
        result = RelatedFilesResult(
            file_path="src/auth.py",
            change_type="modify",
            related_files=[
                RelatedFile(
                    path="tests/test_auth.py",
                    exists=False,
                    action="create",
                    reason="Test file",
                    confidence=0.9,
                    source="convention",
                ),
                RelatedFile(
                    path="src/__init__.py",
                    exists=True,
                    action="update",
                    reason="Package init",
                    confidence=0.8,
                    source="convention",
                ),
                RelatedFile(
                    path="src/api.py",
                    exists=True,
                    action="review",
                    reason="Imports auth",
                    confidence=0.75,
                    source="dependency",
                ),
            ],
        )

        assert len(result.create_files) == 1
        assert result.create_files[0].path == "tests/test_auth.py"

        assert len(result.update_files) == 1
        assert result.update_files[0].path == "src/__init__.py"

        assert len(result.review_files) == 1
        assert result.review_files[0].path == "src/api.py"


class TestConventionPatterns:
    """Tests for built-in convention patterns."""

    def test_python_test_pattern(self) -> None:
        """Python test pattern matches correctly."""
        python_test = next(
            (p for p in CONVENTION_PATTERNS if p.name == "python_test"), None
        )
        assert python_test is not None

        import re

        # Should match Python files
        match = re.match(python_test.source_pattern, "src/auth.py")
        assert match is not None
        assert match.group("name") == "auth"
        assert match.group("dir") == "src"

    def test_typescript_test_pattern(self) -> None:
        """TypeScript test pattern matches correctly."""
        ts_test = next((p for p in CONVENTION_PATTERNS if p.name == "ts_test"), None)
        assert ts_test is not None

        import re

        # Should match TypeScript files
        match = re.match(ts_test.source_pattern, "src/hooks/useAuth.ts")
        assert match is not None
        assert match.group("name") == "useAuth"

        # Should match TSX files
        match = re.match(ts_test.source_pattern, "src/components/Button.tsx")
        assert match is not None
        assert match.group("name") == "Button"

    def test_go_test_pattern(self) -> None:
        """Go test pattern matches correctly."""
        go_test = next((p for p in CONVENTION_PATTERNS if p.name == "go_test"), None)
        assert go_test is not None

        import re

        match = re.match(go_test.source_pattern, "internal/auth/handler.go")
        assert match is not None
        assert match.group("name") == "handler"

    def test_storybook_pattern(self) -> None:
        """Storybook story pattern matches correctly."""
        storybook = next(
            (p for p in CONVENTION_PATTERNS if p.name == "storybook"), None
        )
        assert storybook is not None

        import re

        match = re.match(storybook.source_pattern, "src/components/Button.tsx")
        assert match is not None
        assert match.group("name") == "Button"


class TestRelatedFilesDetector:
    """Tests for RelatedFilesDetector."""

    def test_detect_python_test_file(self, tmp_path: Path) -> None:
        """Detects Python test file from source."""
        # Create source file
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        source_file = src_dir / "auth.py"
        source_file.write_text("class AuthService:\n    pass\n")

        detector = RelatedFilesDetector(root_path=tmp_path)
        result = detector.detect(
            str(source_file),
            change_type="modify",
            include_conventions=True,
            include_git_cochange=False,  # Skip git for this test
            include_dependencies=False,  # No MUbase
        )

        assert result.file_path is not None
        assert any("test_auth" in rf.path for rf in result.related_files)

    def test_detect_typescript_test_file(self, tmp_path: Path) -> None:
        """Detects TypeScript test file from source."""
        # Create source file
        src_dir = tmp_path / "src" / "hooks"
        src_dir.mkdir(parents=True)
        source_file = src_dir / "useAuth.ts"
        source_file.write_text("export function useAuth() {}\n")

        detector = RelatedFilesDetector(root_path=tmp_path)
        result = detector.detect(
            str(source_file.relative_to(tmp_path)),
            change_type="modify",
            include_conventions=True,
            include_git_cochange=False,
            include_dependencies=False,
        )

        # Should suggest test file
        test_files = [rf for rf in result.related_files if "test" in rf.path.lower()]
        assert len(test_files) > 0

    def test_detect_existing_file_gets_update_action(self, tmp_path: Path) -> None:
        """Existing related files get 'update' action."""
        # Create source file
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        source_file = src_dir / "auth.py"
        source_file.write_text("class AuthService:\n    pass\n")

        # Create test file
        tests_dir = tmp_path / "src" / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_auth.py"
        test_file.write_text("def test_auth():\n    pass\n")

        detector = RelatedFilesDetector(root_path=tmp_path)
        result = detector.detect(
            str(source_file.relative_to(tmp_path)),
            change_type="modify",
            include_conventions=True,
            include_git_cochange=False,
            include_dependencies=False,
        )

        # Find the test file in results
        test_results = [rf for rf in result.related_files if "test_auth" in rf.path]
        if test_results:
            assert test_results[0].exists is True
            assert test_results[0].action == "update"

    def test_detect_nonexistent_file_gets_create_action(self, tmp_path: Path) -> None:
        """Non-existent related files get 'create' action."""
        # Create source file only
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        source_file = src_dir / "auth.py"
        source_file.write_text("class AuthService:\n    pass\n")

        detector = RelatedFilesDetector(root_path=tmp_path)
        result = detector.detect(
            str(source_file.relative_to(tmp_path)),
            change_type="modify",
            include_conventions=True,
            include_git_cochange=False,
            include_dependencies=False,
        )

        # Check if any test suggestion has create action
        test_results = [
            rf for rf in result.related_files if "test" in rf.path and not rf.exists
        ]
        if test_results:
            assert test_results[0].action == "create"

    def test_deduplicate_related_files(self, tmp_path: Path) -> None:
        """Duplicate paths are deduplicated keeping highest confidence."""
        # Create source file
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        source_file = src_dir / "auth.py"
        source_file.write_text("class AuthService:\n    pass\n")

        detector = RelatedFilesDetector(root_path=tmp_path)
        result = detector.detect(
            str(source_file.relative_to(tmp_path)),
            change_type="modify",
            include_conventions=True,
            include_git_cochange=False,
            include_dependencies=False,
        )

        # Check no duplicate paths
        paths = [rf.path for rf in result.related_files]
        assert len(paths) == len(set(paths))

    def test_detection_time_is_recorded(self, tmp_path: Path) -> None:
        """Detection time is recorded in milliseconds."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        source_file = src_dir / "auth.py"
        source_file.write_text("class AuthService:\n    pass\n")

        detector = RelatedFilesDetector(root_path=tmp_path)
        result = detector.detect(
            str(source_file.relative_to(tmp_path)),
            include_git_cochange=False,
            include_dependencies=False,
        )

        assert result.detection_time_ms >= 0

    def test_normalize_absolute_path(self, tmp_path: Path) -> None:
        """Absolute paths are normalized to relative."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        source_file = src_dir / "auth.py"
        source_file.write_text("class AuthService:\n    pass\n")

        detector = RelatedFilesDetector(root_path=tmp_path)
        result = detector.detect(
            str(source_file),  # Absolute path
            include_git_cochange=False,
            include_dependencies=False,
        )

        # File path should be relative
        assert not result.file_path.startswith("/")

    def test_create_change_type_suggests_supporting_files(
        self, tmp_path: Path
    ) -> None:
        """Creating a new file suggests supporting files."""
        src_dir = tmp_path / "src" / "hooks"
        src_dir.mkdir(parents=True)
        source_file = src_dir / "useNewFeature.ts"
        source_file.write_text("export function useNewFeature() {}\n")

        detector = RelatedFilesDetector(root_path=tmp_path)
        result = detector.detect(
            str(source_file.relative_to(tmp_path)),
            change_type="create",
            include_conventions=True,
            include_git_cochange=False,
            include_dependencies=False,
        )

        # Should suggest test file
        assert any(
            "test" in rf.path.lower() or "spec" in rf.path.lower()
            for rf in result.related_files
        )


class TestConventionPattern:
    """Tests for ConventionPattern dataclass."""

    def test_pattern_attributes(self) -> None:
        """ConventionPattern has expected attributes."""
        pattern = ConventionPattern(
            name="custom_test",
            source_pattern=r"^(?P<dir>.*)/(?P<name>[^/]+)\.py$",
            target_pattern="{dir}/tests/test_{name}.py",
            reason="Custom test convention",
            confidence=0.85,
        )
        assert pattern.name == "custom_test"
        assert pattern.confidence == 0.85
        assert pattern.reason == "Custom test convention"
