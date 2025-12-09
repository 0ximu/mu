"""Proactive warning generation for code targets.

Provides warnings about potential issues BEFORE modification:
- High impact: Many dependents could break
- Stale: Code hasn't been touched in a long time
- Security: Contains auth/crypto/secrets logic
- No tests: No test coverage detected
- Complexity: High cyclomatic complexity
- Deprecated: Marked as deprecated
- Different owner: Different primary author

Usage:
    from mu.intelligence.warnings import ProactiveWarningGenerator
    from mu.kernel import MUbase

    db = MUbase(".mubase")
    generator = ProactiveWarningGenerator(db)

    result = generator.analyze("src/auth.py")
    for warning in result.warnings:
        print(f"[{warning.level}] {warning.category.value}: {warning.message}")
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mu.intelligence.models import (
    ProactiveWarning,
    WarningCategory,
    WarningsResult,
)

if TYPE_CHECKING:
    from mu.kernel import MUbase

logger = logging.getLogger(__name__)

# Thresholds for warning triggers
HIGH_IMPACT_THRESHOLD = 10  # >10 dependents = high impact
STALE_DAYS_WARN = 180  # 6 months
STALE_DAYS_ERROR = 365  # 1 year
COMPLEXITY_WARN = 20  # Cyclomatic complexity
COMPLEXITY_ERROR = 50

# Security-sensitive keywords
SECURITY_KEYWORDS = frozenset(
    {
        "auth",
        "authenticate",
        "authentication",
        "authorization",
        "authorize",
        "login",
        "logout",
        "password",
        "passwd",
        "credential",
        "token",
        "jwt",
        "oauth",
        "session",
        "cookie",
        "csrf",
        "xss",
        "encrypt",
        "decrypt",
        "crypto",
        "hash",
        "salt",
        "secret",
        "key",
        "private",
        "certificate",
        "ssl",
        "tls",
        "security",
        "permission",
        "role",
        "acl",
        "rbac",
    }
)

# Patterns indicating deprecation
DEPRECATION_PATTERNS = [
    r"@deprecated",
    r"@Deprecated",
    r"\bdeprecated\b",
    r"DEPRECATED",
    r"# deprecated",
    r"// deprecated",
    r"\* @deprecated",
]


@dataclass
class WarningConfig:
    """Configuration for proactive warning generation."""

    # Impact thresholds
    high_impact_threshold: int = HIGH_IMPACT_THRESHOLD

    # Staleness thresholds (days)
    stale_warn_days: int = STALE_DAYS_WARN
    stale_error_days: int = STALE_DAYS_ERROR

    # Complexity thresholds
    complexity_warn: int = COMPLEXITY_WARN
    complexity_error: int = COMPLEXITY_ERROR

    # Feature flags
    check_impact: bool = True
    check_staleness: bool = True
    check_security: bool = True
    check_tests: bool = True
    check_complexity: bool = True
    check_deprecated: bool = True

    # Git integration
    use_git_history: bool = True


class ProactiveWarningGenerator:
    """Generates proactive warnings for code targets before modification.

    Analyzes files and nodes to identify potential issues that should
    be considered before making changes.
    """

    def __init__(
        self,
        db: MUbase,
        config: WarningConfig | None = None,
        root_path: Path | None = None,
    ) -> None:
        """Initialize the warning generator.

        Args:
            db: MUbase database instance.
            config: Optional warning configuration.
            root_path: Optional root path for git operations.
        """
        self.db = db
        self.config = config or WarningConfig()
        self.root_path = root_path or Path.cwd()

    def analyze(self, target: str) -> WarningsResult:
        """Analyze a target and generate proactive warnings.

        Args:
            target: File path or node ID to analyze.

        Returns:
            WarningsResult with all detected warnings.
        """
        start_time = time.time()
        warnings: list[ProactiveWarning] = []

        # Determine target type and resolve to node(s)
        target_type, nodes, file_path = self._resolve_target(target)

        if not nodes and not file_path:
            raise ValueError(f"Target not found: {target}")

        # Run warning checks
        if self.config.check_impact:
            warnings.extend(self._check_impact(nodes))

        if self.config.check_staleness and file_path:
            warnings.extend(self._check_staleness(file_path))

        if self.config.check_security:
            warnings.extend(self._check_security(target, nodes, file_path))

        if self.config.check_tests and file_path:
            warnings.extend(self._check_tests(file_path, nodes))

        if self.config.check_complexity:
            warnings.extend(self._check_complexity(nodes))

        if self.config.check_deprecated and file_path:
            warnings.extend(self._check_deprecated(file_path))

        # Calculate risk score
        risk_score = self._calculate_risk_score(warnings)

        # Generate summary
        summary = self._generate_summary(warnings, target)

        analysis_time_ms = (time.time() - start_time) * 1000

        return WarningsResult(
            target=target,
            target_type=target_type,
            warnings=warnings,
            summary=summary,
            risk_score=risk_score,
            analysis_time_ms=analysis_time_ms,
        )

    def _resolve_target(self, target: str) -> tuple[str, list[Any], Path | None]:
        """Resolve a target string to nodes and file path.

        Returns:
            Tuple of (target_type, nodes, file_path)
        """
        nodes = []
        file_path = None
        target_type = "unknown"

        # Check if it's a file path
        if "/" in target or target.endswith((".py", ".ts", ".tsx", ".js", ".go", ".rs", ".java")):
            # Try to find the file
            candidate = self.root_path / target
            if candidate.exists():
                file_path = candidate
                target_type = "file"

                # Find the module node for this file
                rel_path = str(candidate.relative_to(self.root_path))
                module_id = f"mod:{rel_path}"
                module = self.db.get_node(module_id)
                if module:
                    nodes.append(module)

                    # Also get contained nodes
                    contained = self.db.get_children(module_id)
                    nodes.extend(contained)

        # Check if it's a node ID (mod:, cls:, fn:)
        if target.startswith(("mod:", "cls:", "fn:", "mth:")):
            node = self.db.get_node(target)
            if node:
                nodes = [node]
                target_type = target.split(":")[0]

                # Get file path from node
                if node.file_path:
                    file_path = self.root_path / node.file_path

        # Try name lookup
        if not nodes:
            found = self.db.find_by_name(target)
            if found:
                nodes = found
                target_type = str(nodes[0].type) if nodes else "unknown"

                if nodes and nodes[0].file_path:
                    file_path = self.root_path / nodes[0].file_path

        return target_type, nodes, file_path

    def _check_impact(self, nodes: list[Any]) -> list[ProactiveWarning]:
        """Check for high-impact targets with many dependents."""
        warnings = []

        for node in nodes:
            try:
                # Use graph to find dependents
                from mu.kernel.graph import GraphManager

                gm = GraphManager(self.db.conn)
                gm.load()

                if gm.has_node(node.id):
                    # Get all nodes that would be impacted
                    impacted = gm.impact(node.id)
                    dependent_count = len(impacted)

                    if dependent_count > self.config.high_impact_threshold:
                        level = (
                            "error"
                            if dependent_count > self.config.high_impact_threshold * 3
                            else "warn"
                        )
                        warnings.append(
                            ProactiveWarning(
                                category=WarningCategory.HIGH_IMPACT,
                                level=level,
                                message=f"{dependent_count} nodes depend on {node.name} - changes may have wide impact",
                                details={
                                    "dependent_count": dependent_count,
                                    "node_id": node.id,
                                    "node_name": node.name,
                                    "sample_dependents": impacted[:5],
                                },
                            )
                        )
            except Exception as e:
                logger.debug(f"Impact check failed for {node.id}: {e}")

        return warnings

    def _check_staleness(self, file_path: Path) -> list[ProactiveWarning]:
        """Check if the file hasn't been modified recently."""
        warnings: list[ProactiveWarning] = []

        if not self.config.use_git_history:
            return warnings

        try:
            # Get last modification date from git
            result = subprocess.run(
                ["git", "log", "-1", "--format=%ci", str(file_path)],
                capture_output=True,
                text=True,
                cwd=self.root_path,
                timeout=5,
            )

            if result.returncode == 0 and result.stdout.strip():
                last_modified_str = result.stdout.strip()
                # Parse git date format: 2024-01-15 10:30:00 +0000
                last_modified = datetime.strptime(
                    last_modified_str[:19], "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=UTC)

                now = datetime.now(UTC)
                days_since_modified = (now - last_modified).days

                if days_since_modified > self.config.stale_error_days:
                    warnings.append(
                        ProactiveWarning(
                            category=WarningCategory.STALE,
                            level="error",
                            message=f"File last modified {days_since_modified} days ago ({last_modified_str[:10]}) - may contain outdated patterns",
                            details={
                                "days_since_modified": days_since_modified,
                                "last_modified": last_modified_str[:10],
                            },
                        )
                    )
                elif days_since_modified > self.config.stale_warn_days:
                    warnings.append(
                        ProactiveWarning(
                            category=WarningCategory.STALE,
                            level="warn",
                            message=f"File last modified {days_since_modified} days ago - review for staleness",
                            details={
                                "days_since_modified": days_since_modified,
                                "last_modified": last_modified_str[:10],
                            },
                        )
                    )
        except Exception as e:
            logger.debug(f"Staleness check failed for {file_path}: {e}")

        return warnings

    def _check_security(
        self, target: str, nodes: list[Any], file_path: Path | None
    ) -> list[ProactiveWarning]:
        """Check if the target contains security-sensitive code."""
        warnings = []
        security_indicators: list[str] = []

        # Check node names
        for node in nodes:
            name_lower = node.name.lower()
            for keyword in SECURITY_KEYWORDS:
                if keyword in name_lower:
                    security_indicators.append(f"name contains '{keyword}'")
                    break

        # Check file path
        if file_path:
            path_lower = str(file_path).lower()
            for keyword in SECURITY_KEYWORDS:
                if keyword in path_lower:
                    security_indicators.append(f"path contains '{keyword}'")
                    break

        # Check file content for security-related imports/patterns
        if file_path and file_path.exists():
            try:
                content = file_path.read_text(errors="ignore")[:10000]  # First 10KB
                content_lower = content.lower()

                # Check for security library imports
                security_imports = [
                    "import hashlib",
                    "import hmac",
                    "import secrets",
                    "import ssl",
                    "from cryptography",
                    "import jwt",
                    "import bcrypt",
                    "import passlib",
                    "from oauth",
                    "import pyotp",
                ]
                for imp in security_imports:
                    if imp.lower() in content_lower:
                        security_indicators.append(f"imports {imp.split()[-1]}")

            except Exception as e:
                logger.debug(f"Could not read file {file_path}: {e}")

        if security_indicators:
            warnings.append(
                ProactiveWarning(
                    category=WarningCategory.SECURITY,
                    level="warn",
                    message="Security-sensitive code detected - extra review recommended",
                    details={
                        "indicators": security_indicators[:5],
                        "indicator_count": len(security_indicators),
                    },
                )
            )

        return warnings

    def _check_tests(self, file_path: Path, nodes: list[Any]) -> list[ProactiveWarning]:
        """Check if the target has associated tests."""
        warnings: list[ProactiveWarning] = []

        # Skip test files themselves (check filename, not full path)
        filename = file_path.name.lower()
        filename_upper = file_path.name  # Preserve case for C# check
        if (
            filename.startswith("test_")
            or filename.endswith(
                ("_test.py", ".test.py", ".spec.py", ".test.ts", ".spec.ts", "_test.go")
            )
            or "test" in filename.split("_")  # e.g., my_test_utils.py
            or filename_upper.endswith(
                ("Tests.cs", "Test.cs", "Tests.java", "Test.java")
            )  # C#/Java
        ):
            return warnings

        # Look for test files
        stem = file_path.stem
        suffix = file_path.suffix
        parent = file_path.parent

        # Build patterns based on file type for better relevance
        patterns: list[Path] = []
        patterns_tried: list[str] = []  # Human-readable pattern names

        # Detect language from suffix
        is_csharp = suffix.lower() == ".cs"
        is_java = suffix.lower() == ".java"
        is_python = suffix.lower() == ".py"
        is_js_ts = suffix.lower() in (".js", ".jsx", ".ts", ".tsx")
        is_go = suffix.lower() == ".go"

        # Find project root for top-level tests/ directory
        project_root = self._find_project_root(file_path)

        if is_csharp or is_java:
            # C# / Java style: FooTests.cs or FooTest.cs (prioritize first)
            patterns.extend(
                [
                    parent / f"{stem}Tests{suffix}",
                    parent / f"{stem}Test{suffix}",
                    parent.parent / "Tests" / f"{stem}Tests{suffix}",
                    parent.parent / "Tests" / f"{stem}Test{suffix}",
                    parent.parent.parent / "Tests" / f"{stem}Tests{suffix}",
                ]
            )
            patterns_tried.extend(
                [
                    f"{stem}Tests{suffix}",
                    f"{stem}Test{suffix}",
                    f"../Tests/{stem}Tests{suffix}",
                ]
            )

            # Also check for sibling *.Tests project directory (common .NET convention)
            # e.g., src/MyProject/Services/FooService.cs -> src/MyProject.Tests/Services/FooServiceTests.cs
            for ancestor in [parent.parent, parent.parent.parent, parent.parent.parent.parent]:
                if ancestor.exists():
                    for sibling in ancestor.iterdir():
                        if sibling.is_dir() and sibling.name.endswith(".Tests"):
                            # Try to mirror the path structure
                            try:
                                rel_path = file_path.relative_to(
                                    ancestor / sibling.name.replace(".Tests", "")
                                )
                                test_path = sibling / rel_path.parent / f"{stem}Tests{suffix}"
                                patterns.append(test_path)
                            except ValueError:
                                # Path not relative, try direct lookup
                                test_path = sibling / f"{stem}Tests{suffix}"
                                patterns.append(test_path)
                    break  # Only check one ancestor level for .Tests projects

        elif is_python:
            # Python style: test_foo.py or foo_test.py
            patterns.extend(
                [
                    parent / f"test_{stem}{suffix}",
                    parent / f"{stem}_test{suffix}",
                    parent / "tests" / f"test_{stem}{suffix}",
                    parent.parent / "tests" / f"test_{stem}{suffix}",
                    parent.parent / "tests" / "unit" / f"test_{stem}{suffix}",
                ]
            )
            patterns_tried.extend(
                [
                    f"test_{stem}{suffix}",
                    f"{stem}_test{suffix}",
                    f"tests/test_{stem}{suffix}",
                ]
            )

            # Add project-level tests/ directory patterns
            if project_root:
                tests_dir = project_root / "tests"
                if tests_dir.exists():
                    # Get module name from stem for matching (e.g., "server" from "server.py")
                    module_name = stem.lower()

                    # Common project-level test patterns
                    for test_subdir in ["", "unit", "integration"]:
                        test_base = tests_dir / test_subdir if test_subdir else tests_dir
                        if test_base.exists():
                            patterns.extend(
                                [
                                    test_base / f"test_{module_name}.py",
                                    test_base / f"test_{module_name}s.py",  # plural
                                ]
                            )

                            # Also check for tests named after parent module
                            # e.g., src/mu/mcp/server.py -> tests/unit/test_mcp.py
                            if parent.name != "mu" and parent.name != "src":
                                patterns.extend(
                                    [
                                        test_base / f"test_{parent.name}.py",
                                        test_base / f"test_{parent.name}s.py",
                                    ]
                                )

                    patterns_tried.extend(
                        [
                            f"tests/test_{module_name}.py",
                            f"tests/unit/test_{module_name}.py",
                        ]
                    )

        elif is_js_ts:
            # JS/TS style: foo.test.ts or foo.spec.ts
            patterns.extend(
                [
                    parent / f"{stem}.test{suffix}",
                    parent / f"{stem}.spec{suffix}",
                    parent / "__tests__" / f"{stem}{suffix}",
                    parent / "__tests__" / f"{stem}.test{suffix}",
                ]
            )
            patterns_tried.extend(
                [
                    f"{stem}.test{suffix}",
                    f"{stem}.spec{suffix}",
                    f"__tests__/{stem}{suffix}",
                ]
            )

        elif is_go:
            # Go style: foo_test.go (same directory)
            patterns.extend(
                [
                    parent / f"{stem}_test{suffix}",
                ]
            )
            patterns_tried.extend(
                [
                    f"{stem}_test{suffix}",
                ]
            )

        else:
            # Generic fallback - try common patterns
            patterns.extend(
                [
                    parent / f"test_{stem}{suffix}",
                    parent / f"{stem}_test{suffix}",
                    parent / f"{stem}Tests{suffix}",
                    parent / f"{stem}Test{suffix}",
                    parent / f"{stem}.test{suffix}",
                ]
            )
            patterns_tried.extend(
                [
                    f"test_{stem}{suffix}",
                    f"{stem}Tests{suffix}",
                ]
            )

        test_found = False
        for pattern in patterns:
            if pattern.exists():
                test_found = True
                break

        # If no test file found by pattern, check for imports in test files
        if not test_found and project_root and is_python:
            test_found = self._check_test_imports(file_path, nodes, project_root)

        if not test_found:
            # Check if there are any test imports referencing these nodes
            node_names = [n.name for n in nodes if n.name]

            warnings.append(
                ProactiveWarning(
                    category=WarningCategory.NO_TESTS,
                    level="warn",
                    message="No test file found - consider adding tests before modifying",
                    details={
                        "tried": patterns_tried[:3],
                        "node_names": node_names[:5],
                    },
                )
            )

        return warnings

    def _find_project_root(self, file_path: Path) -> Path | None:
        """Find project root by looking for pyproject.toml, setup.py, or .git."""
        current = file_path.parent
        for _ in range(10):  # Max 10 levels up
            if (current / "pyproject.toml").exists():
                return current
            if (current / "setup.py").exists():
                return current
            if (current / ".git").exists():
                return current
            if current.parent == current:
                break
            current = current.parent
        return None

    def _check_test_imports(self, file_path: Path, nodes: list[Any], project_root: Path) -> bool:
        """Check if any test file imports this module."""
        tests_dir = project_root / "tests"
        if not tests_dir.exists():
            return False

        # Get the module import path
        try:
            # Try relative to src/ first
            src_dir = project_root / "src"
            if src_dir.exists():
                try:
                    rel_path = file_path.relative_to(src_dir)
                    import_path = str(rel_path.with_suffix("")).replace("/", ".").replace("\\", ".")
                except ValueError:
                    # Not under src/, try relative to project root
                    rel_path = file_path.relative_to(project_root)
                    import_path = str(rel_path.with_suffix("")).replace("/", ".").replace("\\", ".")
            else:
                rel_path = file_path.relative_to(project_root)
                import_path = str(rel_path.with_suffix("")).replace("/", ".").replace("\\", ".")
        except ValueError:
            return False

        # Get node names for searching
        node_names = [n.name for n in nodes if n.name]

        # Search for imports in test files (limit depth to avoid scanning too many files)
        try:
            test_files = list(tests_dir.rglob("test_*.py"))[:50]  # Limit to 50 files
            for test_file in test_files:
                try:
                    content = test_file.read_text(errors="ignore")[:10000]  # First 10KB
                    # Check for import path
                    if import_path in content:
                        return True
                    # Check for any node name from the module
                    for name in node_names[:5]:
                        if f"from {import_path.rsplit('.', 1)[0]}" in content and name in content:
                            return True
                except Exception:
                    pass
        except Exception:
            pass

        return False

    def _check_complexity(self, nodes: list[Any]) -> list[ProactiveWarning]:
        """Check for high complexity nodes."""
        warnings = []

        for node in nodes:
            complexity = getattr(node, "complexity", 0) or 0

            if complexity > self.config.complexity_error:
                warnings.append(
                    ProactiveWarning(
                        category=WarningCategory.COMPLEXITY,
                        level="error",
                        message=f"Very high complexity ({complexity}) in {node.name} - consider refactoring before changes",
                        details={
                            "complexity": complexity,
                            "node_id": node.id,
                            "node_name": node.name,
                            "threshold": self.config.complexity_error,
                        },
                    )
                )
            elif complexity > self.config.complexity_warn:
                warnings.append(
                    ProactiveWarning(
                        category=WarningCategory.COMPLEXITY,
                        level="warn",
                        message=f"High complexity ({complexity}) in {node.name} - changes may be risky",
                        details={
                            "complexity": complexity,
                            "node_id": node.id,
                            "node_name": node.name,
                            "threshold": self.config.complexity_warn,
                        },
                    )
                )

        return warnings

    def _check_deprecated(self, file_path: Path) -> list[ProactiveWarning]:
        """Check if the target is marked as deprecated."""
        warnings: list[ProactiveWarning] = []

        if not file_path.exists():
            return warnings

        try:
            content = file_path.read_text(errors="ignore")[:5000]  # First 5KB

            for pattern in DEPRECATION_PATTERNS:
                if re.search(pattern, content, re.IGNORECASE):
                    warnings.append(
                        ProactiveWarning(
                            category=WarningCategory.DEPRECATED,
                            level="warn",
                            message="Target is marked as deprecated - avoid adding new functionality",
                            details={
                                "pattern_found": pattern,
                            },
                        )
                    )
                    break  # Only one deprecation warning needed

        except Exception as e:
            logger.debug(f"Deprecation check failed for {file_path}: {e}")

        return warnings

    def _calculate_risk_score(self, warnings: list[ProactiveWarning]) -> float:
        """Calculate overall risk score based on warnings.

        Returns:
            Risk score from 0.0 (safe) to 1.0 (high risk).
        """
        if not warnings:
            return 0.0

        # Weight by severity and category
        score = 0.0
        for w in warnings:
            # Level weights
            level_weight = {"error": 0.3, "warn": 0.15, "info": 0.05}.get(w.level, 0.1)

            # Category weights (some categories are riskier)
            category_weight = {
                WarningCategory.HIGH_IMPACT: 1.2,
                WarningCategory.SECURITY: 1.3,
                WarningCategory.COMPLEXITY: 1.1,
                WarningCategory.STALE: 0.9,
                WarningCategory.NO_TESTS: 0.8,
                WarningCategory.DEPRECATED: 0.7,
                WarningCategory.DIFFERENT_OWNER: 0.5,
            }.get(w.category, 1.0)

            score += level_weight * category_weight

        # Normalize to 0-1 range (cap at 1.0)
        return min(1.0, score)

    def _generate_summary(self, warnings: list[ProactiveWarning], target: str) -> str:
        """Generate a one-line summary of warnings."""
        if not warnings:
            return f"No warnings for {target}"

        error_count = sum(1 for w in warnings if w.level == "error")
        warn_count = sum(1 for w in warnings if w.level == "warn")
        info_count = sum(1 for w in warnings if w.level == "info")

        parts = []
        if error_count:
            parts.append(f"{error_count} error{'s' if error_count != 1 else ''}")
        if warn_count:
            parts.append(f"{warn_count} warning{'s' if warn_count != 1 else ''}")
        if info_count:
            parts.append(f"{info_count} info")

        # Add key categories mentioned
        categories = {w.category for w in warnings}
        key_categories = []
        if WarningCategory.HIGH_IMPACT in categories:
            key_categories.append("high-impact")
        if WarningCategory.SECURITY in categories:
            key_categories.append("security-sensitive")
        if WarningCategory.STALE in categories:
            key_categories.append("stale")

        summary = f"{', '.join(parts)}"
        if key_categories:
            summary += f" ({', '.join(key_categories)})"

        return summary


__all__ = [
    "ProactiveWarningGenerator",
    "WarningConfig",
]
