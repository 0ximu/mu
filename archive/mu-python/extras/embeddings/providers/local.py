"""Local embedding provider using sentence-transformers.

Uses sentence-transformers models for local embedding generation
without requiring external API calls.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from mu.extras.embeddings.providers.base import (
    BatchEmbeddingResult,
    EmbeddingResult,
)

logger = logging.getLogger(__name__)


# Model configurations
LOCAL_MODELS: dict[str, dict[str, Any]] = {
    "all-MiniLM-L6-v2": {
        "dimensions": 384,
        "max_tokens": 256,
        "version": "v2",
        "hf_name": "sentence-transformers/all-MiniLM-L6-v2",
    },
    "all-mpnet-base-v2": {
        "dimensions": 768,
        "max_tokens": 384,
        "version": "v2",
        "hf_name": "sentence-transformers/all-mpnet-base-v2",
    },
    "paraphrase-MiniLM-L6-v2": {
        "dimensions": 384,
        "max_tokens": 128,
        "version": "v2",
        "hf_name": "sentence-transformers/paraphrase-MiniLM-L6-v2",
    },
}


def _get_model_dimensions(model_path: str) -> int:
    """Detect embedding dimensions from a model's config.

    Args:
        model_path: Path to the model directory

    Returns:
        Embedding dimensions (default: 384 if detection fails)
    """
    import json
    from pathlib import Path

    config_path = Path(model_path) / "config_sentence_transformers.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            # sentence-transformers stores dims in various places
            if "embedding_dimension" in config:
                dim_val = config["embedding_dimension"]
                if isinstance(dim_val, int):
                    return dim_val
                return int(str(dim_val))
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    # Try to get from the model config.json
    config_path = Path(model_path) / "config.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            # Common locations for hidden size (embedding dim)
            for key in ["hidden_size", "dim", "d_model"]:
                if key in config:
                    dim_val = config[key]
                    if isinstance(dim_val, int):
                        return dim_val
                    return int(str(dim_val))
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    # Fallback to default MiniLM dimensions
    return 384


def _detect_device() -> str:
    """Detect best available device for inference.

    Returns:
        Device string: 'cuda', 'mps', or 'cpu'
    """
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


class LocalEmbeddingProvider:
    """Local embedding provider using sentence-transformers.

    Lazy-loads the model on first use to avoid startup overhead.
    Supports GPU acceleration with automatic device detection.
    """

    DEFAULT_MODEL = "all-MiniLM-L6-v2"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        device: str = "auto",
        model_path: str | None = None,
    ) -> None:
        """Initialize local embedding provider.

        Args:
            model: Model name (default: all-MiniLM-L6-v2)
            device: Device to use ('auto', 'cpu', 'cuda', 'mps')
            model_path: Path to a custom sentence-transformers model directory.
                       If provided, this takes precedence over model name.
        """
        self._model_path = model_path
        self._is_custom_model = model_path is not None

        if self._is_custom_model:
            # Custom model from local path
            import os

            assert model_path is not None  # for type checker
            if not os.path.isdir(model_path):
                raise ValueError(f"Model path does not exist: {model_path}")
            self._model_name = os.path.basename(model_path)
            # Detect dimensions from config
            dims = _get_model_dimensions(model_path)
            self._model_config: dict[str, Any] = {
                "dimensions": dims,
                "max_tokens": 256,
                "version": "custom",
                "hf_name": model_path,  # Use path as hf_name
            }
        else:
            # Standard model from registry
            if model not in LOCAL_MODELS:
                raise ValueError(
                    f"Unknown model: {model}. Available models: {list(LOCAL_MODELS.keys())}"
                )
            self._model_name = model
            self._model_config = LOCAL_MODELS[model]

        self._device = device if device != "auto" else _detect_device()
        self._model: Any = None  # Lazy loaded
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._load_lock = asyncio.Lock()

    @property
    def dimensions(self) -> int:
        """Return the dimension of embeddings."""
        return int(self._model_config["dimensions"])

    @property
    def model_name(self) -> str:
        """Return the model name."""
        return self._model_name

    @property
    def model_version(self) -> str:
        """Return the model version."""
        return str(self._model_config["version"])

    @property
    def max_tokens(self) -> int:
        """Return maximum tokens per input."""
        return int(self._model_config["max_tokens"])

    @property
    def device(self) -> str:
        """Return the device being used."""
        return self._device

    def _load_model_sync(self) -> Any:
        """Load the sentence-transformers model synchronously."""
        import os

        # Suppress tokenizer parallelism warnings (happens when forking after load)
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

        try:
            from sentence_transformers import SentenceTransformer

            hf_name = str(self._model_config["hf_name"])
            logger.info(f"Loading model {hf_name} on {self._device}")

            model = SentenceTransformer(hf_name, device=self._device)
            return model

        except ImportError as e:
            raise ImportError(
                "sentence-transformers is required for local embeddings. "
                "Install with: pip install sentence-transformers"
            ) from e
        except Exception as e:
            # Try CPU fallback if GPU fails
            if self._device != "cpu":
                logger.warning(f"Failed to load on {self._device}, falling back to CPU: {e}")
                self._device = "cpu"
                return self._load_model_sync()
            raise

    async def _ensure_model(self) -> Any:
        """Ensure model is loaded."""
        if self._model is None:
            async with self._load_lock:
                if self._model is None:
                    loop = asyncio.get_running_loop()
                    self._model = await loop.run_in_executor(
                        self._executor,
                        self._load_model_sync,
                    )
        return self._model

    def _encode_sync(self, texts: list[str]) -> list[list[float]]:
        """Encode texts synchronously using the model."""
        if self._model is None:
            raise RuntimeError("Model not loaded")

        embeddings = self._model.encode(
            texts,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [emb.tolist() for emb in embeddings]

    async def embed(self, text: str) -> EmbeddingResult:
        """Generate embedding for a single text.

        Args:
            text: The text to embed

        Returns:
            EmbeddingResult with the embedding vector or error
        """
        if not text.strip():
            return EmbeddingResult(
                embedding=None,
                error="Empty text provided",
            )

        try:
            await self._ensure_model()

            loop = asyncio.get_running_loop()
            embeddings = await loop.run_in_executor(
                self._executor,
                self._encode_sync,
                [text],
            )

            return EmbeddingResult(
                embedding=embeddings[0] if embeddings else None,
                tokens_used=0,  # Local models don't track tokens
            )

        except Exception as e:
            return EmbeddingResult(
                embedding=None,
                error=str(e),
            )

    async def embed_batch(self, texts: list[str]) -> BatchEmbeddingResult:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            BatchEmbeddingResult with embeddings in same order as input
        """
        if not texts:
            return BatchEmbeddingResult(embeddings=[], tokens_used=0)

        # Track empty texts
        valid_indices: list[int] = []
        valid_texts: list[str] = []
        for i, text in enumerate(texts):
            if text.strip():
                valid_indices.append(i)
                valid_texts.append(text)

        if not valid_texts:
            return BatchEmbeddingResult(
                embeddings=[None] * len(texts),
                tokens_used=0,
                errors=["Empty text"] * len(texts),
            )

        try:
            await self._ensure_model()

            loop = asyncio.get_running_loop()
            valid_embeddings = await loop.run_in_executor(
                self._executor,
                self._encode_sync,
                valid_texts,
            )

            # Map back to original indices
            result_embeddings: list[list[float] | None] = [None] * len(texts)
            errors: list[str | None] = [None] * len(texts)

            for i, idx in enumerate(valid_indices):
                if i < len(valid_embeddings):
                    result_embeddings[idx] = valid_embeddings[i]

            # Mark empty texts as errors
            for i, text in enumerate(texts):
                if not text.strip():
                    errors[i] = "Empty text"

            return BatchEmbeddingResult(
                embeddings=result_embeddings,
                tokens_used=0,
                errors=errors if any(e is not None for e in errors) else None,
            )

        except Exception as e:
            return BatchEmbeddingResult(
                embeddings=[None] * len(texts),
                tokens_used=0,
                errors=[str(e)] * len(texts),
            )

    async def close(self) -> None:
        """Clean up resources."""
        self._model = None
        self._executor.shutdown(wait=True)


__all__ = [
    "LocalEmbeddingProvider",
    "LOCAL_MODELS",
]
