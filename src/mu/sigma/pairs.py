"""Training pair extraction for MU-SIGMA.

Extracts training triplets from graph edges and validated Q&A pairs.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import TYPE_CHECKING

from mu.sigma.models import PairType, QAPair, TrainingPair

if TYPE_CHECKING:
    from mu.kernel import MUbase

logger = logging.getLogger(__name__)

# Weights for different pair types
PAIR_WEIGHTS = {
    PairType.CONTAINS: 1.0,  # Class contains method - strong signal
    PairType.CALLS: 0.9,  # Function calls another - strong signal
    PairType.IMPORTS: 0.8,  # Module imports another - medium signal
    PairType.INHERITS: 0.9,  # Class inherits from another - strong signal
    PairType.SAME_FILE: 0.7,  # Same file - weaker signal
    PairType.QA_RELEVANCE: 1.0,  # Question to relevant node - strong signal
    PairType.CO_RELEVANT: 0.85,  # Nodes answering same question - medium signal
}


def extract_structural_pairs(
    mubase_path: Path,
    repo_name: str,
    max_pairs_per_type: int = 500,
) -> list[TrainingPair]:
    """Extract training pairs from graph edges.

    Creates triplets where:
    - Anchor: source node
    - Positive: related node (via edge)
    - Negative: hard negative from same codebase

    Args:
        mubase_path: Path to .mubase file
        repo_name: Repository name
        max_pairs_per_type: Maximum pairs per edge type

    Returns:
        List of TrainingPair objects
    """
    from mu.kernel import MUbase

    pairs: list[TrainingPair] = []

    try:
        db = MUbase(mubase_path, read_only=True)

        # Get all nodes for negative sampling
        all_nodes_result = db.conn.execute("SELECT id, name FROM nodes").fetchall()
        all_nodes = {row[0]: row[1] for row in all_nodes_result}
        all_node_names = list(all_nodes.values())

        if len(all_node_names) < 10:
            logger.warning(f"Too few nodes for negative sampling: {len(all_node_names)}")
            db.close()
            return []

        # Extract pairs for each edge type
        edge_type_map = {
            "contains": PairType.CONTAINS,
            "calls": PairType.CALLS,
            "imports": PairType.IMPORTS,
            "inherits": PairType.INHERITS,
        }

        for edge_type, pair_type in edge_type_map.items():
            edge_pairs = _extract_edge_pairs(
                db,
                edge_type,
                pair_type,
                repo_name,
                all_nodes,
                all_node_names,
                max_pairs=max_pairs_per_type,
            )
            pairs.extend(edge_pairs)

        # Extract same-file pairs
        same_file_pairs = _extract_same_file_pairs(
            db,
            repo_name,
            all_nodes,
            all_node_names,
            max_pairs=max_pairs_per_type,
        )
        pairs.extend(same_file_pairs)

        db.close()

    except Exception as e:
        logger.error(f"Error extracting structural pairs: {e}")

    logger.info(f"Extracted {len(pairs)} structural pairs from {repo_name}")
    return pairs


def _extract_edge_pairs(
    db: MUbase,
    edge_type: str,
    pair_type: PairType,
    repo_name: str,
    all_nodes: dict[str, str],
    all_node_names: list[str],
    max_pairs: int = 500,
) -> list[TrainingPair]:
    """Extract pairs for a specific edge type."""
    pairs: list[TrainingPair] = []

    try:
        # Query edges of this type
        result = db.conn.execute(
            """
            SELECT e.source_id, e.target_id, n1.name, n2.name
            FROM edges e
            JOIN nodes n1 ON e.source_id = n1.id
            JOIN nodes n2 ON e.target_id = n2.id
            WHERE e.type = ?
            LIMIT ?
            """,
            [edge_type, max_pairs * 2],  # Fetch more to account for invalid negatives
        ).fetchall()

        for _source_id, _target_id, source_name, target_name in result:
            if len(pairs) >= max_pairs:
                break

            # Get hard negative (different node, not connected)
            negative = _get_hard_negative(source_name, target_name, all_node_names)
            if not negative:
                continue

            pairs.append(
                TrainingPair(
                    anchor=source_name,
                    positive=target_name,
                    negative=negative,
                    pair_type=pair_type,
                    weight=PAIR_WEIGHTS[pair_type],
                    source_repo=repo_name,
                )
            )

    except Exception as e:
        logger.debug(f"Error extracting {edge_type} pairs: {e}")

    return pairs


def _extract_same_file_pairs(
    db: MUbase,
    repo_name: str,
    all_nodes: dict[str, str],
    all_node_names: list[str],
    max_pairs: int = 500,
) -> list[TrainingPair]:
    """Extract pairs for entities in the same file."""
    pairs: list[TrainingPair] = []

    try:
        # Get nodes grouped by file
        result = db.conn.execute(
            """
            SELECT file_path, name
            FROM nodes
            WHERE file_path IS NOT NULL AND type IN ('class', 'function')
            ORDER BY file_path
            """
        ).fetchall()

        # Group by file
        file_nodes: dict[str, list[str]] = {}
        for file_path, name in result:
            if file_path not in file_nodes:
                file_nodes[file_path] = []
            file_nodes[file_path].append(name)

        # Create pairs for nodes in same file
        for _file_path, nodes in file_nodes.items():
            if len(nodes) < 2:
                continue

            # Create pairs between nodes in same file
            for i, anchor in enumerate(nodes):
                if len(pairs) >= max_pairs:
                    break

                for positive in nodes[i + 1 :]:
                    if len(pairs) >= max_pairs:
                        break

                    negative = _get_hard_negative(anchor, positive, all_node_names)
                    if not negative:
                        continue

                    pairs.append(
                        TrainingPair(
                            anchor=anchor,
                            positive=positive,
                            negative=negative,
                            pair_type=PairType.SAME_FILE,
                            weight=PAIR_WEIGHTS[PairType.SAME_FILE],
                            source_repo=repo_name,
                        )
                    )

    except Exception as e:
        logger.debug(f"Error extracting same-file pairs: {e}")

    return pairs


def _get_hard_negative(
    anchor: str,
    positive: str,
    all_node_names: list[str],
    max_attempts: int = 10,
) -> str | None:
    """Get a hard negative from the same codebase.

    Hard negatives are nodes that are NOT semantically related to anchor/positive.
    """
    exclude = {anchor, positive}

    for _ in range(max_attempts):
        negative = random.choice(all_node_names)
        if negative not in exclude:
            return negative

    return None


def extract_qa_pairs(
    qa_pairs: list[QAPair],
    repo_name: str,
    all_node_names: list[str] | None = None,
) -> list[TrainingPair]:
    """Convert validated Q&A pairs to training triplets.

    Creates triplets where:
    - Anchor: question text
    - Positive: each valid relevant node
    - Negative: node from same repo not in relevant_nodes

    Also creates co-relevance pairs (nodes answering the same question).

    Args:
        qa_pairs: Validated Q&A pairs
        repo_name: Repository name
        all_node_names: All node names for negative sampling (optional)

    Returns:
        List of TrainingPair objects
    """
    pairs: list[TrainingPair] = []

    # Filter to valid pairs only
    valid_pairs = [qa for qa in qa_pairs if qa.is_valid]

    if not valid_pairs:
        return []

    # Collect all valid nodes for negative sampling
    all_valid_nodes: set[str] = set()
    for qa in valid_pairs:
        all_valid_nodes.update(qa.valid_nodes)

    if all_node_names:
        negative_pool = list(set(all_node_names) - all_valid_nodes)
    else:
        negative_pool = list(all_valid_nodes)

    if len(negative_pool) < 5:
        logger.warning("Not enough nodes for negative sampling")
        return []

    # Create Q&A relevance pairs
    for qa in valid_pairs:
        for node in qa.valid_nodes:
            # Find negative (node not relevant to this question)
            other_nodes = [n for n in negative_pool if n != node and n not in qa.valid_nodes]
            if not other_nodes:
                continue

            negative = random.choice(other_nodes)

            pairs.append(
                TrainingPair(
                    anchor=qa.question,
                    positive=node,
                    negative=negative,
                    pair_type=PairType.QA_RELEVANCE,
                    weight=PAIR_WEIGHTS[PairType.QA_RELEVANCE],
                    source_repo=repo_name,
                )
            )

    # Create co-relevance pairs (nodes that answer the same question)
    for qa in valid_pairs:
        if len(qa.valid_nodes) < 2:
            continue

        nodes = qa.valid_nodes
        for i, anchor in enumerate(nodes):
            for positive in nodes[i + 1 :]:
                other_nodes = [n for n in negative_pool if n != anchor and n != positive]
                if not other_nodes:
                    continue

                negative = random.choice(other_nodes)

                pairs.append(
                    TrainingPair(
                        anchor=anchor,
                        positive=positive,
                        negative=negative,
                        pair_type=PairType.CO_RELEVANT,
                        weight=PAIR_WEIGHTS[PairType.CO_RELEVANT],
                        source_repo=repo_name,
                    )
                )

    logger.info(f"Extracted {len(pairs)} Q&A training pairs from {repo_name}")
    return pairs


def combine_pairs(
    structural_pairs: list[TrainingPair],
    qa_pairs: list[TrainingPair],
) -> list[TrainingPair]:
    """Combine and deduplicate training pairs.

    Returns combined list with duplicates removed.
    """
    # Use tuple of (anchor, positive, negative) as key for deduplication
    seen: set[tuple[str, str, str]] = set()
    combined: list[TrainingPair] = []

    for pair in structural_pairs + qa_pairs:
        key = (pair.anchor, pair.positive, pair.negative)
        if key not in seen:
            seen.add(key)
            combined.append(pair)

    return combined
