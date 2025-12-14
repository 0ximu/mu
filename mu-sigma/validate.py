"""Answer validation for MU-SIGMA.

Validates Q&A pairs using Claude Haiku for cost efficiency.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mu.sigma.build import get_all_node_names
from mu.sigma.config import SigmaConfig
from mu.sigma.llm_client import get_anthropic_client
from mu.sigma.models import QAPair, ValidationStatus

logger = logging.getLogger(__name__)

VALIDATION_PROMPT = """\
You are validating a Q&A pair about a codebase for training data quality.

## Q&A Pair to Validate

Question: {question}
Category: {category}
Answer: {answer}
Referenced Nodes: {nodes}

## Available Nodes in Codebase

{available_nodes}

## Validation Checks

1. **Node Existence**: Do the referenced nodes exist in the available nodes list?
2. **Semantic Correctness**: Does the answer make sense for the question?
3. **Relevance**: Are the referenced nodes actually relevant to the question?

## Output Format

Return ONLY a JSON object:
```json
{{
  "status": "accepted|corrected|rejected",
  "valid_nodes": ["NodeA", "NodeB"],
  "invalid_nodes": ["NodeC"],
  "reasoning": "Brief explanation of validation decision"
}}
```

Status meanings:
- "accepted": Answer is correct and nodes are valid
- "corrected": Answer is mostly correct but some nodes were invalid (use valid_nodes)
- "rejected": Answer is wrong or no valid nodes found

Validate now:"""


async def validate_answer(
    qa_pair: QAPair,
    mubase_path: Path,
    config: SigmaConfig,
) -> QAPair:
    """Validate a Q&A pair.

    Args:
        qa_pair: Q&A pair to validate
        mubase_path: Path to .mubase file
        config: Pipeline configuration

    Returns:
        Updated QAPair with validation status
    """
    if not qa_pair.answer or not qa_pair.relevant_nodes:
        qa_pair.validation_status = ValidationStatus.REJECTED
        qa_pair.reasoning = "No answer or relevant nodes"
        return qa_pair

    # Get all available nodes
    all_names = get_all_node_names(mubase_path)

    # Pre-validate nodes (before LLM call)
    valid_nodes = [n for n in qa_pair.relevant_nodes if n in all_names]
    invalid_nodes = [n for n in qa_pair.relevant_nodes if n not in all_names]

    # If no nodes are valid, reject without LLM
    if not valid_nodes:
        qa_pair.validation_status = ValidationStatus.REJECTED
        qa_pair.valid_nodes = []
        qa_pair.invalid_nodes = invalid_nodes
        qa_pair.reasoning = "No referenced nodes exist in codebase"
        return qa_pair

    # If all nodes are valid, check semantic correctness with LLM
    available_sample = list(all_names)[:100]  # Sample for prompt

    prompt = VALIDATION_PROMPT.format(
        question=qa_pair.question,
        category=qa_pair.category.value,
        answer=qa_pair.answer,
        nodes=", ".join(qa_pair.relevant_nodes),
        available_nodes=", ".join(available_sample),
    )

    client = get_anthropic_client()

    for attempt in range(config.llm.max_retries + 1):
        try:
            response = await client.messages.create(
                model=config.llm.validation_model,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )

            content = response.content[0].text if response.content else ""
            validation_data = _parse_validation_response(content)

            if validation_data:
                status_str = validation_data.get("status", "rejected")
                try:
                    qa_pair.validation_status = ValidationStatus(status_str)
                except ValueError:
                    qa_pair.validation_status = ValidationStatus.REJECTED

                # Use pre-validated nodes (more reliable than LLM)
                qa_pair.valid_nodes = valid_nodes
                qa_pair.invalid_nodes = invalid_nodes
                qa_pair.reasoning = validation_data.get("reasoning", "")

                return qa_pair

        except Exception as e:
            import anthropic

            if isinstance(e, anthropic.RateLimitError):
                if attempt < config.llm.max_retries:
                    wait_time = 2 ** (attempt + 1)
                    logger.warning(f"Rate limited, waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    # On rate limit, accept if nodes are valid
                    qa_pair.validation_status = ValidationStatus.ACCEPTED
                    qa_pair.valid_nodes = valid_nodes
                    qa_pair.invalid_nodes = invalid_nodes
                    qa_pair.reasoning = "Accepted due to rate limit (nodes validated)"
                    return qa_pair
            else:
                logger.error(f"Validation error: {e}")
                if attempt == config.llm.max_retries:
                    # On error, accept if nodes are valid
                    if valid_nodes:
                        qa_pair.validation_status = ValidationStatus.CORRECTED
                        qa_pair.valid_nodes = valid_nodes
                        qa_pair.invalid_nodes = invalid_nodes
                        qa_pair.reasoning = f"Auto-corrected due to error: {e}"
                    else:
                        qa_pair.validation_status = ValidationStatus.REJECTED
                        qa_pair.reasoning = f"Rejected due to error: {e}"
                    return qa_pair

    return qa_pair


def _parse_validation_response(response: str) -> dict[str, Any] | None:
    """Parse JSON response into validation dict."""
    start = response.find("{")
    end = response.rfind("}") + 1

    if start == -1 or end == 0:
        return None

    try:
        json_str = response[start:end]
        result: dict[str, Any] = json.loads(json_str)
        return result
    except json.JSONDecodeError:
        return None


async def validate_answers_batch(
    qa_pairs: list[QAPair],
    mubase_path: Path,
    config: SigmaConfig,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[QAPair]:
    """Validate multiple Q&A pairs with concurrency control.

    Args:
        qa_pairs: Q&A pairs to validate
        mubase_path: Path to .mubase file
        config: Pipeline configuration
        progress_callback: Optional progress callback(completed, total)

    Returns:
        List of QAPairs with validation status
    """
    if not qa_pairs:
        return []

    semaphore = asyncio.Semaphore(config.llm.concurrency)
    results: list[QAPair | None] = [None] * len(qa_pairs)
    completed = 0

    async def process_one(index: int, qa_pair: QAPair) -> None:
        nonlocal completed
        async with semaphore:
            result = await validate_answer(qa_pair, mubase_path, config)
            results[index] = result
            completed += 1
            if progress_callback:
                progress_callback(completed, len(qa_pairs))

    tasks = [process_one(i, qa) for i, qa in enumerate(qa_pairs)]
    await asyncio.gather(*tasks)

    return [r for r in results if r is not None]


def filter_valid_pairs(qa_pairs: list[QAPair]) -> list[QAPair]:
    """Filter to only validated Q&A pairs.

    Returns pairs with status ACCEPTED or CORRECTED and at least one valid node.
    """
    return [qa for qa in qa_pairs if qa.is_valid]
