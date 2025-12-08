"""Natural Language to MUQL Translation.

Translates natural language questions about codebases into executable MUQL queries.
Uses LLM (via LiteLLM) with few-shot prompting and schema awareness.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import litellm
from litellm import completion

if TYPE_CHECKING:
    from mu.kernel import MUbase

logger = logging.getLogger(__name__)

# Disable LiteLLM verbose logging
litellm.suppress_debug_info = True

# Default model - cheap and fast
DEFAULT_MODEL = "claude-3-haiku-20240307"


@dataclass
class TranslationResult:
    """Result of NL to MUQL translation."""

    question: str
    muql: str
    explanation: str
    confidence: float
    executed: bool = False
    result: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "question": self.question,
            "muql": self.muql,
            "explanation": self.explanation,
            "confidence": self.confidence,
            "executed": self.executed,
            "result": self.result,
            "error": self.error,
        }


# MUQL grammar reference for the prompt
MUQL_GRAMMAR = """
MUQL Query Types:

1. SELECT - Query nodes with filters
   SELECT * FROM functions WHERE complexity > 20
   SELECT name, file_path FROM classes WHERE name LIKE '%Service%'
   SELECT COUNT(*) FROM modules
   SELECT name, complexity FROM functions ORDER BY complexity DESC LIMIT 10

2. SHOW - Explore relationships
   SHOW dependencies OF NodeName DEPTH 2
   SHOW dependents OF NodeName DEPTH 3
   SHOW children OF ClassName
   SHOW callers OF FunctionName
   SHOW callees OF FunctionName
   SHOW impact OF NodeName DEPTH 2
   SHOW ancestors OF NodeName DEPTH 2

3. FIND - Pattern-based search
   FIND functions MATCHING "test_%"
   FIND classes CALLING parse_file
   FIND functions WITH DECORATOR "cache"
   FIND modules IMPORTING requests

4. FIND CYCLES - Detect circular dependencies
   FIND CYCLES
   FIND CYCLES WHERE edge_type = 'imports'

5. PATH - Find paths between nodes
   PATH FROM cli TO parser MAX DEPTH 5
   PATH FROM UserController TO Database VIA imports

6. ANALYZE - Built-in analysis
   ANALYZE complexity
   ANALYZE hotspots FOR kernel
   ANALYZE circular
   ANALYZE impact FOR UserService

7. DESCRIBE - Schema introspection
   DESCRIBE tables
   DESCRIBE columns FROM functions

Node Types: functions, classes, modules, nodes (all)
Available columns: id, name, type, file_path, line_start, line_end, complexity, qualified_name
Operators: =, !=, <, >, <=, >=, LIKE, IN, NOT IN, CONTAINS
"""

FEW_SHOT_EXAMPLES = """
Examples of question -> MUQL translation:

Q: What are the most complex functions?
A: SELECT name, file_path, complexity FROM functions ORDER BY complexity DESC LIMIT 10

Q: Show me all service classes
A: SELECT * FROM classes WHERE name LIKE '%Service%'

Q: What depends on the AuthService class?
A: SHOW dependents OF AuthService DEPTH 2

Q: What does the CLI module depend on?
A: SHOW dependencies OF cli DEPTH 2

Q: Find all test functions
A: FIND functions MATCHING "test_%"

Q: Are there any circular dependencies?
A: FIND CYCLES

Q: How do I get from the API to the database?
A: PATH FROM api TO database MAX DEPTH 5

Q: What functions call parse_file?
A: FIND functions CALLING parse_file

Q: If I change auth.py, what might break?
A: SHOW impact OF auth DEPTH 3

Q: What are the upstream dependencies of the MCP server?
A: SHOW ancestors OF mcp DEPTH 3

Q: Show me functions with the @cache decorator
A: FIND functions WITH DECORATOR "cache"

Q: How many modules are there?
A: SELECT COUNT(*) FROM modules

