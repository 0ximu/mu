# MU Agent - Product Requirements Document

**Version:** 1.0
**Date:** December 7, 2025
**Author:** Yavor Kangalov / Claude
**Status:** Ready to Build

---

## Executive Summary

MU Agent is a specialist AI agent that answers questions about code structure by querying a .mubase graph database. It runs on cheap models (Haiku) and reduces codebase exploration costs by 95%+ compared to having expensive models grep through files.

**The Core Insight:** Coding agents spend 50-100K tokens exploring codebases before writing a single line. MU Agent replaces that exploration with 2-5K tokens of precise, structural answers.

---

## Problem Statement

### Current State: Expensive, Blind Exploration

When Claude Code (or any AI coding agent) needs to understand a codebase:

```
User: "Add rate limiting to the API"

Claude Code (Sonnet @ $3/1M tokens):
1. ripgrep "rate" → 200 matches, reads results (5K tokens)
2. ripgrep "limit" → 300 matches, reads results (8K tokens)  
3. cat middleware.py → reads file (3K tokens)
4. cat api/routes.py → reads file (4K tokens)
5. "Let me check how other middleware works"
6. cat auth_middleware.py → reads file (2K tokens)
7. ... repeats 10-20 more times ...

Total: 50-100K tokens @ $3/1M = $0.15-0.30 PER QUESTION
Result: Still might miss important context
```

### Problems

1. **Expensive** - Exploration burns Sonnet/Opus tokens on file reading
2. **Slow** - Multiple round trips, grep → read → grep → read
3. **Incomplete** - Grep doesn't understand structure, misses relationships
4. **No Memory** - Every new question starts from scratch

---

## Solution: MU Agent

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        CODING AGENT                              │
│                    (Sonnet/Opus - expensive)                     │
│                                                                  │
│   Task: "Add rate limiting to the API"                          │
│                                                                  │
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
│                                                                  │
│   Nodes: 1,805 (modules, classes, functions)                    │
│   Edges: 1,940 (imports, inheritance, calls, contains)          │
│   Vectors: Optional embeddings for semantic search              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### The Economics

| Metric | Current (Grep) | With MU Agent | Savings |
|--------|----------------|---------------|---------|
| Tokens per exploration | 50-100K | 2-5K | 95% |
| Model used | Sonnet ($3/1M) | Haiku ($0.25/1M) | 12x cheaper |
| Cost per question | $0.15-0.30 | $0.001-0.005 | 60-100x |
| Time to answer | 30-60 seconds | 2-5 seconds | 10x faster |
| Accuracy | Grep misses structure | Graph knows all | Higher |

---

## User Stories

### Story 1: Claude Code Integration

```
As a developer using Claude Code,
I want to ask questions about my codebase structure,
So that I can get precise answers without burning tokens on file exploration.

Acceptance Criteria:
- Can invoke MU Agent with @mu-agent or /mu command
- Agent responds with MU format output
- Response includes relevant code paths and relationships
- Total token usage < 5K for typical questions
```

### Story 2: Standalone CLI

```
As a developer,
I want to query my codebase from the terminal,
So that I can explore structure without opening an IDE.

Acceptance Criteria:
- mu agent "How does authentication work?"
- mu agent -i (interactive mode)
- Responses are formatted for terminal readability
- Can pipe output to other tools
```

### Story 3: IDE Agnostic

```
As a developer using Cursor/Windsurf/other AI IDEs,
I want MU Agent to work with any coding assistant,
So that I'm not locked into one tool.

Acceptance Criteria:
- MCP server works with any MCP-compatible client
- HTTP API available for custom integrations
- Response format is standardized
```

---

## Functional Requirements

### FR1: Agent System Prompt

The MU Agent must have a comprehensive system prompt that includes:

