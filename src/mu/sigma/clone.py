"""Repository cloning for MU-SIGMA.

Handles shallow cloning and cleanup of GitHub repositories.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from mu.sigma.models import CloneResult, RepoInfo

logger = logging.getLogger(__name__)

# Valid GitHub URL patterns (https only for safety)
GITHUB_URL_PATTERN = re.compile(r"^https://github\.com/[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+(?:\.git)?$")


def validate_clone_url(url: str) -> bool:
    """Validate that URL is a safe GitHub clone URL.

    Only allows HTTPS GitHub URLs to prevent command injection
    and other security issues with arbitrary URLs.

    Args:
        url: The URL to validate

    Returns:
        True if URL is valid GitHub HTTPS URL
    """
    return bool(GITHUB_URL_PATTERN.match(url))


def clone_repo(
    repo: RepoInfo,
    target_dir: Path,
    depth: int = 1,
    timeout_seconds: int = 120,
) -> CloneResult:
    """Shallow clone a repository.

    Args:
        repo: Repository information
        target_dir: Directory to clone into
        depth: Git clone depth (1 for shallow)
        timeout_seconds: Timeout for clone operation

    Returns:
        CloneResult with success status and local path
    """
    # Validate URL before any operations
    if not validate_clone_url(repo.url):
        return CloneResult(
            repo_name=repo.name,
            local_path=None,
            success=False,
            error=f"Invalid or unsafe clone URL: {repo.url}",
        )

    # Use sanitized repo name for local path
    safe_name = repo.name.replace("/", "__")
    local_path = target_dir / safe_name

    # Clean up if exists
    if local_path.exists():
        shutil.rmtree(local_path)

    try:
        target_dir.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                str(depth),
                "--single-branch",
                repo.url,
                str(local_path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )

        if result.returncode != 0:
            return CloneResult(
                repo_name=repo.name,
                local_path=None,
                success=False,
                error=result.stderr.strip() or "Clone failed with no error message",
            )

        return CloneResult(
            repo_name=repo.name,
            local_path=local_path,
            success=True,
        )

    except subprocess.TimeoutExpired:
        # Clean up partial clone
        if local_path.exists():
            shutil.rmtree(local_path, ignore_errors=True)
        return CloneResult(
            repo_name=repo.name,
            local_path=None,
            success=False,
            error=f"Clone timed out after {timeout_seconds}s",
        )
    except Exception as e:
        # Clean up on any error
        if local_path.exists():
            shutil.rmtree(local_path, ignore_errors=True)
        return CloneResult(
            repo_name=repo.name,
            local_path=None,
            success=False,
            error=str(e),
        )


def cleanup_clone(clone_result: CloneResult) -> None:
    """Remove cloned repository.

    Args:
        clone_result: Result from clone_repo
    """
    if clone_result.local_path and clone_result.local_path.exists():
        try:
            shutil.rmtree(clone_result.local_path)
            logger.debug(f"Cleaned up clone: {clone_result.local_path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup {clone_result.local_path}: {e}")


@contextmanager
def cloned_repo(
    repo: RepoInfo,
    target_dir: Path,
    cleanup: bool = True,
) -> Iterator[CloneResult]:
    """Context manager that clones and auto-cleans.

    Args:
        repo: Repository to clone
        target_dir: Directory to clone into
        cleanup: Whether to cleanup on exit (default True)

    Yields:
        CloneResult with clone status

    Example:
        with cloned_repo(repo, Path("/tmp")) as result:
            if result.success:
                process(result.local_path)
        # Clone is automatically cleaned up
    """
    result = clone_repo(repo, target_dir)
    try:
        yield result
    finally:
        if cleanup:
            cleanup_clone(result)


def get_clone_size_mb(clone_result: CloneResult) -> float:
    """Get size of cloned repo in MB."""
    if not clone_result.local_path or not clone_result.local_path.exists():
        return 0.0

    total_size = 0
    for path in clone_result.local_path.rglob("*"):
        if path.is_file():
            total_size += path.stat().st_size

    return total_size / (1024 * 1024)
