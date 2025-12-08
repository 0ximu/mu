"""Why Layer - Git history analysis for code rationale.

Answers "Why does this code exist?" by analyzing:
- Git commit messages for the node's introduction and modifications
- PR/issue references from commit messages
- Co-change context (what else changed together)
- Author information and ownership

Usage:
    from mu.intelligence.why import WhyAnalyzer
    from mu.kernel import MUbase

    db = MUbase(".mubase")
    analyzer = WhyAnalyzer(db, root_path=Path("."))

    result = analyzer.analyze("AuthService")
    print(result.origin_reason)  # Why code was created
    print(result.evolution_summary)  # How it evolved
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mu.kernel import MUbase

logger = logging.getLogger(__name__)

# Patterns for extracting issue/PR references from commit messages
ISSUE_PATTERNS = [
    r"#(\d+)",  # GitHub: #123
    r"(?:fixes?|closes?|resolves?)\s+#(\d+)",  # fixes #123
    r"([A-Z]+-\d+)",  # JIRA: PROJECT-123
    r"(?:issue|bug|ticket)\s*[:#]?\s*(\d+)",  # issue: 123
]

PR_PATTERNS = [
    r"merge\s+pull\s+request\s+#(\d+)",  # Merge pull request #123
    r"\(#(\d+)\)$",  # (trailing PR number) (#123)
    r"pr[:\s]+#?(\d+)",  # PR: 123 or pr #123
]


@dataclass
class CommitInfo:
    """Information about a git commit."""

    hash: str
    """Short commit hash."""

    full_hash: str
    """Full commit hash."""

    author: str
    """Author name."""

    author_email: str
    """Author email."""

    date: datetime
    """Commit date."""

    message: str
    """Commit message (first line)."""

    full_message: str
    """Full commit message."""

    files_changed: list[str] = field(default_factory=list)
    """Files changed in this commit."""

    issue_refs: list[str] = field(default_factory=list)
    """Issue/ticket references extracted from message."""

    pr_refs: list[str] = field(default_factory=list)
    """PR references extracted from message."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "hash": self.hash,
            "full_hash": self.full_hash,
            "author": self.author,
            "author_email": self.author_email,
            "date": self.date.isoformat() if self.date else None,
            "message": self.message,
            "full_message": self.full_message,
            "files_changed": self.files_changed,
            "issue_refs": self.issue_refs,
            "pr_refs": self.pr_refs,
        }