```markdown
# MU Agent System Prompt

You are the MU Agent, a specialist in code structure analysis. Your job is to
answer questions about codebases by querying a .mubase graph database.

## Your Capabilities

1. **Structural Queries** - Find classes, functions, modules by pattern
2. **Dependency Analysis** - What does X depend on? What depends on X?
3. **Impact Analysis** - What breaks if X changes?
4. **Path Finding** - How does data flow from A to B?
5. **Pattern Recognition** - What architectural patterns exist?

## Your Tools

### mu_query(muql: str) -> QueryResult
Execute MUQL queries against the graph.

Examples:
- SELECT * FROM functions WHERE complexity > 100
- SELECT name, file_path FROM classes WHERE name LIKE '%Service%'
- SHOW dependencies OF UserService
- SHOW callers OF process_payment
- PATH FROM api_routes TO database
- ANALYZE circular

### mu_context(question: str, max_tokens: int = 4000) -> ContextResult
Smart context extraction. Returns the optimal subgraph for a question.

### mu_deps(node: str, depth: int = 1, direction: str = "outgoing") -> DepsResult
Get dependencies of a node.
- direction: "outgoing" (what it uses), "incoming" (what uses it), "both"

### mu_impact(node: str) -> ImpactResult
Get all nodes that would be affected if this node changes.

### mu_ancestors(node: str) -> AncestorsResult
Get all nodes that this node depends on (transitive).

### mu_cycles(edge_types: list[str] = None) -> CyclesResult
Find circular dependencies in the graph.

## Response Format

Always respond in MU format when showing code structure:

!module auth_service
@deps [jwt, bcrypt, redis]

$AuthService
  @attrs [user_repo, token_service]
  #login(credentials) -> Token
  #logout(user_id) -> None

Be concise. Return only what's needed. No boilerplate explanations.

## Examples

### Example 1: Finding Structure

User: "What handles user authentication?"

Your actions:
1. mu_query("SELECT * FROM classes WHERE name LIKE '%Auth%'")
2. mu_deps("AuthService")

Your response:
"Authentication is handled by AuthService in src/auth/service.py.

!module auth_service
@deps [jwt, bcrypt, UserRepository, Redis]

$AuthService
  #login(email, password) -> TokenResponse
  #logout(user_id) -> None  
  #refresh_token(token) -> TokenResponse

It depends on UserRepository for data, jwt for tokens, Redis for sessions."

### Example 2: Impact Analysis

User: "What breaks if I change the User model?"

Your actions:
1. mu_impact("User")

Your response:
"Changing User impacts 14 nodes:

Direct dependents (4):
- UserRepository.create()
- UserRepository.update()
- AuthService.login()
- UserController.get_profile()

Transitive impact (10):
- [list of downstream nodes]

Recommendation: Create a migration and update UserRepository first."

### Example 3: Architecture Question

User: "How does data flow from API request to database?"

Your actions:
1. mu_query("PATH FROM 'api' TO 'database' MAX DEPTH 6")

Your response:
"Request flow:

api/routes.py → controllers/user_controller.py → services/user_service.py 
→ repositories/user_repository.py → database/connection.py

Pattern: Route → Controller → Service → Repository → DB (Clean Architecture)"
```

### FR2: Tool Implementations

All tools must be available via:
1. MCP protocol (for Claude Code / MCP clients)
2. HTTP API (for custom integrations)
3. Python SDK (for programmatic use)

```python
# Python SDK
from mu.agent import MUAgent

agent = MUAgent(mubase_path=".mubase")

# Single question
response = agent.ask("How does authentication work?")

# Conversation mode
agent.ask("What is UserService?")
agent.ask("What depends on it?")  # Remembers context
agent.ask("Show me the most complex method")  # Continues conversation

# Direct tool access
result = agent.query("SELECT * FROM functions WHERE complexity > 100")
context = agent.context("payment processing", max_tokens=4000)
deps = agent.deps("PaymentService", direction="both")
```

### FR3: Claude Code Integration

Create `.claude/agents/mu-agent.md`:

```markdown
---
name: mu-agent
description: Code structure specialist. Ask about architecture, dependencies, impact.
model: claude-haiku-3.5
tools:
  - mcp: mu
---

You are the MU Agent, a specialist in code structure analysis.

[Full system prompt here]
```

### FR4: Conversation Memory

The agent must maintain conversation state:

```python
class MUAgent:
    def __init__(self):
        self.conversation: list[Message] = []
        self.mentioned_nodes: set[str] = set()  # Track discussed nodes
        self.graph_context: str = ""  # High-level graph summary
    
    def ask(self, question: str) -> str:
        # Add graph context if first message
        if not self.conversation:
            self.graph_context = self._get_graph_summary()
        
        # Track mentioned nodes for follow-up questions
        self._extract_mentioned_nodes(question)
        
        # Include conversation history
        self.conversation.append({"role": "user", "content": question})
        
        response = self._call_llm()
        
        self.conversation.append({"role": "assistant", "content": response})
        
        return response
```

### FR5: Response Formatting

Responses must be:
1. **Concise** - No boilerplate, no "I'd be happy to help"
2. **Structural** - Use MU format for code representation
3. **Actionable** - Include file paths, line numbers when relevant
4. **Token-efficient** - Minimize tokens while preserving meaning

