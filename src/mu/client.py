"""Daemon communication client for CLI-to-daemon forwarding.

This module provides a thin client for communicating with the MU daemon.
When the daemon is running, CLI commands can forward requests to avoid
DuckDB lock conflicts from concurrent access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import httpx

__all__ = ["DaemonClient", "is_daemon_running", "forward_query"]

DEFAULT_DAEMON_URL = "http://localhost:8765"
DEFAULT_TIMEOUT = 0.5


@dataclass
class DaemonClient:
    """Client for communicating with MU daemon.

    Example:
        >>> client = DaemonClient()
        >>> if client.is_running():
        ...     result = client.query("SELECT * FROM functions LIMIT 10")
        ...     print(result)
    """

    base_url: str = DEFAULT_DAEMON_URL
    timeout: float = DEFAULT_TIMEOUT
    _client: httpx.Client = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Initialize the HTTP client."""
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout, connect=self.timeout),
        )

    def is_running(self) -> bool:
        """Check if the daemon is running.

        Returns:
            True if daemon is running and responding.
        """
        try:
            response = self._client.get("/status")
            return response.status_code == 200
        except httpx.ConnectError:
            return False
        except httpx.TimeoutException:
            return False
        except Exception:
            return False

    def query(self, muql: str) -> dict[str, Any]:
        """Execute a MUQL query via the daemon.

        Args:
            muql: The MUQL query string.

        Returns:
            Query result as dict with columns, rows, etc.

        Raises:
            DaemonError: If query fails or daemon is not available.
        """
        try:
            response = self._client.post(
                "/query",
                json={"muql": muql},
                timeout=30.0,  # Longer timeout for query execution
            )
            response.raise_for_status()
            data = cast(dict[str, Any], response.json())
            if not data.get("success"):
                raise DaemonError(data.get("error", "Query failed"))
            result = data.get("result", {})
            return cast(dict[str, Any], result)
        except httpx.ConnectError as e:
            raise DaemonError(f"Daemon not available: {e}") from e
        except httpx.HTTPStatusError as e:
            raise DaemonError(f"Query failed: {e.response.text}") from e
        except Exception as e:
            raise DaemonError(f"Query error: {e}") from e

    def status(self) -> dict[str, Any]:
        """Get daemon status and statistics.

        Returns:
            Status information including uptime, connections, etc.

        Raises:
            DaemonError: If status request fails.
        """
        try:
            response = self._client.get("/status")
            response.raise_for_status()
            return cast(dict[str, Any], response.json())
        except httpx.ConnectError as e:
            raise DaemonError(f"Daemon not available: {e}") from e
        except Exception as e:
            raise DaemonError(f"Status request failed: {e}") from e

    def context(
        self,
        question: str,
        max_tokens: int = 8000,
        exclude_tests: bool = False,
    ) -> dict[str, Any]:
        """Get smart context for a question.

        Args:
            question: Natural language question.
            max_tokens: Maximum tokens in output.
            exclude_tests: Whether to exclude test files.

        Returns:
            Context result with mu_text, token_count, nodes.

        Raises:
            DaemonError: If request fails.
        """
        try:
            response = self._client.post(
                "/context",
                json={
                    "question": question,
                    "max_tokens": max_tokens,
                    "exclude_tests": exclude_tests,
                },
                timeout=30.0,
            )
            response.raise_for_status()
            return cast(dict[str, Any], response.json())
        except httpx.ConnectError as e:
            raise DaemonError(f"Daemon not available: {e}") from e
        except Exception as e:
            raise DaemonError(f"Context request failed: {e}") from e

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> DaemonClient:
        """Enter context manager."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Exit context manager."""
        self.close()


class DaemonError(Exception):
    """Exception raised for daemon communication errors."""

    pass


# =============================================================================
# Convenience Functions
# =============================================================================


def is_daemon_running(url: str = DEFAULT_DAEMON_URL) -> bool:
    """Check if the MU daemon is running.

    Args:
        url: Daemon base URL.

    Returns:
        True if daemon is running and responding.
    """
    try:
        response = httpx.get(
            f"{url}/status",
            timeout=DEFAULT_TIMEOUT,
        )
        return response.status_code == 200
    except Exception:
        return False


def forward_query(muql: str, url: str = DEFAULT_DAEMON_URL) -> dict[str, Any]:
    """Forward a MUQL query to the daemon.

    Args:
        muql: The MUQL query string.
        url: Daemon base URL.

    Returns:
        Query result as dict.

    Raises:
        DaemonError: If query fails.
    """
    with DaemonClient(base_url=url) as client:
        return client.query(muql)
