"""MU Agent - Code structure specialist.

MU Agent answers questions about codebases by querying the .mubase graph database.
Designed to run on cheap models (Haiku) to minimize token costs while providing
accurate, structural answers.

Example:
    >>> from mu.agent import MUAgent, AgentConfig
    >>>
    >>> # Create agent with default config
    >>> agent = MUAgent()
    >>> response = agent.ask("How does authentication work?")
    >>> print(response.content)
    >>>
    >>> # Follow-up questions maintain context
    >>> response = agent.ask("What depends on it?")
    >>>
    >>> # Reset conversation
    >>> agent.reset()
    >>>
    >>> # Custom config
    >>> config = AgentConfig(model="claude-3-5-sonnet-latest")
    >>> agent = MUAgent(config)

Direct Methods (bypass LLM):
    >>> agent.query("SELECT * FROM functions WHERE complexity > 50")
    >>> agent.context("payment processing", max_tokens=4000)
    >>> agent.deps("PaymentService", direction="both")
    >>> agent.impact("User")
    >>> agent.cycles()
"""

from mu.agent.core import MUAgent
from mu.agent.formats import (
    format_cycles_summary,
    format_deps_tree,
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
from mu.agent.prompt import EXAMPLES, SYSTEM_PROMPT, format_system_prompt
from mu.agent.tools import TOOL_DEFINITIONS, execute_tool, format_tool_result

__all__ = [
    # Core
    "MUAgent",
    # Models
    "AgentConfig",
    "AgentResponse",
    "Message",
    "ToolCall",
    "ToolResult",
    "GraphSummary",
    # Memory
    "ConversationMemory",
    # Prompt
    "SYSTEM_PROMPT",
    "EXAMPLES",
    "format_system_prompt",
    # Tools
    "TOOL_DEFINITIONS",
    "execute_tool",
    "format_tool_result",
    # Formatting
    "format_mu_output",
    "format_deps_tree",
    "format_impact_summary",
    "format_cycles_summary",
    "truncate_response",
]