---

## Non-Functional Requirements

### NFR1: Performance

| Metric | Target |
|--------|--------|
| Response time (p50) | < 2 seconds |
| Response time (p99) | < 5 seconds |
| Token usage (typical) | < 3K tokens |
| Token usage (max) | < 10K tokens |

### NFR2: Cost

| Metric | Target |
|--------|--------|
| Cost per question (Haiku) | < $0.005 |
| Cost per session (10 questions) | < $0.05 |

### NFR3: Accuracy

| Metric | Target |
|--------|--------|
| Correct tool selection | > 95% |
| Relevant context returned | > 90% |
| No hallucinated nodes | 100% |

---

## Technical Design

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         mu/agent/                                │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │    core.py   │  │   prompt.py  │  │     memory.py        │  │
│  │              │  │              │  │                      │  │
│  │  MUAgent     │  │  SYSTEM_     │  │  ConversationMemory  │  │
│  │  .ask()      │  │  PROMPT      │  │  .add()              │  │
│  │  .query()    │  │              │  │  .get_context()      │  │
│  │  .context()  │  │  EXAMPLES    │  │  .clear()            │  │
│  │  .reset()    │  │              │  │                      │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│          │                                      │                │
│          └──────────────┬───────────────────────┘                │
│                         │                                        │
│  ┌──────────────────────▼───────────────────────────────────┐   │
│  │                    tools.py                               │   │
│  │                                                           │   │
│  │  @tool mu_query(muql: str) -> QueryResult                │   │
│  │  @tool mu_context(question: str) -> ContextResult        │   │
│  │  @tool mu_deps(node: str, ...) -> DepsResult             │   │
│  │  @tool mu_impact(node: str) -> ImpactResult              │   │
│  │  @tool mu_ancestors(node: str) -> AncestorsResult        │   │
│  │  @tool mu_cycles() -> CyclesResult                       │   │
│  │                                                           │   │
│  └──────────────────────┬───────────────────────────────────┘   │
│                         │                                        │
└─────────────────────────┼────────────────────────────────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │       .mubase         │
              │   (existing infra)    │
              └───────────────────────┘
```

### File Structure

```
src/mu/agent/
├── __init__.py          # Public API exports
├── core.py              # MUAgent class
├── prompt.py            # System prompt and examples
├── memory.py            # Conversation state management
├── tools.py             # Tool definitions (wraps existing MCP tools)
├── formats.py           # Response formatting utilities
└── cli.py               # CLI commands (mu agent ...)

.claude/
└── agents/
    └── mu-agent.md      # Claude Code agent definition
```

### API Design

```python
# src/mu/agent/__init__.py

from .core import MUAgent
from .tools import mu_query, mu_context, mu_deps, mu_impact

__all__ = ["MUAgent", "mu_query", "mu_context", "mu_deps", "mu_impact"]
```

```python
# src/mu/agent/core.py

from dataclasses import dataclass
from typing import Optional
import anthropic

from mu.agent.prompt import SYSTEM_PROMPT
from mu.agent.memory import ConversationMemory
from mu.agent.tools import TOOL_DEFINITIONS
from mu.client import DaemonClient


@dataclass
class AgentConfig:
    """Configuration for MU Agent."""
    model: str = "claude-haiku-3.5"
    max_tokens: int = 4096
    temperature: float = 0.0
    mubase_path: Optional[str] = None


