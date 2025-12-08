# MU Agent - Task Breakdown

## Business Context

**Problem**: Coding agents (Claude Code, Cursor, etc.) spend 50-100K tokens exploring codebases before writing code. This costs $0.15-0.30 per question using expensive models like Sonnet/Opus, is slow (30-60 seconds), and often misses structural context.

**Outcome**: MU Agent answers codebase structure questions using cheap models (Haiku) by querying the .mubase graph database. Reduces exploration costs by 95%+ (to $0.001-0.005 per question) while providing more accurate, structural answers in 2-5 seconds.

**Users**:
- Developers using Claude Code, Cursor, or other AI coding assistants
- Teams wanting to reduce LLM costs for codebase exploration
- Developers querying codebase structure from CLI

## Existing Patterns Found

| Pattern | File | Relevance |
|---------|------|-----------|
| Daemon client wrapper | `src/mu/client.py:22-274` | MUAgent will use DaemonClient for .mubase queries |
| MCP tool definitions | `src/mu/mcp/server.py:115-450` | Tools already exist, agent wraps them |
| Dataclass with `to_dict()` | `src/mu/parser/models.py:10-150` | All agent models follow this pattern |
| Click CLI group | `src/mu/cli.py:36-58` | Agent commands added via lazy loading |
| Click command pattern | `src/mu/commands/query.py:130-173` | CLI command structure to follow |
| Test structure with mocks | `tests/unit/test_mcp.py:25-90` | Test patterns for agent module |
| Anthropic API usage | `src/mu/llm/__init__.py` | LLM call patterns for agent |

## Task Breakdown

### Task 1: Create Agent Package Structure
**Status**: Complete

**File(s)**:
- `src/mu/agent/__init__.py`

**Pattern**: Follow `src/mu/mcp/__init__.py` for module exports

**Implementation**:
```python
from .core import MUAgent
from .memory import ConversationMemory
from .models import AgentConfig, AgentResponse, Message

__all__ = ["MUAgent", "ConversationMemory", "AgentConfig", "AgentResponse", "Message"]
```

**Acceptance**:
- [x] Package importable as `from mu.agent import MUAgent`
- [x] All public classes exported in `__all__`
- [x] No circular import issues

---

### Task 2: Create Agent Data Models
**Status**: Complete

**File(s)**: `src/mu/agent/models.py`

**Pattern**: Follow `src/mu/parser/models.py:10-150` (dataclasses with `to_dict()`)

**Implementation**:
```python
@dataclass
class AgentConfig:
    """Configuration for MU Agent."""
    model: str = "claude-3-5-haiku-latest"
    max_tokens: int = 4096
    temperature: float = 0.0
    mubase_path: str | None = None

    def to_dict(self) -> dict[str, Any]: ...

@dataclass
class Message:
    """A conversation message."""
    role: Literal["user", "assistant", "system"]
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_results: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]: ...

@dataclass
class AgentResponse:
    """Response from MU Agent."""
    content: str
    tool_calls_made: int
    tokens_used: int
    model: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]: ...
```

**Acceptance**:
- [x] All dataclasses have `to_dict()` methods
- [x] Type hints on all fields
- [x] Default values for optional fields
- [x] No external dependencies beyond stdlib + typing

---

### Task 3: Create Conversation Memory
**Status**: Complete

**File(s)**: `src/mu/agent/memory.py`

**Pattern**: Follow `src/mu/client.py:22-60` (clean class structure with context manager)

**Implementation**:
```python
@dataclass
class ConversationMemory:
    """Manages conversation state for MU Agent."""
    messages: list[Message] = field(default_factory=list)
    mentioned_nodes: set[str] = field(default_factory=set)
    graph_summary: str | None = None
    max_messages: int = 50  # Prevent unbounded growth

    def add_user_message(self, content: str) -> None: ...
    def add_assistant_message(self, content: str, tool_calls: list[dict] | None = None) -> None: ...
    def get_messages(self) -> list[dict[str, Any]]: ...
    def clear(self) -> None: ...
    def extract_mentioned_nodes(self, text: str) -> set[str]: ...
    def to_dict(self) -> dict[str, Any]: ...
```

**Acceptance**:
- [x] Messages stored as list[Message]
- [x] Tracks mentioned nodes across conversation
- [x] Has max_messages limit to prevent unbounded growth
- [x] `get_messages()` returns format suitable for Anthropic API
- [x] `clear()` resets all state

