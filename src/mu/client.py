"""Daemon communication client for CLI-to-daemon forwarding.

This module provides a thin client for communicating with the MU daemon.
When the daemon is running, CLI commands can forward requests to avoid
DuckDB lock conflicts from concurrent access.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, cast

import httpx

# Suppress httpx INFO logs by default (HTTP request logs pollute CLI output)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

__all__ = ["DaemonClient", "is_daemon_running", "forward_query"]

DEFAULT_DAEMON_URL = "http://localhost:9120"
DEFAULT_TIMEOUT = 2.0


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

    def _unwrap_response(self, data: dict[str, Any]) -> dict[str, Any]:
        """Unwrap response from Rust or Python daemon format.

        The Rust daemon wraps all responses in:
        {"success": bool, "data": {...}, "error": str|null, "duration_ms": int}

        The Python daemon wraps responses in:
        {"success": bool, "result": {...}, "error": str|null}

        Args:
            data: Raw response data.

        Returns:
            Unwrapped data dict.

        Raises:
            DaemonError: If success is False.
        """
        # Check if this is a wrapped response (Rust or Python daemon)
        if "success" in data:
            if not data.get("success"):
                raise DaemonError(data.get("error", "Request failed"))
            # Rust daemon uses "data", Python daemon uses "result"
            return cast(dict[str, Any], data.get("data") or data.get("result", data))
        # Some endpoints return data directly without wrapper
        return data

    def is_running(self, retry: bool = True) -> bool:
        """Check if the daemon is running.

        Args:
            retry: Whether to retry with backoff on failure.

        Returns:
            True if daemon is running and responding.
        """
        max_attempts = 3 if retry else 1
        backoff = 0.1  # Start with 100ms

        for attempt in range(max_attempts):
            try:
                response = self._client.get("/status")
                return response.status_code == 200
            except httpx.ConnectError:
                if attempt < max_attempts - 1:
                    import time

                    time.sleep(backoff)
                    backoff *= 2  # Exponential backoff
                    continue
                return False
            except httpx.TimeoutException:
                if attempt < max_attempts - 1:
                    import time

                    time.sleep(backoff)
                    backoff *= 2
                    continue
                return False
            except Exception:
                return False
        return False

    def query(self, muql: str, cwd: str | None = None) -> dict[str, Any]:
        """Execute a MUQL query via the daemon.

        Args:
            muql: The MUQL query string.
            cwd: Client working directory for multi-project routing.

        Returns:
            Query result as dict with columns, rows, etc.

        Raises:
            DaemonError: If query fails or daemon is not available.
        """
        try:
            payload: dict[str, Any] = {"muql": muql}
            if cwd:
                payload["cwd"] = cwd
            response = self._client.post(
                "/query",
                json=payload,
                timeout=30.0,  # Longer timeout for query execution
            )
            response.raise_for_status()
            data = cast(dict[str, Any], response.json())
            return self._unwrap_response(data)
        except httpx.ConnectError as e:
            raise DaemonError(f"Daemon not available: {e}") from e
        except httpx.HTTPStatusError as e:
            raise DaemonError(f"Query failed: {e.response.text}") from e
        except DaemonError:
            raise
        except Exception as e:
            raise DaemonError(f"Query error: {e}") from e

    def status(self, cwd: str | None = None) -> dict[str, Any]:
        """Get daemon status and statistics.

        Args:
            cwd: Client working directory for project-specific stats.

        Returns:
            Status information including uptime, connections, etc.

        Raises:
            DaemonError: If status request fails.
        """
        try:
            params = {"cwd": cwd} if cwd else {}
            response = self._client.get("/status", params=params)
            response.raise_for_status()
            data = cast(dict[str, Any], response.json())
            return self._unwrap_response(data)
        except httpx.ConnectError as e:
            raise DaemonError(f"Daemon not available: {e}") from e
        except DaemonError:
            raise
        except Exception as e:
            raise DaemonError(f"Status request failed: {e}") from e

    def context(
        self,
        question: str,
        max_tokens: int = 8000,
        exclude_tests: bool = False,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        """Get smart context for a question.

        Args:
            question: Natural language question.
            max_tokens: Maximum tokens in output.
            exclude_tests: Whether to exclude test files.
            cwd: Client working directory for multi-project routing.

        Returns:
            Context result with mu_text, token_count, nodes.

        Raises:
            DaemonError: If request fails.
        """
        try:
            payload: dict[str, Any] = {
                "question": question,
                "max_tokens": max_tokens,
                "exclude_tests": exclude_tests,
            }
            if cwd:
                payload["cwd"] = cwd
            response = self._client.post(
                "/context",
                json=payload,
                timeout=30.0,
            )
            response.raise_for_status()
            data = cast(dict[str, Any], response.json())
            return self._unwrap_response(data)
        except httpx.ConnectError as e:
            raise DaemonError(f"Daemon not available: {e}") from e
        except DaemonError:
            raise
        except Exception as e:
            raise DaemonError(f"Context request failed: {e}") from e

    def deps(
        self,
        node_id: str,
        depth: int = 2,
        direction: str = "outgoing",
        cwd: str | None = None,
    ) -> dict[str, Any]:
        """Get dependencies of a node.

        Args:
            node_id: Node ID or name.
            depth: How many levels deep to traverse (default 2).
            direction: "outgoing" (what it uses), "incoming" (what uses it), or "both".
            cwd: Client working directory for multi-project routing.

        Returns:
            Dependencies result with node_id, direction, dependencies list.
        """
        try:
            payload: dict[str, Any] = {
                "node": node_id,
                "depth": depth,
                "direction": direction,
            }
            if cwd:
                payload["cwd"] = cwd
            response = self._client.post(
                "/deps",
                json=payload,
                timeout=30.0,
            )
            response.raise_for_status()
            data = cast(dict[str, Any], response.json())
            result = self._unwrap_response(data)
            # Rust daemon returns a list of node IDs, normalize to expected dict format
            if isinstance(result, list):
                return {
                    "node_id": node_id,
                    "direction": direction,
                    "dependencies": result,
                }
            return result
        except httpx.ConnectError as e:
            raise DaemonError(f"Daemon not available: {e}") from e
        except httpx.HTTPStatusError as e:
            raise DaemonError(f"Deps request failed: {e.response.text}") from e
        except DaemonError:
            raise
        except Exception as e:
            raise DaemonError(f"Deps error: {e}") from e

    def impact(
        self,
        node_id: str,
        edge_types: list[str] | None = None,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        """Get downstream impact of a node.

        Args:
            node_id: Node ID or name.
            edge_types: Optional edge types to follow.
            cwd: Client working directory for multi-project routing.

        Returns:
            Impact result with node_id, impacted_nodes, count.
        """
        try:
            # Rust daemon uses 'node', Python daemon used 'node_id'
            payload: dict[str, Any] = {"node": node_id}
            if edge_types:
                payload["edge_types"] = edge_types
            if cwd:
                payload["cwd"] = cwd
            response = self._client.post(
                "/impact",
                json=payload,
                timeout=30.0,
            )
            response.raise_for_status()
            data = cast(dict[str, Any], response.json())
            result = self._unwrap_response(data)
            # Rust daemon returns a list, normalize to expected dict format
            if isinstance(result, list):
                return {
                    "node_id": node_id,
                    "impacted_nodes": result,
                    "count": len(result),
                }
            return result
        except httpx.ConnectError as e:
            raise DaemonError(f"Daemon not available: {e}") from e
        except httpx.HTTPStatusError as e:
            raise DaemonError(f"Impact request failed: {e.response.text}") from e
        except DaemonError:
            raise
        except Exception as e:
            raise DaemonError(f"Impact error: {e}") from e

    def ancestors(
        self,
        node_id: str,
        edge_types: list[str] | None = None,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        """Get upstream dependencies of a node.

        Args:
            node_id: Node ID or name.
            edge_types: Optional edge types to follow.
            cwd: Client working directory for multi-project routing.

        Returns:
            Ancestors result with node_id, ancestor_nodes, count.
        """
        try:
            # Rust daemon uses 'node', Python daemon used 'node_id'
            payload: dict[str, Any] = {"node": node_id}
            if edge_types:
                payload["edge_types"] = edge_types
            if cwd:
                payload["cwd"] = cwd
            response = self._client.post(
                "/ancestors",
                json=payload,
                timeout=30.0,
            )
            response.raise_for_status()
            data = cast(dict[str, Any], response.json())
            result = self._unwrap_response(data)
            # Rust daemon returns a list, normalize to expected dict format
            if isinstance(result, list):
                return {
                    "node_id": node_id,
                    "ancestor_nodes": result,
                    "count": len(result),
                }
            return result
        except httpx.ConnectError as e:
            raise DaemonError(f"Daemon not available: {e}") from e
        except httpx.HTTPStatusError as e:
            raise DaemonError(f"Ancestors request failed: {e.response.text}") from e
        except DaemonError:
            raise
        except Exception as e:
            raise DaemonError(f"Ancestors error: {e}") from e

    def cycles(
        self,
        edge_types: list[str] | None = None,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        """Detect circular dependencies.

        Args:
            edge_types: Optional edge types to consider.
            cwd: Client working directory for multi-project routing.

        Returns:
            Cycles result with cycles, cycle_count, total_nodes_in_cycles.
        """
        try:
            payload: dict[str, Any] = {}
            if edge_types:
                payload["edge_types"] = edge_types
            if cwd:
                payload["cwd"] = cwd
            response = self._client.post(
                "/cycles",
                json=payload,
                timeout=30.0,
            )
            response.raise_for_status()
            data = cast(dict[str, Any], response.json())
            result = self._unwrap_response(data)
            # Rust daemon returns a list of cycles, normalize to expected dict format
            if isinstance(result, list):
                total_nodes = sum(len(cycle) for cycle in result)
                return {
                    "cycles": result,
                    "cycle_count": len(result),
                    "total_nodes_in_cycles": total_nodes,
                }
            return result
        except httpx.ConnectError as e:
            raise DaemonError(f"Daemon not available: {e}") from e
        except httpx.HTTPStatusError as e:
            raise DaemonError(f"Cycles request failed: {e.response.text}") from e
        except DaemonError:
            raise
        except Exception as e:
            raise DaemonError(f"Cycles error: {e}") from e

    def context_omega(
        self,
        question: str,
        max_tokens: int = 8000,
        include_synthesized: bool = True,
        max_synthesized_macros: int = 5,
        include_seed: bool = True,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        """Get OMEGA-compressed context for a question.

        Args:
            question: Natural language question.
            max_tokens: Maximum tokens in output.
            include_synthesized: Include codebase-specific macros.
            max_synthesized_macros: Max synthesized macros to use.
            include_seed: Include macro definitions in full_output.
            cwd: Client working directory for multi-project routing.

        Returns:
            OMEGA context result with seed, body, compression metrics.

        Raises:
            DaemonError: If request fails.
        """
        try:
            payload: dict[str, Any] = {
                "question": question,
                "max_tokens": max_tokens,
                "include_synthesized": include_synthesized,
                "max_synthesized_macros": max_synthesized_macros,
                "include_seed": include_seed,
            }
            if cwd:
                payload["cwd"] = cwd
            response = self._client.post(
                "/context/omega",
                json=payload,
                timeout=30.0,
            )
            response.raise_for_status()
            data = cast(dict[str, Any], response.json())
            return self._unwrap_response(data)
        except httpx.ConnectError as e:
            raise DaemonError(f"Daemon not available: {e}") from e
        except httpx.HTTPStatusError as e:
            raise DaemonError(f"OMEGA context request failed: {e.response.text}") from e
        except DaemonError:
            raise
        except Exception as e:
            raise DaemonError(f"OMEGA context error: {e}") from e

    def patterns(
        self,
        category: str | None = None,
        refresh: bool = False,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        """Get detected codebase patterns.

        Args:
            category: Optional category filter (naming, architecture, testing, api, etc.).
            refresh: Force re-analysis (bypass cached patterns).
            cwd: Client working directory for multi-project routing.

        Returns:
            Patterns result with patterns, total_patterns, categories_found.

        Raises:
            DaemonError: If request fails.
        """
        try:
            payload: dict[str, Any] = {"refresh": refresh}
            if category:
                payload["category"] = category
            if cwd:
                payload["cwd"] = cwd
            response = self._client.post(
                "/patterns",
                json=payload,
                timeout=30.0,
            )
            response.raise_for_status()
            data = cast(dict[str, Any], response.json())
            return self._unwrap_response(data)
        except httpx.ConnectError as e:
            raise DaemonError(f"Daemon not available: {e}") from e
        except httpx.HTTPStatusError as e:
            raise DaemonError(f"Patterns request failed: {e.response.text}") from e
        except DaemonError:
            raise
        except Exception as e:
            raise DaemonError(f"Patterns error: {e}") from e

    def warn(
        self,
        target: str,
        cwd: str | None = None,
    ) -> dict[str, Any]:
        """Get proactive warnings about a target.

        Args:
            target: File path or node ID to analyze.
            cwd: Client working directory for multi-project routing.

        Returns:
            Warnings result with target, target_type, warnings, summary, risk_score.

        Raises:
            DaemonError: If request fails.
        """
        try:
            payload: dict[str, Any] = {"target": target}
            if cwd:
                payload["cwd"] = cwd
            response = self._client.post(
                "/warn",
                json=payload,
                timeout=30.0,
            )
            response.raise_for_status()
            data = cast(dict[str, Any], response.json())
            return self._unwrap_response(data)
        except httpx.ConnectError as e:
            raise DaemonError(f"Daemon not available: {e}") from e
        except httpx.HTTPStatusError as e:
            raise DaemonError(f"Warn request failed: {e.response.text}") from e
        except DaemonError:
            raise
        except Exception as e:
            raise DaemonError(f"Warn error: {e}") from e

    def node(self, node_id: str, cwd: str | None = None) -> dict[str, Any]:
        """Get a node by ID.

        Args:
            node_id: Node ID (e.g., "mod:src/cli.py", "cls:src/auth.py:AuthService").
            cwd: Client working directory for multi-project routing.

        Returns:
            Node information dict with id, name, type, file_path, line_start, line_end.

        Raises:
            DaemonError: If request fails or node not found.
        """
        try:
            # URL-encode the node_id since it may contain special characters
            import urllib.parse

            encoded_id = urllib.parse.quote(node_id, safe="")
            params = {"cwd": cwd} if cwd else {}
            response = self._client.get(
                f"/node/{encoded_id}",
                params=params,
                timeout=10.0,
            )
            response.raise_for_status()
            data = cast(dict[str, Any], response.json())
            return self._unwrap_response(data)
        except httpx.ConnectError as e:
            raise DaemonError(f"Daemon not available: {e}") from e
        except httpx.HTTPStatusError as e:
            raise DaemonError(f"Node request failed: {e.response.text}") from e
        except DaemonError:
            raise
        except Exception as e:
            raise DaemonError(f"Node error: {e}") from e

    def find_node(
        self,
        name: str,
        cwd: str | None = None,
    ) -> dict[str, Any] | None:
        """Find a node by name or file path (fuzzy match).

        Uses MUQL to search for nodes by name pattern or file_path.

        Args:
            name: Node name or file path to search for.
            cwd: Client working directory for multi-project routing.

        Returns:
            First matching node info, or None if not found.
        """
        try:
            # Check if it looks like a file path
            looks_like_path = (
                "/" in name
                or "\\" in name
                or name.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rs", ".cs"))
            )

            if looks_like_path:
                # Normalize path separators
                normalized = name.replace("\\", "/")
                # Try by file_path (exact or suffix match)
                query = f"SELECT * FROM nodes WHERE file_path = '{normalized}' AND type = 'module' LIMIT 1"
                result = self.query(query, cwd=cwd)
                if result.get("rows"):
                    row = result["rows"][0]
                    cols = result.get("columns", [])
                    return dict(zip(cols, row, strict=False))

                # Try suffix match
                query = f"SELECT * FROM nodes WHERE file_path LIKE '%{normalized}' AND type = 'module' LIMIT 1"
                result = self.query(query, cwd=cwd)
                if result.get("rows"):
                    row = result["rows"][0]
                    cols = result.get("columns", [])
                    return dict(zip(cols, row, strict=False))

            # First try exact name match
            query = f"SELECT * FROM nodes WHERE name = '{name}' LIMIT 1"
            result = self.query(query, cwd=cwd)
            if result.get("rows"):
                row = result["rows"][0]
                cols = result.get("columns", [])
                return dict(zip(cols, row, strict=False))

            # Fall back to pattern match
            query = f"SELECT * FROM nodes WHERE name LIKE '%{name}%' ORDER BY CASE WHEN name = '{name}' THEN 0 ELSE 1 END LIMIT 1"
            result = self.query(query, cwd=cwd)
            if result.get("rows"):
                row = result["rows"][0]
                cols = result.get("columns", [])
                return dict(zip(cols, row, strict=False))

            return None
        except DaemonError:
            return None

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


def is_daemon_running(url: str = DEFAULT_DAEMON_URL, retry: bool = True) -> bool:
    """Check if the MU daemon is running.

    Args:
        url: Daemon base URL.
        retry: Whether to retry with backoff on failure.

    Returns:
        True if daemon is running and responding.
    """
    max_attempts = 3 if retry else 1
    backoff = 0.1  # Start with 100ms

    for attempt in range(max_attempts):
        try:
            response = httpx.get(
                f"{url}/status",
                timeout=DEFAULT_TIMEOUT,
            )
            return response.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            if attempt < max_attempts - 1:
                import time

                time.sleep(backoff)
                backoff *= 2
                continue
            return False
        except Exception:
            return False
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