class MUAgent:
    """
    MU Agent - Code structure specialist.
    
    Answers questions about codebases by querying .mubase graph database.
    Designed to run on cheap models (Haiku) to minimize token costs.
    
    Usage:
        agent = MUAgent()
        response = agent.ask("How does authentication work?")
        
        # Follow-up questions maintain context
        response = agent.ask("What depends on it?")
        
        # Reset conversation
        agent.reset()
    """
    
    def __init__(self, config: AgentConfig = None):
        self.config = config or AgentConfig()
        self.client = anthropic.Client()
        self.mu_client = DaemonClient()
        self.memory = ConversationMemory()
        self._graph_summary: Optional[str] = None
    
    def ask(self, question: str) -> str:
        """
        Ask a question about the codebase.
        
        Args:
            question: Natural language question about code structure
            
        Returns:
            MU-formatted response with relevant code context
        """
        # Lazy-load graph summary
        if self._graph_summary is None:
            self._graph_summary = self._get_graph_summary()
        
        # Add to conversation
        self.memory.add_user_message(question)
        
        # Build messages with context
        messages = self.memory.get_messages()
        
        # Call LLM with tools
        response = self.client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            system=SYSTEM_PROMPT.format(graph_summary=self._graph_summary),
            messages=messages,
            tools=TOOL_DEFINITIONS,
        )
        
        # Process tool calls
        final_response = self._process_response(response)
        
        # Add to memory
        self.memory.add_assistant_message(final_response)
        
        return final_response
    
    def query(self, muql: str) -> dict:
        """Execute MUQL query directly."""
        return self.mu_client.query(muql)
    
    def context(self, question: str, max_tokens: int = 4000) -> dict:
        """Get smart context for a question."""
        return self.mu_client.context(question, max_tokens)
    
    def deps(self, node: str, direction: str = "outgoing") -> dict:
        """Get dependencies of a node."""
        return self.mu_client.deps(node, direction=direction)
    
    def impact(self, node: str) -> dict:
        """Get impact analysis for a node."""
        return self.mu_client.impact(node)
    
    def reset(self):
        """Reset conversation memory."""
        self.memory.clear()
    
    def _get_graph_summary(self) -> str:
        """Get high-level summary of the graph."""
        status = self.mu_client.status()
        if not status.get("success"):
            return "Graph not available. Run `mu kernel build` first."
        
        stats = status.get("stats", {})
        return f"""Graph Summary:
- Nodes: {stats.get('node_count', 'unknown')}
- Edges: {stats.get('edge_count', 'unknown')}
- Modules: {stats.get('modules', 'unknown')}
- Classes: {stats.get('classes', 'unknown')}
- Functions: {stats.get('functions', 'unknown')}"""
    
    def _process_response(self, response) -> str:
        """Process LLM response, executing tool calls as needed."""
        # Handle tool use loop
        while response.stop_reason == "tool_use":
            tool_results = []
            
            for content in response.content:
                if content.type == "tool_use":
                    result = self._execute_tool(content.name, content.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": content.id,
                        "content": str(result),
                    })
            
            # Continue conversation with tool results
            response = self.client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                system=SYSTEM_PROMPT.format(graph_summary=self._graph_summary),
                messages=self.memory.get_messages() + [
                    {"role": "assistant", "content": response.content},
                    {"role": "user", "content": tool_results},
                ],
                tools=TOOL_DEFINITIONS,
            )
        
        # Extract text response
        return "".join(
            content.text for content in response.content 
            if hasattr(content, "text")
        )
    
    def _execute_tool(self, name: str, args: dict) -> dict:
        """Execute a tool and return results."""
        if name == "mu_query":
            return self.mu_client.query(args["muql"])
        elif name == "mu_context":
            return self.mu_client.context(
                args["question"], 
                args.get("max_tokens", 4000)
            )
        elif name == "mu_deps":
            return self.mu_client.deps(
                args["node"],
                direction=args.get("direction", "outgoing"),
            )
        elif name == "mu_impact":
            return self.mu_client.impact(args["node"])
        elif name == "mu_ancestors":
            return self.mu_client.ancestors(args["node"])
        elif name == "mu_cycles":
            return self.mu_client.cycles(args.get("edge_types"))
        else:
            return {"error": f"Unknown tool: {name}"}
```

### CLI Commands

```python
# src/mu/agent/cli.py

import click
from mu.agent import MUAgent


@click.group()
def agent():
    """MU Agent - Code structure specialist."""
    pass


@agent.command()
@click.argument("question")
@click.option("--model", default="claude-haiku-3.5", help="Model to use")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def ask(question: str, model: str, as_json: bool):
    """Ask a question about the codebase."""
    agent = MUAgent(AgentConfig(model=model))
    response = agent.ask(question)
    
    if as_json:
        click.echo(json.dumps({"response": response}))
    else:
        click.echo(response)


@agent.command()
@click.option("--model", default="claude-haiku-3.5", help="Model to use")
def interactive(model: str):
    """Start interactive session with MU Agent."""
    agent = MUAgent(AgentConfig(model=model))
    
    click.echo("MU Agent - Code Structure Specialist")
    click.echo("Type 'exit' to quit, 'reset' to clear conversation\n")
    
    while True:
        try:
            question = click.prompt("You", prompt_suffix=": ")
        except (EOFError, KeyboardInterrupt):
            break
        
        if question.lower() == "exit":
            break
        elif question.lower() == "reset":
            agent.reset()
            click.echo("Conversation cleared.\n")
            continue
        
        response = agent.ask(question)
        click.echo(f"\nMU: {response}\n")
    
    click.echo("Goodbye!")
