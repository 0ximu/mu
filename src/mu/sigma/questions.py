"""Question generation for MU-SIGMA.

Generates diverse questions about codebases using Claude Haiku.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from mu.sigma.build import get_graph_summary
from mu.sigma.config import SigmaConfig
from mu.sigma.llm_client import get_anthropic_client
from mu.sigma.models import QAPair, QuestionCategory

logger = logging.getLogger(__name__)

# Prompt version for cache invalidation
PROMPT_VERSION = "1.0"

QUESTION_PROMPT = """\
You are analyzing a codebase to generate questions for training an embedding model.
Your questions should help the model learn to map natural language queries to relevant code entities.

## Codebase Information

Repository: {repo_name}
Language: {language}

### Available Classes (sample)
{classes}

### Available Functions (sample)
{functions}

### Available Modules (sample)
{modules}

## Task

Generate exactly {count} diverse questions about this codebase across these categories:

1. **Architecture** ({arch_count}): Questions about code structure, patterns, organization
   - "How is X structured?"
   - "What pattern does Y use?"
   - "What is the architecture of Z?"

2. **Dependencies** ({deps_count}): Questions about what code depends on or is depended upon
   - "What does X depend on?"
   - "What uses Y?"
   - "What are the dependencies of Z?"

3. **Navigation** ({nav_count}): Questions about finding specific code
   - "Where is X implemented?"
   - "What handles Y?"
   - "Which file contains Z?"

4. **Understanding** ({under_count}): Questions about purpose and behavior
   - "How does X work?"
   - "What is the purpose of Y?"
   - "What does Z do?"

## Requirements

1. Questions MUST reference actual entity names from the lists above
2. Questions should be natural and varied (don't use the exact same phrasing)
3. Focus on questions that require structural understanding to answer
4. Mix simple and complex questions

## Output Format

Return ONLY a JSON array with this structure:
```json
[
  {{"question": "How does the AuthService authenticate users?", "category": "understanding"}},
  {{"question": "What modules depend on the database layer?", "category": "dependencies"}}
]
```

Generate exactly {count} questions now:"""


def _format_entity_list(entities: list[str], max_items: int = 30) -> str:
    """Format entity list for prompt."""
    if not entities:
        return "(none found)"

    sample = entities[:max_items]
    result = ", ".join(sample)
    if len(entities) > max_items:
        result += f", ... ({len(entities) - max_items} more)"
    return result


async def generate_questions(
    mubase_path: Path,
    repo_name: str,
    language: str,
    config: SigmaConfig,
) -> list[QAPair]:
    """Generate questions about a codebase using Haiku.

    Args:
        mubase_path: Path to .mubase file
        repo_name: Repository name (owner/repo)
        language: Primary language of repo
        config: Pipeline configuration

    Returns:
        List of QAPair objects with questions (answers not yet generated)
    """
    # Get graph summary for prompt
    summary = get_graph_summary(mubase_path)

    count = config.pipeline.questions_per_repo

    # Category distribution
    arch_count = 5
    deps_count = 5
    nav_count = 10
    under_count = 10

    prompt = QUESTION_PROMPT.format(
        repo_name=repo_name,
        language=language,
        classes=_format_entity_list(summary["classes"]),
        functions=_format_entity_list(summary["functions"]),
        modules=_format_entity_list(summary["modules"]),
        count=count,
        arch_count=arch_count,
        deps_count=deps_count,
        nav_count=nav_count,
        under_count=under_count,
    )

    client = get_anthropic_client()

    for attempt in range(config.llm.max_retries + 1):
        try:
            response = await client.messages.create(
                model=config.llm.question_model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )

            # Extract text content
            content = response.content[0].text if response.content else ""

            # Parse JSON from response
            questions = _parse_questions_response(content, repo_name)

            if questions:
                logger.info(f"Generated {len(questions)} questions for {repo_name}")
                return questions

            logger.warning(f"No questions parsed from response, attempt {attempt + 1}")

        except Exception as e:
            # Handle rate limit separately for retry logic
            import anthropic

            if isinstance(e, anthropic.RateLimitError):
                if attempt < config.llm.max_retries:
                    import asyncio

                    wait_time = 2 ** (attempt + 1)
                    logger.warning(f"Rate limited, waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Rate limit exhausted for {repo_name}")
                    return []
            else:
                logger.error(f"Error generating questions for {repo_name}: {e}")
                if attempt == config.llm.max_retries:
                    return []

    return []


def _parse_questions_response(response: str, repo_name: str) -> list[QAPair]:
    """Parse JSON response into QAPair objects."""
    # Find JSON array in response
    start = response.find("[")
    end = response.rfind("]") + 1

    if start == -1 or end == 0:
        logger.warning("No JSON array found in response")
        return []

    try:
        json_str = response[start:end]
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse JSON: {e}")
        return []

    questions: list[QAPair] = []
    for item in data:
        if not isinstance(item, dict):
            continue

        question = item.get("question", "").strip()
        category_str = item.get("category", "understanding").lower()

        if not question:
            continue

        # Map category string to enum
        try:
            category = QuestionCategory(category_str)
        except ValueError:
            category = QuestionCategory.UNDERSTANDING

        questions.append(
            QAPair(
                question=question,
                category=category,
                repo_name=repo_name,
            )
        )

    return questions


async def generate_questions_batch(
    build_results: list[tuple[Path, str, str]],  # (mubase_path, repo_name, language)
    config: SigmaConfig,
) -> dict[str, list[QAPair]]:
    """Generate questions for multiple repos.

    Args:
        build_results: List of (mubase_path, repo_name, language) tuples
        config: Pipeline configuration

    Returns:
        Dict mapping repo_name to list of QAPairs
    """
    import asyncio

    results: dict[str, list[QAPair]] = {}
    semaphore = asyncio.Semaphore(config.llm.concurrency)

    async def process_one(
        mubase_path: Path, repo_name: str, language: str
    ) -> tuple[str, list[QAPair]]:
        async with semaphore:
            questions = await generate_questions(mubase_path, repo_name, language, config)
            return repo_name, questions

    tasks = [process_one(path, name, lang) for path, name, lang in build_results]

    for coro in asyncio.as_completed(tasks):
        repo_name, questions = await coro
        results[repo_name] = questions

    return results
