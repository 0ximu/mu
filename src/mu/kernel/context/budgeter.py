"""Token budgeting for context extraction.

Selects nodes to fit within a token budget using accurate token counting
and greedy selection by relevance score.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import tiktoken

from mu.kernel.context.models import ExportConfig, ScoredNode
from mu.kernel.schema import NodeType

if TYPE_CHECKING:
    from mu.kernel.models import Node
    from mu.kernel.mubase import MUbase


class TokenBudgeter:
    """Select nodes to fit within a token budget.

    Uses tiktoken for accurate token counting and greedy selection
    by relevance score. Ensures essential context (parent classes)
    is included when needed.
    """

    # Base tokens for different node types (signature overhead)
    NODE_TYPE_BASE_TOKENS: dict[str, int] = {
        "module": 15,  # ! module name + @deps
        "class": 25,  # $ class < bases + @attrs
        "function": 20,  # # func(params) -> type
        "external": 5,  # Just the name
    }

    # Average tokens per parameter
    TOKENS_PER_PARAM = 5

    # Average tokens per class attribute
    TOKENS_PER_ATTR = 3

    def __init__(
        self,
        max_tokens: int,
        encoding: str = "cl100k_base",
        export_config: ExportConfig | None = None,
    ) -> None:
        """Initialize the token budgeter.

        Args:
            max_tokens: Maximum tokens to allow in output.
            encoding: Tiktoken encoding name (default: cl100k_base for GPT-4).
            export_config: Configuration for export options (docstrings, line numbers, etc.).
        """
        self.max_tokens = max_tokens
        self.encoding = tiktoken.get_encoding(encoding)
        self.export_config = export_config or ExportConfig()
        self._token_cache: dict[str, int] = {}

    def count_tokens(self, text: str) -> int:
        """Count tokens in a text string.

        Args:
            text: The text to count tokens for.

        Returns:
            Number of tokens.
        """
        return len(self.encoding.encode(text))

    def estimate_node_tokens(self, node: Node) -> int:
        """Estimate token count for a node.

        Uses cached estimates when possible. Estimation is based on
        node type and properties (parameters, attributes, etc.).

        Args:
            node: The node to estimate tokens for.

        Returns:
            Estimated token count.
        """
        # Check cache
        if node.id in self._token_cache:
            return self._token_cache[node.id]

        # Base tokens for node type
        base = self.NODE_TYPE_BASE_TOKENS.get(node.type.value, 10)

        # Add tokens for the name
        tokens = base + len(node.name.split("_")) + len(node.name.split("."))

        # Add based on properties
        props = node.properties

        # Function/method parameters
        if node.type == NodeType.FUNCTION:
            params = props.get("parameters", [])
            tokens += len(params) * self.TOKENS_PER_PARAM

            # Return type
            if props.get("return_type"):
                tokens += 3

            # Modifiers
            if props.get("is_async"):
                tokens += 1
            if props.get("is_static") or props.get("is_classmethod"):
                tokens += 1

        # Class attributes and bases
        elif node.type == NodeType.CLASS:
            attrs = props.get("attributes", [])
            tokens += len(attrs) * self.TOKENS_PER_ATTR

            bases = props.get("bases", [])
            tokens += len(bases) * 3

        # Module imports
        elif node.type == NodeType.MODULE:
            # Estimate based on file path length
            if node.file_path:
                tokens += len(node.file_path.split("/")) * 2

        # Docstring estimation
        if self.export_config.include_docstrings:
            docstring = props.get("docstring")
            if docstring:
                # Rough estimate: 1 token per 4 chars, capped at 50 tokens
                doc_tokens = min(len(docstring) // 4, 50)
                tokens += doc_tokens

        # Line numbers overhead if enabled
        if self.export_config.include_line_numbers:
            tokens += 5  # :L123-456 approx

        # Cache and return
        self._token_cache[node.id] = tokens
        return tokens

    def fit_to_budget(
        self,
        scored_nodes: list[ScoredNode],
        mubase: MUbase | None = None,
        include_parent: bool = True,
    ) -> list[ScoredNode]:
        """Select nodes to fit within the token budget.

        Uses greedy selection by score, ensuring higher-scored nodes
        are prioritized. Optionally includes parent context.

        Args:
            scored_nodes: Nodes with scores, assumed sorted by score descending.
            mubase: MUbase for looking up parent nodes.
            include_parent: Whether to include parent class for methods.

        Returns:
            Selected nodes within budget.
        """
        selected: list[ScoredNode] = []
        selected_ids: set[str] = set()
        used_tokens = 0

        # Track which parent nodes we need to add
        needed_parents: dict[str, ScoredNode] = {}

        for scored_node in scored_nodes:
            node = scored_node.node
            estimated = self.estimate_node_tokens(node)

            # Check if we need to add parent context
            parent_tokens = 0
            parent_node = None

            if (
                include_parent
                and mubase is not None
                and node.type == NodeType.FUNCTION
                and node.properties.get("is_method")
            ):
                parent = mubase.get_parent(node.id)
                if parent and parent.id not in selected_ids:
                    parent_tokens = self.estimate_node_tokens(parent)
                    parent_node = parent

            total_new_tokens = estimated + parent_tokens

            # Check if fits in budget
            if used_tokens + total_new_tokens <= self.max_tokens:
                # Add parent if needed
                if parent_node:
                    parent_scored = ScoredNode(
                        node=parent_node,
                        score=scored_node.score * 0.9,  # Slightly lower than child
                        proximity_score=1.0,  # Direct parent
                        estimated_tokens=parent_tokens,
                    )
                    needed_parents[parent_node.id] = parent_scored
                    selected_ids.add(parent_node.id)
                    used_tokens += parent_tokens

                # Add the node
                scored_node.estimated_tokens = estimated
                selected.append(scored_node)
                selected_ids.add(node.id)
                used_tokens += estimated

            elif used_tokens >= self.max_tokens:
                # Budget exhausted
                break

        # Insert parent nodes before their children for better output ordering
        final_selected = []
        for scored_node in selected:
            node = scored_node.node
            # Check if there's a needed parent
            parent = mubase.get_parent(node.id) if mubase else None
            if parent and parent.id in needed_parents:
                parent_scored = needed_parents.pop(parent.id)
                final_selected.append(parent_scored)
            final_selected.append(scored_node)

        # Add any remaining parents
        final_selected.extend(needed_parents.values())

        return final_selected

    def get_actual_tokens(self, mu_text: str) -> int:
        """Get actual token count for generated MU text.

        Args:
            mu_text: The generated MU format text.

        Returns:
            Actual token count.
        """
        return self.count_tokens(mu_text)


__all__ = ["TokenBudgeter"]