```

---

## Implementation Plan

### Phase 1: Core Agent (4 hours)

| Task | Time | Output |
|------|------|--------|
| Create src/mu/agent/ package | 30m | Package structure |
| Write system prompt + examples | 1h | prompt.py |
| Implement MUAgent class | 1.5h | core.py |
| Implement memory management | 30m | memory.py |
| Wrap existing tools | 30m | tools.py |

### Phase 2: CLI Integration (1 hour)

| Task | Time | Output |
|------|------|--------|
| Add agent commands | 30m | cli.py |
| Wire into main CLI | 15m | Updated cli.py |
| Test interactive mode | 15m | Working REPL |

### Phase 3: Claude Code Integration (1 hour)

| Task | Time | Output |
|------|------|--------|
| Create agent definition file | 30m | .claude/agents/mu-agent.md |
| Test with Claude Code | 30m | Working integration |

### Phase 4: Testing & Polish (2 hours)

| Task | Time | Output |
|------|------|--------|
| Write unit tests | 1h | tests/test_agent.py |
| Test real-world questions | 30m | Validated responses |
| Tune prompt based on results | 30m | Improved accuracy |

**Total: 8 hours**

---

## Success Metrics

### Week 1

| Metric | Target |
|--------|--------|
| Agent responds correctly | > 80% of questions |
| Token usage | < 5K per question |
| Response time | < 5 seconds |

### Week 4

| Metric | Target |
|--------|--------|
| Agent responds correctly | > 95% of questions |
| Users report cost savings | > 50% reduction |
| Claude Code integration works | 100% |

### Month 3

| Metric | Target |
|--------|--------|
| Active users | > 100 |
| Questions answered | > 10,000 |
| Community contributions | > 5 PRs |

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Haiku too dumb for complex queries | High | Fall back to Sonnet for complex questions |
| Tool selection errors | Medium | Improve few-shot examples in prompt |
| Response too verbose | Low | Add response length limits, tune prompt |
| .mubase not built | Medium | Agent prompts user to run `mu kernel build` |

---

## Open Questions

1. **Model selection**: Should we auto-detect question complexity and upgrade to Sonnet?
2. **Caching**: Should we cache frequent queries? (e.g., "what's the architecture")
3. **Streaming**: Should responses stream for better UX?
4. **Multi-repo**: How does the agent handle monorepos or multi-repo setups?

---

## Appendix: Full System Prompt

```markdown
You are the MU Agent, a specialist in code structure analysis.

You have access to a .mubase graph database containing the structural representation
of a codebase. Your job is to answer questions about code architecture, dependencies,
and relationships by querying this graph.

## Graph Summary

{graph_summary}

## Your Tools

### mu_query(muql: str) -> QueryResult
Execute MUQL queries against the graph database.

MUQL supports:
- SELECT: `SELECT name, complexity FROM functions WHERE complexity > 100`
- SHOW: `SHOW dependencies OF UserService`, `SHOW callers OF process_payment`
- FIND: `FIND classes IMPLEMENTING Repository`, `FIND functions WITH DECORATOR "cache"`
- PATH: `PATH FROM api_routes TO database MAX DEPTH 5`
- ANALYZE: `ANALYZE circular`, `ANALYZE coupling`

### mu_context(question: str, max_tokens: int = 4000) -> ContextResult
Smart context extraction. Returns the optimal code subgraph for answering a question.
Use this when the user asks a broad question and you need comprehensive context.

### mu_deps(node: str, depth: int = 1, direction: str = "outgoing") -> DepsResult
Get dependencies of a node.
- direction "outgoing": What this node depends on
- direction "incoming": What depends on this node (dependents)
- direction "both": Both directions

### mu_impact(node: str) -> ImpactResult
Get all nodes that would be affected if this node changes.
Useful for understanding the blast radius of a change.

### mu_ancestors(node: str) -> AncestorsResult  
Get all transitive dependencies of a node.
Useful for understanding what a component ultimately relies on.

### mu_cycles(edge_types: list[str] = None) -> CyclesResult
Find circular dependencies in the graph.
Optionally filter by edge types: ["imports", "calls", "inherits"]

## Response Guidelines