---

### Task 4: Create System Prompt Module
**Status**: Complete

**File(s)**: `src/mu/agent/prompt.py`

**Pattern**: Follow PRD specification (docs/mu-agent-prd.md lines 152-269)

**Implementation**:
```python
SYSTEM_PROMPT = """You are the MU Agent, a specialist in code structure analysis.
...
## Graph Summary
{graph_summary}
...
"""

EXAMPLES = [
    {
        "question": "What handles authentication?",
        "actions": ["mu_query(...)", "mu_deps(...)"],
        "response": "Authentication is handled by..."
    },
    ...
]

def format_system_prompt(graph_summary: str) -> str:
    """Format system prompt with graph summary."""
    return SYSTEM_PROMPT.format(graph_summary=graph_summary)
```

**Acceptance**:
- [x] System prompt matches PRD specification
- [x] Includes tool documentation
- [x] Includes MU format guidelines
- [x] Has 5+ few-shot examples (6 examples implemented)
- [x] `{graph_summary}` placeholder for runtime injection

---

### Task 5: Create Tool Definitions
**Status**: Complete

**File(s)**: `src/mu/agent/tools.py`

**Pattern**: Follow `src/mu/mcp/server.py:115-320` (tool wrappers)

**Implementation**:
```python
# Tool schema definitions for Anthropic API
TOOL_DEFINITIONS = [
    {
        "name": "mu_query",
        "description": "Execute MUQL query against the code graph.",
        "input_schema": {
            "type": "object",
            "properties": {
                "muql": {"type": "string", "description": "The MUQL query"}
            },
            "required": ["muql"]
        }
    },
    {
        "name": "mu_context",
        "description": "Get smart context for a question.",
        "input_schema": {...}
    },
    # mu_deps, mu_impact, mu_ancestors, mu_cycles
]

def execute_tool(name: str, args: dict, client: DaemonClient) -> dict[str, Any]:
    """Execute a tool and return results."""
    if name == "mu_query":
        return client.query(args["muql"])
    elif name == "mu_context":
        return client.context(args["question"], args.get("max_tokens", 4000))
    ...
```

**Acceptance**:
- [x] Tool definitions match Anthropic tool use schema
- [x] All 6 tools defined: mu_query, mu_context, mu_deps, mu_impact, mu_ancestors, mu_cycles
- [x] `execute_tool()` dispatches to DaemonClient methods
- [x] Error handling returns error dict instead of raising

---

### Task 6: Create Core MUAgent Class
**Status**: Complete

**File(s)**: `src/mu/agent/core.py`

**Pattern**: Follow `src/mu/client.py:22-274` (class with methods, context manager)

**Implementation**:
```python
class MUAgent:
    """MU Agent - Code structure specialist."""

    def __init__(self, config: AgentConfig | None = None):
        self.config = config or AgentConfig()
        self.client = anthropic.Anthropic()
        self.mu_client = DaemonClient()
        self.memory = ConversationMemory()
        self._graph_summary: str | None = None

    def ask(self, question: str) -> AgentResponse:
        """Ask a question about the codebase."""
        # 1. Lazy-load graph summary
        # 2. Add to conversation memory
        # 3. Call LLM with tools
        # 4. Process tool calls in loop
        # 5. Return final response
        ...

    def query(self, muql: str) -> dict[str, Any]:
        """Execute MUQL query directly (bypass LLM)."""
        return self.mu_client.query(muql)

    def context(self, question: str, max_tokens: int = 4000) -> dict[str, Any]:
        """Get smart context (bypass LLM)."""
        return self.mu_client.context(question, max_tokens)

    def deps(self, node: str, direction: str = "outgoing") -> dict[str, Any]:
        """Get dependencies (bypass LLM)."""
        ...

    def impact(self, node: str) -> dict[str, Any]:
        """Get impact analysis (bypass LLM)."""
        return self.mu_client.impact(node)

    def reset(self) -> None:
        """Reset conversation memory."""
        self.memory.clear()
        self._graph_summary = None

    def _get_graph_summary(self) -> str:
        """Get high-level graph summary from daemon."""
        ...

    def _process_response(self, response: anthropic.Message) -> str:
        """Process LLM response, executing tool calls."""
        # Handle tool_use blocks
        # Loop until stop_reason is "end_turn"
        ...

    def _execute_tool(self, name: str, args: dict) -> dict[str, Any]:
        """Execute a single tool call."""
        ...
```

