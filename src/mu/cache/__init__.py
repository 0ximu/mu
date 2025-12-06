"""MU Cache - File and LLM response caching.

Provides persistent caching using diskcache for:
- File-level MU output (keyed by content hash)
- LLM summarization responses (keyed by body hash + prompt version + model)

Cache structure:
    .mu-cache/
    ├── manifest.json          # Cache metadata
    ├── files/                  # Cached MU output per file
    │   └── <hash>.json
    └── llm/                    # Cached LLM responses
        └── <hash>.json
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from diskcache import Cache

from mu.config import CacheConfig

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class CacheManifest:
    """Cache manifest with metadata and statistics."""

    version: str = "1.0"
    created_at: str = ""
    last_accessed: str = ""
    ttl_hours: int = 168
    stats: dict[str, int] = field(default_factory=lambda: {
        "file_entries": 0,
        "llm_entries": 0,
        "hits": 0,
        "misses": 0,
    })

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "version": self.version,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "ttl_hours": self.ttl_hours,
            "stats": self.stats,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CacheManifest:
        """Deserialize from dictionary."""
        return cls(
            version=data.get("version", "1.0"),
            created_at=data.get("created_at", ""),
            last_accessed=data.get("last_accessed", ""),
            ttl_hours=data.get("ttl_hours", 168),
            stats=data.get("stats", {
                "file_entries": 0,
                "llm_entries": 0,
                "hits": 0,
                "misses": 0,
            }),
        )


@dataclass
class CachedFileResult:
    """Cached MU output for a single file."""

    file_hash: str
    mu_output: str
    language: str
    cached_at: str
    source_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_hash": self.file_hash,
            "mu_output": self.mu_output,
            "language": self.language,
            "cached_at": self.cached_at,
            "source_path": self.source_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CachedFileResult:
        return cls(
            file_hash=data["file_hash"],
            mu_output=data["mu_output"],
            language=data["language"],
            cached_at=data["cached_at"],
            source_path=data["source_path"],
        )


@dataclass
class CachedLLMResult:
    """Cached LLM summarization result."""

    cache_key: str
    function_name: str
    summary: list[str]
    model: str
    prompt_version: str
    cached_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache_key": self.cache_key,
            "function_name": self.function_name,
            "summary": self.summary,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "cached_at": self.cached_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CachedLLMResult:
        return cls(
            cache_key=data["cache_key"],
            function_name=data["function_name"],
            summary=data["summary"],
            model=data["model"],
            prompt_version=data["prompt_version"],
            cached_at=data["cached_at"],
        )


class CacheManager:
    """Manages persistent caching for MU operations.

    Uses diskcache for reliable file-based caching with TTL support.
    Maintains separate namespaces for file results and LLM responses.
    """

    def __init__(self, config: CacheConfig, base_path: Path | None = None):
        """Initialize the cache manager.

        Args:
            config: Cache configuration from MUConfig
            base_path: Base directory for cache (defaults to cwd)
        """
        self.config = config
        self.base_path = base_path or Path.cwd()
        self.cache_dir = self.base_path / config.directory
        self.ttl_seconds = config.ttl_hours * 3600

        # Initialize caches (lazy - only created when enabled and accessed)
        self._file_cache: Cache | None = None
        self._llm_cache: Cache | None = None
        self._manifest: CacheManifest | None = None

    @property
    def enabled(self) -> bool:
        """Check if caching is enabled."""
        return self.config.enabled

    def _ensure_initialized(self) -> None:
        """Ensure cache directories and caches are initialized."""
        if not self.enabled:
            return

        if self._file_cache is None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            files_dir = self.cache_dir / "files"
            llm_dir = self.cache_dir / "llm"
            files_dir.mkdir(exist_ok=True)
            llm_dir.mkdir(exist_ok=True)

            # Initialize diskcache instances
            self._file_cache = Cache(str(files_dir))
            self._llm_cache = Cache(str(llm_dir))

            # Load or create manifest
            self._load_manifest()

    def _load_manifest(self) -> None:
        """Load or create the cache manifest."""
        manifest_path = self.cache_dir / "manifest.json"
        if manifest_path.exists():
            try:
                with open(manifest_path) as f:
                    data = json.load(f)
                self._manifest = CacheManifest.from_dict(data)
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Invalid cache manifest, creating new: {e}")
                self._manifest = self._create_manifest()
        else:
            self._manifest = self._create_manifest()

    def _create_manifest(self) -> CacheManifest:
        """Create a new cache manifest."""
        now = datetime.now(UTC).isoformat()
        manifest = CacheManifest(
            created_at=now,
            last_accessed=now,
            ttl_hours=self.config.ttl_hours,
        )
        self._save_manifest(manifest)
        return manifest

    def _save_manifest(self, manifest: CacheManifest | None = None) -> None:
        """Save the cache manifest to disk."""
        if manifest is None:
            manifest = self._manifest
        if manifest is None:
            return

        manifest.last_accessed = datetime.now(UTC).isoformat()
        manifest_path = self.cache_dir / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest.to_dict(), f, indent=2)

    def _update_stats(self, stat_key: str, increment: int = 1) -> None:
        """Update manifest statistics."""
        if self._manifest:
            self._manifest.stats[stat_key] = (
                self._manifest.stats.get(stat_key, 0) + increment
            )

    # -------------------------------------------------------------------------
    # File Cache Operations
    # -------------------------------------------------------------------------

    def get_file_result(self, file_hash: str) -> CachedFileResult | None:
        """Get cached MU output for a file.

        Args:
            file_hash: SHA-256 hash of file content (from scanner)

        Returns:
            Cached result if found and not expired, None otherwise
        """
        if not self.enabled:
            return None

        self._ensure_initialized()
        assert self._file_cache is not None

        try:
            data = self._file_cache.get(file_hash)
            if data is not None:
                self._update_stats("hits")
                logger.debug(f"Cache hit for file: {file_hash[:12]}...")
                return CachedFileResult.from_dict(data)
        except Exception as e:
            logger.warning(f"Error reading file cache: {e}")

        self._update_stats("misses")
        return None

    def set_file_result(
        self,
        file_hash: str,
        mu_output: str,
        language: str,
        source_path: str,
    ) -> None:
        """Cache MU output for a file.

        Args:
            file_hash: SHA-256 hash of file content
            mu_output: Generated MU output
            language: Source language
            source_path: Original file path (for reference)
        """
        if not self.enabled:
            return

        self._ensure_initialized()
        assert self._file_cache is not None

        result = CachedFileResult(
            file_hash=file_hash,
            mu_output=mu_output,
            language=language,
            cached_at=datetime.now(UTC).isoformat(),
            source_path=source_path,
        )

        try:
            self._file_cache.set(
                file_hash,
                result.to_dict(),
                expire=self.ttl_seconds,
            )
            self._update_stats("file_entries")
            logger.debug(f"Cached file result: {file_hash[:12]}...")
        except Exception as e:
            logger.warning(f"Error writing file cache: {e}")

    # -------------------------------------------------------------------------
    # LLM Cache Operations
    # -------------------------------------------------------------------------

    @staticmethod
    def compute_llm_cache_key(
        body_source: str,
        prompt_version: str,
        model: str,
    ) -> str:
        """Compute cache key for LLM summarization.

        Key includes body hash + prompt version + model to invalidate
        when any of these change.

        Args:
            body_source: Function body source code
            prompt_version: Version of the prompt template
            model: LLM model name

        Returns:
            16-character hex hash
        """
        content = f"{body_source}|{prompt_version}|{model}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def get_llm_result(self, cache_key: str) -> CachedLLMResult | None:
        """Get cached LLM summarization result.

        Args:
            cache_key: Key from compute_llm_cache_key()

        Returns:
            Cached result if found and not expired, None otherwise
        """
        if not self.enabled:
            return None

        self._ensure_initialized()
        assert self._llm_cache is not None

        try:
            data = self._llm_cache.get(cache_key)
            if data is not None:
                self._update_stats("hits")
                logger.debug(f"LLM cache hit: {cache_key}")
                return CachedLLMResult.from_dict(data)
        except Exception as e:
            logger.warning(f"Error reading LLM cache: {e}")

        self._update_stats("misses")
        return None

    def set_llm_result(
        self,
        cache_key: str,
        function_name: str,
        summary: list[str],
        model: str,
        prompt_version: str,
    ) -> None:
        """Cache LLM summarization result.

        Args:
            cache_key: Key from compute_llm_cache_key()
            function_name: Name of the summarized function
            summary: List of summary bullet points
            model: LLM model used
            prompt_version: Prompt template version
        """
        if not self.enabled:
            return

        self._ensure_initialized()
        assert self._llm_cache is not None

        result = CachedLLMResult(
            cache_key=cache_key,
            function_name=function_name,
            summary=summary,
            model=model,
            prompt_version=prompt_version,
            cached_at=datetime.now(UTC).isoformat(),
        )

        try:
            self._llm_cache.set(
                cache_key,
                result.to_dict(),
                expire=self.ttl_seconds,
            )
            self._update_stats("llm_entries")
            logger.debug(f"Cached LLM result: {cache_key}")
        except Exception as e:
            logger.warning(f"Error writing LLM cache: {e}")

    # -------------------------------------------------------------------------
    # Cache Management
    # -------------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache stats including size, entries, hit rate
        """
        if not self.enabled or not self.cache_dir.exists():
            return {
                "enabled": self.enabled,
                "directory": str(self.cache_dir),
                "exists": False,
            }

        self._ensure_initialized()

        # Calculate disk usage
        total_size = 0
        file_count = 0
        for f in self.cache_dir.rglob("*"):
            if f.is_file():
                total_size += f.stat().st_size
                file_count += 1

        # Get entry counts from diskcache
        file_entries = len(self._file_cache) if self._file_cache else 0
        llm_entries = len(self._llm_cache) if self._llm_cache else 0

        # Calculate hit rate
        hits = self._manifest.stats.get("hits", 0) if self._manifest else 0
        misses = self._manifest.stats.get("misses", 0) if self._manifest else 0
        total_requests = hits + misses
        hit_rate = (hits / total_requests * 100) if total_requests > 0 else 0.0

        return {
            "enabled": True,
            "directory": str(self.cache_dir),
            "exists": True,
            "size_bytes": total_size,
            "size_kb": total_size / 1024,
            "file_count": file_count,
            "file_entries": file_entries,
            "llm_entries": llm_entries,
            "ttl_hours": self.config.ttl_hours,
            "hits": hits,
            "misses": misses,
            "hit_rate_percent": round(hit_rate, 1),
            "manifest": self._manifest.to_dict() if self._manifest else None,
        }

    def clear(self) -> dict[str, int]:
        """Clear all cached data.

        Returns:
            Dictionary with counts of cleared entries
        """
        cleared = {"file_entries": 0, "llm_entries": 0}

        if not self.cache_dir.exists():
            return cleared

        self._ensure_initialized()

        if self._file_cache:
            cleared["file_entries"] = len(self._file_cache)
            self._file_cache.clear()

        if self._llm_cache:
            cleared["llm_entries"] = len(self._llm_cache)
            self._llm_cache.clear()

        # Reset manifest stats
        if self._manifest:
            self._manifest.stats = {
                "file_entries": 0,
                "llm_entries": 0,
                "hits": 0,
                "misses": 0,
            }
            self._save_manifest()

        logger.info(f"Cleared cache: {cleared}")
        return cleared

    def expire_old_entries(self) -> int:
        """Expire entries older than TTL.

        Note: diskcache handles TTL automatically, but this forces cleanup.

        Returns:
            Number of entries expired
        """
        if not self.enabled:
            return 0

        self._ensure_initialized()

        expired = 0
        if self._file_cache:
            expired += self._file_cache.expire()
        if self._llm_cache:
            expired += self._llm_cache.expire()

        if expired > 0:
            logger.info(f"Expired {expired} cache entries")

        return expired

    def close(self) -> None:
        """Close cache connections and save manifest."""
        if self._manifest:
            self._save_manifest()

        if self._file_cache:
            self._file_cache.close()
            self._file_cache = None

        if self._llm_cache:
            self._llm_cache.close()
            self._llm_cache = None


# Convenience function for creating cache manager
def create_cache_manager(
    config: CacheConfig,
    base_path: Path | None = None,
) -> CacheManager:
    """Create a cache manager from configuration.

    Args:
        config: Cache configuration
        base_path: Base directory for cache

    Returns:
        Configured CacheManager instance
    """
    return CacheManager(config, base_path)
