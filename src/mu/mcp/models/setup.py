"""Setup models (status, bootstrap)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class BootstrapResult:
    """Result of mu_bootstrap."""

    success: bool
    mubase_path: str
    stats: dict[str, Any]
    duration_ms: float
    message: str
    suggestion: str | None = None
