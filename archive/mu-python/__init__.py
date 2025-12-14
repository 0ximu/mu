"""MU - Machine Understanding: Semantic compression for AI-native development."""

from typing import Any

__version__ = "0.1.0"

# Rust core availability flag
RUST_CORE_AVAILABLE: bool = False
RUST_CORE_VERSION: str | None = None
rust_core: Any = None

try:
    from mu import _core

    rust_core = _core
    RUST_CORE_AVAILABLE = True
    RUST_CORE_VERSION = _core.version()
except ImportError:
    pass