Q: List all classes in order of complexity
A: SELECT name, file_path, complexity FROM classes ORDER BY complexity DESC

Q: What modules import requests?
A: FIND modules IMPORTING requests
"""


def _build_prompt(question: str, schema_info: str | None = None) -> str:
    """Build the translation prompt."""
    schema_section = ""
    if schema_info:
        schema_section = f"""
Current codebase context:
{schema_info}
"""

    return f"""You are a MUQL query translator. Translate the natural language question into a valid MUQL query.

{MUQL_GRAMMAR}

{FEW_SHOT_EXAMPLES}
{schema_section}
Instructions:
1. Analyze the question and identify what information is being requested
2. Choose the most appropriate query type (SELECT, SHOW, FIND, PATH, ANALYZE)
3. Use appropriate filters and clauses
4. Return ONLY the MUQL query, no explanation

Question: {question}

MUQL:"""


def _extract_muql(response: str) -> tuple[str, str]:
    """Extract MUQL query and any explanation from response.

    Returns:
        Tuple of (muql_query, explanation)
    """
    # Clean up the response
    text = response.strip()

    # Remove markdown code blocks if present
    if "```" in text:
        # Extract content between code blocks
        match = re.search(r"```(?:sql|muql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
        if match:
            text = match.group(1).strip()
        else:
            # Remove any remaining backticks
            text = text.replace("```", "").strip()

    # Split into query and explanation if there's extra text
    lines = text.split("\n")
    query_lines: list[str] = []
    explanation_lines: list[str] = []
    in_explanation = False

    for line in lines:
        stripped = line.strip()
        # Skip empty lines at the start
        if not query_lines and not stripped:
            continue
        # Detect explanation markers
        if stripped.lower().startswith(("explanation:", "note:", "this query", "--")):
            in_explanation = True

        if in_explanation:
            explanation_lines.append(stripped)
        else:
            # Only include lines that look like MUQL
            if stripped and not stripped.startswith("#"):
                query_lines.append(stripped)

    muql = " ".join(query_lines).strip()
    explanation = " ".join(explanation_lines).strip()

    # Clean up common artifacts
    muql = re.sub(r"\s+", " ", muql)  # Normalize whitespace

    return muql, explanation


def _get_schema_info(db: MUbase) -> str:
    """Get schema context from the database."""
    try:
        from mu.kernel.schema import NodeType

        stats = db.stats()
        nodes = stats.get("nodes", 0)
        edges = stats.get("edges", 0)

        # Get sample node names for context
        sample_info: list[str] = []

        # Sample classes
        classes = db.get_nodes(node_type=NodeType.CLASS)[:5]
        if classes:
            class_names = [n.name for n in classes]
            sample_info.append(f"Sample classes: {', '.join(class_names)}")

        # Sample modules
        modules = db.get_nodes(node_type=NodeType.MODULE)[:5]
        if modules:
            mod_names = [n.name for n in modules]
            sample_info.append(f"Sample modules: {', '.join(mod_names)}")

        return f"""Database has {nodes} nodes and {edges} edges.
{chr(10).join(sample_info)}"""
    except Exception as e:
        logger.debug(f"Failed to get schema info: {e}")
        return ""


class NL2MUQLTranslator:
    """Translates natural language to MUQL queries.

    Uses an LLM with few-shot prompting to convert natural language
    questions about codebases into executable MUQL queries.
    """

    def __init__(
        self,
        db: MUbase | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ):
        """Initialize the translator.

        Args:
            db: Optional MUbase instance for schema context and query execution
            model: LLM model to use (default: claude-3-haiku)
            api_key: API key for the LLM provider (falls back to env vars)
        """
        self.db = db
        self.model = model or os.getenv("MU_ASK_MODEL", DEFAULT_MODEL)
        self._api_key = api_key

    def translate(
        self,
        question: str,
        execute: bool = True,
        include_schema: bool = True,
    ) -> TranslationResult:
        """Translate a natural language question to MUQL.

        Args:
            question: Natural language question about the codebase
            execute: Whether to execute the generated query
            include_schema: Whether to include schema context in the prompt

        Returns:
            TranslationResult with the generated MUQL and optionally results
        """
        # Get schema context if available
        schema_info = None
        if include_schema and self.db:
            schema_info = _get_schema_info(self.db)

        # Build and send prompt
        prompt = _build_prompt(question, schema_info)

        try:
            response = completion(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.1,  # Low temperature for consistent output
            )

            response_text = response.choices[0].message.content
            muql, explanation = _extract_muql(response_text)

            # Estimate confidence based on response characteristics
            confidence = self._estimate_confidence(question, muql)

            result = TranslationResult(
                question=question,
                muql=muql,
                explanation=explanation,
                confidence=confidence,
            )

            # Execute if requested and we have a database
            if execute and self.db and muql:
                result = self._execute_query(result)

            return result

        except Exception as e:
            logger.error(f"Translation failed: {e}")
            return TranslationResult(
                question=question,
                muql="",
                explanation="",
                confidence=0.0,
                error=str(e),
            )

    def _estimate_confidence(self, question: str, muql: str) -> float:
        """Estimate confidence in the translation.

        Uses heuristics to estimate how confident we are in the translation.
        """
        if not muql:
            return 0.0

        confidence = 0.5  # Base confidence

        # Check for valid query start
        valid_starts = ("SELECT", "SHOW", "FIND", "PATH", "ANALYZE", "DESCRIBE")
        if muql.upper().startswith(valid_starts):
            confidence += 0.2

        # Check for balanced quotes
        if muql.count("'") % 2 == 0 and muql.count('"') % 2 == 0:
            confidence += 0.1

        # Check for balanced parentheses
        if muql.count("(") == muql.count(")"):
            confidence += 0.1

        # Penalize very short or very long queries
        if len(muql) < 10:
            confidence -= 0.2
        elif len(muql) > 500:
            confidence -= 0.1

        # Boost for clear keyword matches between question and query
        q_lower = question.lower()
        if "complex" in q_lower and "complexity" in muql.lower():
            confidence += 0.1
        if "depend" in q_lower and ("dependencies" in muql.lower() or "dependents" in muql.lower()):
            confidence += 0.1
        if "circular" in q_lower and "cycles" in muql.lower():
            confidence += 0.1

        return min(1.0, max(0.0, confidence))

    def _execute_query(self, result: TranslationResult) -> TranslationResult:
        """Execute the MUQL query and add results."""
        if not self.db or not result.muql:
            return result

        try:
            from mu.kernel.muql import MUQLEngine

            engine = MUQLEngine(self.db)
            query_result = engine.query_dict(result.muql)

            return TranslationResult(
                question=result.question,
                muql=result.muql,
                explanation=result.explanation,
                confidence=result.confidence,
                executed=True,
                result=query_result,
            )
        except Exception as e:
            logger.warning(f"Query execution failed: {e}")
            return TranslationResult(
                question=result.question,
                muql=result.muql,
                explanation=result.explanation,
                confidence=result.confidence,
                executed=False,
                error=f"Query execution failed: {e}",
            )


def translate(
    question: str,
    db: MUbase | None = None,
    execute: bool = True,
    model: str | None = None,
) -> TranslationResult:
    """Translate a natural language question to MUQL.

    Convenience function that creates a translator and translates the question.

    Args:
        question: Natural language question about the codebase
        db: Optional MUbase instance for context and execution
        execute: Whether to execute the generated query
        model: LLM model to use

    Returns:
        TranslationResult with the generated MUQL
    """
    translator = NL2MUQLTranslator(db=db, model=model)
    return translator.translate(question, execute=execute)


__all__ = [
    "NL2MUQLTranslator",
    "TranslationResult",
    "translate",
]
