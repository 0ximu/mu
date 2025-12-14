"""Prompt templates for LLM summarization."""

from __future__ import annotations

# Version tracking for cache invalidation when prompts change
PROMPT_VERSION = "1.0"

# Main summarization prompt
SUMMARIZE_FUNCTION_PROMPT = """\
You are summarizing code for an AI-readable format called MU.

Given this {language} function{context}:
```{language}
{body}
```

Provide 3-5 bullet points covering:
- Primary purpose
- Key inputs and outputs
- Important side effects (DB writes, API calls, state mutations)
- Business rules or invariants

Rules:
- Be extremely concise. Each bullet should be <15 words.
- Use technical terms, avoid fluff
- Focus on WHAT it does, not HOW (skip implementation details)
- Flag any: transactions, race conditions, external calls, mutations

Return ONLY the bullet points as a plain list starting with "- ", no preamble or explanation."""

# Shorter prompt for simpler functions
SUMMARIZE_SIMPLE_PROMPT = """\
Summarize this {language} function in 2-3 bullet points (<15 words each):
```{language}
{body}
```

Focus on: purpose, inputs/outputs, side effects. Return only "- " prefixed bullets."""


def format_summarize_prompt(
    body: str,
    language: str,
    context: str | None = None,
    simple: bool = False,
) -> str:
    """Format the summarization prompt with given parameters.

    Args:
        body: The function source code
        language: Programming language (python, typescript, csharp, etc.)
        context: Optional context like class name or module path
        simple: Use shorter prompt for simpler functions

    Returns:
        Formatted prompt string
    """
    template = SUMMARIZE_SIMPLE_PROMPT if simple else SUMMARIZE_FUNCTION_PROMPT

    context_str = ""
    if context:
        context_str = f" (in {context})"

    return template.format(
        body=body.strip(),
        language=language.lower(),
        context=context_str,
    )


def parse_summary_response(response: str) -> list[str]:
    """Parse LLM response into list of bullet points.

    Args:
        response: Raw LLM response text

    Returns:
        List of summary bullet points (cleaned)
    """
    bullets = []
    for line in response.strip().split("\n"):
        line = line.strip()
        # Handle various bullet formats: -, *, •, numbered
        if line.startswith(("-", "*", "•")):
            bullet = line.lstrip("-*• ").strip()
            if bullet:
                bullets.append(bullet)
        elif line and line[0].isdigit() and "." in line[:3]:
            # Handle "1. " or "1) " format
            bullet = line.split(".", 1)[-1].strip()
            if not bullet:
                bullet = line.split(")", 1)[-1].strip()
            if bullet:
                bullets.append(bullet)

    return bullets[:5]  # Cap at 5 bullets
