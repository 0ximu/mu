"""Core MUAgent class implementation."""

from __future__ import annotations

import os
from typing import Any

from mu.agent.memory import ConversationMemory
from mu.agent.models import AgentConfig, AgentResponse, GraphSummary
from mu.agent.prompt import format_system_prompt
from mu.agent.tools import TOOL_DEFINITIONS, execute_tool, format_tool_result
from mu.client import DaemonClient, DaemonError


class MUAgent:
    """MU Agent - Code structure specialist.

    Answers questions about codebases by querying .mubase graph database.
    Designed to run on cheap models (Haiku) to minimize token costs.

    Example:
        >>> agent = MUAgent()
        >>> response = agent.ask("How does authentication work?")
        >>> print(response.content)

        # Follow-up questions maintain context
        >>> response = agent.ask("What depends on it?")

        # Reset conversation
        >>> agent.reset()

    Attributes:
        config: Agent configuration.
        memory: Conversation memory manager.
    """

    def __init__(self, config: AgentConfig | None = None) -> None:
        """Initialize the MU Agent.

        Args:
            config: Optional agent configuration. Uses defaults if not provided.
        """
        self.config = config or AgentConfig()
        self.memory = ConversationMemory()
        self._graph_summary: GraphSummary | None = None
        self._mu_client: DaemonClient | None = None
        self._anthropic_client: Any = None

    def ask(self, question: str) -> AgentResponse:
        """Ask a question about the codebase.

        Args:
            question: Natural language question about code structure.

        Returns:
            AgentResponse with content and metadata.
        """
        # Lazy-load graph summary
        if self._graph_summary is None:
            self._graph_summary = self._get_graph_summary()

        # Add to conversation memory
        self.memory.add_user_message(question)

        # Get Anthropic client
        client = self._get_anthropic_client()
        if client is None:
            return AgentResponse(
                content="",
                error="ANTHROPIC_API_KEY not set. Please set the environment variable.",
            )

        # Build system prompt with graph summary
        system_prompt = format_system_prompt(self._graph_summary.to_text())

        # Get messages for API
        messages = self.memory.get_messages()

        try:
            # Call LLM with tools
            response = client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                system=system_prompt,
                messages=messages,
                tools=TOOL_DEFINITIONS,
            )

            # Process response (handle tool calls)
            content, tool_calls_made, tokens_used = self._process_response(
                response, messages, system_prompt
            )

            # Add to memory
            self.memory.add_assistant_message(content)

            return AgentResponse(
                content=content,
                tool_calls_made=tool_calls_made,
                tokens_used=tokens_used,
                model=self.config.model,
            )

        except Exception as e:
            return AgentResponse(
                content="",
                error=f"LLM request failed: {e}",
                model=self.config.model,
            )

    def query(self, muql: str) -> dict[str, Any]:
        """Execute MUQL query directly (bypass LLM).

        Args:
            muql: The MUQL query string.

        Returns:
            Query result dictionary.
        """
        client = self._get_mu_client()
        try:
            return client.query(muql)
        except DaemonError as e:
            return {"error": str(e)}

    def context(self, question: str, max_tokens: int = 4000) -> dict[str, Any]:
        """Get smart context directly (bypass LLM).

        Args:
            question: Natural language question.
            max_tokens: Maximum tokens in output.

        Returns:
            Context result dictionary.
        """
        client = self._get_mu_client()
        try:
            return client.context(question, max_tokens=max_tokens)
        except DaemonError as e:
            return {"error": str(e)}

    def deps(
        self,
        node: str,
        direction: str = "outgoing",
        depth: int = 2,
    ) -> dict[str, Any]:
        """Get dependencies directly (bypass LLM).

        Args:
            node: Node name or ID.
            direction: Direction to traverse ("outgoing", "incoming", "both").
            depth: How many levels deep.

        Returns:
            Dependencies result dictionary.
        """
        client = self._get_mu_client()
        try:
            # Build MUQL query
            if direction == "incoming":
                muql = f"SHOW dependents OF {node} DEPTH {depth}"
            else:
                muql = f"SHOW dependencies OF {node} DEPTH {depth}"
            return client.query(muql)
        except DaemonError as e:
            return {"error": str(e)}

    def impact(self, node: str) -> dict[str, Any]:
        """Get impact analysis directly (bypass LLM).

        Args:
            node: Node name or ID.

        Returns:
            Impact result dictionary.
        """
        client = self._get_mu_client()
        try:
            return client.impact(node)
        except DaemonError as e:
            return {"error": str(e)}

    def ancestors(self, node: str) -> dict[str, Any]:
        """Get ancestors directly (bypass LLM).

        Args:
            node: Node name or ID.

        Returns:
            Ancestors result dictionary.
        """
        client = self._get_mu_client()
        try:
            return client.ancestors(node)
        except DaemonError as e:
            return {"error": str(e)}

    def cycles(self, edge_types: list[str] | None = None) -> dict[str, Any]:
        """Detect circular dependencies directly (bypass LLM).

        Args:
            edge_types: Optional list of edge types to consider.

        Returns:
            Cycles result dictionary.
        """
        client = self._get_mu_client()
        try:
            return client.cycles(edge_types=edge_types)
        except DaemonError as e:
            return {"error": str(e)}

    def reset(self) -> None:
        """Reset conversation memory and cached state."""
        self.memory.clear()
        self._graph_summary = None

    def _get_mu_client(self) -> DaemonClient:
        """Get or create the MU daemon client."""
        if self._mu_client is None:
            self._mu_client = DaemonClient(base_url=self.config.daemon_url)
        return self._mu_client

    def _get_anthropic_client(self) -> Any:
        """Get or create the Anthropic client."""
        if self._anthropic_client is None:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                return None
            try:
                import anthropic  # type: ignore[import-not-found]

                self._anthropic_client = anthropic.Anthropic(api_key=api_key)
            except ImportError:
                return None
        return self._anthropic_client

    def _get_graph_summary(self) -> GraphSummary:
        """Get high-level summary of the graph from daemon."""
        client = self._get_mu_client()
        try:
            status = client.status()
            if not status:
                return GraphSummary()

            stats = status.get("stats", {})

            # Get top-level modules
            top_modules: list[str] = []
            try:
                result = client.query(
                    "SELECT name FROM modules WHERE name NOT LIKE 'test%' LIMIT 10"
                )
                if "rows" in result:
                    top_modules = [row[0] for row in result["rows"] if row]
            except Exception:
                pass

            return GraphSummary(
                node_count=stats.get("node_count", 0),
                edge_count=stats.get("edge_count", 0),
                modules=stats.get("nodes_by_type", {}).get("module", 0),
                classes=stats.get("nodes_by_type", {}).get("class", 0),
                functions=stats.get("nodes_by_type", {}).get("function", 0),
                top_level_modules=top_modules,
            )
        except DaemonError:
            return GraphSummary()

    def _process_response(
        self,
        response: Any,
        messages: list[dict[str, Any]],
        system_prompt: str,
    ) -> tuple[str, int, int]:
        """Process LLM response, executing tool calls as needed.

        Args:
            response: The initial LLM response.
            messages: Current conversation messages.
            system_prompt: The system prompt used.

        Returns:
            Tuple of (final_content, tool_calls_made, total_tokens).
        """
        tool_calls_made = 0
        total_tokens = 0

        # Track tokens from initial response
        if hasattr(response, "usage"):
            total_tokens += response.usage.input_tokens + response.usage.output_tokens

        client = self._get_anthropic_client()
        mu_client = self._get_mu_client()

        # Handle tool use loop (max 10 iterations to prevent infinite loops)
        max_iterations = 10
        iteration = 0

        while response.stop_reason == "tool_use" and iteration < max_iterations:
            iteration += 1
            tool_results = []

            for content in response.content:
                if content.type == "tool_use":
                    tool_calls_made += 1
                    # Execute the tool
                    result = execute_tool(content.name, content.input, mu_client)
                    formatted_result = format_tool_result(result)

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": content.id,
                            "content": formatted_result,
                        }
                    )

            # Continue conversation with tool results
            response = client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                system=system_prompt,
                messages=messages
                + [
                    {"role": "assistant", "content": response.content},
                    {"role": "user", "content": tool_results},
                ],
                tools=TOOL_DEFINITIONS,
            )

            # Track tokens
            if hasattr(response, "usage"):
                total_tokens += response.usage.input_tokens + response.usage.output_tokens

        # Extract text response
        content_parts = []
        for content in response.content:
            if hasattr(content, "text"):
                content_parts.append(content.text)

        final_content = "".join(content_parts)
        return final_content, tool_calls_made, total_tokens

    def close(self) -> None:
        """Close all client connections."""
        if self._mu_client is not None:
            self._mu_client.close()
            self._mu_client = None

    def __enter__(self) -> MUAgent:
        """Enter context manager."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Exit context manager."""
        self.close()


__all__ = ["MUAgent"]
