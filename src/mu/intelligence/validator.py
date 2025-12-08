"""Change validator - Pre-commit pattern validation.

Validates code changes against detected codebase patterns to ensure
new code follows established conventions and architectural rules.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mu.intelligence.models import Pattern, PatternCategory
from mu.intelligence.patterns import PatternDetector

if TYPE_CHECKING:
    from mu.kernel import MUbase


class ViolationSeverity(Enum):
    """Severity levels for pattern violations."""

    ERROR = "error"
    """Must fix - blocks commit."""

    WARNING = "warning"
    """Should fix - doesn't block but strongly recommended."""

    INFO = "info"
    """Consider - style suggestion."""


@dataclass
class Violation:
    """A pattern violation found in the changes."""

    file_path: str
    """Path to the file with the violation."""

    line_start: int | None
    """Starting line number (1-indexed), if applicable."""

    line_end: int | None
    """Ending line number (1-indexed), if applicable."""

    severity: ViolationSeverity
    """Severity of the violation."""

    rule: str
    """The rule that was violated (pattern name)."""

    message: str
    """Human-readable description of the violation."""

    suggestion: str = ""
    """How to fix the violation."""

    pattern_category: str = ""
    """Category of the pattern (naming, architecture, etc.)."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "severity": self.severity.value,
            "rule": self.rule,
            "message": self.message,
            "suggestion": self.suggestion,
            "pattern_category": self.pattern_category,
        }


@dataclass
class ValidationResult:
    """Result of change validation."""

    valid: bool
    """Whether all changes pass validation (no errors)."""

    violations: list[Violation] = field(default_factory=list)
    """List of violations found."""

    patterns_checked: list[str] = field(default_factory=list)
    """Names of patterns that were checked."""

    files_checked: list[str] = field(default_factory=list)
    """Files that were validated."""

    error_count: int = 0
    """Number of error-level violations."""

    warning_count: int = 0
    """Number of warning-level violations."""

    info_count: int = 0
    """Number of info-level violations."""

    validation_time_ms: float = 0.0
    """Time taken for validation in milliseconds."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "valid": self.valid,
            "violations": [v.to_dict() for v in self.violations],
            "patterns_checked": self.patterns_checked,
            "files_checked": self.files_checked,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "validation_time_ms": round(self.validation_time_ms, 2),
        }


@dataclass
class ChangedFile:
    """A file that has been changed."""

    path: str
    """File path relative to repo root."""

    status: str
    """Git status: A (added), M (modified), D (deleted), R (renamed)."""

    content: str = ""
    """File content (for added/modified files)."""

    added_lines: list[tuple[int, str]] = field(default_factory=list)
    """List of (line_number, content) for added lines."""


