"""GitHub repository fetching for MU-SIGMA.

Fetches top repositories by stars using the GitHub Search API.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from mu.sigma.config import SigmaConfig
from mu.sigma.models import RepoInfo

logger = logging.getLogger(__name__)

# Suppress verbose httpx logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

GITHUB_API_URL = "https://api.github.com"
DEFAULT_TIMEOUT = 30.0


class GitHubClient:
    """Async client for GitHub API."""

    def __init__(self, token: str | None = None, timeout: float = DEFAULT_TIMEOUT):
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> GitHubClient:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "MU-SIGMA/0.1",
        }
        if self.token:
            headers["Authorization"] = f"token {self.token}"

        self._client = httpx.AsyncClient(
            base_url=GITHUB_API_URL,
            headers=headers,
            timeout=httpx.Timeout(self.timeout),
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()

    async def search_repos(
        self,
        language: str,
        min_stars: int,
        max_size_kb: int,
        per_page: int = 100,
        page: int = 1,
    ) -> dict[str, Any]:
        """Search for repositories by language and stars."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use async with.")

        # GitHub search query
        query = f"language:{language} stars:>={min_stars} size:<={max_size_kb}"

        response = await self._client.get(
            "/search/repositories",
            params={
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": per_page,
                "page": page,
            },
        )

        if response.status_code == 403:
            # Rate limited
            reset_time = response.headers.get("X-RateLimit-Reset", "unknown")
            raise RuntimeError(
                f"GitHub API rate limited. Resets at: {reset_time}. "
                f"Set GITHUB_TOKEN for higher limits."
            )

        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    async def get_rate_limit(self) -> dict[str, Any]:
        """Get current rate limit status."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use async with.")

        response = await self._client.get("/rate_limit")
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result


async def fetch_repos_for_language(
    client: GitHubClient,
    language: str,
    count: int,
    min_stars: int,
    max_size_kb: int,
) -> list[RepoInfo]:
    """Fetch top repos for a single language."""
    repos: list[RepoInfo] = []
    page = 1
    per_page = min(100, count)  # GitHub max is 100

    while len(repos) < count:
        try:
            result = await client.search_repos(
                language=language,
                min_stars=min_stars,
                max_size_kb=max_size_kb,
                per_page=per_page,
                page=page,
            )
        except httpx.HTTPStatusError as e:
            logger.warning(f"Error fetching page {page} for {language}: {e}")
            break

        items = result.get("items", [])
        if not items:
            break

        for item in items:
            if len(repos) >= count:
                break

            repo = RepoInfo(
                name=item["full_name"],
                url=item["clone_url"],
                stars=item["stargazers_count"],
                language=language.lower(),
                size_kb=item["size"],
                description=item.get("description"),
            )
            repos.append(repo)

        page += 1

        # Small delay to avoid rate limiting
        await asyncio.sleep(0.5)

    return repos


async def fetch_top_repos(
    config: SigmaConfig,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[RepoInfo]:
    """Fetch top repos by stars for configured languages.

    Args:
        config: Pipeline configuration
        progress_callback: Optional callback(completed, total) for progress

    Returns:
        List of RepoInfo for all fetched repositories
    """
    all_repos: list[RepoInfo] = []
    total_languages = len(config.repos.languages)
    completed = 0

    async with GitHubClient() as client:
        # Check rate limit first
        try:
            rate_info = await client.get_rate_limit()
            remaining = rate_info.get("resources", {}).get("search", {}).get("remaining", 0)
            logger.info(f"GitHub API rate limit remaining: {remaining}")
            if remaining < 10:
                logger.warning("Low rate limit remaining. Consider setting GITHUB_TOKEN.")
        except Exception as e:
            logger.warning(f"Could not check rate limit: {e}")

        for language in config.repos.languages:
            logger.info(f"Fetching {config.repos.repos_per_language} {language} repos...")

            repos = await fetch_repos_for_language(
                client=client,
                language=language,
                count=config.repos.repos_per_language,
                min_stars=config.repos.min_stars,
                max_size_kb=config.repos.max_size_kb,
            )

            all_repos.extend(repos)
            completed += 1

            if progress_callback:
                progress_callback(completed, total_languages)

            logger.info(f"Fetched {len(repos)} {language} repos")

    return all_repos


def save_repos(repos: list[RepoInfo], path: Path) -> None:
    """Save repos to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([r.to_dict() for r in repos], f, indent=2)


def load_repos(path: Path) -> list[RepoInfo]:
    """Load repos from JSON file."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [RepoInfo.from_dict(r) for r in data]


async def fetch_and_save_repos(
    config: SigmaConfig,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[RepoInfo]:
    """Fetch repos and save to configured location.

    Returns:
        List of fetched RepoInfo
    """
    config.ensure_directories()

    # Check if repos already exist
    existing = load_repos(config.paths.repos_file)
    if existing:
        logger.info(f"Found {len(existing)} existing repos in {config.paths.repos_file}")
        return existing

    repos = await fetch_top_repos(config, progress_callback)
    save_repos(repos, config.paths.repos_file)
    logger.info(f"Saved {len(repos)} repos to {config.paths.repos_file}")

    return repos
