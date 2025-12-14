"""Git integration for temporal layer.

Provides git operations for commit history, file changes, and repository management.
"""

from __future__ import annotations

import subprocess
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


class GitError(Exception):
    """Error during git operations."""

    pass


@dataclass
class CommitInfo:
    """Information about a git commit."""

    hash: str
    message: str
    author: str
    date: datetime

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "hash": self.hash,
            "message": self.message,
            "author": self.author,
            "date": self.date.isoformat() if self.date else None,
        }

    @property
    def short_hash(self) -> str:
        """Get abbreviated commit hash."""
        return self.hash[:8] if self.hash else ""


class GitIntegration:
    """Interface with git for history operations.

    Provides methods to get commit info, list commits, and detect file changes.
    All git commands use subprocess with list arguments (never shell=True)
    to prevent command injection.
    """

    def __init__(self, repo_path: Path) -> None:
        """Initialize git integration.

        Args:
            repo_path: Path to the git repository (or any subdirectory).

        Raises:
            GitError: If the path is not within a git repository.
        """
        self.repo_path = repo_path.resolve()
        self._repo_root: Path | None = None
        self._is_shallow: bool | None = None

        # Validate this is a git repo
        try:
            self._repo_root = self._get_repo_root()
        except GitError as e:
            raise GitError(f"Not a git repository: {repo_path}") from e

    def _run_git(
        self,
        args: list[str],
        cwd: Path | None = None,
        check: bool = True,
    ) -> str:
        """Run a git command and return output.

        Args:
            args: Git command arguments (without 'git' prefix).
            cwd: Working directory for the command.
            check: Whether to raise on non-zero exit code.

        Returns:
            Command stdout as string.

        Raises:
            GitError: If command fails and check is True.
        """
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=cwd or self._repo_root or self.repo_path,
                capture_output=True,
                text=True,
                check=check,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise GitError(f"Git command failed: git {' '.join(args)}\n{e.stderr}") from e
        except FileNotFoundError as e:
            raise GitError("Git is not installed or not in PATH") from e

    def _get_repo_root(self) -> Path:
        """Get the git repository root."""
        root = self._run_git(["rev-parse", "--show-toplevel"])
        return Path(root)

    @property
    def repo_root(self) -> Path:
        """Get the repository root directory."""
        if self._repo_root is None:
            self._repo_root = self._get_repo_root()
        return self._repo_root

    @property
    def is_shallow(self) -> bool:
        """Check if this is a shallow clone."""
        if self._is_shallow is None:
            try:
                result = self._run_git(
                    ["rev-parse", "--is-shallow-repository"],
                    check=False,
                )
                self._is_shallow = result.lower() == "true"
            except GitError:
                self._is_shallow = False
        return self._is_shallow

    def get_current_commit(self) -> str:
        """Get the current HEAD commit hash.

        Returns:
            Full commit hash of HEAD.

        Raises:
            GitError: If unable to get HEAD commit.
        """
        return self._run_git(["rev-parse", "HEAD"])

    def get_commit_info(self, commit_hash: str) -> CommitInfo:
        """Get detailed information about a commit.

        Args:
            commit_hash: Full or abbreviated commit hash.

        Returns:
            CommitInfo with message, author, and date.

        Raises:
            GitError: If commit doesn't exist.
        """
        # Get commit info in a parseable format
        # Format: hash%x00message%x00author%x00date
        format_str = "%H%x00%s%x00%an%x00%aI"
        output = self._run_git(["show", "-s", f"--format={format_str}", commit_hash])

        parts = output.split("\x00")
        if len(parts) < 4:
            raise GitError(f"Failed to parse commit info: {commit_hash}")

        try:
            date = datetime.fromisoformat(parts[3])
        except (ValueError, TypeError):
            date = datetime.now()

        return CommitInfo(
            hash=parts[0],
            message=parts[1],
            author=parts[2],
            date=date,
        )

    def get_commits(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        path: str | None = None,
        limit: int | None = None,
    ) -> list[str]:
        """Get list of commit hashes matching criteria.

        Args:
            since: Only commits after this date.
            until: Only commits before this date.
            path: Only commits affecting this path.
            limit: Maximum number of commits to return.

        Returns:
            List of commit hashes in reverse chronological order.

        Note:
            For shallow clones, results may be incomplete. A warning is issued.
        """
        if self.is_shallow:
            warnings.warn(
                "Repository is a shallow clone. Commit history may be incomplete.",
                UserWarning,
                stacklevel=2,
            )

        args = ["log", "--format=%H"]

        if since:
            args.append(f"--since={since.isoformat()}")
        if until:
            args.append(f"--until={until.isoformat()}")
        if limit:
            args.append(f"-{limit}")
        if path:
            args.extend(["--", path])

        try:
            output = self._run_git(args)
            if not output:
                return []
            return output.split("\n")
        except GitError:
            return []

    def get_changed_files(
        self,
        from_commit: str,
        to_commit: str,
    ) -> tuple[list[str], list[str], list[str]]:
        """Get files changed between two commits.

        Args:
            from_commit: Base commit hash.
            to_commit: Target commit hash.

        Returns:
            Tuple of (added, modified, deleted) file lists.
        """
        # Use diff-tree to get changed files with status
        output = self._run_git(
            [
                "diff-tree",
                "-r",
                "--name-status",
                "--no-commit-id",
                from_commit,
                to_commit,
            ]
        )

        added: list[str] = []
        modified: list[str] = []
        deleted: list[str] = []

        if not output:
            return added, modified, deleted

        for line in output.split("\n"):
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) < 2:
                continue

            status, filepath = parts[0], parts[1]
            if status.startswith("A"):
                added.append(filepath)
            elif status.startswith("M"):
                modified.append(filepath)
            elif status.startswith("D"):
                deleted.append(filepath)
            elif status.startswith("R"):
                # Renamed: line format is "R100\told_path\tnew_path"
                # Treat as delete old + add new
                rename_parts = line.split("\t")
                if len(rename_parts) >= 3:
                    deleted.append(rename_parts[1])
                    added.append(rename_parts[2])

        return added, modified, deleted

    def get_file_at_commit(
        self,
        filepath: str,
        commit_hash: str,
    ) -> str | None:
        """Get file contents at a specific commit.

        Args:
            filepath: Path relative to repo root.
            commit_hash: Commit to retrieve file from.

        Returns:
            File contents as string, or None if file doesn't exist.
        """
        try:
            return self._run_git(["show", f"{commit_hash}:{filepath}"])
        except GitError:
            return None

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        """Check if one commit is an ancestor of another.

        Args:
            ancestor: Potential ancestor commit.
            descendant: Potential descendant commit.

        Returns:
            True if ancestor is an ancestor of descendant.
        """
        try:
            self._run_git(["merge-base", "--is-ancestor", ancestor, descendant])
            return True
        except GitError:
            return False

    def get_parent_commit(self, commit_hash: str) -> str | None:
        """Get the first parent of a commit.

        Args:
            commit_hash: Commit to get parent for.

        Returns:
            Parent commit hash, or None if no parent (initial commit).
        """
        try:
            output = self._run_git(["rev-parse", f"{commit_hash}^"])
            return output if output else None
        except GitError:
            return None

    def get_common_ancestor(self, commit1: str, commit2: str) -> str | None:
        """Get the merge-base (common ancestor) of two commits.

        Args:
            commit1: First commit.
            commit2: Second commit.

        Returns:
            Common ancestor commit hash, or None if none exists.
        """
        try:
            return self._run_git(["merge-base", commit1, commit2])
        except GitError:
            return None

    def resolve_ref(self, ref: str) -> str:
        """Resolve a git reference to a commit hash.

        Args:
            ref: Branch name, tag, or commit hash.

        Returns:
            Full commit hash.

        Raises:
            GitError: If reference cannot be resolved.
        """
        try:
            return self._run_git(["rev-parse", ref])
        except GitError as e:
            raise GitError(f"Cannot resolve git reference: {ref}") from e

    def is_valid_repo(self) -> bool:
        """Check if the repository is valid and accessible.

        Returns:
            True if repo is valid, False otherwise.
        """
        try:
            self._run_git(["rev-parse", "--git-dir"])
            return True
        except GitError:
            return False


__all__ = [
    "GitError",
    "CommitInfo",
    "GitIntegration",
]
