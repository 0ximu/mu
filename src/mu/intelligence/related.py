"""Related files detection for F4: mu_related.

Suggests files that typically change together based on:
1. Convention-based patterns (test files, stories, index exports)
2. Git co-change analysis (files that historically change together)
3. Dependency analysis (files that import/export from changed file)
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from mu.kernel import MUbase


@dataclass
class RelatedFile:
    """A file related to the target file."""

    path: str
    """Path to the related file (relative to project root)."""

    exists: bool
    """Whether the file currently exists."""

    action: Literal["update", "create", "review"]
    """Suggested action: update existing, create new, or review."""

    reason: str
    """Why this file is related."""

    confidence: float
    """Confidence score (0.0 - 1.0)."""

    source: str
    """Detection source: convention, git_cochange, dependency."""

    template: str | None = None
    """Optional template content for new files."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "path": self.path,
            "exists": self.exists,
            "action": self.action,
            "reason": self.reason,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "template": self.template,
        }


@dataclass
class RelatedFilesResult:
    """Result of related files detection."""

    file_path: str
    """The original file being analyzed."""

    change_type: str
    """Type of change: create, modify, delete."""

    related_files: list[RelatedFile] = field(default_factory=list)
    """List of related files, sorted by confidence."""

    detection_time_ms: float = 0.0
    """Time taken for detection in milliseconds."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "file_path": self.file_path,
            "change_type": self.change_type,
            "related_files": [f.to_dict() for f in self.related_files],
            "detection_time_ms": round(self.detection_time_ms, 2),
        }

    @property
    def create_files(self) -> list[RelatedFile]:
        """Files that should be created."""
        return [f for f in self.related_files if f.action == "create"]

    @property
    def update_files(self) -> list[RelatedFile]:
        """Files that should be updated."""
        return [f for f in self.related_files if f.action == "update"]

    @property
    def review_files(self) -> list[RelatedFile]:
        """Files that should be reviewed."""
        return [f for f in self.related_files if f.action == "review"]


@dataclass
class ConventionPattern:
    """A file naming convention pattern."""

    name: str
    """Pattern name (e.g., 'test_file')."""

    source_pattern: str
    """Regex pattern for source files."""

    target_pattern: str
    """Template for target file path. Use {name}, {dir}, {ext} placeholders."""

    reason: str
    """Why this pattern suggests a related file."""

    confidence: float = 0.9
    """Default confidence for this pattern."""


# Common file convention patterns
CONVENTION_PATTERNS: list[ConventionPattern] = [
    # Python test files
    ConventionPattern(
        name="python_test",
        source_pattern=r"^(?P<dir>.*?)/?(?P<name>[^/]+)\.py$",
        target_pattern="{dir}/tests/test_{name}.py",
        reason="Python test file convention",
        confidence=0.9,
    ),
    ConventionPattern(
        name="python_test_unit",
        source_pattern=r"^(?P<dir>src/[^/]+)/(?P<subdir>.*?)/?(?P<name>[^/]+)\.py$",
        target_pattern="tests/unit/test_{name}.py",
        reason="Unit test file in tests/unit/",
        confidence=0.85,
    ),
    # TypeScript/JavaScript test files
    ConventionPattern(
        name="ts_test",
        source_pattern=r"^(?P<dir>.*?)/?(?P<name>[^/]+)\.(ts|tsx|js|jsx)$",
        target_pattern="{dir}/__tests__/{name}.test.{ext}",
        reason="TypeScript test file convention",
        confidence=0.9,
    ),
    ConventionPattern(
        name="ts_spec",
        source_pattern=r"^(?P<dir>.*?)/?(?P<name>[^/]+)\.(ts|tsx|js|jsx)$",
        target_pattern="{dir}/{name}.spec.{ext}",
        reason="TypeScript spec file convention",
        confidence=0.85,
    ),
    # React/Vue story files
    ConventionPattern(
        name="storybook",
        source_pattern=r"^(?P<dir>.*?)/?(?P<name>[^/]+)\.(tsx|jsx)$",
        target_pattern="{dir}/{name}.stories.{ext}",
        reason="Storybook story file convention",
        confidence=0.8,
    ),
    # Index/barrel exports
    ConventionPattern(
        name="ts_index",
        source_pattern=r"^(?P<dir>src/[^/]+)/(?P<subdir>.*?)/?(?P<name>[^/]+)\.(ts|tsx)$",
        target_pattern="{dir}/index.ts",
        reason="Barrel export file (index.ts)",
        confidence=0.85,
    ),
    ConventionPattern(
        name="py_init",
        source_pattern=r"^(?P<dir>src/[^/]+)/(?P<subdir>.*?)/?(?P<name>[^/]+)\.py$",
        target_pattern="{dir}/__init__.py",
        reason="Python package __init__.py",
        confidence=0.8,
    ),
    # CSS/SCSS modules
    ConventionPattern(
        name="css_module",
        source_pattern=r"^(?P<dir>.*?)/?(?P<name>[^/]+)\.(tsx|jsx)$",
        target_pattern="{dir}/{name}.module.css",
        reason="CSS module for component",
        confidence=0.7,
    ),
    # Go test files
    ConventionPattern(
        name="go_test",
        source_pattern=r"^(?P<dir>.*?)/?(?P<name>[^/]+)\.go$",
        target_pattern="{dir}/{name}_test.go",
        reason="Go test file convention",
        confidence=0.9,
    ),
    # Rust test files
    ConventionPattern(
        name="rust_test",
        source_pattern=r"^(?P<dir>src)/(?P<name>[^/]+)\.rs$",
        target_pattern="tests/{name}_test.rs",
        reason="Rust integration test convention",
        confidence=0.85,
    ),
]


class RelatedFilesDetector:
    """Detects files that typically change together with a given file."""

    def __init__(
        self,
        db: MUbase | None = None,
        root_path: Path | None = None,
        git_history_depth: int = 100,
    ):
        """Initialize the detector.

        Args:
            db: Optional MUbase instance for dependency analysis.
            root_path: Project root path. Auto-detected if not provided.
            git_history_depth: Number of commits to analyze for co-change patterns.
        """
        self.db = db
        self.root_path = root_path or Path.cwd()
        self.git_history_depth = git_history_depth

    def detect(
        self,
        file_path: str,
        change_type: Literal["create", "modify", "delete"] = "modify",
        include_conventions: bool = True,
        include_git_cochange: bool = True,
        include_dependencies: bool = True,
    ) -> RelatedFilesResult:
        """Detect related files for a given file.

        Args:
            file_path: Path to the file being modified.
            change_type: Type of change being made.
            include_conventions: Include convention-based related files.
            include_git_cochange: Include git co-change analysis.
            include_dependencies: Include dependency analysis.

        Returns:
            RelatedFilesResult with all detected related files.
        """
        start_time = time.time()
        related_files: list[RelatedFile] = []

        # Normalize file path
        file_path = self._normalize_path(file_path)

        # 1. Convention-based detection
        if include_conventions:
            conv_files = self._detect_by_convention(file_path, change_type)
            related_files.extend(conv_files)

        # 2. Git co-change analysis
        if include_git_cochange:
            cochange_files = self._detect_by_git_cochange(file_path, change_type)
            related_files.extend(cochange_files)

        # 3. Dependency analysis
        if include_dependencies and self.db:
            dep_files = self._detect_by_dependency(file_path, change_type)
            related_files.extend(dep_files)

        # Deduplicate and sort by confidence
        related_files = self._deduplicate(related_files)
        related_files.sort(key=lambda f: f.confidence, reverse=True)

        duration_ms = (time.time() - start_time) * 1000

        return RelatedFilesResult(
            file_path=file_path,
            change_type=change_type,
            related_files=related_files,
            detection_time_ms=duration_ms,
        )

    def _normalize_path(self, file_path: str) -> str:
        """Normalize file path to be relative to root."""
        path = Path(file_path)

        # If absolute, make relative to root
        if path.is_absolute():
            try:
                path = path.relative_to(self.root_path)
            except ValueError:
                pass

        return str(path)

    def _detect_by_convention(self, file_path: str, change_type: str) -> list[RelatedFile]:
        """Detect related files based on naming conventions."""
        related: list[RelatedFile] = []

        for pattern in CONVENTION_PATTERNS:
            match = re.match(pattern.source_pattern, file_path)
            if not match:
                continue

            # Build target path from template
            groups = match.groupdict()

            # Extract extension if present
            ext_match = re.search(r"\.(\w+)$", file_path)
            if ext_match:
                groups["ext"] = ext_match.group(1)

            try:
                target_path = pattern.target_pattern.format(**groups)
            except KeyError:
                continue

            # Skip if target is the same as source
            if target_path == file_path:
                continue

            # Check if target exists
            target_full = self.root_path / target_path
            exists = target_full.exists()

            # Determine action
            if exists:
                action: Literal["update", "create", "review"] = (
                    "update" if change_type == "modify" else "review"
                )
            else:
                action = "create"

            related.append(
                RelatedFile(
                    path=target_path,
                    exists=exists,
                    action=action,
                    reason=pattern.reason,
                    confidence=pattern.confidence,
                    source="convention",
                    template=self._get_template(pattern.name, file_path) if not exists else None,
                )
            )

        return related

    def _detect_by_git_cochange(self, file_path: str, change_type: str) -> list[RelatedFile]:
        """Detect files that historically change together via git log."""
        related: list[RelatedFile] = []

        # Skip for new files - no history
        if change_type == "create":
            return related

        try:
            # Get commits that touched this file
            result = subprocess.run(
                [
                    "git",
                    "log",
                    f"-{self.git_history_depth}",
                    "--pretty=format:%H",
                    "--follow",
                    "--",
                    file_path,
                ],
                cwd=self.root_path,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                return related

            commits = result.stdout.strip().split("\n")
            if not commits or commits == [""]:
                return related

            # Count co-occurring files
            cochange_counts: dict[str, int] = {}

            for commit in commits[:50]:  # Limit to avoid slow queries
                # Get files in this commit
                files_result = subprocess.run(
                    ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit],
                    cwd=self.root_path,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

                if files_result.returncode != 0:
                    continue

                files = files_result.stdout.strip().split("\n")
                for f in files:
                    if f and f != file_path:
                        cochange_counts[f] = cochange_counts.get(f, 0) + 1

            # Calculate confidence based on co-occurrence frequency
            total_commits = len(commits)
            for cofile, count in cochange_counts.items():
                confidence = min(count / total_commits, 0.95)

                # Only include files with >20% co-occurrence
                if confidence < 0.2:
                    continue

                # Check if file exists
                full_path = self.root_path / cofile
                exists = full_path.exists()

                if not exists:
                    continue  # Skip deleted files

                related.append(
                    RelatedFile(
                        path=cofile,
                        exists=exists,
                        action="review",
                        reason=f"Changed together in {count}/{total_commits} commits ({confidence:.0%})",
                        confidence=confidence,
                        source="git_cochange",
                    )
                )

        except (subprocess.TimeoutExpired, FileNotFoundError):
            # Git not available or timeout
            pass

        return related

    def _detect_by_dependency(self, file_path: str, change_type: str) -> list[RelatedFile]:
        """Detect related files based on import/dependency graph."""
        related: list[RelatedFile] = []

        if not self.db:
            return related

        try:
            # Find the module node for this file
            nodes = self.db.get_nodes_by_file(file_path)
            if not nodes:
                return related

            # Find the module node (prefer module type)
            module_node = nodes[0]
            for node in nodes:
                if node.type.value == "module":
                    module_node = node
                    break

            # Find files that import this module (dependents)
            from mu.kernel.graph import GraphManager

            gm = GraphManager(self.db.conn)
            gm.load()

            if not gm.has_node(module_node.id):
                return related

            # Get incoming edges (files that depend on this)
            dependents = gm.impact(module_node.id, edge_types=["imports"])

            for dep_id in dependents[:20]:  # Limit results
                dep_node = self.db.get_node(dep_id)
                if not dep_node or not dep_node.file_path:
                    continue

                # Skip self
                if dep_node.file_path == file_path:
                    continue

                full_path = self.root_path / dep_node.file_path
                exists = full_path.exists()

                related.append(
                    RelatedFile(
                        path=dep_node.file_path,
                        exists=exists,
                        action="review",
                        reason=f"Imports from {Path(file_path).stem}",
                        confidence=0.75,
                        source="dependency",
                    )
                )

            # Also check what this file imports (ancestors) - for delete operations
            if change_type == "delete":
                ancestors = gm.ancestors(module_node.id, edge_types=["imports"])
                for anc_id in ancestors[:10]:
                    anc_node = self.db.get_node(anc_id)
                    if not anc_node or not anc_node.file_path:
                        continue

                    full_path = self.root_path / anc_node.file_path
                    exists = full_path.exists()

                    related.append(
                        RelatedFile(
                            path=anc_node.file_path,
                            exists=exists,
                            action="review",
                            reason="May need import cleanup after deletion",
                            confidence=0.6,
                            source="dependency",
                        )
                    )

        except Exception:
            # Gracefully handle DB errors
            pass

        return related

    def _deduplicate(self, related_files: list[RelatedFile]) -> list[RelatedFile]:
        """Remove duplicate files, keeping highest confidence entry."""
        seen: dict[str, RelatedFile] = {}

        for rf in related_files:
            if rf.path in seen:
                # Keep higher confidence
                if rf.confidence > seen[rf.path].confidence:
                    seen[rf.path] = rf
            else:
                seen[rf.path] = rf

        return list(seen.values())

    def _get_template(self, pattern_name: str, source_path: str) -> str | None:
        """Get a template for creating a new file based on pattern.

        Returns minimal template hints - actual generation should use mu_generate.
        """
        templates: dict[str, str] = {
            "python_test": "# Test file for {name}\nimport pytest\n\n\ndef test_{name}():\n    pass\n",
            "python_test_unit": "# Unit tests for {name}\nimport pytest\n\n\nclass Test{Name}:\n    def test_example(self):\n        pass\n",
            "ts_test": "// Test file for {name}\nimport {{ describe, it, expect }} from 'vitest';\n\ndescribe('{name}', () => {{\n  it('should work', () => {{\n    expect(true).toBe(true);\n  }});\n}});\n",
            "ts_spec": "// Spec file for {name}\nimport {{ describe, it, expect }} from 'vitest';\n\ndescribe('{name}', () => {{\n  it('should work', () => {{\n    expect(true).toBe(true);\n  }});\n}});\n",
            "storybook": "// Storybook story for {name}\nimport type {{ Meta, StoryObj }} from '@storybook/react';\nimport {{ {Name} }} from './{name}';\n\nconst meta: Meta<typeof {Name}> = {{\n  component: {Name},\n}};\n\nexport default meta;\ntype Story = StoryObj<typeof {Name}>;\n\nexport const Default: Story = {{}};\n",
            "go_test": '// Test file for {name}\npackage {package}\n\nimport "testing"\n\nfunc Test{Name}(t *testing.T) {{\n\t// TODO: Add tests\n}}\n',
        }

        template = templates.get(pattern_name)
        if not template:
            return None

        # Extract name from source path
        name = Path(source_path).stem
        name_pascal = "".join(word.capitalize() for word in re.split(r"[_-]", name))

        return template.format(name=name, Name=name_pascal, package="main")


__all__ = [
    "ConventionPattern",
    "RelatedFile",
    "RelatedFilesDetector",
    "RelatedFilesResult",
]
