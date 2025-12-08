"""Conversation memory management for MU Agent."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from mu.agent.models import Message


@dataclass
class ConversationMemory:
    """Manages conversation state for MU Agent.

    Tracks conversation history, mentioned code nodes, and provides
    methods to convert messages to API format.

    Attributes:
        messages: List of conversation messages.
        mentioned_nodes: Set of node IDs/names mentioned in conversation.
        graph_summary: Cached high-level graph summary text.
        max_messages: Maximum messages to retain (prevents unbounded growth).
    """

    messages: list[Message] = field(default_factory=list)
    mentioned_nodes: set[str] = field(default_factory=set)
    graph_summary: str | None = None
    max_messages: int = 50

    def add_user_message(self, content: str) -> None:
        """Add a user message to the conversation.

        Also extracts and tracks any mentioned code nodes from the content.

        Args:
            content: The user's message text.
        """
        self.messages.append(Message(role="user", content=content))
        self._enforce_limit()

        # Extract mentioned nodes from user message
        new_nodes = self.extract_mentioned_nodes(content)
        self.mentioned_nodes.update(new_nodes)

    def add_assistant_message(
        self,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        """Add an assistant message to the conversation.

        Also extracts and tracks any mentioned code nodes from the content.

        Args:
            content: The assistant's response text.
            tool_calls: Optional list of tool calls made.
        """
        self.messages.append(Message(role="assistant", content=content, tool_calls=tool_calls))
        self._enforce_limit()

        # Extract mentioned nodes from assistant response
        new_nodes = self.extract_mentioned_nodes(content)
        self.mentioned_nodes.update(new_nodes)

    def get_messages(self) -> list[dict[str, Any]]:
        """Get messages in Anthropic API format.

        Returns:
            List of message dictionaries suitable for the Anthropic API.
        """
        return [msg.to_api_format() for msg in self.messages]

    def get_recent_messages(self, count: int = 10) -> list[dict[str, Any]]:
        """Get the most recent messages for context.

        Args:
            count: Maximum number of messages to return.

        Returns:
            List of recent message dictionaries.
        """
        return [msg.to_api_format() for msg in self.messages[-count:]]

    def clear(self) -> None:
        """Clear all conversation state."""
        self.messages.clear()
        self.mentioned_nodes.clear()
        self.graph_summary = None

    def extract_mentioned_nodes(self, text: str) -> set[str]:
        """Extract code node references from text.

        Looks for patterns like:
        - Class names: PascalCase words (e.g., AuthService, UserRepository)
        - Function names: snake_case with parentheses (e.g., process_payment())
        - Module paths: dotted paths (e.g., src/auth.py, mu.parser)
        - Node IDs: prefixed IDs (e.g., mod:src/auth.py, cls:AuthService)

        Args:
            text: Text to extract node references from.

        Returns:
            Set of extracted node names/identifiers.
        """
        nodes: set[str] = set()

        # Match node IDs (mod:, cls:, fn:, etc.)
        node_id_pattern = r"\b(mod|cls|fn|class|func|module):[a-zA-Z0-9_/\.\:]+\b"
        for match in re.finditer(node_id_pattern, text):
            nodes.add(match.group(0))

        # Match PascalCase class names (at least 2 parts or known patterns)
        pascal_pattern = r"\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b"
        for match in re.finditer(pascal_pattern, text):
            name = match.group(1)
            # Filter out common words that match the pattern
            if name not in {"HttpClient", "IntelliSense"}:
                nodes.add(name)

        # Match function calls with parentheses
        func_pattern = r"\b([a-z_][a-z0-9_]*)\s*\("
        for match in re.finditer(func_pattern, text):
            name = match.group(1)
            # Filter out common words
            if name not in {"if", "for", "while", "with", "def", "class", "return"}:
                nodes.add(name)

        # Match file paths (e.g., src/auth/service.py)
        path_pattern = r"\b([a-zA-Z_][a-zA-Z0-9_]*(?:/[a-zA-Z_][a-zA-Z0-9_]*)+\.py)\b"
        for match in re.finditer(path_pattern, text):
            nodes.add(match.group(1))

        return nodes

    def get_context_summary(self) -> str:
        """Get a summary of the conversation context.

        Returns:
            A summary string including message count and mentioned nodes.
        """
        lines = [
            f"Messages: {len(self.messages)}",
        ]
        if self.mentioned_nodes:
            nodes_list = sorted(self.mentioned_nodes)[:20]
            lines.append(f"Discussed nodes: {', '.join(nodes_list)}")
            if len(self.mentioned_nodes) > 20:
                lines.append(f"  ... and {len(self.mentioned_nodes) - 20} more")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation of the conversation memory.
        """
        return {
            "messages": [msg.to_dict() for msg in self.messages],
            "mentioned_nodes": list(self.mentioned_nodes),
            "graph_summary": self.graph_summary,
            "max_messages": self.max_messages,
        }

    def _enforce_limit(self) -> None:
        """Enforce the maximum message limit.

        When the limit is exceeded, removes the oldest messages while
        keeping a reasonable context window.
        """
        if len(self.messages) > self.max_messages:
            # Keep the most recent messages, but ensure we don't break
            # a user/assistant pair
            excess = len(self.messages) - self.max_messages
            # Remove from the beginning, but in pairs to maintain coherence
            remove_count = (excess + 1) // 2 * 2  # Round up to even number
            self.messages = self.messages[remove_count:]

    @property
    def message_count(self) -> int:
        """Get the current number of messages."""
        return len(self.messages)

    @property
    def is_empty(self) -> bool:
        """Check if the conversation is empty."""
        return len(self.messages) == 0


__all__ = ["ConversationMemory"]