@dataclass
class WhyResult:
    """Result of why analysis for a code target."""

    target: str
    """The analyzed target (node name/ID or file path)."""

    target_type: str
    """Type of target: module, class, function, file."""

    file_path: str
    """Source file path."""

    line_start: int | None
    """Start line (for non-file targets)."""

    line_end: int | None
    """End line (for non-file targets)."""

    # Origin story
    origin_commit: CommitInfo | None = None
    """The commit that introduced this code."""

    origin_reason: str = ""
    """Why this code was created (extracted from commit)."""

    # Evolution
    total_commits: int = 0
    """Total number of commits touching this code."""

    recent_commits: list[CommitInfo] = field(default_factory=list)
    """Recent commits modifying this code."""

    evolution_summary: str = ""
    """Summary of how this code has evolved."""

    # Contributors
    primary_author: str = ""
    """Primary author (most commits)."""

    contributors: list[dict[str, Any]] = field(default_factory=list)
    """List of contributors with commit counts."""

    # References
    issue_refs: list[str] = field(default_factory=list)
    """All issue/ticket references found."""

    pr_refs: list[str] = field(default_factory=list)
    """All PR references found."""

    # Co-changes
    frequently_changed_with: list[str] = field(default_factory=list)
    """Files that frequently change together with this target."""

    # Metadata
    analysis_time_ms: float = 0.0
    """Time taken for analysis."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "target": self.target,
            "target_type": self.target_type,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "origin_commit": self.origin_commit.to_dict() if self.origin_commit else None,
            "origin_reason": self.origin_reason,
            "total_commits": self.total_commits,
            "recent_commits": [c.to_dict() for c in self.recent_commits],
            "evolution_summary": self.evolution_summary,
            "primary_author": self.primary_author,
            "contributors": self.contributors,
            "issue_refs": self.issue_refs,
            "pr_refs": self.pr_refs,
            "frequently_changed_with": self.frequently_changed_with,
            "analysis_time_ms": round(self.analysis_time_ms, 2),
        }


class WhyAnalyzer:
    """Analyzes git history to answer "Why does this code exist?"

    Provides context about code origin, evolution, and rationale by
    examining commit history, messages, and co-change patterns.
    """

    def __init__(
        self,
        db: MUbase | None = None,
        root_path: Path | None = None,
    ) -> None:
        """Initialize the analyzer.

        Args:
            db: Optional MUbase database instance.
            root_path: Root path for git operations (default: cwd).
        """
        self.db = db
        self.root_path = root_path or Path.cwd()

    def analyze(
        self,
        target: str,
        max_commits: int = 20,
        include_cochanges: bool = True,
    ) -> WhyResult:
        """Analyze why a code target exists.

        Args:
            target: Node name/ID, file path, or file:line_start-line_end
            max_commits: Maximum commits to analyze (default 20)
            include_cochanges: Include co-change analysis (slower)

        Returns:
            WhyResult with origin, evolution, and context information.
        """
        start_time = time.time()

        # Resolve target to file and optional line range
        file_path, line_start, line_end, target_type = self._resolve_target(target)

        if not file_path:
            return WhyResult(
                target=target,
                target_type="unknown",
                file_path="",
                line_start=None,
                line_end=None,
                origin_reason=f"Target not found: {target}",
                analysis_time_ms=(time.time() - start_time) * 1000,
            )

        # Get git log for the file/lines
        commits = self._get_commits(file_path, line_start, line_end, max_commits)

        if not commits:
            return WhyResult(
                target=target,
                target_type=target_type,
                file_path=str(file_path),
                line_start=line_start,
                line_end=line_end,
                origin_reason="No git history found (file may be untracked or new)",
                analysis_time_ms=(time.time() - start_time) * 1000,
            )

        # Extract issue and PR references
        all_issue_refs: set[str] = set()
        all_pr_refs: set[str] = set()
        for commit in commits:
            all_issue_refs.update(commit.issue_refs)
            all_pr_refs.update(commit.pr_refs)

        # Identify origin commit (first commit that introduced this code)
        origin_commit = commits[-1] if commits else None

        # Analyze contributors
        contributors = self._analyze_contributors(commits)
        primary_author = contributors[0]["author"] if contributors else ""

        # Generate origin reason
        origin_reason = self._generate_origin_reason(origin_commit, all_issue_refs)

        # Generate evolution summary
        evolution_summary = self._generate_evolution_summary(commits, contributors)

        # Co-change analysis (optional, slower)
        frequently_changed_with: list[str] = []
        if include_cochanges and len(commits) >= 2:
            frequently_changed_with = self._analyze_cochanges(
                file_path, commits, max_cochanges=5
            )

        analysis_time_ms = (time.time() - start_time) * 1000

        return WhyResult(
            target=target,
            target_type=target_type,
            file_path=str(file_path),
            line_start=line_start,
            line_end=line_end,
            origin_commit=origin_commit,
            origin_reason=origin_reason,
            total_commits=len(commits),
            recent_commits=commits[:5],  # Return only 5 most recent
            evolution_summary=evolution_summary,
            primary_author=primary_author,
            contributors=contributors,
            issue_refs=sorted(all_issue_refs),
            pr_refs=sorted(all_pr_refs),
            frequently_changed_with=frequently_changed_with,
            analysis_time_ms=analysis_time_ms,
        )

    def _resolve_target(
        self, target: str
    ) -> tuple[Path | None, int | None, int | None, str]:
        """Resolve a target string to file path and optional line range.

        Args:
            target: Node name/ID, file path, or file:line_start-line_end

        Returns:
            Tuple of (file_path, line_start, line_end, target_type)
        """
        # Check for file:line_start-line_end format
        if ":" in target and "-" in target.split(":")[-1]:
            parts = target.rsplit(":", 1)
            if len(parts) == 2:
                file_part = parts[0]
                line_part = parts[1]
                if "-" in line_part:
                    try:
                        start, end = line_part.split("-")
                        line_start = int(start)
                        line_end = int(end)
                        file_path = self.root_path / file_part
                        if file_path.exists():
                            return file_path, line_start, line_end, "lines"
                    except ValueError:
                        pass

        # Check if it's a file path
        if "/" in target or target.endswith(
            (".py", ".ts", ".tsx", ".js", ".go", ".rs", ".java")
        ):
            file_path = self.root_path / target
            if file_path.exists():
                return file_path, None, None, "file"

        # Check if it's a node ID (mod:, cls:, fn:)
        if self.db and target.startswith(("mod:", "cls:", "fn:", "mth:")):
            node = self.db.get_node(target)
            if node and node.file_path:
                file_path = self.root_path / node.file_path
                target_type = target.split(":")[0]
                return (
                    file_path,
                    node.line_start,
                    node.line_end,
                    target_type,
                )

        # Try name lookup in database
        if self.db:
            nodes = self.db.find_by_name(target)
            if not nodes:
                nodes = self.db.find_by_name(f"%{target}%")

            if nodes:
                node = nodes[0]
                if node.file_path:
                    file_path = self.root_path / node.file_path
                    target_type = str(node.type) if hasattr(node, "type") else "node"
                    return (
                        file_path,
                        node.line_start,
                        node.line_end,
                        target_type,
                    )

        return None, None, None, "unknown"

    def _get_commits(
        self,
        file_path: Path,
        line_start: int | None,
        line_end: int | None,
        max_commits: int,
    ) -> list[CommitInfo]:
        """Get git commits for a file or line range.

        Args:
            file_path: Path to the file
            line_start: Optional start line
            line_end: Optional end line
            max_commits: Maximum commits to retrieve

        Returns:
            List of CommitInfo objects, most recent first.
        """
        try:
            # Build git log command
            cmd = [
                "git",
                "log",
                f"-{max_commits}",
                "--format=%H%x00%h%x00%an%x00%ae%x00%aI%x00%s%x00%b%x1e",
                "--follow",  # Follow renames
            ]

            # Add line range if specified (git blame -L style)
            if line_start and line_end:
                cmd.extend([f"-L{line_start},{line_end}:{file_path}"])
            else:
                cmd.append("--")
                cmd.append(str(file_path))

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.root_path,
                timeout=30,
            )

            if result.returncode != 0:
                logger.debug(f"git log failed: {result.stderr}")
                return []

            # Parse commit records (separated by \x1e)
            commits = []
            records = result.stdout.strip().split("\x1e")

            for record in records:
                record = record.strip()
                if not record:
                    continue

                # Parse fields (separated by \x00)
                fields = record.split("\x00")
                if len(fields) < 6:
                    continue

                full_hash = fields[0]
                short_hash = fields[1]
                author = fields[2]
                author_email = fields[3]
                date_str = fields[4]
                subject = fields[5]
                body = fields[6] if len(fields) > 6 else ""

                # Parse date
                try:
                    commit_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except ValueError:
                    commit_date = datetime.now()

                # Extract references from commit message
                full_message = f"{subject}\n\n{body}".strip()
                issue_refs = self._extract_issue_refs(full_message)
                pr_refs = self._extract_pr_refs(full_message)

                # Get files changed in this commit
                files_changed = self._get_commit_files(full_hash)

                commits.append(
                    CommitInfo(
                        hash=short_hash,
                        full_hash=full_hash,
                        author=author,
                        author_email=author_email,
                        date=commit_date,
                        message=subject,
                        full_message=full_message,
                        files_changed=files_changed,
                        issue_refs=issue_refs,
                        pr_refs=pr_refs,
                    )
                )

            return commits

        except subprocess.TimeoutExpired:
            logger.warning(f"git log timed out for {file_path}")
            return []
        except Exception as e:
            logger.debug(f"Failed to get commits: {e}")
            return []

    def _get_commit_files(self, commit_hash: str) -> list[str]:
        """Get list of files changed in a commit."""
        try:
            result = subprocess.run(
                ["git", "show", "--name-only", "--format=", commit_hash],
                capture_output=True,
                text=True,
                cwd=self.root_path,
                timeout=5,
            )
            if result.returncode == 0:
                return [f for f in result.stdout.strip().split("\n") if f]
        except Exception:
            pass
        return []

    def _extract_issue_refs(self, message: str) -> list[str]:
        """Extract issue/ticket references from a commit message."""
        refs = []
        for pattern in ISSUE_PATTERNS:
            matches = re.findall(pattern, message, re.IGNORECASE)
            refs.extend(matches)
        return list(set(refs))

    def _extract_pr_refs(self, message: str) -> list[str]:
        """Extract PR references from a commit message."""
        refs = []
        for pattern in PR_PATTERNS:
            matches = re.findall(pattern, message, re.IGNORECASE)
            refs.extend(matches)
        return list(set(refs))

    def _analyze_contributors(
        self, commits: list[CommitInfo]
    ) -> list[dict[str, Any]]:
        """Analyze contributors from commits.

        Returns:
            List of contributors sorted by commit count.
        """
        author_counts: dict[str, int] = {}
        author_emails: dict[str, str] = {}

        for commit in commits:
            author = commit.author
            author_counts[author] = author_counts.get(author, 0) + 1
            author_emails[author] = commit.author_email

        contributors = [
            {
                "author": author,
                "email": author_emails[author],
                "commits": count,
                "percentage": round(count / len(commits) * 100, 1) if commits else 0,
            }
            for author, count in author_counts.items()
        ]

        return sorted(contributors, key=lambda x: x["commits"], reverse=True)

    def _generate_origin_reason(
        self,
        origin_commit: CommitInfo | None,
        issue_refs: set[str],
    ) -> str:
        """Generate a reason for why this code was created."""
        if not origin_commit:
            return "Origin unknown"

        parts = []

        # Date context
        if origin_commit.date:
            date_str = origin_commit.date.strftime("%Y-%m-%d")
            parts.append(f"Created on {date_str}")

        # Author
        parts.append(f"by {origin_commit.author}")

        # Commit message reason
        message = origin_commit.message
        if message:
            # Clean up common prefixes
            message = re.sub(r"^(feat|fix|chore|refactor|docs|test|style)(\(.+\))?:\s*", "", message)
            parts.append(f": \"{message}\"")

        # Issue references
        if issue_refs:
            refs_str = ", ".join(sorted(issue_refs)[:3])
            parts.append(f" (refs: {refs_str})")

        return "".join(parts)

    def _generate_evolution_summary(
        self,
        commits: list[CommitInfo],
        contributors: list[dict[str, Any]],
    ) -> str:
        """Generate a summary of how the code has evolved."""
        if not commits:
            return "No evolution data available"

        parts = []

        # Commit count
        parts.append(f"{len(commits)} commits")

        # Time span
        if len(commits) >= 2:
            newest = commits[0].date
            oldest = commits[-1].date
            if newest and oldest:
                days = (newest - oldest).days
                if days > 365:
                    parts.append(f"over {days // 365} year(s)")
                elif days > 30:
                    parts.append(f"over {days // 30} month(s)")
                else:
                    parts.append(f"over {days} days")

        # Contributors
        if len(contributors) == 1:
            parts.append(f"by {contributors[0]['author']}")
        elif len(contributors) > 1:
            parts.append(f"by {len(contributors)} contributors")

        # Most recent activity
        if commits:
            recent = commits[0]
            if recent.date:
                days_ago = (datetime.now(recent.date.tzinfo) - recent.date).days
                if days_ago == 0:
                    parts.append("(modified today)")
                elif days_ago == 1:
                    parts.append("(modified yesterday)")
                elif days_ago < 30:
                    parts.append(f"(modified {days_ago} days ago)")
                elif days_ago < 365:
                    parts.append(f"(modified {days_ago // 30} months ago)")
                else:
                    parts.append(f"(modified {days_ago // 365} years ago)")

        return " ".join(parts)

    def _analyze_cochanges(
        self,
        file_path: Path,
        commits: list[CommitInfo],
        max_cochanges: int = 5,
    ) -> list[str]:
        """Analyze which files frequently change together with this file.

        Returns:
            List of file paths that frequently change together.
        """
        # Count co-occurrences
        cochange_counts: dict[str, int] = {}
        target_file = str(file_path.relative_to(self.root_path))

        for commit in commits:
            for changed_file in commit.files_changed:
                if changed_file != target_file:
                    cochange_counts[changed_file] = cochange_counts.get(changed_file, 0) + 1

        # Sort by frequency and filter out low-frequency
        min_count = max(2, len(commits) // 5)  # At least 20% co-occurrence
        frequent = [
            (f, count)
            for f, count in cochange_counts.items()
            if count >= min_count
        ]
        frequent.sort(key=lambda x: x[1], reverse=True)

        return [f for f, _ in frequent[:max_cochanges]]


__all__ = [
    "CommitInfo",
    "WhyAnalyzer",
    "WhyResult",
]
