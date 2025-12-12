"""Answer generation for MU-SIGMA.

Generates answers to questions using Claude Sonnet (higher quality).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mu.sigma.build import get_all_node_names, get_graph_summary
from mu.sigma.config import SigmaConfig
from mu.sigma.llm_client import get_anthropic_client
from mu.sigma.models import QAPair

logger = logging.getLogger(__name__)

ANSWER_PROMPT = """\
You are answering a question about a codebase to help train an embedding model.
Your answer should identify the relevant code entities that answer the question.

## Codebase Information

Repository: {repo_name}

### Available Entities
You MUST only reference entities from this list:
{entities}

## Question

Category: {category}
Question: {question}

## Task

Provide a concise answer that:
1. Directly addresses the question
2. References specific entities from the available list above
3. Is confident in your assessment

## Output Format

Return ONLY a JSON object:
```json
{{
  "answer": "Brief 2-3 sentence answer explaining the relevant code",
  "relevant_nodes": ["EntityA", "EntityB", "EntityC"],
  "confidence": 0.95
}}
```

- `relevant_nodes` MUST contain only names from the available entities list
- `confidence` should be 0.0-1.0 (0.9+ if you're sure, 0.7-0.9 if uncertain)
- If no entities are relevant, use an empty list and low confidence

Answer now:"""


async def generate_answer(
    qa_pair: QAPair,
    mubase_path: Path,
    config: SigmaConfig,
) -> QAPair:
    """Generate answer for a single question.

    Args:
        qa_pair: Question to answer
        mubase_path: Path to .mubase file
        config: Pipeline configuration

    Returns:
        Updated QAPair with answer filled in
    """
    # Get available entities
    summary = get_graph_summary(mubase_path)
    all_names = get_all_node_names(mubase_path)

    # Build entity list for prompt (include all names)
    entities = []
    entities.extend(summary["classes"][:50])
    entities.extend(summary["functions"][:50])
    entities.extend(summary["modules"][:30])
    entity_list = ", ".join(entities) if entities else "(no entities found)"

    prompt = ANSWER_PROMPT.format(
        repo_name=qa_pair.repo_name,
        entities=entity_list,
        category=qa_pair.category.value,
        question=qa_pair.question,
    )

    client = get_anthropic_client()

    for attempt in range(config.llm.max_retries + 1):
        try:
            response = await client.messages.create(
                model=config.llm.answer_model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )

            content = response.content[0].text if response.content else ""

            # Parse response
            answer_data = _parse_answer_response(content)

            if answer_data:
                # Validate node references against actual nodes
                valid_nodes = [n for n in answer_data.get("relevant_nodes", []) if n in all_names]

                qa_pair.answer = answer_data.get("answer", "")
                qa_pair.relevant_nodes = answer_data.get("relevant_nodes", [])
                qa_pair.confidence = answer_data.get("confidence", 0.0)
                qa_pair.valid_nodes = valid_nodes

                return qa_pair

        except Exception as e:
            import anthropic

            if isinstance(e, anthropic.RateLimitError):
                if attempt < config.llm.max_retries:
                    wait_time = 2 ** (attempt + 1)
                    logger.warning(f"Rate limited, waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Rate limit exhausted for question: {qa_pair.question[:50]}...")
                    return qa_pair
            else:
                logger.error(f"Error generating answer: {e}")
                if attempt == config.llm.max_retries:
                    return qa_pair

    return qa_pair


def _parse_answer_response(response: str) -> dict[str, Any] | None:
    """Parse JSON response into answer dict."""
    # Find JSON object in response
    start = response.find("{")
    end = response.rfind("}") + 1

    if start == -1 or end == 0:
        logger.warning("No JSON object found in response")
        return None

    try:
        json_str = response[start:end]
        result: dict[str, Any] = json.loads(json_str)
        return result
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse answer JSON: {e}")
        return None


async def generate_answers_batch(
    qa_pairs: list[QAPair],
    mubase_path: Path,
    config: SigmaConfig,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[QAPair]:
    """Generate answers for multiple questions with concurrency control.

    Args:
        qa_pairs: Questions to answer
        mubase_path: Path to .mubase file
        config: Pipeline configuration
        progress_callback: Optional progress callback(completed, total)

    Returns:
        List of QAPairs with answers filled in
    """
    if not qa_pairs:
        return []

    semaphore = asyncio.Semaphore(config.llm.concurrency)
    results: list[QAPair | None] = [None] * len(qa_pairs)
    completed = 0

    async def process_one(index: int, qa_pair: QAPair) -> None:
        nonlocal completed
        async with semaphore:
            result = await generate_answer(qa_pair, mubase_path, config)
            results[index] = result
            completed += 1
            if progress_callback:
                progress_callback(completed, len(qa_pairs))

    tasks = [process_one(i, qa) for i, qa in enumerate(qa_pairs)]
    await asyncio.gather(*tasks)

    return [r for r in results if r is not None]
