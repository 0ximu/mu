"""Question generation for MU-SIGMA.

Generates diverse questions about codebases using Claude Haiku.
"""

from __future__ import annotations

import json
import logging
import re
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
                # Deduplicate similar questions
                questions = deduplicate_questions(questions)
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


def deduplicate_questions(questions: list[QAPair], similarity_threshold: float = 0.6) -> list[QAPair]:
    """Remove semantically similar questions to avoid redundant training signal.

    Uses heuristics:
    - Normalize and compare question structure
    - Extract entity names and compare overlap
    - Detect semantically equivalent phrasings
    - Keep the first question from each similar cluster

    Args:
        questions: List of QAPair objects
        similarity_threshold: Similarity threshold for deduplication (default 0.6)

    Returns:
        Deduplicated list of questions
    """
    if len(questions) <= 1:
        return questions

    def normalize(text: str) -> str:
        """Normalize question for comparison."""
        text = text.lower()
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def extract_entities(text: str) -> set[str]:
        """Extract likely entity names (CamelCase or significant words)."""
        # Common question words to ignore
        question_words = {"what", "how", "where", "which", "when", "why", "does", "is", "are", "the", "this", "that"}

        entities: set[str] = set()
        # Find CamelCase words (e.g., Blueprint, AuthService)
        for w in re.findall(r"[A-Z][a-zA-Z]+", text):
            if w.lower() not in question_words:
                entities.add(w.lower())
        # Find snake_case words
        entities.update(re.findall(r"[a-z]+_[a-z_]+", text.lower()))
        # Capitalized words that might be class/function names
        for word in text.split():
            clean = re.sub(r"[^\w]", "", word)
            if clean and clean[0].isupper() and len(clean) > 2:
                if clean.lower() not in question_words:
                    entities.add(clean.lower())
        return entities

    # Question intent categories for equivalence detection
    # Each group contains patterns that ask semantically similar things
    INTENT_PATTERNS = {
        "what_does": [r"what does .+ do", r"what is the purpose of", r"what is .+ for"],
        "how_works": [r"how does .+ work", r"how is .+ implemented", r"how .+ works"],
        "where_is": [r"where is .+", r"which file contains", r"where .+ implemented"],
        "depends_on": [r"what .+ depend", r"dependencies of", r"what .+ requires"],
        "depended_by": [r"what depends on", r"what uses", r"who uses"],
    }

    def get_intent(text: str) -> str | None:
        """Get the question intent category."""
        normalized = normalize(text)
        for intent, patterns in INTENT_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, normalized):
                    return intent
        return None

    def get_canonical_pattern(text: str) -> str:
        """Convert question to canonical pattern for comparison.

        Only replaces entity names (capitalized words), preserving question structure.
        """
        # Common words to keep
        keep_words = {"what", "how", "where", "which", "when", "why", "does", "is", "are",
                      "the", "this", "that", "do", "for", "of", "in", "to", "a", "an",
                      "have", "has", "handle", "work", "use", "call", "depend", "class"}

        pattern = normalize(text)
        words = pattern.split()
        result = []
        for i, word in enumerate(words):
            # Keep first word (question word), common words, and short words
            if i == 0 or word in keep_words or len(word) <= 3:
                result.append(word)
            else:
                result.append("*")
        return " ".join(result)

    def patterns_equivalent(p1: str, p2: str, q1_text: str, q2_text: str) -> bool:
        """Check if two question patterns are semantically equivalent."""
        # Same pattern = same question structure with different entities
        if p1 == p2 and p1.count("*") >= 1:
            return True
        # Check if same intent (e.g., both asking "what does X do" style questions)
        intent1 = get_intent(q1_text)
        intent2 = get_intent(q2_text)
        if intent1 and intent2 and intent1 == intent2:
            return True
        return False

    def similarity(q1: QAPair, q2: QAPair) -> float:
        """Compute similarity between two questions."""
        # Same category is a prerequisite for high similarity
        category_match = q1.category == q2.category

        # Pattern similarity
        p1 = get_canonical_pattern(q1.question)
        p2 = get_canonical_pattern(q2.question)
        if patterns_equivalent(p1, p2, q1.question, q2.question):
            # Check if they're about the same entity
            e1 = extract_entities(q1.question)
            e2 = extract_entities(q2.question)
            if e1 & e2:  # Same entity mentioned
                return 0.95
            return 0.5 if category_match else 0.3

        # Entity overlap (Jaccard)
        e1 = extract_entities(q1.question)
        e2 = extract_entities(q2.question)
        if e1 and e2:
            jaccard = len(e1 & e2) / len(e1 | e2)
            if jaccard >= 0.5:  # Same entities
                # IMPORTANT: Same entity doesn't mean same question
                # Need significant word overlap too (excluding stop words AND entities)
                w1 = set(normalize(q1.question).split())
                w2 = set(normalize(q2.question).split())
                stop_words = {"what", "how", "does", "the", "is", "are", "of", "in", "to", "a", "an", "this", "class"}
                w1 -= stop_words
                w2 -= stop_words
                # Also remove entity words from comparison
                w1 -= {e.lower() for e in e1}
                w2 -= {e.lower() for e in e2}
                if w1 and w2:
                    word_overlap = len(w1 & w2) / len(w1 | w2)
                    # Only high similarity if significant word overlap beyond entities
                    if word_overlap >= 0.3:
                        return 0.4 + jaccard * 0.2 + word_overlap * 0.4
                # Low entity overlap + low word overlap = different questions about same entity
                return 0.3 if category_match else 0.2

        # Fallback: word overlap only
        w1 = set(normalize(q1.question).split())
        w2 = set(normalize(q2.question).split())
        stop_words = {"what", "how", "does", "the", "is", "are", "of", "in", "to", "a", "an", "this"}
        w1 -= stop_words
        w2 -= stop_words
        if w1 and w2:
            word_jaccard = len(w1 & w2) / len(w1 | w2)
            return word_jaccard * 0.5

        return 0.0

    # Greedy deduplication - keep first, skip similar
    kept: list[QAPair] = []
    for q in questions:
        is_duplicate = False
        for existing in kept:
            sim = similarity(q, existing)
            if sim >= similarity_threshold:
                is_duplicate = True
                logger.debug(f"Dedup ({sim:.2f}): '{q.question[:40]}...' ~ '{existing.question[:40]}...'")
                break
        if not is_duplicate:
            kept.append(q)

    if len(kept) < len(questions):
        logger.info(f"Deduplicated {len(questions)} -> {len(kept)} questions")

    return kept


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
