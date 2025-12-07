"""Data models for MU Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class AgentConfig:
    """Configuration for MU Agent.

    Attributes:
        model: The Anthropic model to use for chat completions.
        max_tokens: Maximum tokens in the response.
        temperature: Sampling temperature (0.0 = deterministic).
        mubase_path: Optional path to .mubase file.
        daemon_url: URL of the MU daemon.
    """

    model: str = "gpt-5-nano-2025-08-07"  # Cheapest & fastest, supports tool use
    max_tokens: int = 4096
    temperature: float = 0.0
    mubase_path: str | None = None
    daemon_url: str = "http://localhost:8765"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "mubase_path": self.mubase_path,
            "daemon_url": self.daemon_url,
        }


@dataclass
class Message:
    """A conversation message.

    Attributes:
        role: The message role (user, assistant, or system).
        content: The text content of the message.
        tool_calls: Optional list of tool calls made by assistant.
        tool_results: Optional list of tool results from execution.
    """

    role: Literal["user", "assistant", "system"]
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_results: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, Any] = {
            "role": self.role,
            "content": self.content,
        }
        if self.tool_calls is not None:
            result["tool_calls"] = self.tool_calls
        if self.tool_results is not None:
            result["tool_results"] = self.tool_results
        return result

    def to_api_format(self) -> dict[str, Any]:
        """Convert to Anthropic API message format."""
        return {
            "role": self.role,
            "content": self.content,
        }


@dataclass
class ToolCall:
    """A tool call made by the assistant.

    Attributes:
        id: Unique identifier for this tool call.
        name: The name of the tool being called.
        args: Arguments passed to the tool.
    """

    id: str
    name: str
    args: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "args": self.args,
        }


@dataclass
class ToolResult:
    """Result from executing a tool.

    Attributes:
        tool_call_id: ID of the tool call this result is for.
        content: The result content (JSON-serializable).
        error: Error message if tool execution failed.
    """

    tool_call_id: str
    content: Any
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, Any] = {
            "tool_call_id": self.tool_call_id,
            "content": self.content,
        }
        if self.error is not None:
            result["error"] = self.error
        return result


@dataclass
class AgentResponse:
    """Response from MU Agent.

    Attributes:
        content: The text response from the agent.
        tool_calls_made: Number of tool calls made during this response.
        tokens_used: Total tokens used (input + output).
        model: The model used for generation.
        error: Error message if the request failed.
    """

    content: str
    tool_calls_made: int = 0
    tokens_used: int = 0
    model: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, Any] = {
            "content": self.content,
            "tool_calls_made": self.tool_calls_made,
            "tokens_used": self.tokens_used,
            "model": self.model,
        }
        if self.error is not None:
            result["error"] = self.error
        return result

    @property
    def success(self) -> bool:
        """Check if the response was successful."""
        return self.error is None


@dataclass
class GraphSummary:
    """Summary of the code graph for context.

    Attributes:
        node_count: Total number of nodes in the graph.
        edge_count: Total number of edges in the graph.
        modules: Number of module nodes.
        classes: Number of class nodes.
        functions: Number of function nodes.
        top_level_modules: List of top-level module names.
    """

    node_count: int = 0
    edge_count: int = 0
    modules: int = 0
    classes: int = 0
    functions: int = 0
    top_level_modules: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "modules": self.modules,
            "classes": self.classes,
            "functions": self.functions,
            "top_level_modules": self.top_level_modules,
        }

    def to_text(self) -> str:
        """Format as human-readable text for system prompt."""
        lines = [
            f"- Total Nodes: {self.node_count}",
            f"- Total Edges: {self.edge_count}",
            f"- Modules: {self.modules}",
            f"- Classes: {self.classes}",
            f"- Functions: {self.functions}",
        ]
        if self.top_level_modules:
            modules_str = ", ".join(self.top_level_modules[:10])
            if len(self.top_level_modules) > 10:
                modules_str += f" ... and {len(self.top_level_modules) - 10} more"
            lines.append(f"- Top-level modules: {modules_str}")
        return "\n".join(lines)


__all__ = [
    "AgentConfig",
    "Message",
    "ToolCall",
    "ToolResult",
    "AgentResponse",
    "GraphSummary",
]
