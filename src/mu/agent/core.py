"""Core MUAgent class implementation."""

from __future__ import annotations

from typing import Any

from mu.agent.memory import ConversationMemory
from mu.agent.models import AgentConfig, AgentResponse, GraphSummary
from mu.agent.prompt import format_system_prompt
from mu.agent.providers import LLMProvider, get_provider
from mu.agent.tools import execute_tool, format_tool_result
from mu.client import DaemonClient, DaemonError


class MUAgent:
    """MU Agent - Code structure specialist.

    Answers questions about codebases by querying .mubase graph database.
    Supports multiple LLM providers (OpenAI, Anthropic) for flexibility.

    Example:
        >>> agent = MUAgent()
        >>> response = agent.ask("How does authentication work?")
        >>> print(response.content)

        # Use OpenAI instead
        >>> config = AgentConfig(model="gpt-4o-mini")
        >>> agent = MUAgent(config)

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
        self._provider: LLMProvider | None = None

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

        # Get LLM provider
        try:
            provider = self._get_provider()
        except ValueError as e:
            return AgentResponse(
                content="",
                error=str(e),
            )

        # Build system prompt with graph summary
        system_prompt = format_system_prompt(self._graph_summary.to_text())

        # Get messages for API
        messages = self.memory.get_messages()

        try:
            # Call LLM with tools
            response = provider.chat(
                messages=messages,
                system=system_prompt,
                tools=provider.tool_definitions,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
            )

            # Process response (handle tool calls)
            content, tool_calls_made, tokens_used = self._process_response(
                provider, response, messages, system_prompt
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

    def _get_provider(self) -> LLMProvider:
        """Get or create the LLM provider."""
        if self._provider is None:
            self._provider = get_provider(self.config.model)
        return self._provider

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
        provider: LLMProvider,
        response: Any,
        messages: list[dict[str, Any]],
        system_prompt: str,
    ) -> tuple[str, int, int]:
        """Process LLM response, executing tool calls as needed.

        Args:
            provider: The LLM provider.
            response: The initial LLM response.
            messages: Current conversation messages.
            system_prompt: The system prompt used.

        Returns:
            Tuple of (final_content, tool_calls_made, total_tokens).
        """
        from mu.agent.providers import LLMResponse

        tool_calls_made = 0
        total_tokens = response.input_tokens + response.output_tokens

        mu_client = self._get_mu_client()

        # Handle tool use loop - enforce single-tool strategy
        # The model should answer after 1 tool call, but allow 1 retry if empty
        max_iterations = 1
        iteration = 0

        while response.stop_reason == "tool_use" and iteration < max_iterations:
            iteration += 1

            # Execute tool calls
            tool_results = []
            for tc in response.tool_calls:
                tool_calls_made += 1
                result = execute_tool(tc["name"], tc["args"], mu_client)
                formatted_result = format_tool_result(result)
                tool_results.append(
                    provider.format_tool_result(tc["id"], formatted_result)
                )

            # Build continuation messages
            # For OpenAI, we need to include the assistant message with tool_calls
            assistant_msg = self._build_assistant_message(provider, response)
            continuation_messages = messages + [assistant_msg]

            # Add tool results - format differs by provider
            from mu.agent.providers import OpenAIProvider

            if isinstance(provider, OpenAIProvider):
                # OpenAI: each tool result is a separate message
                continuation_messages.extend(tool_results)
            else:
                # Anthropic: tool results go in a user message
                continuation_messages.append({"role": "user", "content": tool_results})

            # Continue conversation
            response = provider.chat(
                messages=continuation_messages,
                system=system_prompt,
                tools=provider.tool_definitions,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
            )

            total_tokens += response.input_tokens + response.output_tokens

        return response.content, tool_calls_made, total_tokens

    def _build_assistant_message(
        self,
        provider: LLMProvider,
        response: Any,
    ) -> dict[str, Any]:
        """Build assistant message for continuation."""
        from mu.agent.providers import AnthropicProvider, OpenAIProvider

        if isinstance(provider, OpenAIProvider):
            # OpenAI needs the tool_calls in the message
            import json

            msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content or None,
            }
            if response.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["args"]),
                        },
                    }
                    for tc in response.tool_calls
                ]
            return msg
        else:
            # Anthropic - use raw content blocks (tool_use blocks)
            return {"role": "assistant", "content": response.raw_content}

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
