"""Tests for caching module."""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from mu.cache import (
    CacheManager,
    CacheManifest,
    CachedFileResult,
    CachedLLMResult,
    create_cache_manager,
)
from mu.config import CacheConfig


class TestCacheManifest:
    """Tests for CacheManifest dataclass."""

    def test_manifest_creation(self):
        """Test creating a new manifest."""
        manifest = CacheManifest(
            created_at="2024-12-06T10:00:00Z",
            last_accessed="2024-12-06T10:00:00Z",
            ttl_hours=168,
        )
        assert manifest.version == "1.0"
        assert manifest.ttl_hours == 168

    def test_manifest_to_dict(self):
        """Test manifest serialization."""
        manifest = CacheManifest(
            created_at="2024-12-06T10:00:00Z",
            last_accessed="2024-12-06T10:00:00Z",
        )
        data = manifest.to_dict()
        assert data["version"] == "1.0"
        assert "stats" in data

    def test_manifest_from_dict(self):
        """Test manifest deserialization."""
        data = {
            "version": "1.0",
            "created_at": "2024-12-06T10:00:00Z",
            "last_accessed": "2024-12-06T10:00:00Z",
            "ttl_hours": 72,
            "stats": {"hits": 10, "misses": 5},
        }
        manifest = CacheManifest.from_dict(data)
        assert manifest.ttl_hours == 72
        assert manifest.stats["hits"] == 10


class TestCachedFileResult:
    """Tests for CachedFileResult dataclass."""

    def test_file_result_creation(self):
        """Test creating a file result."""
        result = CachedFileResult(
            file_hash="sha256:abc123",
            mu_output="!module test",
            language="python",
            cached_at="2024-12-06T10:00:00Z",
            source_path="src/test.py",
        )
        assert result.file_hash == "sha256:abc123"
        assert result.language == "python"

    def test_file_result_serialization(self):
        """Test file result round-trip serialization."""
        result = CachedFileResult(
            file_hash="sha256:abc123",
            mu_output="!module test",
            language="python",
            cached_at="2024-12-06T10:00:00Z",
            source_path="src/test.py",
        )
        data = result.to_dict()
        restored = CachedFileResult.from_dict(data)
        assert restored.file_hash == result.file_hash
        assert restored.mu_output == result.mu_output


class TestCachedLLMResult:
    """Tests for CachedLLMResult dataclass."""

    def test_llm_result_creation(self):
        """Test creating an LLM result."""
        result = CachedLLMResult(
            cache_key="abc123def456",
            function_name="process_data",
            summary=["Processes input data", "Returns filtered results"],
            model="claude-3-haiku-20240307",
            prompt_version="1.0",
            cached_at="2024-12-06T10:00:00Z",
        )
        assert len(result.summary) == 2
        assert result.model == "claude-3-haiku-20240307"

    def test_llm_result_serialization(self):
        """Test LLM result round-trip serialization."""
        result = CachedLLMResult(
            cache_key="abc123def456",
            function_name="process_data",
            summary=["Point 1", "Point 2"],
            model="claude-3-haiku-20240307",
            prompt_version="1.0",
            cached_at="2024-12-06T10:00:00Z",
        )
        data = result.to_dict()
        restored = CachedLLMResult.from_dict(data)
        assert restored.function_name == result.function_name
        assert restored.summary == result.summary


