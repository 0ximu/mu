"""LLM provider abstraction for MU Agent."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from mu.agent.tools import TOOL_DEFINITIONS

# OpenAI-format tool definitions (converted from Anthropic format)
OPENAI_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        },
    }
    for tool in TOOL_DEFINITIONS
]


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""

    content: str
    tool_calls: list[dict[str, Any]]  # List of {id, name, args}
    stop_reason: str  # "end_turn", "tool_use", etc.
    input_tokens: int
    output_tokens: int
    raw_content: Any = None  # Provider-specific raw content for continuations


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]],
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        """Send a chat request to the LLM."""
        pass

    @abstractmethod
    def format_tool_result(
        self,
        tool_call_id: str,
        result: str,
    ) -> dict[str, Any]:
        """Format a tool result for the provider's API."""
        pass

    @abstractmethod
    def format_assistant_message(
        self,
        content: Any,
    ) -> dict[str, Any]:
        """Format an assistant message for the provider's API."""
        pass

    @property
    @abstractmethod
    def tool_definitions(self) -> list[dict[str, Any]]:
        """Return the tool definitions in the provider's format."""
        pass


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider."""

    def __init__(self, model: str) -> None:
        self.model = model
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not set")
            import anthropic  # type: ignore[import-not-found,unused-ignore]

            self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    def chat(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]],
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        client = self._get_client()
        response = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=messages,
            tools=tools,
        )

        # Extract content and tool calls
        content_parts = []
        tool_calls = []
        for block in response.content:
            if hasattr(block, "text"):
                content_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    {
                        "id": block.id,
                        "name": block.name,
                        "args": block.input,
                    }
                )

        return LLMResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            stop_reason="tool_use" if response.stop_reason == "tool_use" else "end_turn",
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            raw_content=response.content,  # Keep raw content for continuation
        )

    def format_tool_result(
        self,
        tool_call_id: str,
        result: str,
    ) -> dict[str, Any]:
        return {
            "type": "tool_result",
            "tool_use_id": tool_call_id,
            "content": result,
        }

    def format_assistant_message(
        self,
        content: Any,
    ) -> dict[str, Any]:
        # Anthropic expects the raw content blocks
        return {"role": "assistant", "content": content}

    @property
    def tool_definitions(self) -> list[dict[str, Any]]:
        return TOOL_DEFINITIONS


class OpenAIProvider(LLMProvider):
    """OpenAI GPT provider."""

    def __init__(self, model: str) -> None:
        self.model = model
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not set")
            import openai  # type: ignore[import-not-found,unused-ignore]

            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def chat(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]],
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        import json

        client = self._get_client()

        # OpenAI uses system message in the messages list
        full_messages = [{"role": "system", "content": system}] + messages

        # GPT-5/o1/o3 models have different API requirements
        is_new_model = self.model.startswith(("gpt-5", "o1", "o3"))

        # Build kwargs based on model capabilities
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": full_messages,
        }

        # Token parameter differs
        if is_new_model:
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens
            kwargs["temperature"] = temperature  # Only supported on older models

        # Tools
        if tools:
            kwargs["tools"] = tools

        response = client.chat.completions.create(**kwargs)

        choice = response.choices[0]
        message = choice.message

        # Extract tool calls
        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "args": json.loads(tc.function.arguments),
                    }
                )

        stop_reason = "tool_use" if choice.finish_reason == "tool_calls" else "end_turn"

        return LLMResponse(
            content=message.content or "",
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
        )

    def format_tool_result(
        self,
        tool_call_id: str,
        result: str,
    ) -> dict[str, Any]:
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": result,
        }

    def format_assistant_message(
        self,
        content: Any,
    ) -> dict[str, Any]:
        # For OpenAI, we need to reconstruct the assistant message with tool_calls
        # This is called when we have tool calls to continue the conversation
        if isinstance(content, list):
            # This is Anthropic format, need to convert
            text_parts = []
            tool_calls = []
            for block in content:
                if hasattr(block, "text"):
                    text_parts.append(block.text)
                elif hasattr(block, "type") and block.type == "tool_use":
                    import json

                    tool_calls.append(
                        {
                            "id": block.id,
                            "type": "function",
                            "function": {
                                "name": block.name,
                                "arguments": json.dumps(block.input),
                            },
                        }
                    )
            msg: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts) or None}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            return msg
        return {"role": "assistant", "content": content}

    @property
    def tool_definitions(self) -> list[dict[str, Any]]:
        return OPENAI_TOOL_DEFINITIONS


def get_provider(model: str) -> LLMProvider:
    """Get the appropriate provider for a model.

    Args:
        model: Model identifier (e.g., "gpt-4o-mini", "claude-haiku-4-5-20251001")

    Returns:
        LLMProvider instance for the model.
    """
    if model.startswith("gpt-") or model.startswith("o1") or model.startswith("o3"):
        return OpenAIProvider(model)
    else:
        # Default to Anthropic for claude-* models
        return AnthropicProvider(model)


__all__ = [
    "LLMProvider",
    "LLMResponse",
    "AnthropicProvider",
    "OpenAIProvider",
    "get_provider",
    "OPENAI_TOOL_DEFINITIONS",
]