1. **Be concise** - No boilerplate. No "I'd be happy to help." Just answer.
2. **Use MU format** - When showing code structure, use MU sigils:
   - `!module name` for modules
   - `$ClassName` for classes (use `< BaseClass` for inheritance)
   - `#function_name(params) -> ReturnType` for functions
   - `@deps [dep1, dep2]` for dependencies
   - `@attrs [attr1, attr2]` for attributes
3. **Include paths** - Always mention file paths so users can navigate
4. **Be structural** - Focus on relationships, not implementation details
5. **Suggest next steps** - If relevant, suggest what to explore next

## Examples

### Example 1: Finding Components

User: "What handles authentication?"

Think: I need to find auth-related classes and understand their structure.

Actions:
1. mu_query("SELECT name, file_path FROM classes WHERE name LIKE '%Auth%'")
2. mu_deps("AuthService")

Response:
Authentication is handled by `AuthService` in `src/auth/service.py`.

!module auth_service
@deps [jwt, bcrypt, UserRepository, RedisClient]

$AuthService
  @attrs [user_repo, token_service, cache]
  #login(email: str, password: str) -> TokenResponse
  #logout(user_id: UUID) -> None
  #refresh_token(token: str) -> TokenResponse
  #validate_token(token: str) -> User | None

Dependencies:
- `UserRepository` for user data
- `jwt` for token generation
- `RedisClient` for session storage

### Example 2: Impact Analysis

User: "What breaks if I change the User model?"

Think: I need to find all code that depends on User.

Actions:
1. mu_impact("User")

Response:
Changing `User` impacts 14 nodes across 3 layers:

**Direct dependents (4):**
- `UserRepository.create()` - creates User instances
- `UserRepository.update()` - updates User fields
- `AuthService.login()` - returns User
- `UserController.get_profile()` - serializes User

**Transitive impact (10):**
- `api/routes/auth.py` - exposes login endpoint
- `api/routes/users.py` - exposes profile endpoint
- [8 more nodes...]

**Recommendation:** If changing User fields, update UserRepository first, then run tests for AuthService.

### Example 3: Architecture Overview

User: "How is this codebase structured?"

Think: I need to give a high-level overview of the architecture.

Actions:
1. mu_context("architecture overview", max_tokens=2000)
2. mu_query("SELECT name FROM modules WHERE name NOT LIKE 'test%' LIMIT 20")

Response:
This codebase follows **Clean Architecture** with 4 layers:

```
api/          → HTTP routes, request handling
controllers/  → Business logic orchestration  
services/     → Domain logic, business rules
repositories/ → Data access, persistence
```

Key modules:
- `auth_service` - Authentication (JWT + sessions)
- `user_service` - User management
- `payment_service` - Payment processing (Stripe)

External dependencies: Redis (caching), PostgreSQL (data), Stripe (payments)

### Example 4: Circular Dependencies

User: "Are there any circular dependencies?"

Actions:
1. mu_cycles()

Response:
Found 2 circular dependency chains:

**Cycle 1:** `auth_service` → `user_service` → `auth_service`
- auth_service imports user_service for User model
- user_service imports auth_service for permission checks
- **Fix:** Extract permissions to separate module

**Cycle 2:** `payment_service` → `notification_service` → `payment_service`  
- payment_service notifies on payment
- notification_service checks payment status
- **Fix:** Use events instead of direct imports

### Example 5: Following Up

User: "Tell me more about AuthService"
[Previous context: user asked about authentication]

Think: User wants more detail on AuthService specifically.

Actions:
1. mu_query("SELECT * FROM functions WHERE qualified_name LIKE 'AuthService.%'")
2. mu_deps("AuthService", direction="both")

Response:
`AuthService` in detail:

!module auth_service
$AuthService
  #login(email, password) -> TokenResponse :: complexity:45
    Validates credentials, creates JWT + refresh token, stores session in Redis
  
  #logout(user_id) -> None :: complexity:12
    Invalidates all sessions for user
  
  #refresh_token(token) -> TokenResponse :: complexity:38
    Validates refresh token, issues new access token
  
  #validate_token(token) -> User | None :: complexity:28
    Decodes JWT, checks expiry, loads user from cache/DB

**Used by (incoming):**
- `AuthMiddleware` - validates requests
- `UserController` - login/logout endpoints
- `WebSocketHandler` - authenticates connections

**Uses (outgoing):**
- `UserRepository` - user lookup
- `TokenService` - JWT operations
- `RedisClient` - session storage
```

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-07 | Initial PRD |

---

*Built for the MU project by Yavor Kangalov and Claude.*
*"Stop paying Sonnet to grep. Let Haiku + MU do it."*
