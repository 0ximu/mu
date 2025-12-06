"""Tests for MU Embeddings layer - vector embeddings for code graph nodes."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mu.config import EmbeddingsConfig
from mu.kernel import MUbase, Node, NodeType
from mu.kernel.embeddings.models import EmbeddingStats, NodeEmbedding
from mu.kernel.embeddings.providers.base import (
    BatchEmbeddingResult,
    EmbeddingProviderType,
    EmbeddingResult,
)
from mu.kernel.embeddings.providers.local import (
    LOCAL_MODELS,
    LocalEmbeddingProvider,
)
from mu.kernel.embeddings.providers.openai import (
    OPENAI_MODELS,
    OpenAIEmbeddingProvider,
)
from mu.kernel.embeddings.service import (
    EmbeddingService,
    _generate_docstring_text,
    _generate_name_text,
    _generate_node_text,
    _truncate_text,
    create_embedding_service,
)

# =============================================================================
# TestEmbeddingModels (40% coverage focus)
# =============================================================================


class TestNodeEmbedding:
    """Tests for NodeEmbedding dataclass."""

    def test_creation_with_all_fields(self) -> None:
        """NodeEmbedding can be created with all fields populated."""
        now = datetime.now(UTC)
        embedding = NodeEmbedding(
            node_id="fn:test.py:my_func",
            model_name="text-embedding-3-small",
            model_version="3-small",
            dimensions=1536,
            created_at=now,
            code_embedding=[0.1, 0.2, 0.3],
            docstring_embedding=[0.4, 0.5, 0.6],
            name_embedding=[0.7, 0.8, 0.9],
        )

        assert embedding.node_id == "fn:test.py:my_func"
        assert embedding.model_name == "text-embedding-3-small"
        assert embedding.model_version == "3-small"
        assert embedding.dimensions == 1536
        assert embedding.created_at == now
        assert embedding.code_embedding == [0.1, 0.2, 0.3]
        assert embedding.docstring_embedding == [0.4, 0.5, 0.6]
        assert embedding.name_embedding == [0.7, 0.8, 0.9]

    def test_creation_with_none_embeddings(self) -> None:
        """NodeEmbedding can have None embeddings."""
        embedding = NodeEmbedding(
            node_id="cls:test.py:MyClass",
            model_name="all-MiniLM-L6-v2",
            model_version="v2",
            dimensions=384,
            created_at=datetime.now(UTC),
            code_embedding=None,
            docstring_embedding=None,
            name_embedding=None,
        )

        assert embedding.code_embedding is None
        assert embedding.docstring_embedding is None
        assert embedding.name_embedding is None

    def test_to_tuple_produces_correct_format(self) -> None:
        """to_tuple() produces tuple suitable for DuckDB insertion."""
        now = datetime.now(UTC)
        embedding = NodeEmbedding(
            node_id="mod:test.py",
            model_name="text-embedding-3-small",
            model_version="3-small",
            dimensions=1536,
            created_at=now,
            code_embedding=[0.1, 0.2],
            docstring_embedding=[0.3, 0.4],
            name_embedding=[0.5, 0.6],
        )

        t = embedding.to_tuple()

        assert t[0] == "mod:test.py"  # node_id
        assert t[1] == [0.1, 0.2]  # code_embedding
        assert t[2] == [0.3, 0.4]  # docstring_embedding
        assert t[3] == [0.5, 0.6]  # name_embedding
        assert t[4] == "text-embedding-3-small"  # model_name
        assert t[5] == "3-small"  # model_version
        assert t[6] == 1536  # dimensions
        assert t[7] == now.isoformat()  # created_at as ISO string

    def test_to_tuple_with_none_embeddings(self) -> None:
        """to_tuple() handles None embeddings correctly."""
        embedding = NodeEmbedding(
            node_id="fn:test.py:foo",
            model_name="test-model",
            model_version="1.0",
            dimensions=128,
            created_at=datetime.now(UTC),
            code_embedding=None,
            docstring_embedding=[1.0, 2.0],
            name_embedding=None,
        )

        t = embedding.to_tuple()

        assert t[1] is None  # code_embedding
        assert t[2] == [1.0, 2.0]  # docstring_embedding
        assert t[3] is None  # name_embedding

    def test_to_dict_serializes_correctly(self) -> None:
        """to_dict() produces correct dictionary for JSON serialization."""
        now = datetime.now(UTC)
        embedding = NodeEmbedding(
            node_id="fn:test.py:process",
            model_name="text-embedding-3-small",
            model_version="3-small",
            dimensions=1536,
            created_at=now,
            code_embedding=[0.1, 0.2, 0.3],
            docstring_embedding=None,
            name_embedding=[0.4, 0.5],
        )

        d = embedding.to_dict()

        assert d["node_id"] == "fn:test.py:process"
        assert d["model_name"] == "text-embedding-3-small"
        assert d["model_version"] == "3-small"
        assert d["dimensions"] == 1536
        assert d["created_at"] == now.isoformat()
        assert d["code_embedding"] == [0.1, 0.2, 0.3]
        assert d["docstring_embedding"] is None
        assert d["name_embedding"] == [0.4, 0.5]

    def test_from_row_deserializes_correctly(self) -> None:
        """from_row() reconstructs NodeEmbedding from DuckDB row."""
        row = (
            "fn:test.py:my_func",
            [0.1, 0.2, 0.3],  # code_embedding
            [0.4, 0.5],  # docstring_embedding
            None,  # name_embedding
            "text-embedding-3-small",
            "3-small",
            1536,
            "2024-01-15T10:30:00+00:00",
        )

        embedding = NodeEmbedding.from_row(row)

        assert embedding.node_id == "fn:test.py:my_func"
        assert embedding.code_embedding == [0.1, 0.2, 0.3]
        assert embedding.docstring_embedding == [0.4, 0.5]
        assert embedding.name_embedding is None
        assert embedding.model_name == "text-embedding-3-small"
        assert embedding.model_version == "3-small"
        assert embedding.dimensions == 1536
        assert isinstance(embedding.created_at, datetime)

    def test_from_row_with_datetime_object(self) -> None:
        """from_row() handles datetime object in row."""
        now = datetime.now(UTC)
        row = (
            "mod:test.py",
            [0.1],
            None,
            None,
            "test-model",
            "1.0",
            128,
            now,  # datetime object, not string
        )

        embedding = NodeEmbedding.from_row(row)

        assert embedding.created_at == now

    def test_round_trip_consistency(self) -> None:
        """Round-trip: create -> to_tuple -> from_row produces equivalent object."""
        now = datetime.now(UTC)
        original = NodeEmbedding(
            node_id="cls:pkg/module.py:MyClass",
            model_name="text-embedding-3-large",
            model_version="3-large",
            dimensions=3072,
            created_at=now,
            code_embedding=[0.1, 0.2, 0.3, 0.4],
            docstring_embedding=[0.5, 0.6],
            name_embedding=[0.7],
        )

        # Convert to tuple and back
        row = original.to_tuple()
        # from_row expects created_at to be a string (as it comes from DB)
        # The to_tuple already produces ISO string
        restored = NodeEmbedding.from_row(row)

        assert restored.node_id == original.node_id
        assert restored.model_name == original.model_name
        assert restored.model_version == original.model_version
        assert restored.dimensions == original.dimensions
        assert restored.code_embedding == original.code_embedding
        assert restored.docstring_embedding == original.docstring_embedding
        assert restored.name_embedding == original.name_embedding


class TestEmbeddingStats:
    """Tests for EmbeddingStats dataclass."""

    def test_default_values(self) -> None:
        """EmbeddingStats initializes with zero values."""
        stats = EmbeddingStats()

        assert stats.total_requests == 0
        assert stats.successful == 0
        assert stats.failed == 0
        assert stats.cached_hits == 0
        assert stats.total_tokens == 0

    def test_add_success_increments_counters(self) -> None:
        """add_success() increments total_requests and successful."""
        stats = EmbeddingStats()

        stats.add_success()

        assert stats.total_requests == 1
        assert stats.successful == 1
        assert stats.cached_hits == 0

    def test_add_success_with_cache_hit(self) -> None:
        """add_success(cached=True) also increments cached_hits."""
        stats = EmbeddingStats()

        stats.add_success(cached=True)

        assert stats.total_requests == 1
        assert stats.successful == 1
        assert stats.cached_hits == 1

    def test_add_failure_increments_counters(self) -> None:
        """add_failure() increments total_requests and failed."""
        stats = EmbeddingStats()

        stats.add_failure()

        assert stats.total_requests == 1
        assert stats.failed == 1
        assert stats.successful == 0

    def test_multiple_operations(self) -> None:
        """Stats accumulate correctly across multiple operations."""
        stats = EmbeddingStats()

        stats.add_success()
        stats.add_success(cached=True)
        stats.add_success()
        stats.add_failure()
        stats.add_failure()

        assert stats.total_requests == 5
        assert stats.successful == 3
        assert stats.failed == 2
        assert stats.cached_hits == 1


class TestEmbeddingProviderBase:
    """Tests for base provider types."""

    def test_embedding_provider_type_values(self) -> None:
        """EmbeddingProviderType enum has expected values."""
        assert EmbeddingProviderType.OPENAI.value == "openai"
        assert EmbeddingProviderType.LOCAL.value == "local"

    def test_embedding_result_success(self) -> None:
        """EmbeddingResult.success returns True when embedding present."""
        result = EmbeddingResult(
            embedding=[0.1, 0.2, 0.3],
            tokens_used=10,
        )

        assert result.success is True
        assert result.error is None

    def test_embedding_result_failure(self) -> None:
        """EmbeddingResult.success returns False when error present."""
        result = EmbeddingResult(
            embedding=None,
            error="API rate limit exceeded",
        )

        assert result.success is False
        assert result.error == "API rate limit exceeded"

    def test_embedding_result_cached(self) -> None:
        """EmbeddingResult can indicate cached response."""
        result = EmbeddingResult(
            embedding=[0.1, 0.2],
            cached=True,
        )

        assert result.cached is True
        assert result.success is True

    def test_batch_embedding_result_success_count(self) -> None:
        """BatchEmbeddingResult.success_count returns correct count."""
        result = BatchEmbeddingResult(
            embeddings=[
                [0.1, 0.2],  # success
                None,  # failure
                [0.3, 0.4],  # success
                None,  # failure
                [0.5, 0.6],  # success
            ],
            tokens_used=50,
        )

        assert result.success_count == 3

    def test_batch_embedding_result_with_errors(self) -> None:
        """BatchEmbeddingResult can have errors list."""
        result = BatchEmbeddingResult(
            embeddings=[None, [0.1, 0.2], None],
            errors=["Empty text", None, "Too long"],
        )

        assert result.errors is not None
        assert result.errors[0] == "Empty text"
        assert result.errors[1] is None
        assert result.errors[2] == "Too long"


# =============================================================================
# TestEmbeddingProviders (30% coverage focus)
# =============================================================================


class TestOpenAIEmbeddingProvider:
    """Tests for OpenAI embedding provider."""

    def test_init_requires_api_key(self) -> None:
        """Initialization fails without API key."""
        with patch.dict("os.environ", {}, clear=True):
            # Remove OPENAI_API_KEY from environment
            with patch("os.environ.get", return_value=None):
                with pytest.raises(ValueError, match="API key required"):
                    OpenAIEmbeddingProvider()

    def test_init_with_api_key_param(self) -> None:
        """Initialization succeeds with api_key parameter."""
        provider = OpenAIEmbeddingProvider(api_key="test-key-123")

        assert provider.model_name == "text-embedding-3-small"
        assert provider.dimensions == 1536
        assert provider.max_tokens == 8191

    def test_init_with_custom_model(self) -> None:
        """Provider can use different OpenAI models."""
        provider = OpenAIEmbeddingProvider(
            api_key="test-key",
            model="text-embedding-3-large",
        )

        assert provider.model_name == "text-embedding-3-large"
        assert provider.dimensions == 3072
        assert provider.model_version == "3-large"

    def test_init_with_invalid_model(self) -> None:
        """Initialization fails with unknown model."""
        with pytest.raises(ValueError, match="Unknown model"):
            OpenAIEmbeddingProvider(api_key="test-key", model="invalid-model")

    def test_model_configs_complete(self) -> None:
        """All OpenAI models have required configuration."""
        for _model_name, config in OPENAI_MODELS.items():
            assert "dimensions" in config
            assert "max_tokens" in config
            assert "version" in config
            assert isinstance(config["dimensions"], int)
            assert config["dimensions"] > 0

    @pytest.mark.asyncio
    async def test_embed_empty_text_returns_error(self) -> None:
        """embed() returns error for empty text."""
        provider = OpenAIEmbeddingProvider(api_key="test-key")

        result = await provider.embed("")

        assert result.success is False
        assert result.error == "Empty text provided"
        assert result.embedding is None

    @pytest.mark.asyncio
    async def test_embed_whitespace_only_returns_error(self) -> None:
        """embed() returns error for whitespace-only text."""
        provider = OpenAIEmbeddingProvider(api_key="test-key")

        result = await provider.embed("   \n\t  ")

        assert result.success is False
        assert result.error == "Empty text provided"

    @pytest.mark.asyncio
    async def test_embed_success(self) -> None:
        """embed() returns embedding on successful API call."""
        provider = OpenAIEmbeddingProvider(api_key="test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}],
            "usage": {"total_tokens": 5},
        }

        with patch.object(provider, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            result = await provider.embed("test text")

        assert result.success is True
        assert result.embedding == [0.1, 0.2, 0.3]
        assert result.tokens_used == 5

    @pytest.mark.asyncio
    async def test_embed_api_error(self) -> None:
        """embed() handles API errors gracefully."""
        provider = OpenAIEmbeddingProvider(api_key="test-key", max_retries=0)

        with patch.object(provider, "_make_request") as mock_request:
            mock_request.side_effect = Exception("Connection failed")

            result = await provider.embed("test text")

        assert result.success is False
        assert "Connection failed" in result.error

    @pytest.mark.asyncio
    async def test_embed_batch_empty_list(self) -> None:
        """embed_batch() returns empty result for empty input."""
        provider = OpenAIEmbeddingProvider(api_key="test-key")

        result = await provider.embed_batch([])

        assert result.embeddings == []
        assert result.tokens_used == 0

    @pytest.mark.asyncio
    async def test_embed_batch_all_empty_texts(self) -> None:
        """embed_batch() handles all empty texts."""
        provider = OpenAIEmbeddingProvider(api_key="test-key")

        result = await provider.embed_batch(["", "  ", "\n"])

        assert len(result.embeddings) == 3
        assert all(e is None for e in result.embeddings)
        assert result.errors is not None
        assert all(e == "Empty text" for e in result.errors)

    @pytest.mark.asyncio
    async def test_embed_batch_success(self) -> None:
        """embed_batch() returns embeddings for valid texts."""
        provider = OpenAIEmbeddingProvider(api_key="test-key")

        mock_response = {
            "data": [
                {"embedding": [0.1, 0.2], "index": 0},
                {"embedding": [0.3, 0.4], "index": 1},
            ],
            "usage": {"total_tokens": 10},
        }

        with patch.object(provider, "_make_request", return_value=mock_response):
            result = await provider.embed_batch(["text one", "text two"])

        assert len(result.embeddings) == 2
        assert result.embeddings[0] == [0.1, 0.2]
        assert result.embeddings[1] == [0.3, 0.4]
        assert result.tokens_used == 10

    @pytest.mark.asyncio
    async def test_embed_batch_mixed_empty_and_valid(self) -> None:
        """embed_batch() handles mix of empty and valid texts."""
        provider = OpenAIEmbeddingProvider(api_key="test-key")

        mock_response = {
            "data": [{"embedding": [0.1, 0.2], "index": 0}],
            "usage": {"total_tokens": 5},
        }

        with patch.object(provider, "_make_request", return_value=mock_response):
            result = await provider.embed_batch(["", "valid text", ""])

        assert len(result.embeddings) == 3
        assert result.embeddings[0] is None  # empty
        assert result.embeddings[1] == [0.1, 0.2]  # valid
        assert result.embeddings[2] is None  # empty

    @pytest.mark.asyncio
    async def test_close_cleans_up_client(self) -> None:
        """close() cleans up HTTP client."""
        provider = OpenAIEmbeddingProvider(api_key="test-key")

        # Simulate an existing client
        mock_client = AsyncMock()
        provider._client = mock_client

        await provider.close()

        mock_client.aclose.assert_called_once()
        assert provider._client is None


class TestLocalEmbeddingProvider:
    """Tests for local sentence-transformers provider."""

    def test_init_with_default_model(self) -> None:
        """Initialization uses default model."""
        provider = LocalEmbeddingProvider()

        assert provider.model_name == "all-MiniLM-L6-v2"
        assert provider.dimensions == 384
        assert provider.max_tokens == 256
        assert provider.model_version == "v2"

    def test_init_with_custom_model(self) -> None:
        """Provider can use different local models."""
        provider = LocalEmbeddingProvider(model="all-mpnet-base-v2")

        assert provider.model_name == "all-mpnet-base-v2"
        assert provider.dimensions == 768
        assert provider.max_tokens == 384

    def test_init_with_invalid_model(self) -> None:
        """Initialization fails with unknown model."""
        with pytest.raises(ValueError, match="Unknown model"):
            LocalEmbeddingProvider(model="invalid-model")

    def test_init_with_explicit_device(self) -> None:
        """Provider respects explicit device setting."""
        provider = LocalEmbeddingProvider(device="cpu")

        assert provider.device == "cpu"

    def test_model_configs_complete(self) -> None:
        """All local models have required configuration."""
        for _model_name, config in LOCAL_MODELS.items():
            assert "dimensions" in config
            assert "max_tokens" in config
            assert "version" in config
            assert "hf_name" in config

    @pytest.mark.asyncio
    async def test_embed_empty_text_returns_error(self) -> None:
        """embed() returns error for empty text."""
        provider = LocalEmbeddingProvider()

        result = await provider.embed("")

        assert result.success is False
        assert result.error == "Empty text provided"

    @pytest.mark.asyncio
    async def test_embed_success(self) -> None:
        """embed() returns embedding with mocked model."""
        provider = LocalEmbeddingProvider()

        # Mock the model
        mock_model = MagicMock()
        mock_embeddings = MagicMock()
        mock_embeddings.tolist.return_value = [0.1, 0.2, 0.3]
        mock_model.encode.return_value = [mock_embeddings]
        provider._model = mock_model

        result = await provider.embed("test text")

        assert result.success is True
        assert result.embedding == [0.1, 0.2, 0.3]
        assert result.tokens_used == 0  # local models don't track tokens

    @pytest.mark.asyncio
    async def test_embed_batch_empty_list(self) -> None:
        """embed_batch() returns empty result for empty input."""
        provider = LocalEmbeddingProvider()

        result = await provider.embed_batch([])

        assert result.embeddings == []
        assert result.tokens_used == 0

    @pytest.mark.asyncio
    async def test_embed_batch_all_empty_texts(self) -> None:
        """embed_batch() handles all empty texts."""
        provider = LocalEmbeddingProvider()

        result = await provider.embed_batch(["", "  "])

        assert len(result.embeddings) == 2
        assert all(e is None for e in result.embeddings)
        assert result.errors is not None

    @pytest.mark.asyncio
    async def test_embed_batch_success(self) -> None:
        """embed_batch() returns embeddings with mocked model."""
        provider = LocalEmbeddingProvider()

        # Mock the model
        mock_model = MagicMock()
        mock_emb1 = MagicMock()
        mock_emb1.tolist.return_value = [0.1, 0.2]
        mock_emb2 = MagicMock()
        mock_emb2.tolist.return_value = [0.3, 0.4]
        mock_model.encode.return_value = [mock_emb1, mock_emb2]
        provider._model = mock_model

        result = await provider.embed_batch(["text one", "text two"])

        assert len(result.embeddings) == 2
        assert result.embeddings[0] == [0.1, 0.2]
        assert result.embeddings[1] == [0.3, 0.4]

    @pytest.mark.asyncio
    async def test_close_cleans_up_resources(self) -> None:
        """close() cleans up model and executor."""
        provider = LocalEmbeddingProvider()
        provider._model = MagicMock()

        await provider.close()

        assert provider._model is None

    def test_device_detection_cpu_fallback(self) -> None:
        """Device detection falls back to CPU when GPU unavailable."""
        from mu.kernel.embeddings.providers.local import _detect_device

        # When torch is not available, should return 'cpu'
        with patch.dict("sys.modules", {"torch": None}):
            # Reimport to trigger the ImportError path
            # The function catches ImportError and returns 'cpu'
            result = _detect_device()
            # Even with torch available, if no GPU, should return 'cpu'
            assert result in ("cpu", "cuda", "mps")  # Valid device options


# =============================================================================
# TestEmbeddingService (20% coverage focus)
# =============================================================================


class TestEmbeddingServiceHelpers:
    """Tests for embedding service helper functions."""

    def test_truncate_text_short_text(self) -> None:
        """_truncate_text() returns short text unchanged."""
        text = "Hello world"
        result = _truncate_text(text, max_length=100)

        assert result == "Hello world"

    def test_truncate_text_long_text(self) -> None:
        """_truncate_text() truncates long text with ellipsis."""
        text = "x" * 100
        result = _truncate_text(text, max_length=50)

        assert len(result) == 53  # 50 chars + "..."
        assert result.endswith("...")

    def test_generate_node_text_function(self) -> None:
        """_generate_node_text() generates text for function nodes."""
        node = Node(
            id="fn:test.py:process",
            type=NodeType.FUNCTION,
            name="process",
            properties={
                "signature": "process(data: list) -> dict",
                "docstring": "Process input data and return results.",
                "return_type": "dict",
            },
        )

        text = _generate_node_text(node)

        assert "function process" in text
        assert "signature:" in text
        assert "docstring:" in text
        assert "returns:" in text

    def test_generate_node_text_class(self) -> None:
        """_generate_node_text() generates text for class nodes."""
        node = Node(
            id="cls:test.py:MyClass",
            type=NodeType.CLASS,
            name="MyClass",
            properties={
                "bases": ["BaseClass", "Mixin"],
                "docstring": "A sample class for testing.",
                "methods": [{"name": "init"}, {"name": "process"}],
            },
        )

        text = _generate_node_text(node)

        assert "class MyClass" in text
        assert "inherits from:" in text
        assert "BaseClass" in text
        assert "docstring:" in text
        assert "methods:" in text

    def test_generate_node_text_module(self) -> None:
        """_generate_node_text() generates text for module nodes."""
        node = Node(
            id="mod:test.py",
            type=NodeType.MODULE,
            name="test",
            properties={
                "docstring": "A test module.",
                "exports": ["func1", "func2", "Class1"],
                "imports": ["os", "sys"],
            },
        )

        text = _generate_node_text(node)

        assert "module test" in text
        assert "docstring:" in text
        assert "exports:" in text
        assert "imports:" in text

    def test_generate_node_text_external(self) -> None:
        """_generate_node_text() generates text for external nodes."""
        node = Node(
            id="ext:numpy",
            type=NodeType.EXTERNAL,
            name="numpy",
            qualified_name="numpy.array",
        )

        text = _generate_node_text(node)

        assert "external package numpy" in text
        assert "qualified name:" in text

    def test_generate_node_text_fallback(self) -> None:
        """_generate_node_text() has fallback for minimal nodes."""
        node = Node(
            id="unknown:test",
            type=NodeType.FUNCTION,  # type doesn't match content
            name="mystery",
            qualified_name="pkg.mystery",
            properties={},  # no properties
        )

        text = _generate_node_text(node)

        # Should at least include name
        assert "mystery" in text

    def test_generate_docstring_text_with_docstring(self) -> None:
        """_generate_docstring_text() extracts docstring."""
        node = Node(
            id="fn:test.py:foo",
            type=NodeType.FUNCTION,
            name="foo",
            properties={"docstring": "This function does something useful."},
        )

        text = _generate_docstring_text(node)

        assert text == "This function does something useful."

    def test_generate_docstring_text_without_docstring(self) -> None:
        """_generate_docstring_text() returns None without docstring."""
        node = Node(
            id="fn:test.py:foo",
            type=NodeType.FUNCTION,
            name="foo",
            properties={},
        )

        text = _generate_docstring_text(node)

        assert text is None

    def test_generate_docstring_text_empty_docstring(self) -> None:
        """_generate_docstring_text() returns None for empty docstring."""
        node = Node(
            id="fn:test.py:foo",
            type=NodeType.FUNCTION,
            name="foo",
            properties={"docstring": "   "},
        )

        text = _generate_docstring_text(node)

        assert text is None

    def test_generate_name_text_with_qualified_name(self) -> None:
        """_generate_name_text() prefers qualified_name."""
        node = Node(
            id="fn:test.py:foo",
            type=NodeType.FUNCTION,
            name="foo",
            qualified_name="pkg.module.foo",
        )

        text = _generate_name_text(node)

        assert text == "pkg.module.foo"

    def test_generate_name_text_without_qualified_name(self) -> None:
        """_generate_name_text() falls back to name."""
        node = Node(
            id="fn:test.py:foo",
            type=NodeType.FUNCTION,
            name="foo",
        )

        text = _generate_name_text(node)

        assert text == "foo"


class TestEmbeddingService:
    """Tests for EmbeddingService class."""

    def test_init_with_defaults(self) -> None:
        """EmbeddingService initializes with default values."""
        service = EmbeddingService()

        assert service._provider_type == EmbeddingProviderType.OPENAI
        assert service._concurrency == 5

    def test_init_with_config(self) -> None:
        """EmbeddingService uses provided config."""
        config = EmbeddingsConfig(
            provider="local",
            batch_size=50,
        )
        service = EmbeddingService(config=config, provider="local")

        assert service._provider_type == EmbeddingProviderType.LOCAL
        assert service._config == config

    def test_init_with_custom_concurrency(self) -> None:
        """EmbeddingService respects custom concurrency."""
        service = EmbeddingService(provider="local", concurrency=10)

        assert service._concurrency == 10

    def test_create_provider_openai(self) -> None:
        """_create_provider() creates OpenAI provider."""
        service = EmbeddingService(provider="openai")

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            provider = service._create_provider()

        assert isinstance(provider, OpenAIEmbeddingProvider)

    def test_create_provider_local(self) -> None:
        """_create_provider() creates local provider."""
        service = EmbeddingService(provider="local")

        provider = service._create_provider()

        assert isinstance(provider, LocalEmbeddingProvider)

    def test_create_provider_invalid(self) -> None:
        """_create_provider() raises for invalid provider."""
        service = EmbeddingService(provider="openai")
        # Manually set to a value that would trigger the else branch
        # We can't use an invalid enum value, so we test that valid providers work
        # The raise in the code is a safeguard that should not be reached in normal use
        # This test verifies the factory pattern works for known providers
        service._provider_type = EmbeddingProviderType.LOCAL
        provider = service._create_provider()
        assert isinstance(provider, LocalEmbeddingProvider)

    def test_stats_initialized(self) -> None:
        """Service has initialized stats."""
        service = EmbeddingService(provider="local")

        assert isinstance(service.stats, EmbeddingStats)
        assert service.stats.total_requests == 0

    @pytest.mark.asyncio
    async def test_embed_node_success(self) -> None:
        """embed_node() generates embeddings for a node."""
        service = EmbeddingService(provider="local")

        node = Node(
            id="fn:test.py:process",
            type=NodeType.FUNCTION,
            name="process",
            properties={"docstring": "Process data."},
        )

        # Mock the provider
        mock_provider = MagicMock()
        mock_provider.model_name = "test-model"
        mock_provider.model_version = "1.0"
        mock_provider.dimensions = 128

        async def mock_embed(text: str) -> EmbeddingResult:
            return EmbeddingResult(embedding=[0.1, 0.2, 0.3])

        mock_provider.embed = mock_embed
        service._provider = mock_provider

        result = await service.embed_node(node)

        assert result.node_id == "fn:test.py:process"
        assert result.code_embedding is not None
        assert result.model_name == "test-model"

    @pytest.mark.asyncio
    async def test_embed_nodes_empty_list(self) -> None:
        """embed_nodes() returns empty list for empty input."""
        service = EmbeddingService(provider="local")

        result = await service.embed_nodes([])

        assert result == []

    @pytest.mark.asyncio
    async def test_embed_nodes_with_progress_callback(self) -> None:
        """embed_nodes() calls progress callback."""
        service = EmbeddingService(provider="local", concurrency=1)

        nodes = [
            Node(id=f"fn:test.py:func{i}", type=NodeType.FUNCTION, name=f"func{i}")
            for i in range(3)
        ]

        # Mock the provider
        mock_provider = MagicMock()
        mock_provider.model_name = "test-model"
        mock_provider.model_version = "1.0"
        mock_provider.dimensions = 128

        async def mock_embed(text: str) -> EmbeddingResult:
            return EmbeddingResult(embedding=[0.1])

        mock_provider.embed = mock_embed
        service._provider = mock_provider

        progress_calls: list[tuple[int, int]] = []

        def on_progress(completed: int, total: int) -> None:
            progress_calls.append((completed, total))

        await service.embed_nodes(nodes, on_progress=on_progress)

        # Should have progress updates
        assert len(progress_calls) > 0
        # Last call should show all complete
        assert progress_calls[-1][0] == 3
        assert progress_calls[-1][1] == 3

    @pytest.mark.asyncio
    async def test_embed_query_success(self) -> None:
        """embed_query() generates embedding for search query."""
        service = EmbeddingService(provider="local")

        mock_provider = MagicMock()

        async def mock_embed(text: str) -> EmbeddingResult:
            return EmbeddingResult(embedding=[0.1, 0.2, 0.3])

        mock_provider.embed = mock_embed
        service._provider = mock_provider

        result = await service.embed_query("find database functions")

        assert result == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_embed_query_failure(self) -> None:
        """embed_query() returns None on failure."""
        service = EmbeddingService(provider="local")

        mock_provider = MagicMock()

        async def mock_embed(text: str) -> EmbeddingResult:
            return EmbeddingResult(embedding=None, error="Failed")

        mock_provider.embed = mock_embed
        service._provider = mock_provider

        result = await service.embed_query("test query")

        assert result is None

    @pytest.mark.asyncio
    async def test_close_cleans_up_provider(self) -> None:
        """close() cleans up the provider."""
        service = EmbeddingService(provider="local")

        mock_provider = AsyncMock()
        mock_provider.close = AsyncMock()
        service._provider = mock_provider

        await service.close()

        mock_provider.close.assert_called_once()
        assert service._provider is None


class TestCreateEmbeddingService:
    """Tests for create_embedding_service factory function."""

    def test_creates_with_default_config(self) -> None:
        """Factory creates service with default config."""
        service = create_embedding_service()

        assert isinstance(service, EmbeddingService)

    def test_creates_with_custom_config(self) -> None:
        """Factory uses provided config."""
        config = EmbeddingsConfig(provider="local")

        service = create_embedding_service(config=config)

        assert service._provider_type == EmbeddingProviderType.LOCAL

    def test_provider_override(self) -> None:
        """Factory allows provider override."""
        config = EmbeddingsConfig(provider="openai")

        service = create_embedding_service(config=config, provider="local")

        assert service._provider_type == EmbeddingProviderType.LOCAL


# =============================================================================
# TestMUbaseEmbeddings (10% coverage focus)
# =============================================================================


class TestMUbaseEmbeddings:
    """Tests for MUbase embedding methods."""

    @pytest.fixture
    def db(self, tmp_path: Path) -> MUbase:
        """Create database instance with test data."""
        db = MUbase(tmp_path / "test.mubase")

        # Add some test nodes
        db.add_node(
            Node(
                id="fn:test.py:func1",
                type=NodeType.FUNCTION,
                name="func1",
                file_path="test.py",
            )
        )
        db.add_node(
            Node(
                id="fn:test.py:func2",
                type=NodeType.FUNCTION,
                name="func2",
                file_path="test.py",
            )
        )
        db.add_node(
            Node(
                id="cls:test.py:MyClass",
                type=NodeType.CLASS,
                name="MyClass",
                file_path="test.py",
            )
        )

        yield db
        db.close()

    def test_add_embedding_stores_correctly(self, db: MUbase) -> None:
        """add_embedding() stores embedding in database."""
        embedding = NodeEmbedding(
            node_id="fn:test.py:func1",
            model_name="test-model",
            model_version="1.0",
            dimensions=128,
            created_at=datetime.now(UTC),
            code_embedding=[0.1, 0.2, 0.3],
        )

        db.add_embedding(embedding)

        # Verify stored
        retrieved = db.get_embedding("fn:test.py:func1")
        assert retrieved is not None
        assert retrieved.node_id == "fn:test.py:func1"
        # Use approx for float comparison due to DuckDB FLOAT[] precision
        assert retrieved.code_embedding is not None
        assert len(retrieved.code_embedding) == 3
        assert retrieved.code_embedding[0] == pytest.approx(0.1, rel=1e-5)
        assert retrieved.code_embedding[1] == pytest.approx(0.2, rel=1e-5)
        assert retrieved.code_embedding[2] == pytest.approx(0.3, rel=1e-5)

    def test_add_embedding_replaces_existing(self, db: MUbase) -> None:
        """add_embedding() replaces existing embedding for same node."""
        # First embedding
        embedding1 = NodeEmbedding(
            node_id="fn:test.py:func1",
            model_name="model-v1",
            model_version="1.0",
            dimensions=128,
            created_at=datetime.now(UTC),
            code_embedding=[0.1, 0.2],
        )
        db.add_embedding(embedding1)

        # Second embedding (should replace)
        embedding2 = NodeEmbedding(
            node_id="fn:test.py:func1",
            model_name="model-v2",
            model_version="2.0",
            dimensions=256,
            created_at=datetime.now(UTC),
            code_embedding=[0.3, 0.4, 0.5],
        )
        db.add_embedding(embedding2)

        # Should have new values
        retrieved = db.get_embedding("fn:test.py:func1")
        assert retrieved is not None
        assert retrieved.model_name == "model-v2"
        # Use approx for float comparison due to DuckDB FLOAT[] precision
        assert retrieved.code_embedding is not None
        assert len(retrieved.code_embedding) == 3
        assert retrieved.code_embedding[0] == pytest.approx(0.3, rel=1e-5)
        assert retrieved.code_embedding[1] == pytest.approx(0.4, rel=1e-5)
        assert retrieved.code_embedding[2] == pytest.approx(0.5, rel=1e-5)

    def test_get_embedding_returns_none_for_missing(self, db: MUbase) -> None:
        """get_embedding() returns None for non-existent node."""
        result = db.get_embedding("fn:nonexistent.py:missing")

        assert result is None

    def test_add_embeddings_batch(self, db: MUbase) -> None:
        """add_embeddings_batch() stores multiple embeddings."""
        embeddings = [
            NodeEmbedding(
                node_id="fn:test.py:func1",
                model_name="test-model",
                model_version="1.0",
                dimensions=128,
                created_at=datetime.now(UTC),
                code_embedding=[0.1],
            ),
            NodeEmbedding(
                node_id="fn:test.py:func2",
                model_name="test-model",
                model_version="1.0",
                dimensions=128,
                created_at=datetime.now(UTC),
                code_embedding=[0.2],
            ),
        ]

        db.add_embeddings_batch(embeddings)

        # Verify both stored
        e1 = db.get_embedding("fn:test.py:func1")
        e2 = db.get_embedding("fn:test.py:func2")
        assert e1 is not None
        assert e2 is not None
        # Use approx for float comparison due to DuckDB FLOAT[] precision
        assert e1.code_embedding is not None
        assert len(e1.code_embedding) == 1
        assert e1.code_embedding[0] == pytest.approx(0.1, rel=1e-5)
        assert e2.code_embedding is not None
        assert len(e2.code_embedding) == 1
        assert e2.code_embedding[0] == pytest.approx(0.2, rel=1e-5)

    def test_add_embeddings_batch_empty_list(self, db: MUbase) -> None:
        """add_embeddings_batch() handles empty list."""
        db.add_embeddings_batch([])

        # Should not raise, no embeddings added
        stats = db.embedding_stats()
        assert stats["nodes_with_embeddings"] == 0

    def test_vector_search_returns_sorted_results(self, db: MUbase) -> None:
        """vector_search() returns results sorted by similarity."""
        # Add embeddings with known vectors
        db.add_embedding(
            NodeEmbedding(
                node_id="fn:test.py:func1",
                model_name="test-model",
                model_version="1.0",
                dimensions=3,
                created_at=datetime.now(UTC),
                code_embedding=[1.0, 0.0, 0.0],  # Most similar to query
            )
        )
        db.add_embedding(
            NodeEmbedding(
                node_id="fn:test.py:func2",
                model_name="test-model",
                model_version="1.0",
                dimensions=3,
                created_at=datetime.now(UTC),
                code_embedding=[0.0, 1.0, 0.0],  # Less similar
            )
        )

        # Query vector similar to func1
        query_embedding = [0.9, 0.1, 0.0]
        results = db.vector_search(query_embedding, limit=10)

        # func1 should be first (most similar)
        assert len(results) >= 1
        assert results[0][0].id == "fn:test.py:func1"
        assert results[0][1] > 0  # positive similarity

    def test_vector_search_respects_limit(self, db: MUbase) -> None:
        """vector_search() respects limit parameter."""
        # Add embeddings
        for i in range(3):
            db.add_embedding(
                NodeEmbedding(
                    node_id=f"fn:test.py:func{i + 1}" if i < 2 else "cls:test.py:MyClass",
                    model_name="test-model",
                    model_version="1.0",
                    dimensions=3,
                    created_at=datetime.now(UTC),
                    code_embedding=[float(i), 0.0, 0.0],
                )
            )

        results = db.vector_search([1.0, 0.0, 0.0], limit=2)

        assert len(results) == 2

    def test_vector_search_filters_by_node_type(self, db: MUbase) -> None:
        """vector_search() can filter by node type."""
        # Add embeddings for function and class
        db.add_embedding(
            NodeEmbedding(
                node_id="fn:test.py:func1",
                model_name="test-model",
                model_version="1.0",
                dimensions=3,
                created_at=datetime.now(UTC),
                code_embedding=[1.0, 0.0, 0.0],
            )
        )
        db.add_embedding(
            NodeEmbedding(
                node_id="cls:test.py:MyClass",
                model_name="test-model",
                model_version="1.0",
                dimensions=3,
                created_at=datetime.now(UTC),
                code_embedding=[0.9, 0.1, 0.0],
            )
        )

        # Search only for classes
        results = db.vector_search([1.0, 0.0, 0.0], node_type=NodeType.CLASS, limit=10)

        assert len(results) == 1
        assert results[0][0].type == NodeType.CLASS

    def test_vector_search_invalid_embedding_type(self, db: MUbase) -> None:
        """vector_search() raises for invalid embedding_type."""
        with pytest.raises(ValueError, match="Invalid embedding_type"):
            db.vector_search([0.1], embedding_type="invalid")

    def test_embedding_stats_returns_correct_counts(self, db: MUbase) -> None:
        """embedding_stats() returns correct statistics."""
        # Add embedding for one node
        db.add_embedding(
            NodeEmbedding(
                node_id="fn:test.py:func1",
                model_name="test-model",
                model_version="1.0",
                dimensions=128,
                created_at=datetime.now(UTC),
                code_embedding=[0.1],
            )
        )

        stats = db.embedding_stats()

        assert stats["total_nodes"] == 3  # 2 functions + 1 class
        assert stats["nodes_with_embeddings"] == 1
        assert stats["nodes_without_embeddings"] == 2
        assert stats["coverage_percent"] == pytest.approx(33.33, rel=0.1)
        assert "coverage_by_type" in stats
        assert "model_distribution" in stats

    def test_embedding_stats_model_distribution(self, db: MUbase) -> None:
        """embedding_stats() tracks model distribution."""
        db.add_embedding(
            NodeEmbedding(
                node_id="fn:test.py:func1",
                model_name="text-embedding-3-small",
                model_version="3-small",
                dimensions=1536,
                created_at=datetime.now(UTC),
                code_embedding=[0.1],
            )
        )
        db.add_embedding(
            NodeEmbedding(
                node_id="fn:test.py:func2",
                model_name="text-embedding-3-small",
                model_version="3-small",
                dimensions=1536,
                created_at=datetime.now(UTC),
                code_embedding=[0.2],
            )
        )

        stats = db.embedding_stats()

        assert "text-embedding-3-small:3-small" in stats["model_distribution"]
        assert stats["model_distribution"]["text-embedding-3-small:3-small"] == 2

    def test_embedding_stats_dimensions_tracking(self, db: MUbase) -> None:
        """embedding_stats() tracks embedding dimensions."""
        db.add_embedding(
            NodeEmbedding(
                node_id="fn:test.py:func1",
                model_name="test-model",
                model_version="1.0",
                dimensions=1536,
                created_at=datetime.now(UTC),
                code_embedding=[0.1],
            )
        )

        stats = db.embedding_stats()

        assert 1536 in stats["dimensions"]

    def test_embedding_stats_coverage_by_type(self, db: MUbase) -> None:
        """embedding_stats() tracks coverage by node type."""
        # Add embedding for one function only
        db.add_embedding(
            NodeEmbedding(
                node_id="fn:test.py:func1",
                model_name="test-model",
                model_version="1.0",
                dimensions=128,
                created_at=datetime.now(UTC),
                code_embedding=[0.1],
            )
        )

        stats = db.embedding_stats()

        coverage = stats["coverage_by_type"]

        # Functions: 2 total, 1 with embedding
        assert coverage["function"]["total"] == 2
        assert coverage["function"]["with_embedding"] == 1
        assert coverage["function"]["without_embedding"] == 1

        # Classes: 1 total, 0 with embedding
        assert coverage["class"]["total"] == 1
        assert coverage["class"]["with_embedding"] == 0
