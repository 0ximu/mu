"""Git utilities for semantic diff - worktree management for branch comparison."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


class GitError(Exception):
    """Error during git operations."""

    pass


@dataclass
class GitRef:
    """A git reference (branch, commit, tag)."""

    ref: str
    commit_hash: str
    is_branch: bool = False
    is_tag: bool = False

    @property
    def short_hash(self) -> str:
        return self.commit_hash[:8]


def run_git(args: list[str], cwd: Path | None = None) -> str:
    """Run a git command and return output."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise GitError(f"Git command failed: git {' '.join(args)}\n{e.stderr}")


def resolve_ref(ref: str, repo_path: Path) -> GitRef:
    """Resolve a git reference to its commit hash."""
    # Get the commit hash
    try:
        commit_hash = run_git(["rev-parse", ref], cwd=repo_path)
    except GitError:
        raise GitError(f"Could not resolve git reference: {ref}")

    # Check if it's a branch
    is_branch = False
    try:
        run_git(["show-ref", "--verify", f"refs/heads/{ref}"], cwd=repo_path)
        is_branch = True
    except GitError:
        pass

    # Check if it's a tag
    is_tag = False
    try:
        run_git(["show-ref", "--verify", f"refs/tags/{ref}"], cwd=repo_path)
        is_tag = True
    except GitError:
        pass

    return GitRef(
        ref=ref,
        commit_hash=commit_hash,
        is_branch=is_branch,
        is_tag=is_tag,
    )


def get_repo_root(path: Path) -> Path:
    """Get the git repository root for a path."""
    try:
        root = run_git(["rev-parse", "--show-toplevel"], cwd=path)
        return Path(root)
    except GitError:
        raise GitError(f"Not a git repository: {path}")


def is_clean_worktree(repo_path: Path) -> bool:
    """Check if the working tree is clean (no uncommitted changes)."""
    try:
        status = run_git(["status", "--porcelain"], cwd=repo_path)
        return len(status) == 0
    except GitError:
        return False


class GitWorktreeManager:
    """Manages temporary git worktrees for comparing different versions.

    Uses git worktree to efficiently checkout different versions without
    modifying the main working directory.
    """

    def __init__(self, repo_path: Path):
        """Initialize with the path to a git repository.

        Args:
            repo_path: Path to any directory within a git repository.
        """
        self.repo_root = get_repo_root(repo_path)
        self._temp_dir: Path | None = None
        self._worktrees: list[Path] = []

    @contextmanager
    def checkout(self, ref: str) -> Iterator[Path]:
        """Checkout a git ref into a temporary worktree.

        Args:
            ref: Git reference (branch, commit, tag) to checkout.

        Yields:
            Path to the temporary worktree directory.

        Example:
            with manager.checkout("main") as main_path:
                # main_path contains the codebase at "main"
                scan_result = scan_codebase(main_path)
        """
        # Resolve the ref first
        git_ref = resolve_ref(ref, self.repo_root)

        # Create temp directory if needed
        if self._temp_dir is None:
            self._temp_dir = Path(tempfile.mkdtemp(prefix="mu-diff-"))

        # Create worktree path
        worktree_path = self._temp_dir / f"worktree-{git_ref.short_hash}"

        try:
            # Add worktree
            run_git(
                ["worktree", "add", "--detach", str(worktree_path), git_ref.commit_hash],
                cwd=self.repo_root,
            )
            self._worktrees.append(worktree_path)

            yield worktree_path

        finally:
            # Clean up worktree
            self._cleanup_worktree(worktree_path)

    def _cleanup_worktree(self, worktree_path: Path) -> None:
        """Remove a worktree."""
        if worktree_path in self._worktrees:
            self._worktrees.remove(worktree_path)

        try:
            # Remove worktree from git
            run_git(["worktree", "remove", "--force", str(worktree_path)], cwd=self.repo_root)
        except GitError:
            # Force cleanup if git worktree remove fails
            if worktree_path.exists():
                shutil.rmtree(worktree_path, ignore_errors=True)

    def cleanup(self) -> None:
        """Clean up all temporary worktrees."""
        for worktree in list(self._worktrees):
            self._cleanup_worktree(worktree)

        if self._temp_dir and self._temp_dir.exists():
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None

    def __enter__(self) -> "GitWorktreeManager":
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: object) -> None:
        self.cleanup()


@contextmanager
def compare_refs(
    repo_path: Path,
    base_ref: str,
    target_ref: str,
) -> Iterator[tuple[Path, Path, GitRef, GitRef]]:
    """Context manager to checkout two refs for comparison.

    Args:
        repo_path: Path to the git repository.
        base_ref: Base git reference (older version).
        target_ref: Target git reference (newer version).

    Yields:
        Tuple of (base_path, target_path, base_git_ref, target_git_ref)

    Example:
        with compare_refs(Path("."), "main", "feature-branch") as (base, target, base_ref, target_ref):
            base_modules = parse_codebase(base)
            target_modules = parse_codebase(target)
            diff = compute_diff(base_modules, target_modules)
    """
    base_git_ref = resolve_ref(base_ref, repo_path)
    target_git_ref = resolve_ref(target_ref, repo_path)

    with GitWorktreeManager(repo_path) as manager:
        with manager.checkout(base_ref) as base_path:
            with manager.checkout(target_ref) as target_path:
                yield base_path, target_path, base_git_ref, target_git_ref