class TestCacheManager:
    """Tests for CacheManager."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def cache_config(self):
        """Create a test cache configuration."""
        return CacheConfig(
            enabled=True,
            directory=".mu-cache",
            ttl_hours=24,
        )

    @pytest.fixture
    def cache_manager(self, temp_dir, cache_config):
        """Create a cache manager for testing."""
        manager = CacheManager(cache_config, temp_dir)
        yield manager
        manager.close()

    def test_cache_manager_creation(self, temp_dir, cache_config):
        """Test creating a cache manager."""
        manager = CacheManager(cache_config, temp_dir)
        assert manager.enabled
        assert manager.cache_dir == temp_dir / ".mu-cache"
        manager.close()

    def test_cache_manager_disabled(self, temp_dir):
        """Test cache manager when disabled."""
        config = CacheConfig(enabled=False)
        manager = CacheManager(config, temp_dir)
        assert not manager.enabled

        # Operations should be no-ops when disabled
        result = manager.get_file_result("test")
        assert result is None

        manager.set_file_result("test", "output", "python", "test.py")
        result = manager.get_file_result("test")
        assert result is None
        manager.close()

    def test_compute_llm_cache_key(self):
        """Test LLM cache key computation."""
        key1 = CacheManager.compute_llm_cache_key(
            "def foo(): pass",
            "1.0",
            "claude-3-haiku",
        )
        key2 = CacheManager.compute_llm_cache_key(
            "def foo(): pass",
            "1.0",
            "claude-3-haiku",
        )
        assert key1 == key2
        assert len(key1) == 16

    def test_compute_llm_cache_key_varies(self):
        """Test that cache key varies with inputs."""
        key1 = CacheManager.compute_llm_cache_key("code1", "1.0", "model")
        key2 = CacheManager.compute_llm_cache_key("code2", "1.0", "model")
        key3 = CacheManager.compute_llm_cache_key("code1", "2.0", "model")
        key4 = CacheManager.compute_llm_cache_key("code1", "1.0", "other")

        assert key1 != key2  # Different code
        assert key1 != key3  # Different prompt version
        assert key1 != key4  # Different model

    def test_file_cache_operations(self, cache_manager):
        """Test file cache set and get."""
        file_hash = "sha256:abc123"
        mu_output = "!module test\n#func test()"
        language = "python"
        source_path = "src/test.py"

        # Initially should miss
        result = cache_manager.get_file_result(file_hash)
        assert result is None

        # Set cache
        cache_manager.set_file_result(file_hash, mu_output, language, source_path)

        # Should now hit
        result = cache_manager.get_file_result(file_hash)
        assert result is not None
        assert result.file_hash == file_hash
        assert result.mu_output == mu_output
        assert result.language == language

    def test_llm_cache_operations(self, cache_manager):
        """Test LLM cache set and get."""
        cache_key = CacheManager.compute_llm_cache_key(
            "def foo(): pass",
            "1.0",
            "claude-3-haiku",
        )
        summary = ["Does something", "Returns nothing"]

        # Initially should miss
        result = cache_manager.get_llm_result(cache_key)
        assert result is None

        # Set cache
        cache_manager.set_llm_result(
            cache_key=cache_key,
            function_name="foo",
            summary=summary,
            model="claude-3-haiku",
            prompt_version="1.0",
        )

        # Should now hit
        result = cache_manager.get_llm_result(cache_key)
        assert result is not None
        assert result.function_name == "foo"
        assert result.summary == summary

    def test_cache_stats(self, cache_manager):
        """Test cache statistics."""
        # Add some entries
        cache_manager.set_file_result("hash1", "output1", "python", "test1.py")
        cache_manager.set_llm_result("key1", "func1", ["summary"], "model", "1.0")

        # Get stats
        stats = cache_manager.get_stats()
        assert stats["enabled"]
        assert stats["exists"]
        assert stats["file_entries"] >= 1
        assert stats["llm_entries"] >= 1

    def test_cache_clear(self, cache_manager):
        """Test clearing cache."""
        # Add entries
        cache_manager.set_file_result("hash1", "output1", "python", "test1.py")
        cache_manager.set_llm_result("key1", "func1", ["summary"], "model", "1.0")

        # Clear
        cleared = cache_manager.clear()
        assert cleared["file_entries"] >= 1
        assert cleared["llm_entries"] >= 1

        # Verify empty
        stats = cache_manager.get_stats()
        assert stats["file_entries"] == 0
        assert stats["llm_entries"] == 0

    def test_cache_persistence(self, temp_dir, cache_config):
        """Test that cache persists across manager instances."""
        # Create first manager and add data
        manager1 = CacheManager(cache_config, temp_dir)
        manager1.set_file_result("hash1", "output1", "python", "test1.py")
        manager1.close()

        # Create second manager and verify data
        manager2 = CacheManager(cache_config, temp_dir)
        result = manager2.get_file_result("hash1")
        assert result is not None
        assert result.mu_output == "output1"
        manager2.close()

    def test_manifest_persistence(self, temp_dir, cache_config):
        """Test that manifest is persisted."""
        manager = CacheManager(cache_config, temp_dir)
        manager._ensure_initialized()
        manager.close()

        # Check manifest file exists
        manifest_path = temp_dir / ".mu-cache" / "manifest.json"
        assert manifest_path.exists()

        with open(manifest_path) as f:
            data = json.load(f)
        assert data["version"] == "1.0"


class TestCreateCacheManager:
    """Tests for create_cache_manager factory function."""

    def test_create_cache_manager(self):
        """Test factory function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = CacheConfig()
            manager = create_cache_manager(config, Path(tmpdir))
            assert isinstance(manager, CacheManager)
            manager.close()