class ChangeValidator:
    """Validates code changes against codebase patterns.

    Uses detected patterns to check if new or modified code follows
    established conventions.
    """

    def __init__(self, mubase: MUbase) -> None:
        """Initialize the validator.

        Args:
            mubase: The MUbase database with codebase patterns.
        """
        self.db = mubase
        self._pattern_detector = PatternDetector(mubase)
        self._patterns: list[Pattern] = []
        self._root_path: Path | None = None

    def validate(
        self,
        files: list[str] | None = None,
        staged: bool = False,
        category: PatternCategory | None = None,
    ) -> ValidationResult:
        """Validate changes against detected patterns.

        Args:
            files: Specific files to validate. If None, uses staged or all changed.
            staged: If True and files is None, validate staged changes only.
            category: Optional category filter - only check patterns in this category.

        Returns:
            ValidationResult with violations and metadata.
        """
        import time

        start_time = time.time()

        # Get root path from metadata
        stats = self.db.stats()
        root_path_str = stats.get("root_path")
        self._root_path = Path(root_path_str) if root_path_str else Path.cwd()

        # Load patterns (use cached if available)
        self._load_patterns(category)

        # Get changed files
        if files:
            changed_files = self._get_files_from_paths(files)
        elif staged:
            changed_files = self._get_staged_changes()
        else:
            changed_files = self._get_all_changes()

        if not changed_files:
            elapsed_ms = (time.time() - start_time) * 1000
            return ValidationResult(
                valid=True,
                patterns_checked=[p.name for p in self._patterns],
                files_checked=[],
                validation_time_ms=elapsed_ms,
            )

        # Run validation rules
        violations: list[Violation] = []
        for changed_file in changed_files:
            file_violations = self._validate_file(changed_file)
            violations.extend(file_violations)

        # Count by severity
        error_count = sum(1 for v in violations if v.severity == ViolationSeverity.ERROR)
        warning_count = sum(1 for v in violations if v.severity == ViolationSeverity.WARNING)
        info_count = sum(1 for v in violations if v.severity == ViolationSeverity.INFO)

        elapsed_ms = (time.time() - start_time) * 1000

        return ValidationResult(
            valid=error_count == 0,
            violations=violations,
            patterns_checked=[p.name for p in self._patterns],
            files_checked=[f.path for f in changed_files],
            error_count=error_count,
            warning_count=warning_count,
            info_count=info_count,
            validation_time_ms=elapsed_ms,
        )

    def _load_patterns(self, category: PatternCategory | None = None) -> None:
        """Load patterns from database or detect them."""
        # Try cached patterns first
        if self.db.has_patterns():
            stored = self.db.get_patterns(category.value if category else None)
            if stored:
                self._patterns = stored
                return

        # Detect patterns
        result = self._pattern_detector.detect(category=category)
        self._patterns = result.patterns

        # Cache for future use
        if not category:
            self.db.save_patterns(self._patterns)

    def _get_staged_changes(self) -> list[ChangedFile]:
        """Get files staged for commit."""
        try:
            # Get list of staged files
            result = subprocess.run(
                ["git", "diff", "--cached", "--name-status"],
                capture_output=True,
                text=True,
                cwd=self._root_path,
                check=False,
            )
            if result.returncode != 0:
                return []

            return self._parse_git_status(result.stdout, staged=True)
        except (subprocess.SubprocessError, FileNotFoundError):
            return []

    def _get_all_changes(self) -> list[ChangedFile]:
        """Get all changed files (staged + unstaged)."""
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=self._root_path,
                check=False,
            )
            if result.returncode != 0:
                return []

            return self._parse_porcelain_status(result.stdout)
        except (subprocess.SubprocessError, FileNotFoundError):
            return []

    def _get_files_from_paths(self, paths: list[str]) -> list[ChangedFile]:
        """Create ChangedFile objects from explicit paths."""
        changed_files = []
        for path in paths:
            full_path = self._root_path / path if self._root_path else Path(path)
            if full_path.exists():
                try:
                    content = full_path.read_text()
                    # Mark all lines as added for validation purposes
                    added_lines = [(i + 1, line) for i, line in enumerate(content.splitlines())]
                    changed_files.append(
                        ChangedFile(
                            path=path,
                            status="M",  # Treat as modified
                            content=content,
                            added_lines=added_lines,
                        )
                    )
                except (OSError, UnicodeDecodeError):
                    continue
        return changed_files

    def _parse_git_status(self, output: str, staged: bool = True) -> list[ChangedFile]:
        """Parse git diff --name-status output."""
        changed_files = []
        for line in output.strip().splitlines():
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                status = parts[0][0]  # A, M, D, R
                path = parts[-1]  # Handle renames (R100\told\tnew)

                if status == "D":
                    # Skip deleted files
                    continue

                changed_file = self._create_changed_file(path, status, staged)
                if changed_file:
                    changed_files.append(changed_file)

        return changed_files

    def _parse_porcelain_status(self, output: str) -> list[ChangedFile]:
        """Parse git status --porcelain output."""
        changed_files = []
        for line in output.strip().splitlines():
            if not line or len(line) < 3:
                continue

            status = line[:2].strip()
            path = line[3:].strip()

            # Handle renames: "R  old -> new"
            if " -> " in path:
                path = path.split(" -> ")[-1]

            # Skip deleted files
            if status == "D" or status == " D":
                continue

            # Map to simple status
            if "A" in status:
                simple_status = "A"
            elif "M" in status or "?" in status:
                simple_status = "M"
            elif "R" in status:
                simple_status = "R"
            else:
                simple_status = "M"

            changed_file = self._create_changed_file(path, simple_status, staged=False)
            if changed_file:
                changed_files.append(changed_file)

        return changed_files

    def _create_changed_file(
        self, path: str, status: str, staged: bool = False
    ) -> ChangedFile | None:
        """Create a ChangedFile object with content and changed lines."""
        full_path = self._root_path / path if self._root_path else Path(path)

        if not full_path.exists():
            return None

        try:
            content = full_path.read_text()
        except (OSError, UnicodeDecodeError):
            return None

        # Get added lines from git diff
        added_lines = self._get_added_lines(path, staged)

        # If no diff info, treat all lines as new (for new files)
        if status == "A" or not added_lines:
            added_lines = [(i + 1, line) for i, line in enumerate(content.splitlines())]

        return ChangedFile(
            path=path,
            status=status,
            content=content,
            added_lines=added_lines,
        )

    def _get_added_lines(self, path: str, staged: bool = False) -> list[tuple[int, str]]:
        """Get lines added in the diff."""
        try:
            cmd = ["git", "diff"]
            if staged:
                cmd.append("--cached")
            cmd.extend(["--unified=0", "--", path])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self._root_path,
                check=False,
            )

            if result.returncode != 0:
                return []

            return self._parse_diff_for_added_lines(result.stdout)
        except (subprocess.SubprocessError, FileNotFoundError):
            return []

    def _parse_diff_for_added_lines(self, diff_output: str) -> list[tuple[int, str]]:
        """Parse unified diff to extract added lines with line numbers."""
        added_lines: list[tuple[int, str]] = []
        current_line = 0

        for line in diff_output.splitlines():
            # @@ -start,count +start,count @@
            if line.startswith("@@"):
                match = re.search(r"\+(\d+)", line)
                if match:
                    current_line = int(match.group(1)) - 1

            elif line.startswith("+") and not line.startswith("+++"):
                current_line += 1
                added_lines.append((current_line, line[1:]))

            elif line.startswith("-") or line.startswith("\\"):
                # Removed lines or "\ No newline" - don't increment
                pass
            else:
                # Context line
                current_line += 1

        return added_lines

    def _validate_file(self, changed_file: ChangedFile) -> list[Violation]:
        """Validate a single changed file against patterns."""
        violations: list[Violation] = []

        # Run all validation rules
        violations.extend(self._check_naming_patterns(changed_file))
        violations.extend(self._check_architecture_patterns(changed_file))
        violations.extend(self._check_testing_patterns(changed_file))
        violations.extend(self._check_import_patterns(changed_file))

        return violations

    def _check_naming_patterns(self, changed_file: ChangedFile) -> list[Violation]:
        """Check naming convention violations."""
        violations: list[Violation] = []
        path = Path(changed_file.path)

        # Get naming patterns
        naming_patterns = [p for p in self._patterns if p.category == PatternCategory.NAMING]
        if not naming_patterns:
            return violations

        # Check file extension
        ext = path.suffix

        # Check function casing patterns
        snake_case_pattern = next(
            (p for p in naming_patterns if p.name == "snake_case_functions"), None
        )

        # Check class suffix patterns
        class_suffix_patterns = [p for p in naming_patterns if p.name.startswith("class_suffix_")]

        # Validate function naming in Python files
        if ext in (".py",) and snake_case_pattern and snake_case_pattern.confidence > 0.7:
            # Find function definitions in added lines
            for line_num, line in changed_file.added_lines:
                match = re.match(r"^\s*def\s+(\w+)\s*\(", line)
                if match:
                    func_name = match.group(1)
                    # Skip dunder methods
                    if func_name.startswith("__") and func_name.endswith("__"):
                        continue
                    # Check if camelCase (has uppercase after first char, no underscores)
                    if (
                        any(c.isupper() for c in func_name[1:])
                        and "_" not in func_name
                        and not func_name[0].isupper()
                    ):
                        violations.append(
                            Violation(
                                file_path=changed_file.path,
                                line_start=line_num,
                                line_end=line_num,
                                severity=ViolationSeverity.WARNING,
                                rule="snake_case_functions",
                                message=f"Function '{func_name}' uses camelCase but codebase uses snake_case",
                                suggestion=f"Rename to '{self._to_snake_case(func_name)}'",
                                pattern_category="naming",
                            )
                        )

        # Validate class naming
        if ext in (".py",) and class_suffix_patterns:
            # Find most common class suffix pattern
            dominant_suffix = max(class_suffix_patterns, key=lambda p: p.frequency)
            suffix = dominant_suffix.name.replace("class_suffix_", "").title()

            for line_num, line in changed_file.added_lines:
                match = re.match(r"^\s*class\s+(\w+)\s*[:\(]", line)
                if match:
                    class_name = match.group(1)
                    # Check if class could benefit from suffix
                    # Only suggest for service/repository/controller like classes
                    if (
                        suffix.lower() in ("service", "repository", "controller", "handler")
                        and not class_name.endswith(suffix)
                        and any(
                            hint in class_name.lower()
                            for hint in ("service", "repo", "handler", "controller", "manager")
                        )
                    ):
                        violations.append(
                            Violation(
                                file_path=changed_file.path,
                                line_start=line_num,
                                line_end=line_num,
                                severity=ViolationSeverity.INFO,
                                rule=dominant_suffix.name,
                                message=f"Class '{class_name}' may benefit from '{suffix}' suffix",
                                suggestion=f"Consider renaming to '{class_name}{suffix}'",
                                pattern_category="naming",
                            )
                        )

        return violations

    def _check_architecture_patterns(self, changed_file: ChangedFile) -> list[Violation]:
        """Check architectural pattern violations."""
        violations: list[Violation] = []
        path = Path(changed_file.path)

        # Get architecture patterns
        arch_patterns = [p for p in self._patterns if p.category == PatternCategory.ARCHITECTURE]
        if not arch_patterns:
            return violations

        # Check service layer pattern - services shouldn't directly access databases
        service_pattern = next((p for p in arch_patterns if p.name == "service_layer"), None)
        repo_pattern = next((p for p in arch_patterns if p.name == "repository_pattern"), None)

        if service_pattern and repo_pattern and repo_pattern.frequency >= 3:
            # If file looks like a service
            if "service" in path.stem.lower():
                for line_num, line in changed_file.added_lines:
                    # Check for direct database/ORM access patterns
                    db_patterns = [
                        (r"\bSession\s*\(", "SQLAlchemy Session"),
                        (r"\.execute\s*\(", "direct SQL execution"),
                        (r"\bCursor\b", "database cursor"),
                        (r"\.query\s*\(", "direct query"),
                        (r"\bconnection\s*\.", "database connection"),
                    ]
                    for pattern, desc in db_patterns:
                        if re.search(pattern, line):
                            violations.append(
                                Violation(
                                    file_path=changed_file.path,
                                    line_start=line_num,
                                    line_end=line_num,
                                    severity=ViolationSeverity.WARNING,
                                    rule="service_layer",
                                    message=f"Service appears to use {desc} directly",
                                    suggestion="Consider using a repository for data access",
                                    pattern_category="architecture",
                                )
                            )
                            break  # One violation per line

        return violations

    def _check_testing_patterns(self, changed_file: ChangedFile) -> list[Violation]:
        """Check testing pattern violations."""
        violations: list[Violation] = []
        path = Path(changed_file.path)

        # Get testing patterns
        test_patterns = [p for p in self._patterns if p.category == PatternCategory.TESTING]
        if not test_patterns:
            return violations

        # Check if this is a test file
        is_test_file = any(
            kw in path.name.lower() for kw in ["test_", "_test", ".test.", ".spec."]
        ) or "/tests/" in str(path)

        if not is_test_file:
            return violations

        # Check test function naming
        test_func_pattern = next(
            (p for p in test_patterns if p.name == "test_function_naming"), None
        )

        if test_func_pattern and test_func_pattern.confidence > 0.8:
            for line_num, line in changed_file.added_lines:
                match = re.match(r"^\s*def\s+(\w+)\s*\(", line)
                if match:
                    func_name = match.group(1)
                    # Test functions should start with test_
                    if not func_name.startswith("test_") and not func_name.startswith("_"):
                        # But skip helper/fixture functions
                        if not any(
                            kw in func_name.lower()
                            for kw in ["setup", "teardown", "fixture", "helper", "mock"]
                        ):
                            violations.append(
                                Violation(
                                    file_path=changed_file.path,
                                    line_start=line_num,
                                    line_end=line_num,
                                    severity=ViolationSeverity.WARNING,
                                    rule="test_function_naming",
                                    message=f"Test function '{func_name}' doesn't follow test_ prefix convention",
                                    suggestion=f"Rename to 'test_{func_name}' or mark as helper",
                                    pattern_category="testing",
                                )
                            )

        return violations

    def _check_import_patterns(self, changed_file: ChangedFile) -> list[Violation]:
        """Check import organization violations."""
        violations: list[Violation] = []
        path = Path(changed_file.path)

        if path.suffix not in (".py",):
            return violations

        # Get import patterns
        import_patterns = [p for p in self._patterns if p.category == PatternCategory.IMPORTS]
        if not import_patterns:
            return violations

        # Check for import * usage
        for line_num, line in changed_file.added_lines:
            if re.match(r"^\s*from\s+\S+\s+import\s+\*", line):
                violations.append(
                    Violation(
                        file_path=changed_file.path,
                        line_start=line_num,
                        line_end=line_num,
                        severity=ViolationSeverity.WARNING,
                        rule="no_star_imports",
                        message="Star imports (import *) are discouraged",
                        suggestion="Import specific names instead",
                        pattern_category="imports",
                    )
                )

        return violations

    def _to_snake_case(self, name: str) -> str:
        """Convert camelCase to snake_case."""
        # Insert underscore before uppercase letters
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


__all__ = [
    "ChangeValidator",
    "ChangedFile",
    "ValidationResult",
    "Violation",
    "ViolationSeverity",
]
