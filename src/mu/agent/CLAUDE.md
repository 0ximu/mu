# MU Agent Module - Code Structure Specialist

This module provides the MU Agent, a specialist AI agent that answers questions about code structure by querying the .mubase graph database. It runs on cheap models (Haiku) to reduce codebase exploration costs by 95%+.

## Overview

**The Core Insight:** Coding agents spend 50-100K tokens exploring codebases before writing a single line. MU Agent replaces that exploration with 2-5K tokens of precise, structural answers.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        CODING AGENT                              │
│                    (Sonnet/Opus - expensive)                     │
│                                                                  │
│   Task: "Add rate limiting to the API"                          │
│   Instead of: grep + cat + grep + cat (100K tokens)             │
│   Does: @mu-agent "How is middleware structured?"               │
│                           │                                      │
└───────────────────────────┼──────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                        MU AGENT                                  │
│                    (Haiku - 60x cheaper)                         │
│                                                                  │
│   System: "You are a code structure specialist..."              │
│   Tools: mu_query, mu_context, mu_deps, mu_impact               │
│                           │                                      │
│   1. mu_query("SELECT * FROM classes WHERE name LIKE '%Mid%'")  │
│   2. mu_deps("AuthMiddleware")                                  │
│   3. Returns: 500 tokens of MU format                           │
│                                                                  │
└───────────────────────────┼──────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                        .mubase                                   │
│                    (DuckDB Graph DB)                             │
└─────────────────────────────────────────────────────────────────┘
```

## Cost Economics

| Metric | Current (Grep) | With MU Agent | Savings |
|--------|----------------|---------------|---------|
| Tokens per exploration | 50-100K | 2-5K | 95% |
| Model used | Sonnet ($3/1M) | Haiku ($0.25/1M) | 12x cheaper |
| Cost per question | $0.15-0.30 | $0.001-0.005 | 60-100x |
| Time to answer | 30-60 seconds | 2-5 seconds | 10x faster |

## CLI Commands

```bash
# Ask a question about the codebase
mu agent ask "How does authentication work?"

# Start interactive session
mu agent interactive

# Direct MUQL query (bypasses LLM)
mu agent query "SELECT * FROM functions WHERE complexity > 50"

# Show dependencies
mu agent deps AuthService --direction both

# Show impact analysis
mu agent impact User

# Detect circular dependencies
mu agent cycles
```

## Python API

```python
from mu.agent import MUAgent, AgentConfig

# Create agent with default config (Haiku)
agent = MUAgent()

# Ask a question
response = agent.ask("How does authentication work?")
print(response.content)

# Follow-up questions maintain context
response = agent.ask("What depends on it?")

# Direct methods (bypass LLM for quick queries)
result = agent.query("SELECT * FROM functions WHERE complexity > 50")
deps = agent.deps("AuthService", direction="both")
impact = agent.impact("User")
cycles = agent.cycles()

# Reset conversation
agent.reset()

# Custom configuration
config = AgentConfig(
    model="claude-3-5-sonnet-latest",  # Use more capable model
    max_tokens=8192,
    temperature=0.0,
)
agent = MUAgent(config)
```

## Claude Code Integration

The module provides a Claude Code agent definition at `.claude/agents/mu-agent.md`. This allows invoking MU Agent from within Claude Code sessions:

```markdown
@mu-agent How does the payment processing work?
```

The agent definition:
- Uses `claude-3-5-haiku-latest` for cost efficiency
- References MCP tools from the `mu` server
- Includes the full system prompt with examples

## Data Models

### AgentConfig

```python
@dataclass
class AgentConfig:
    model: str = "claude-3-5-haiku-latest"
    max_tokens: int = 4096
    temperature: float = 0.0
    mubase_path: str | None = None
```

### AgentResponse

```python
@dataclass
class AgentResponse:
    content: str           # Response text
    tool_calls_made: int   # Number of tool calls
    tokens_used: int       # Estimated token usage
    model: str             # Model used
    error: str | None      # Error message if failed
```

### ConversationMemory

```python
@dataclass
class ConversationMemory:
    messages: list[Message]
    mentioned_nodes: set[str]  # Track discussed nodes
    graph_summary: str | None
    max_messages: int = 50     # Prevent unbounded growth
```

## Available Tools

The agent has access to these tools for querying the code graph:

| Tool | Purpose | Example |
|------|---------|---------|
| `mu_query` | Execute MUQL queries | `SELECT * FROM functions WHERE complexity > 100` |
| `mu_context` | Smart context for questions | "How does authentication work?" |
| `mu_deps` | Dependency traversal | Show what `AuthService` depends on |
| `mu_impact` | Impact analysis | What breaks if `User` changes |
| `mu_ancestors` | Upstream dependencies | What does `cli.py` depend on |
| `mu_cycles` | Circular dependencies | Find import cycles |

## Response Format

Responses use MU format for compact code representation:

```
!module auth_service
@deps [jwt, bcrypt, UserRepository, Redis]

$AuthService
  @attrs [user_repo, token_service, cache]
  #login(email: str, password: str) -> TokenResponse
  #logout(user_id: UUID) -> None
  #refresh_token(token: str) -> TokenResponse
```

## Files

| File | Purpose |
|------|---------|
| `__init__.py` | Public API exports |
| `core.py` | MUAgent class implementation |
| `models.py` | Data models (AgentConfig, Message, etc.) |
| `memory.py` | Conversation state management |
| `prompt.py` | System prompt and examples |
| `tools.py` | Tool definitions for Anthropic API |
| `formats.py` | Response formatting utilities |
| `cli.py` | CLI commands |
| `CLAUDE.md` | This documentation |

## Testing

```bash
# Run agent tests
pytest tests/unit/test_agent.py -v

# Run with coverage
pytest tests/unit/test_agent.py --cov=src/mu/agent

# Run CLI commands
mu agent --help
```

## Error Handling

The agent uses error-as-data pattern:

```python
response = agent.ask("...")
if response.error:
    print(f"Error: {response.error}")
else:
    print(response.content)
```

Common errors:
- **Daemon not running**: Agent prompts user to run `mu daemon start`
- **No .mubase**: Agent prompts user to run `mu kernel build`
- **API key missing**: Clear error for missing `ANTHROPIC_API_KEY`
- **Tool execution fails**: Error returned in response, not raised

## Dependencies

- `anthropic` - Anthropic API client (optional, only needed for `ask()`)
- `click` - CLI framework
- `mu.client` - DaemonClient for .mubase queries
