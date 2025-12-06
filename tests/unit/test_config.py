"""Tests for MU configuration."""

import pytest
from pathlib import Path
import tempfile

from mu.config import MUConfig, get_default_config_toml


class TestMUConfig:
    """Test configuration loading and defaults."""

    def test_default_config(self):
        """Test that default config loads without errors."""
        config = MUConfig()
        assert config.version == "1.0"
        assert config.llm.enabled is False
        assert config.security.redact_secrets is True

    def test_scanner_defaults(self):
        """Test scanner default values."""
        config = MUConfig()
        assert "node_modules/" in config.scanner.ignore
        assert ".git/" in config.scanner.ignore
        assert config.scanner.include_hidden is False
        assert config.scanner.max_file_size_kb == 1000

    def test_llm_defaults(self):
        """Test LLM default values."""
        config = MUConfig()
        assert config.llm.provider == "anthropic"
        assert config.llm.model == "claude-3-haiku-20240307"
        assert config.llm.timeout_seconds == 30

    def test_load_from_toml(self):
        """Test loading config from TOML file."""
        toml_content = """
[mu]
version = "1.0"

[llm]
enabled = true
provider = "openai"
model = "gpt-4o-mini"
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False
        ) as f:
            f.write(toml_content)
            f.flush()

            config = MUConfig.load(Path(f.name))
            assert config.llm.enabled is True
            assert config.llm.provider == "openai"
            assert config.llm.model == "gpt-4o-mini"

    def test_default_config_toml_is_valid(self):
        """Test that default config TOML can be parsed."""
        toml_content = get_default_config_toml()
        assert "[scanner]" in toml_content
        assert "[llm]" in toml_content
        assert "[security]" in toml_content


class TestSecurityConfig:
    """Test security configuration."""

    def test_redact_secrets_default(self):
        """Test that secret redaction is enabled by default."""
        config = MUConfig()
        assert config.security.redact_secrets is True

    def test_default_secret_patterns(self):
        """Test default secret patterns value."""
        config = MUConfig()
        assert config.security.secret_patterns == "default"


class TestCacheConfig:
    """Test cache configuration."""

    def test_cache_defaults(self):
        """Test cache default values."""
        config = MUConfig()
        assert config.cache.enabled is True
        assert config.cache.directory == ".mu-cache"
        assert config.cache.ttl_hours == 168  # 1 week
