"""Tests for the MU Agent module."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from mu.agent.cli import agent
from mu.agent.formats import (
    format_cycles_summary,
    format_deps_tree,
    format_for_terminal,
    format_impact_summary,
    format_mu_output,
    truncate_response,
)
from mu.agent.memory import ConversationMemory
from mu.agent.models import (
    AgentConfig,
    AgentResponse,
    GraphSummary,
    Message,
    ToolCall,
    ToolResult,
)
from mu.agent.prompt import (
    EXAMPLES,
    SYSTEM_PROMPT,
    format_system_prompt,
    get_default_graph_summary,
)
from mu.agent.tools import TOOL_DEFINITIONS, execute_tool, format_tool_result

# =============================================================================
# Test Data Models
# =============================================================================


class TestAgentConfig:
    """Tests for AgentConfig dataclass."""

    def test_default_values(self) -> None:
        """Test AgentConfig initializes with defaults."""
        config = AgentConfig()
        assert config.model == "gpt-5-nano-2025-08-07"
        assert config.max_tokens == 4096
        assert config.temperature == 0.0
        assert config.mubase_path is None
        assert config.daemon_url == "http://localhost:8765"

    def test_custom_values(self) -> None:
        """Test AgentConfig with custom values."""
        config = AgentConfig(
            model="claude-3-5-sonnet-latest",
            max_tokens=8192,
            temperature=0.5,
            mubase_path="/path/to/.mubase",
            daemon_url="http://custom:9000",
        )
        assert config.model == "claude-3-5-sonnet-latest"
        assert config.max_tokens == 8192
        assert config.temperature == 0.5
        assert config.mubase_path == "/path/to/.mubase"
        assert config.daemon_url == "http://custom:9000"

    def test_to_dict(self) -> None:
        """Test AgentConfig.to_dict() serialization."""
        config = AgentConfig(model="test-model", max_tokens=1000)
        result = config.to_dict()

        assert result["model"] == "test-model"
        assert result["max_tokens"] == 1000
        assert result["temperature"] == 0.0
        assert result["mubase_path"] is None
        assert result["daemon_url"] == "http://localhost:8765"
        assert isinstance(result, dict)


class TestMessage:
    """Tests for Message dataclass."""

    def test_user_message(self) -> None:
        """Test creating a user message."""
        msg = Message(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.tool_calls is None
        assert msg.tool_results is None

    def test_assistant_message_with_tool_calls(self) -> None:
        """Test creating assistant message with tool calls."""
        tool_calls = [{"name": "mu_query", "args": {"muql": "SELECT 1"}}]
        msg = Message(role="assistant", content="Response", tool_calls=tool_calls)
        assert msg.role == "assistant"
        assert msg.tool_calls == tool_calls

    def test_to_dict(self) -> None:
        """Test Message.to_dict() serialization."""
        msg = Message(role="user", content="Test message")
        result = msg.to_dict()

        assert result["role"] == "user"
        assert result["content"] == "Test message"
        assert "tool_calls" not in result
        assert "tool_results" not in result

    def test_to_dict_with_optional_fields(self) -> None:
        """Test Message.to_dict() with optional fields."""
        tool_calls = [{"name": "mu_query"}]
        tool_results = [{"result": "data"}]
        msg = Message(
            role="assistant",
            content="Response",
            tool_calls=tool_calls,
            tool_results=tool_results,
        )
        result = msg.to_dict()

        assert result["tool_calls"] == tool_calls
        assert result["tool_results"] == tool_results

    def test_to_api_format(self) -> None:
        """Test Message.to_api_format() for Anthropic API."""
        msg = Message(role="user", content="Query", tool_calls=[{"name": "test"}])
        result = msg.to_api_format()

        assert result == {"role": "user", "content": "Query"}
        assert "tool_calls" not in result


class TestToolCall:
    """Tests for ToolCall dataclass."""

    def test_creation(self) -> None:
        """Test creating a ToolCall."""
        tc = ToolCall(id="123", name="mu_query", args={"muql": "SELECT 1"})
        assert tc.id == "123"
        assert tc.name == "mu_query"
        assert tc.args == {"muql": "SELECT 1"}

    def test_to_dict(self) -> None:
        """Test ToolCall.to_dict() serialization."""
        tc = ToolCall(id="abc", name="mu_deps", args={"node": "AuthService"})
        result = tc.to_dict()

        assert result["id"] == "abc"
        assert result["name"] == "mu_deps"
        assert result["args"] == {"node": "AuthService"}


class TestToolResult:
    """Tests for ToolResult dataclass."""

    def test_success_result(self) -> None:
        """Test creating a successful ToolResult."""
        tr = ToolResult(tool_call_id="123", content={"rows": []})
        assert tr.tool_call_id == "123"
        assert tr.content == {"rows": []}
        assert tr.error is None

    def test_error_result(self) -> None:
        """Test creating an error ToolResult."""
        tr = ToolResult(tool_call_id="123", content=None, error="Query failed")
        assert tr.error == "Query failed"

    def test_to_dict(self) -> None:
        """Test ToolResult.to_dict() serialization."""
        tr = ToolResult(tool_call_id="abc", content={"data": 42})
        result = tr.to_dict()

        assert result["tool_call_id"] == "abc"
        assert result["content"] == {"data": 42}
        assert "error" not in result

    def test_to_dict_with_error(self) -> None:
        """Test ToolResult.to_dict() with error."""
        tr = ToolResult(tool_call_id="abc", content=None, error="Failed")
        result = tr.to_dict()

        assert result["error"] == "Failed"


class TestAgentResponse:
    """Tests for AgentResponse dataclass."""

    def test_success_response(self) -> None:
        """Test creating a successful response."""
        resp = AgentResponse(
            content="Answer",
            tool_calls_made=2,
            tokens_used=500,
            model="gpt-5-nano-2025-08-07",
        )
        assert resp.content == "Answer"
        assert resp.tool_calls_made == 2
        assert resp.tokens_used == 500
        assert resp.error is None
        assert resp.success is True

    def test_error_response(self) -> None:
        """Test creating an error response."""
        resp = AgentResponse(content="", error="API key not set")
        assert resp.content == ""
        assert resp.error == "API key not set"
        assert resp.success is False

    def test_default_values(self) -> None:
        """Test AgentResponse default values."""
        resp = AgentResponse(content="Test")
        assert resp.tool_calls_made == 0
        assert resp.tokens_used == 0
        assert resp.model == ""
        assert resp.error is None

    def test_to_dict(self) -> None:
        """Test AgentResponse.to_dict() serialization."""
        resp = AgentResponse(
            content="Hello",
            tool_calls_made=1,
            tokens_used=100,
            model="test-model",
        )
        result = resp.to_dict()

        assert result["content"] == "Hello"
        assert result["tool_calls_made"] == 1
        assert result["tokens_used"] == 100
        assert result["model"] == "test-model"
        assert "error" not in result

    def test_to_dict_with_error(self) -> None:
        """Test AgentResponse.to_dict() with error."""
        resp = AgentResponse(content="", error="Error message")
        result = resp.to_dict()

        assert result["error"] == "Error message"


class TestGraphSummary:
    """Tests for GraphSummary dataclass."""

    def test_default_values(self) -> None:
        """Test GraphSummary default values."""
        gs = GraphSummary()
        assert gs.node_count == 0
        assert gs.edge_count == 0
        assert gs.modules == 0
        assert gs.classes == 0
        assert gs.functions == 0
        assert gs.top_level_modules == []

    def test_custom_values(self) -> None:
        """Test GraphSummary with custom values."""
        gs = GraphSummary(
            node_count=100,
            edge_count=200,
            modules=10,
            classes=30,
            functions=60,
            top_level_modules=["auth", "api", "db"],
        )
        assert gs.node_count == 100
        assert gs.modules == 10
        assert gs.top_level_modules == ["auth", "api", "db"]

    def test_to_dict(self) -> None:
        """Test GraphSummary.to_dict() serialization."""
        gs = GraphSummary(node_count=50, modules=5, top_level_modules=["mod1"])
        result = gs.to_dict()

        assert result["node_count"] == 50
        assert result["modules"] == 5
        assert result["top_level_modules"] == ["mod1"]

    def test_to_text(self) -> None:
        """Test GraphSummary.to_text() formatting."""
        gs = GraphSummary(
            node_count=100,
            edge_count=200,
            modules=10,
            classes=30,
            functions=60,
            top_level_modules=["auth", "api"],
        )
        text = gs.to_text()

        assert "Total Nodes: 100" in text
        assert "Total Edges: 200" in text
        assert "Modules: 10" in text
        assert "Classes: 30" in text
        assert "Functions: 60" in text
        assert "auth, api" in text

    def test_to_text_truncates_modules(self) -> None:
        """Test GraphSummary.to_text() truncates long module lists."""
        modules = [f"mod{i}" for i in range(15)]
        gs = GraphSummary(top_level_modules=modules)
        text = gs.to_text()

        assert "... and 5 more" in text

    def test_to_text_without_modules(self) -> None:
        """Test GraphSummary.to_text() without top-level modules."""
        gs = GraphSummary(node_count=50)
        text = gs.to_text()

        assert "top-level modules" not in text.lower()


# =============================================================================
# Test Conversation Memory
# =============================================================================


class TestConversationMemory:
    """Tests for ConversationMemory class."""

    def test_init(self) -> None:
        """Test ConversationMemory initialization."""
        memory = ConversationMemory()
        assert memory.messages == []
        assert memory.mentioned_nodes == set()
        assert memory.graph_summary is None
        assert memory.max_messages == 50
        assert memory.is_empty is True
        assert memory.message_count == 0

    def test_add_user_message(self) -> None:
        """Test adding a user message."""
        memory = ConversationMemory()
        memory.add_user_message("Hello agent")

        assert memory.message_count == 1
        assert memory.is_empty is False
        assert memory.messages[0].role == "user"
        assert memory.messages[0].content == "Hello agent"

    def test_add_assistant_message(self) -> None:
        """Test adding an assistant message."""
        memory = ConversationMemory()
        memory.add_assistant_message("Response from agent")

        assert memory.message_count == 1
        assert memory.messages[0].role == "assistant"
        assert memory.messages[0].content == "Response from agent"

    def test_add_assistant_message_with_tool_calls(self) -> None:
        """Test adding assistant message with tool calls."""
        memory = ConversationMemory()
        tool_calls = [{"name": "mu_query", "args": {"muql": "SELECT 1"}}]
        memory.add_assistant_message("Response", tool_calls=tool_calls)

        assert memory.messages[0].tool_calls == tool_calls

    def test_get_messages_format(self) -> None:
        """Test get_messages returns Anthropic API format."""
        memory = ConversationMemory()
        memory.add_user_message("Question")
        memory.add_assistant_message("Answer")

        messages = memory.get_messages()

        assert len(messages) == 2
        assert messages[0] == {"role": "user", "content": "Question"}
        assert messages[1] == {"role": "assistant", "content": "Answer"}

    def test_get_recent_messages(self) -> None:
        """Test get_recent_messages returns subset."""
        memory = ConversationMemory()
        for i in range(5):
            memory.add_user_message(f"Message {i}")

        recent = memory.get_recent_messages(count=2)
        assert len(recent) == 2
        assert recent[0]["content"] == "Message 3"
        assert recent[1]["content"] == "Message 4"

    def test_clear(self) -> None:
        """Test clear resets all state."""
        memory = ConversationMemory()
        memory.add_user_message("Test")
        memory.mentioned_nodes.add("AuthService")
        memory.graph_summary = "Summary text"

        memory.clear()

        assert memory.messages == []
        assert memory.mentioned_nodes == set()
        assert memory.graph_summary is None
        assert memory.is_empty is True

    def test_max_messages_limit(self) -> None:
        """Test max_messages limit enforcement."""
        memory = ConversationMemory(max_messages=5)

        # Add 10 messages (5 pairs)
        for i in range(10):
            memory.add_user_message(f"Message {i}")

        # Should be limited to max_messages
        assert memory.message_count <= 5

    def test_max_messages_removes_in_pairs(self) -> None:
        """Test that message limit removes in pairs."""
        memory = ConversationMemory(max_messages=4)

        # Add 6 messages
        for i in range(6):
            if i % 2 == 0:
                memory.add_user_message(f"User {i}")
            else:
                memory.add_assistant_message(f"Assistant {i}")

        # Should have 4 messages (2 pairs removed)
        assert memory.message_count <= 4

    def test_extract_mentioned_nodes_class_names(self) -> None:
        """Test extracting PascalCase class names."""
        memory = ConversationMemory()
        nodes = memory.extract_mentioned_nodes("Check the AuthService and UserRepository")

        assert "AuthService" in nodes
        assert "UserRepository" in nodes

    def test_extract_mentioned_nodes_function_calls(self) -> None:
        """Test extracting function calls."""
        memory = ConversationMemory()
        nodes = memory.extract_mentioned_nodes("Call process_payment() and validate_token()")

        assert "process_payment" in nodes
        assert "validate_token" in nodes

    def test_extract_mentioned_nodes_file_paths(self) -> None:
        """Test extracting file paths."""
        memory = ConversationMemory()
        nodes = memory.extract_mentioned_nodes("Look at src/auth/service.py")

        assert "src/auth/service.py" in nodes

    def test_extract_mentioned_nodes_node_ids(self) -> None:
        """Test extracting node IDs."""
        memory = ConversationMemory()
        nodes = memory.extract_mentioned_nodes("Check mod:src/auth.py and cls:AuthService")

        assert "mod:src/auth.py" in nodes
        assert "cls:AuthService" in nodes

    def test_extract_mentioned_nodes_filters_keywords(self) -> None:
        """Test that common keywords are filtered."""
        memory = ConversationMemory()
        nodes = memory.extract_mentioned_nodes("if (x) return y")

        assert "if" not in nodes
        assert "return" not in nodes

    def test_mentioned_nodes_tracked_across_messages(self) -> None:
        """Test mentioned nodes accumulate across messages."""
        memory = ConversationMemory()
        memory.add_user_message("What about AuthService?")
        memory.add_assistant_message("AuthService uses UserRepository")

        assert "AuthService" in memory.mentioned_nodes
        assert "UserRepository" in memory.mentioned_nodes

    def test_get_context_summary(self) -> None:
        """Test get_context_summary formatting."""
        memory = ConversationMemory()
        memory.add_user_message("Test AuthService")
        memory.add_assistant_message("It uses UserRepository")

        summary = memory.get_context_summary()

        assert "Messages: 2" in summary
        assert "AuthService" in summary

    def test_to_dict(self) -> None:
        """Test ConversationMemory.to_dict() serialization."""
        memory = ConversationMemory()
        memory.add_user_message("Test")
        memory.mentioned_nodes.add("TestNode")
        memory.graph_summary = "Summary"

        result = memory.to_dict()

        assert len(result["messages"]) == 1
        assert "TestNode" in result["mentioned_nodes"]
        assert result["graph_summary"] == "Summary"
        assert result["max_messages"] == 50


# =============================================================================
# Test System Prompt
# =============================================================================


class TestSystemPrompt:
    """Tests for system prompt module."""

    def test_system_prompt_exists(self) -> None:
        """Test SYSTEM_PROMPT is defined and non-empty."""
        assert SYSTEM_PROMPT is not None
        assert len(SYSTEM_PROMPT) > 0

    def test_system_prompt_has_placeholder(self) -> None:
        """Test SYSTEM_PROMPT contains graph_summary placeholder."""
        assert "{graph_summary}" in SYSTEM_PROMPT

    def test_system_prompt_has_tool_docs(self) -> None:
        """Test SYSTEM_PROMPT documents tools."""
        assert "mu_query" in SYSTEM_PROMPT
        assert "mu_context" in SYSTEM_PROMPT
        assert "mu_deps" in SYSTEM_PROMPT
        assert "mu_impact" in SYSTEM_PROMPT
        assert "mu_ancestors" in SYSTEM_PROMPT
        assert "mu_cycles" in SYSTEM_PROMPT

    def test_system_prompt_has_mu_format_guidelines(self) -> None:
        """Test SYSTEM_PROMPT includes MU format guidelines."""
        # Check for sigil documentation
        assert "!" in SYSTEM_PROMPT  # Module sigil
        assert "$" in SYSTEM_PROMPT  # Class sigil
        assert "#" in SYSTEM_PROMPT  # Function sigil

    def test_examples_list_exists(self) -> None:
        """Test EXAMPLES list exists and has items."""
        assert isinstance(EXAMPLES, list)
        assert len(EXAMPLES) >= 5  # PRD specifies 5+ examples

    def test_examples_structure(self) -> None:
        """Test each example has required fields."""
        for example in EXAMPLES:
            assert "question" in example
            assert "actions" in example
            assert "response" in example
            assert isinstance(example["actions"], list)

    def test_format_system_prompt(self) -> None:
        """Test format_system_prompt inserts graph summary."""
        summary = "- Nodes: 100\n- Edges: 200"
        result = format_system_prompt(summary)

        assert "- Nodes: 100" in result
        assert "- Edges: 200" in result
        assert "{graph_summary}" not in result

    def test_get_default_graph_summary(self) -> None:
        """Test get_default_graph_summary returns placeholder."""
        summary = get_default_graph_summary()

        assert "Graph not available" in summary
        assert "mu kernel build" in summary


# =============================================================================
# Test Tool Definitions
# =============================================================================


class TestToolDefinitions:
    """Tests for tool definitions."""

    def test_all_tools_defined(self) -> None:
        """Test all 6 required tools are defined."""
        tool_names = [t["name"] for t in TOOL_DEFINITIONS]

        assert "mu_query" in tool_names
        assert "mu_context" in tool_names
        assert "mu_deps" in tool_names
        assert "mu_impact" in tool_names
        assert "mu_ancestors" in tool_names
        assert "mu_cycles" in tool_names
        assert len(TOOL_DEFINITIONS) == 6

    def test_tool_schema_structure(self) -> None:
        """Test each tool has valid Anthropic schema structure."""
        for tool in TOOL_DEFINITIONS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool

            schema = tool["input_schema"]
            assert schema["type"] == "object"
            assert "properties" in schema
            assert "required" in schema

    def test_mu_query_schema(self) -> None:
        """Test mu_query tool schema."""
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "mu_query")

        assert "muql" in tool["input_schema"]["properties"]
        assert "muql" in tool["input_schema"]["required"]

    def test_mu_context_schema(self) -> None:
        """Test mu_context tool schema."""
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "mu_context")

        assert "question" in tool["input_schema"]["properties"]
        assert "max_tokens" in tool["input_schema"]["properties"]
        assert "question" in tool["input_schema"]["required"]

    def test_mu_deps_schema(self) -> None:
        """Test mu_deps tool schema."""
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "mu_deps")
        props = tool["input_schema"]["properties"]

        assert "node" in props
        assert "depth" in props
        assert "direction" in props
        assert "node" in tool["input_schema"]["required"]

    def test_mu_impact_schema(self) -> None:
        """Test mu_impact tool schema."""
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "mu_impact")

        assert "node" in tool["input_schema"]["properties"]
        assert "edge_types" in tool["input_schema"]["properties"]
        assert "node" in tool["input_schema"]["required"]


class TestExecuteTool:
    """Tests for execute_tool function."""

    def test_execute_mu_query(self) -> None:
        """Test execute_tool dispatches mu_query correctly."""
        mock_client = MagicMock()
        mock_client.query.return_value = {"columns": ["name"], "rows": [["test"]]}

        result = execute_tool("mu_query", {"muql": "SELECT name FROM functions"}, mock_client)

        mock_client.query.assert_called_once_with("SELECT name FROM functions")
        assert result["columns"] == ["name"]

    def test_execute_mu_query_missing_arg(self) -> None:
        """Test execute_tool returns error for missing muql."""
        mock_client = MagicMock()

        result = execute_tool("mu_query", {}, mock_client)

        assert "error" in result
        assert "muql" in result["error"].lower()

    def test_execute_mu_context(self) -> None:
        """Test execute_tool dispatches mu_context correctly."""
        mock_client = MagicMock()
        mock_client.context.return_value = {"mu_text": "!module Test", "token_count": 100}

        result = execute_tool(
            "mu_context",
            {"question": "How does auth work?", "max_tokens": 2000},
            mock_client,
        )

        mock_client.context.assert_called_once_with("How does auth work?", max_tokens=2000)
        assert result["mu_text"] == "!module Test"

    def test_execute_mu_deps_outgoing(self) -> None:
        """Test execute_tool dispatches mu_deps outgoing correctly."""
        mock_client = MagicMock()
        mock_client.query.return_value = {"columns": ["id"], "rows": []}

        result = execute_tool(
            "mu_deps",
            {"node": "AuthService", "depth": 3, "direction": "outgoing"},
            mock_client,
        )

        call_args = mock_client.query.call_args[0][0]
        assert "dependencies" in call_args.lower()
        assert "AuthService" in call_args
        assert result["direction"] == "outgoing"

    def test_execute_mu_deps_incoming(self) -> None:
        """Test execute_tool dispatches mu_deps incoming correctly."""
        mock_client = MagicMock()
        mock_client.query.return_value = {"columns": ["id"], "rows": []}

        execute_tool(
            "mu_deps",
            {"node": "AuthService", "direction": "incoming"},
            mock_client,
        )

        call_args = mock_client.query.call_args[0][0]
        assert "dependents" in call_args.lower()

    def test_execute_mu_impact(self) -> None:
        """Test execute_tool dispatches mu_impact correctly."""
        mock_client = MagicMock()
        mock_client.impact.return_value = {"impacted_nodes": ["node1", "node2"]}

        result = execute_tool("mu_impact", {"node": "User"}, mock_client)

        mock_client.impact.assert_called_once_with("User", edge_types=None)
        assert result["impacted_nodes"] == ["node1", "node2"]

    def test_execute_mu_ancestors(self) -> None:
        """Test execute_tool dispatches mu_ancestors correctly."""
        mock_client = MagicMock()
        mock_client.ancestors.return_value = {"ancestor_nodes": ["parent1"]}

        result = execute_tool("mu_ancestors", {"node": "Child"}, mock_client)

        mock_client.ancestors.assert_called_once_with("Child", edge_types=None)
        assert result["ancestor_nodes"] == ["parent1"]

    def test_execute_mu_cycles(self) -> None:
        """Test execute_tool dispatches mu_cycles correctly."""
        mock_client = MagicMock()
        mock_client.cycles.return_value = {"cycles": [["a", "b", "a"]]}

        result = execute_tool("mu_cycles", {}, mock_client)

        mock_client.cycles.assert_called_once_with(edge_types=None)
        assert result["cycles"] == [["a", "b", "a"]]

    def test_execute_unknown_tool(self) -> None:
        """Test execute_tool returns error for unknown tool."""
        mock_client = MagicMock()

        result = execute_tool("unknown_tool", {}, mock_client)

        assert "error" in result
        assert "Unknown tool" in result["error"]

    def test_execute_tool_handles_exception(self) -> None:
        """Test execute_tool handles exceptions gracefully."""
        mock_client = MagicMock()
        mock_client.query.side_effect = Exception("Connection failed")

        result = execute_tool("mu_query", {"muql": "SELECT 1"}, mock_client)

        assert "error" in result
        assert "Connection failed" in result["error"]


class TestFormatToolResult:
    """Tests for format_tool_result function."""

    def test_format_error_result(self) -> None:
        """Test formatting error results."""
        result = format_tool_result({"error": "Query failed"})

        assert "Error: Query failed" in result

    def test_format_query_result(self) -> None:
        """Test formatting query results."""
        result = format_tool_result(
            {
                "columns": ["name", "complexity"],
                "rows": [["test_func", 10], ["other_func", 20]],
                "row_count": 2,
            }
        )

        assert "2 rows" in result
        assert "name=test_func" in result
        assert "complexity=10" in result

    def test_format_empty_query_result(self) -> None:
        """Test formatting empty query results."""
        result = format_tool_result({"columns": ["name"], "rows": [], "row_count": 0})

        assert "No results found" in result

    def test_format_context_result(self) -> None:
        """Test formatting context results."""
        result = format_tool_result({"mu_text": "!module Auth\n$AuthService"})

        assert "!module Auth" in result
        assert "$AuthService" in result

    def test_format_impact_result(self) -> None:
        """Test formatting impact results."""
        result = format_tool_result({"impacted_nodes": ["node1", "node2", "node3"]})

        assert "3 affected nodes" in result
        assert "node1" in result
        assert "node2" in result

    def test_format_ancestors_result(self) -> None:
        """Test formatting ancestors results."""
        result = format_tool_result({"ancestor_nodes": ["parent1", "parent2"]})

        assert "2 dependencies" in result
        assert "parent1" in result

    def test_format_cycles_result(self) -> None:
        """Test formatting cycles results."""
        result = format_tool_result({"cycles": [["a", "b"], ["c", "d", "e"]]})

        assert "2 circular dependency cycles" in result
        assert "a -> b" in result
        assert "c -> d -> e" in result

    def test_format_no_cycles(self) -> None:
        """Test formatting empty cycles results."""
        result = format_tool_result({"cycles": []})

        assert "No circular dependencies" in result

    def test_format_default_json(self) -> None:
        """Test default JSON formatting."""
        result = format_tool_result({"custom": "data", "number": 42})

        # Should be valid JSON
        parsed = json.loads(result)
        assert parsed["custom"] == "data"
        assert parsed["number"] == 42


# =============================================================================
# Test MUAgent Core
# =============================================================================


class TestMUAgent:
    """Tests for MUAgent class."""

    @patch("mu.agent.core.DaemonClient")
    def test_init_default_config(self, mock_daemon_class: MagicMock) -> None:
        """Test MUAgent initialization with default config."""
        from mu.agent.core import MUAgent

        agent = MUAgent()

        assert agent.config.model == "gpt-5-nano-2025-08-07"
        assert agent.memory.is_empty is True
        agent.close()

    @patch("mu.agent.core.DaemonClient")
    def test_init_custom_config(self, mock_daemon_class: MagicMock) -> None:
        """Test MUAgent initialization with custom config."""
        from mu.agent.core import MUAgent

        config = AgentConfig(model="claude-3-5-sonnet-latest", max_tokens=8192)
        agent = MUAgent(config)

        assert agent.config.model == "claude-3-5-sonnet-latest"
        assert agent.config.max_tokens == 8192
        agent.close()

    @patch("mu.agent.core.DaemonClient")
    def test_reset_clears_memory(self, mock_daemon_class: MagicMock) -> None:
        """Test reset() clears memory and graph summary."""
        from mu.agent.core import MUAgent

        agent = MUAgent()
        agent.memory.add_user_message("Test")
        agent._graph_summary = GraphSummary(node_count=100)

        agent.reset()

        assert agent.memory.is_empty is True
        assert agent._graph_summary is None
        agent.close()

    @patch("mu.agent.core.DaemonClient")
    def test_query_direct(self, mock_daemon_class: MagicMock) -> None:
        """Test query() bypasses LLM."""
        from mu.agent.core import MUAgent

        mock_client = MagicMock()
        mock_client.query.return_value = {"columns": ["name"], "rows": [["test"]]}
        mock_daemon_class.return_value = mock_client

        agent = MUAgent()
        result = agent.query("SELECT * FROM functions")

        mock_client.query.assert_called_once_with("SELECT * FROM functions")
        assert result["columns"] == ["name"]
        agent.close()

    @patch("mu.agent.core.DaemonClient")
    def test_query_handles_daemon_error(self, mock_daemon_class: MagicMock) -> None:
        """Test query() handles DaemonError."""
        from mu.agent.core import MUAgent
        from mu.client import DaemonError

        mock_client = MagicMock()
        mock_client.query.side_effect = DaemonError("Not running")
        mock_daemon_class.return_value = mock_client

        agent = MUAgent()
        result = agent.query("SELECT * FROM functions")

        assert "error" in result
        assert "Not running" in result["error"]
        agent.close()

    @patch("mu.agent.core.DaemonClient")
    def test_context_direct(self, mock_daemon_class: MagicMock) -> None:
        """Test context() bypasses LLM."""
        from mu.agent.core import MUAgent

        mock_client = MagicMock()
        mock_client.context.return_value = {"mu_text": "!module", "token_count": 50}
        mock_daemon_class.return_value = mock_client

        agent = MUAgent()
        result = agent.context("How does auth work?", max_tokens=2000)

        mock_client.context.assert_called_once_with("How does auth work?", max_tokens=2000)
        assert result["mu_text"] == "!module"
        agent.close()

    @patch("mu.agent.core.DaemonClient")
    def test_deps_direct_outgoing(self, mock_daemon_class: MagicMock) -> None:
        """Test deps() with outgoing direction."""
        from mu.agent.core import MUAgent

        mock_client = MagicMock()
        mock_client.query.return_value = {"columns": ["id"], "rows": []}
        mock_daemon_class.return_value = mock_client

        agent = MUAgent()
        agent.deps("AuthService", direction="outgoing", depth=3)

        call_args = mock_client.query.call_args[0][0]
        assert "SHOW dependencies OF AuthService DEPTH 3" in call_args
        agent.close()

    @patch("mu.agent.core.DaemonClient")
    def test_deps_direct_incoming(self, mock_daemon_class: MagicMock) -> None:
        """Test deps() with incoming direction."""
        from mu.agent.core import MUAgent

        mock_client = MagicMock()
        mock_client.query.return_value = {"columns": ["id"], "rows": []}
        mock_daemon_class.return_value = mock_client

        agent = MUAgent()
        agent.deps("AuthService", direction="incoming")

        call_args = mock_client.query.call_args[0][0]
        assert "dependents" in call_args.lower()
        agent.close()

    @patch("mu.agent.core.DaemonClient")
    def test_impact_direct(self, mock_daemon_class: MagicMock) -> None:
        """Test impact() bypasses LLM."""
        from mu.agent.core import MUAgent

        mock_client = MagicMock()
        mock_client.impact.return_value = {"impacted_nodes": ["node1"]}
        mock_daemon_class.return_value = mock_client

        agent = MUAgent()
        result = agent.impact("User")

        mock_client.impact.assert_called_once_with("User")
        assert result["impacted_nodes"] == ["node1"]
        agent.close()

    @patch("mu.agent.core.DaemonClient")
    def test_ancestors_direct(self, mock_daemon_class: MagicMock) -> None:
        """Test ancestors() bypasses LLM."""
        from mu.agent.core import MUAgent

        mock_client = MagicMock()
        mock_client.ancestors.return_value = {"ancestor_nodes": ["parent1"]}
        mock_daemon_class.return_value = mock_client

        agent = MUAgent()
        result = agent.ancestors("Child")

        mock_client.ancestors.assert_called_once_with("Child")
        assert result["ancestor_nodes"] == ["parent1"]
        agent.close()

    @patch("mu.agent.core.DaemonClient")
    def test_cycles_direct(self, mock_daemon_class: MagicMock) -> None:
        """Test cycles() bypasses LLM."""
        from mu.agent.core import MUAgent

        mock_client = MagicMock()
        mock_client.cycles.return_value = {"cycles": []}
        mock_daemon_class.return_value = mock_client

        agent = MUAgent()
        result = agent.cycles()

        mock_client.cycles.assert_called_once_with(edge_types=None)
        assert result["cycles"] == []
        agent.close()

    @patch("mu.agent.core.DaemonClient")
    def test_context_manager(self, mock_daemon_class: MagicMock) -> None:
        """Test MUAgent works as context manager."""
        from mu.agent.core import MUAgent

        mock_client = MagicMock()
        mock_daemon_class.return_value = mock_client

        with MUAgent() as agent:
            assert agent is not None
            # Force client creation by calling a method
            agent.query("SELECT 1")

        mock_client.close.assert_called_once()

    @patch("mu.agent.core.DaemonClient")
    def test_ask_without_api_key(self, mock_daemon_class: MagicMock) -> None:
        """Test ask() returns error without API key."""
        from mu.agent.core import MUAgent

        mock_client = MagicMock()
        mock_client.status.return_value = {"stats": {}}
        mock_client.query.return_value = {"rows": []}
        mock_daemon_class.return_value = mock_client

        with patch.dict("os.environ", {}, clear=True):
            agent = MUAgent()
            response = agent.ask("Test question")

            assert response.error is not None
            assert "API_KEY" in response.error  # Could be ANTHROPIC_API_KEY or OPENAI_API_KEY
            agent.close()

    @patch("mu.agent.core.DaemonClient")
    def test_get_graph_summary_lazy_loading(self, mock_daemon_class: MagicMock) -> None:
        """Test graph summary is lazy loaded."""
        from mu.agent.core import MUAgent

        mock_client = MagicMock()
        mock_client.status.return_value = {
            "stats": {
                "node_count": 100,
                "edge_count": 200,
                "nodes_by_type": {"module": 10, "class": 30, "function": 60},
            }
        }
        mock_client.query.return_value = {"rows": [["auth"], ["api"]]}
        mock_daemon_class.return_value = mock_client

        agent = MUAgent()
        # Access private method for testing
        summary = agent._get_graph_summary()

        assert summary.node_count == 100
        assert summary.edge_count == 200
        assert summary.modules == 10
        assert summary.classes == 30
        assert summary.functions == 60
        agent.close()

    @patch("mu.agent.core.DaemonClient")
    def test_get_graph_summary_handles_error(self, mock_daemon_class: MagicMock) -> None:
        """Test graph summary handles daemon errors."""
        from mu.agent.core import MUAgent
        from mu.client import DaemonError

        mock_client = MagicMock()
        mock_client.status.side_effect = DaemonError("Not running")
        mock_daemon_class.return_value = mock_client

        agent = MUAgent()
        summary = agent._get_graph_summary()

        # Should return empty GraphSummary on error
        assert summary.node_count == 0
        agent.close()


# =============================================================================
# Test Response Formats
# =============================================================================


class TestFormatMuOutput:
    """Tests for format_mu_output function."""

    def test_format_mu_text(self) -> None:
        """Test formatting mu_text passthrough."""
        result = format_mu_output({"mu_text": "!module Test\n$TestClass"})

        assert result == "!module Test\n$TestClass"

    def test_format_query_as_mu(self) -> None:
        """Test formatting query results as MU."""
        result = format_mu_output(
            {
                "columns": ["type", "name", "file_path"],
                "rows": [
                    ["module", "auth", "src/auth.py"],
                    ["class", "AuthService", "src/auth.py"],
                    ["function", "login", "src/auth.py"],
                ],
            }
        )

        assert "!auth" in result
        assert "$AuthService" in result
        assert "#login" in result

    def test_format_error(self) -> None:
        """Test formatting error results."""
        result = format_mu_output({"error": "Something failed"})

        assert "Error: Something failed" in result

    def test_format_empty_query(self) -> None:
        """Test formatting empty query results."""
        result = format_mu_output({"columns": ["name"], "rows": []})

        assert "No results found" in result


class TestFormatDepsTree:
    """Tests for format_deps_tree function."""

    def test_format_outgoing_deps(self) -> None:
        """Test formatting outgoing dependencies."""
        deps = [
            {"name": "Utils", "type": "module"},
            {"name": "Helper", "type": "class"},
        ]
        result = format_deps_tree(deps, "outgoing")

        assert "Dependencies (what it uses)" in result
        assert "!Utils" in result
        assert "$Helper" in result

    def test_format_incoming_deps(self) -> None:
        """Test formatting incoming dependencies."""
        deps = [{"name": "Consumer", "type": "function"}]
        result = format_deps_tree(deps, "incoming")

        assert "Dependents (what uses it)" in result
        assert "#Consumer" in result

    def test_format_empty_deps(self) -> None:
        """Test formatting empty dependencies."""
        result = format_deps_tree([], "outgoing")

        assert "No dependencies found" in result


class TestFormatImpactSummary:
    """Tests for format_impact_summary function."""

    def test_format_impact(self) -> None:
        """Test formatting impact summary."""
        impacted = ["node1", "node2", "node3", "node4", "node5", "node6"]
        result = format_impact_summary("User", impacted)

        assert "Impact of changing User" in result
        assert "Total affected: 6 nodes" in result
        assert "Direct dependents" in result
        assert "Transitive impact" in result

    def test_format_no_impact(self) -> None:
        """Test formatting empty impact."""
        result = format_impact_summary("IsolatedNode", [])

        assert "No downstream impact" in result

    def test_format_truncates_large_impact(self) -> None:
        """Test impact summary truncates large lists."""
        impacted = [f"node{i}" for i in range(50)]
        result = format_impact_summary("BigNode", impacted, max_show=10)

        assert "... and 40 more" in result


class TestFormatCyclesSummary:
    """Tests for format_cycles_summary function."""

    def test_format_cycles(self) -> None:
        """Test formatting cycles."""
        cycles = [["a", "b"], ["c", "d", "e"]]
        result = format_cycles_summary(cycles)

        assert "2 circular dependency cycles" in result
        assert "Cycle 1" in result
        assert "Cycle 2" in result
        assert "a -> b -> a" in result
        assert "c -> d -> e -> c" in result

    def test_format_no_cycles(self) -> None:
        """Test formatting empty cycles."""
        result = format_cycles_summary([])

        assert "No circular dependencies" in result

    def test_format_truncates_many_cycles(self) -> None:
        """Test cycles summary truncates long lists."""
        cycles = [[f"node{i}", f"node{i + 1}"] for i in range(15)]
        result = format_cycles_summary(cycles)

        assert "... and 5 more cycles" in result


class TestTruncateResponse:
    """Tests for truncate_response function."""

    def test_no_truncation_needed(self) -> None:
        """Test short text is not truncated."""
        text = "Short response"
        result = truncate_response(text, max_chars=100)

        assert result == text

    def test_truncation_at_newline(self) -> None:
        """Test truncation prefers newline boundaries."""
        text = "Line one\nLine two\nLine three\n" * 100
        result = truncate_response(text, max_chars=500)

        assert len(result) < 600
        assert "truncated" in result.lower()

    def test_truncation_message(self) -> None:
        """Test truncation includes remaining char count."""
        text = "x" * 1000
        result = truncate_response(text, max_chars=100)

        assert "truncated" in result.lower()
        assert "more characters" in result


class TestFormatForTerminal:
    """Tests for format_for_terminal function."""

    def test_short_lines_unchanged(self) -> None:
        """Test short lines are not modified."""
        text = "Short line\nAnother short"
        result = format_for_terminal(text, width=80)

        assert result == text

    def test_long_lines_wrapped(self) -> None:
        """Test long lines are wrapped."""
        text = "This is a very long line that should be wrapped " * 5
        result = format_for_terminal(text, width=50)

        for line in result.split("\n"):
            assert len(line) <= 50


# =============================================================================
# Test CLI Commands
# =============================================================================


class TestAgentCLI:
    """Tests for agent CLI commands."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_agent_group_help(self, runner: CliRunner) -> None:
        """Test mu agent --help shows usage."""
        result = runner.invoke(agent, ["--help"])
        assert result.exit_code == 0
        assert "Code structure specialist" in result.output

    def test_agent_subcommands_registered(self, runner: CliRunner) -> None:
        """Test all agent subcommands are registered."""
        result = runner.invoke(agent, ["--help"])
        assert result.exit_code == 0

        expected = ["ask", "interactive", "query", "deps", "impact", "cycles"]
        for cmd in expected:
            assert cmd in result.output, f"Command '{cmd}' not found"

    def test_ask_help(self, runner: CliRunner) -> None:
        """Test mu agent ask --help."""
        result = runner.invoke(agent, ["ask", "--help"])
        assert result.exit_code == 0
        assert "--model" in result.output
        assert "--json" in result.output
        assert "--max-tokens" in result.output

    def test_interactive_help(self, runner: CliRunner) -> None:
        """Test mu agent interactive --help."""
        result = runner.invoke(agent, ["interactive", "--help"])
        assert result.exit_code == 0
        assert "--model" in result.output

    def test_query_help(self, runner: CliRunner) -> None:
        """Test mu agent query --help."""
        result = runner.invoke(agent, ["query", "--help"])
        assert result.exit_code == 0
        assert "--json" in result.output
        assert "MUQL" in result.output

    def test_deps_help(self, runner: CliRunner) -> None:
        """Test mu agent deps --help."""
        result = runner.invoke(agent, ["deps", "--help"])
        assert result.exit_code == 0
        assert "--direction" in result.output
        assert "--depth" in result.output
        assert "--json" in result.output

    def test_impact_help(self, runner: CliRunner) -> None:
        """Test mu agent impact --help."""
        result = runner.invoke(agent, ["impact", "--help"])
        assert result.exit_code == 0
        assert "--json" in result.output

    def test_cycles_help(self, runner: CliRunner) -> None:
        """Test mu agent cycles --help."""
        result = runner.invoke(agent, ["cycles", "--help"])
        assert result.exit_code == 0
        assert "--json" in result.output

    @patch("mu.agent.cli.MUAgent")
    def test_ask_command_success(self, mock_agent_class: MagicMock, runner: CliRunner) -> None:
        """Test mu agent ask command with successful response."""
        mock_agent = MagicMock()
        mock_agent.ask.return_value = AgentResponse(
            content="Authentication is handled by AuthService",
            tool_calls_made=2,
            tokens_used=500,
            model="gpt-5-nano-2025-08-07",
        )
        mock_agent.__enter__ = MagicMock(return_value=mock_agent)
        mock_agent.__exit__ = MagicMock(return_value=False)
        mock_agent_class.return_value = mock_agent

        result = runner.invoke(agent, ["ask", "How does auth work?"])

        assert result.exit_code == 0
        assert "AuthService" in result.output

    @patch("mu.agent.cli.MUAgent")
    def test_ask_command_json_output(self, mock_agent_class: MagicMock, runner: CliRunner) -> None:
        """Test mu agent ask --json produces JSON output."""
        mock_agent = MagicMock()
        mock_agent.ask.return_value = AgentResponse(
            content="Answer",
            tool_calls_made=1,
            tokens_used=100,
            model="test-model",
        )
        mock_agent.__enter__ = MagicMock(return_value=mock_agent)
        mock_agent.__exit__ = MagicMock(return_value=False)
        mock_agent_class.return_value = mock_agent

        result = runner.invoke(agent, ["ask", "--json", "Question"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["content"] == "Answer"
        assert parsed["tool_calls_made"] == 1

    @patch("mu.agent.cli.MUAgent")
    def test_ask_command_error(self, mock_agent_class: MagicMock, runner: CliRunner) -> None:
        """Test mu agent ask handles error response."""
        mock_agent = MagicMock()
        mock_agent.ask.return_value = AgentResponse(
            content="",
            error="API key not set",
        )
        mock_agent.__enter__ = MagicMock(return_value=mock_agent)
        mock_agent.__exit__ = MagicMock(return_value=False)
        mock_agent_class.return_value = mock_agent

        result = runner.invoke(agent, ["ask", "Question"])

        assert result.exit_code == 1
        assert "API key not set" in result.output

    @patch("mu.agent.cli.MUAgent")
    def test_query_command_success(self, mock_agent_class: MagicMock, runner: CliRunner) -> None:
        """Test mu agent query command."""
        mock_agent = MagicMock()
        mock_agent.query.return_value = {
            "columns": ["name", "complexity"],
            "rows": [["test_func", 10]],
        }
        mock_agent.__enter__ = MagicMock(return_value=mock_agent)
        mock_agent.__exit__ = MagicMock(return_value=False)
        mock_agent_class.return_value = mock_agent

        result = runner.invoke(agent, ["query", "SELECT * FROM functions"])

        assert result.exit_code == 0
        assert "test_func" in result.output

    @patch("mu.agent.cli.MUAgent")
    def test_query_command_json(self, mock_agent_class: MagicMock, runner: CliRunner) -> None:
        """Test mu agent query --json."""
        mock_agent = MagicMock()
        mock_agent.query.return_value = {
            "columns": ["name"],
            "rows": [["func1"]],
        }
        mock_agent.__enter__ = MagicMock(return_value=mock_agent)
        mock_agent.__exit__ = MagicMock(return_value=False)
        mock_agent_class.return_value = mock_agent

        result = runner.invoke(agent, ["query", "--json", "SELECT 1"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["columns"] == ["name"]

    @patch("mu.agent.cli.MUAgent")
    def test_query_command_error(self, mock_agent_class: MagicMock, runner: CliRunner) -> None:
        """Test mu agent query handles error."""
        mock_agent = MagicMock()
        mock_agent.query.return_value = {"error": "Invalid query"}
        mock_agent.__enter__ = MagicMock(return_value=mock_agent)
        mock_agent.__exit__ = MagicMock(return_value=False)
        mock_agent_class.return_value = mock_agent

        result = runner.invoke(agent, ["query", "INVALID"])

        assert result.exit_code == 1
        assert "Invalid query" in result.output

    @patch("mu.agent.cli.MUAgent")
    def test_deps_command(self, mock_agent_class: MagicMock, runner: CliRunner) -> None:
        """Test mu agent deps command."""
        mock_agent = MagicMock()
        mock_agent.deps.return_value = {
            "columns": ["name"],
            "rows": [["dep1"], ["dep2"]],
        }
        mock_agent.__enter__ = MagicMock(return_value=mock_agent)
        mock_agent.__exit__ = MagicMock(return_value=False)
        mock_agent_class.return_value = mock_agent

        result = runner.invoke(
            agent, ["deps", "AuthService", "--direction", "incoming", "--depth", "3"]
        )

        assert result.exit_code == 0
        mock_agent.deps.assert_called_once_with("AuthService", direction="incoming", depth=3)

    @patch("mu.agent.cli.MUAgent")
    def test_impact_command(self, mock_agent_class: MagicMock, runner: CliRunner) -> None:
        """Test mu agent impact command."""
        mock_agent = MagicMock()
        mock_agent.impact.return_value = {"impacted_nodes": ["node1", "node2", "node3"]}
        mock_agent.__enter__ = MagicMock(return_value=mock_agent)
        mock_agent.__exit__ = MagicMock(return_value=False)
        mock_agent_class.return_value = mock_agent

        result = runner.invoke(agent, ["impact", "User"])

        assert result.exit_code == 0
        assert "Impact of changing User" in result.output
        assert "3 nodes" in result.output

    @patch("mu.agent.cli.MUAgent")
    def test_cycles_command_no_cycles(self, mock_agent_class: MagicMock, runner: CliRunner) -> None:
        """Test mu agent cycles with no cycles found."""
        mock_agent = MagicMock()
        mock_agent.cycles.return_value = {"cycles": []}
        mock_agent.__enter__ = MagicMock(return_value=mock_agent)
        mock_agent.__exit__ = MagicMock(return_value=False)
        mock_agent_class.return_value = mock_agent

        result = runner.invoke(agent, ["cycles"])

        assert result.exit_code == 0
        assert "No circular dependencies" in result.output

    @patch("mu.agent.cli.MUAgent")
    def test_cycles_command_with_cycles(
        self, mock_agent_class: MagicMock, runner: CliRunner
    ) -> None:
        """Test mu agent cycles with cycles found."""
        mock_agent = MagicMock()
        mock_agent.cycles.return_value = {"cycles": [["a", "b"], ["c", "d", "e"]]}
        mock_agent.__enter__ = MagicMock(return_value=mock_agent)
        mock_agent.__exit__ = MagicMock(return_value=False)
        mock_agent_class.return_value = mock_agent

        result = runner.invoke(agent, ["cycles"])

        assert result.exit_code == 0
        assert "2 circular dependency cycles" in result.output
        assert "a -> b" in result.output


# =============================================================================
# Integration-style Tests
# =============================================================================


class TestAgentIntegration:
    """Integration-style tests for MUAgent."""

    @patch("mu.agent.core.DaemonClient")
    def test_ask_with_mocked_llm_and_daemon(
        self,
        mock_daemon_class: MagicMock,
    ) -> None:
        """Test ask() with both LLM and daemon mocked."""
        from mu.agent.core import MUAgent

        # Mock daemon client
        mock_mu_client = MagicMock()
        mock_mu_client.status.return_value = {"stats": {"node_count": 100}}
        mock_mu_client.query.return_value = {"rows": [["auth"]]}
        mock_daemon_class.return_value = mock_mu_client

        # Mock Anthropic client
        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.content = [MagicMock(type="text", text="Auth is handled by AuthService")]
        mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        mock_llm_client = MagicMock()
        mock_llm_client.messages.create.return_value = mock_response

        # Mock the anthropic import inside _get_anthropic_client
        mock_anthropic_module = MagicMock()
        mock_anthropic_module.Anthropic.return_value = mock_llm_client

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.dict("sys.modules", {"anthropic": mock_anthropic_module}):
                agent = MUAgent()
                response = agent.ask("How does authentication work?")

                assert response.success is True
                assert "AuthService" in response.content
                assert response.tokens_used > 0  # Tokens vary by model
                agent.close()

    @patch("mu.agent.core.DaemonClient")
    def test_ask_with_tool_use(
        self,
        mock_daemon_class: MagicMock,
    ) -> None:
        """Test ask() handles tool use loop."""
        from mu.agent.core import MUAgent

        # Mock daemon client
        mock_mu_client = MagicMock()
        mock_mu_client.status.return_value = {"stats": {}}
        mock_mu_client.query.return_value = {
            "columns": ["name"],
            "rows": [["AuthService"]],
            "row_count": 1,
        }
        mock_daemon_class.return_value = mock_mu_client

        # Mock tool use response - use spec to prevent auto-creating .text attribute
        mock_tool_content = MagicMock(spec=["type", "id", "name", "input"])
        mock_tool_content.type = "tool_use"
        mock_tool_content.id = "tool_123"
        mock_tool_content.name = "mu_query"
        mock_tool_content.input = {"muql": "SELECT name FROM classes"}

        mock_first_response = MagicMock()
        mock_first_response.stop_reason = "tool_use"
        mock_first_response.content = [mock_tool_content]
        mock_first_response.usage = MagicMock(input_tokens=50, output_tokens=25)

        # Mock final response
        mock_text_content = MagicMock()
        mock_text_content.type = "text"
        mock_text_content.text = "Found AuthService class."

        mock_final_response = MagicMock()
        mock_final_response.stop_reason = "end_turn"
        mock_final_response.content = [mock_text_content]
        mock_final_response.usage = MagicMock(input_tokens=100, output_tokens=50)

        mock_llm_client = MagicMock()
        mock_llm_client.messages.create.side_effect = [
            mock_first_response,
            mock_final_response,
        ]

        # Mock the anthropic import inside _get_anthropic_client
        mock_anthropic_module = MagicMock()
        mock_anthropic_module.Anthropic.return_value = mock_llm_client

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.dict("sys.modules", {"anthropic": mock_anthropic_module}):
                # Use Anthropic model to trigger AnthropicProvider
                config = AgentConfig(model="claude-haiku-4-5-20251001")
                agent = MUAgent(config)
                response = agent.ask("Find auth classes")

                assert response.success is True
                assert response.tool_calls_made == 1
                assert "AuthService" in response.content
                agent.close()