**Acceptance**:
- [x] Constructor accepts AgentConfig
- [x] `ask()` returns AgentResponse with content and metadata
- [x] Tool call loop handles multiple iterations (max 10)
- [x] Direct methods (query, context, deps, impact) bypass LLM
- [x] `reset()` clears conversation state
- [x] Handles DaemonError gracefully

---

### Task 7: Create Response Formatter
**Status**: Complete

**File(s)**: `src/mu/agent/formats.py`

**Pattern**: Follow `src/mu/kernel/muql/formatter.py` for output formatting

**Implementation**:
```python
def format_mu_output(data: dict[str, Any]) -> str:
    """Format query/context result as MU notation."""
    ...

def format_deps_tree(deps: list[dict], direction: str) -> str:
    """Format dependency list as tree."""
    ...

def format_impact_summary(impacted: list[str]) -> str:
    """Format impact analysis as summary."""
    ...

def truncate_response(text: str, max_tokens: int = 4000) -> str:
    """Truncate response to fit token budget."""
    ...
```

**Acceptance**:
- [x] MU format output uses sigils (!, $, #, @)
- [x] Tree format shows hierarchical dependencies
- [x] Impact summary groups by direct/transitive
- [x] Truncation preserves structure

---

### Task 8: Create CLI Commands
**Status**: Complete

**File(s)**: `src/mu/agent/cli.py`

**Pattern**: Follow `src/mu/commands/query.py:130-173` (Click commands)

**Implementation**:
```python
import click
from mu.agent import MUAgent, AgentConfig

@click.group()
def agent():
    """MU Agent - Code structure specialist."""
    pass

@agent.command()
@click.argument("question")
@click.option("--model", default="claude-3-5-haiku-latest", help="Model to use")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def ask(question: str, model: str, as_json: bool):
    """Ask a question about the codebase."""
    agent = MUAgent(AgentConfig(model=model))
    response = agent.ask(question)
    if as_json:
        click.echo(json.dumps(response.to_dict()))
    else:
        click.echo(response.content)

@agent.command()
@click.option("--model", default="claude-3-5-haiku-latest", help="Model to use")
def interactive(model: str):
    """Start interactive session with MU Agent."""
    # REPL loop with prompt_toolkit or basic input
    ...
```

**Acceptance**:
- [x] `mu agent ask "question"` works
- [x] `mu agent interactive` starts REPL
- [x] `--json` flag outputs structured JSON
- [x] `--model` flag allows model override
- [x] Handles KeyboardInterrupt gracefully

---

### Task 9: Wire CLI into Main CLI
**Status**: Complete

**File(s)**: `src/mu/cli.py`

**Pattern**: Follow existing lazy command registration (lines 36-58)

**Implementation**:
```python
LAZY_COMMANDS: dict[str, tuple[str, str]] = {
    ...
    "agent": ("mu.agent.cli", "agent"),  # Add this line
}
```

**Acceptance**:
- [x] `mu agent` command group available
- [x] `mu agent ask` subcommand works
- [x] `mu agent interactive` subcommand works
- [x] No import errors at startup (lazy loading)

---

### Task 10: Create Claude Code Agent Definition
**Status**: Complete

**File(s)**: `.claude/agents/mu-agent.md`

**Pattern**: Follow Claude Code agent definition format

**Implementation**:
```markdown
---
name: mu-agent
description: Code structure specialist. Ask about architecture, dependencies, impact analysis.
model: claude-3-5-haiku-latest
tools:
  - mcp: mu
---

You are the MU Agent, a specialist in code structure analysis.

[Full system prompt from prompt.py]
```

**Acceptance**:
- [x] Valid YAML frontmatter
- [x] Model set to Haiku for cost efficiency
- [x] MCP tools reference works
- [x] System prompt matches prompt.py content

---

### Task 11: Create Unit Tests
**Status**: Complete

**File(s)**: `tests/unit/test_agent.py`

**Pattern**: Follow `tests/unit/test_mcp.py` and `tests/unit/test_client.py`

**Implementation**: Created comprehensive test file with 128 tests covering:

| Test Class | Tests | Focus |
|------------|-------|-------|
| `TestAgentConfig` | 3 | Default values, custom values, to_dict() |
| `TestMessage` | 5 | User/assistant messages, API format |
| `TestToolCall` | 2 | Tool call dataclass |
| `TestToolResult` | 4 | Success/error results, serialization |
| `TestAgentResponse` | 5 | Response dataclass, success property |
| `TestGraphSummary` | 6 | Graph stats, to_text() formatting |
| `TestConversationMemory` | 18 | All memory operations, node extraction |
| `TestSystemPrompt` | 8 | Prompt structure, examples, formatting |
| `TestToolDefinitions` | 6 | All 6 tools, schema validation |
| `TestExecuteTool` | 10 | Tool dispatch, error handling |
| `TestFormatToolResult` | 9 | Result formatting for all types |
| `TestMUAgent` | 15 | Core agent, direct methods, LLM bypass |
| `TestFormatMuOutput` | 4 | MU format output |
| `TestFormatDepsTree` | 3 | Dependency tree formatting |
| `TestFormatImpactSummary` | 3 | Impact summary formatting |
| `TestFormatCyclesSummary` | 3 | Cycle detection formatting |
| `TestTruncateResponse` | 3 | Response truncation |
| `TestFormatForTerminal` | 2 | Terminal formatting |
| `TestAgentCLI` | 17 | All CLI commands with CliRunner |
| `TestAgentIntegration` | 2 | End-to-end with mocked LLM/daemon |

**Coverage**:
- Lines: 87% (exceeds 80% target)
- Branches: ~75% (exceeds 65% target)

**Acceptance**:
- [x] Tests for all data models
- [x] Tests for ConversationMemory operations
- [x] Tests for MUAgent with mocked LLM/daemon
- [x] Tests for CLI commands using CliRunner
- [x] All tests pass with `pytest tests/unit/test_agent.py`

---

### Task 12: Update CLAUDE.md Documentation

**File(s)**: `src/mu/agent/CLAUDE.md`

**Pattern**: Follow `src/mu/mcp/CLAUDE.md`

**Implementation**: Create module documentation covering:
- Architecture overview
- API reference
- Usage examples
- Integration with Claude Code
- Testing guidance

**Acceptance**:
- [ ] Documents all public classes and methods
- [ ] Includes usage examples
- [ ] Explains Claude Code integration
- [ ] Lists configuration options

---

## Dependencies

```
Task 2 (models) -> Task 3 (memory) -> Task 6 (core)
Task 4 (prompt) -> Task 6 (core)
Task 5 (tools) -> Task 6 (core)
Task 6 (core) -> Task 7 (formats) [optional integration]
Task 6 (core) -> Task 8 (cli)
Task 8 (cli) -> Task 9 (wire CLI)
Task 1 (package) should be done first
Task 10 (Claude agent) can run in parallel after Task 4
Task 11 (tests) runs after all implementation tasks
Task 12 (docs) runs last
```

**Suggested Order**:
1. Task 1 (package structure)
2. Task 2 (models)
3. Task 3 (memory)
4. Task 4 (prompt) + Task 5 (tools) [parallel]
5. Task 6 (core)
6. Task 7 (formats)
7. Task 8 (cli)
8. Task 9 (wire CLI)
9. Task 10 (Claude agent def)
10. Task 11 (tests)
11. Task 12 (docs)

## Edge Cases

1. **Daemon not running**: Agent should provide helpful error message directing user to `mu daemon start`
2. **No .mubase exists**: Agent should prompt user to run `mu kernel build`
3. **API key missing**: Clear error for missing `ANTHROPIC_API_KEY`
4. **Tool execution fails**: Agent should handle gracefully and report to user
5. **Response too long**: Truncate with indication that more exists
6. **Conversation too long**: Auto-summarize or warn about token limits

## Security Considerations

1. **API Key**: Never log or expose ANTHROPIC_API_KEY
2. **MUQL Injection**: DaemonClient already handles parameterization
3. **File Paths**: Only return paths relative to codebase root
4. **Rate Limiting**: Consider adding basic rate limiting for interactive mode

## Performance Considerations

1. **Graph Summary Caching**: Cache `_graph_summary` for session duration
2. **Tool Results**: Consider caching frequent queries (e.g., architecture overview)
3. **Memory Limits**: Enforce max_messages to prevent unbounded growth
4. **Streaming**: Consider streaming responses for better UX (future enhancement)
