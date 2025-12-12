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

# Names to EXCLUDE entirely - too generic across all codebases
EXCLUDE_NODE_NAMES = frozenset(
    {
        # Python dunder methods (structural, not semantic)
        "__init__",
        "__main__",
        "__str__",
        "__repr__",
        "__eq__",
        "__hash__",
        "__len__",
        "__iter__",
        "__next__",
        "__enter__",
        "__exit__",
        # Module-level noise
        "conftest",
        "fixture",
        "mock",
    }
)

# Names to DOWNWEIGHT (not exclude) - useful but common
DOWNWEIGHT_NODE_NAMES = frozenset(
    {
        # Common function names
        "main",
        "run",
        "start",
        "stop",
        "init",
        "setup",
        "teardown",
        "get",
        "set",
        "update",
        "delete",
        "create",
        "read",
        "write",
        "load",
        "save",
        "parse",
        "build",
        "make",
        "do",
        "execute",
        "handle",
        "process",
        "validate",
        "check",
        "config",
        "index",
        "app",
        "db",
        "api",
        "utils",
        "helpers",
        "common",
        "base",
        "core",
        "model",
        "view",
        "controller",
        "service",
        # Module names
        "models",
        "views",
        "urls",
        "forms",
        "admin",
        "settings",
        "constants",
        "exceptions",
        "types",
        "schemas",
        "tests",
    }
)

# Minimum name length for meaningful nodes
MIN_NODE_NAME_LENGTH = 3

# Weight multipliers
DOWNWEIGHT_FACTOR = 0.5  # Generic names get 50% weight
TEST_WEIGHT_FACTOR = 0.7  # Test functions get 70% weight (they show what code does)


def _is_excluded_name(name: str) -> bool:
    """Check if a node name should be excluded entirely."""
    name_lower = name.lower()
    if name_lower in EXCLUDE_NODE_NAMES:
        return True
    # Too short to be meaningful
    if len(name) < MIN_NODE_NAME_LENGTH:
        return True
    return False


def _is_downweighted_name(name: str) -> bool:
    """Check if a node name should be downweighted (but not excluded)."""
    name_lower = name.lower()
    return name_lower in DOWNWEIGHT_NODE_NAMES


def _is_test_name(name: str) -> bool:
    """Check if this is a test function/class name."""
    name_lower = name.lower()
    return (
        name_lower.startswith("test_")
        or name_lower.endswith("_test")
        or name_lower.startswith("test")
    )


def _is_high_quality_pair(anchor: str, positive: str) -> bool:
    """Check if anchor-positive pair should be included (possibly downweighted)."""
    # Exclude if either name is in the hard-exclude list
    if _is_excluded_name(anchor) or _is_excluded_name(positive):
        return False
    # Must be different enough (not just prefix/suffix variants)
    if anchor in positive or positive in anchor:
        # Allow if significantly different in length
        if abs(len(anchor) - len(positive)) < 5:
            return False
    return True


def _compute_specificity_weight(name: str) -> float:
    """Compute a weight based on how specific/meaningful a name is.

    More specific names get higher weights:
    - Longer names (more descriptive)
    - CamelCase names (proper class/function names)
    - Names with domain-specific terms

    Downweighted names get reduced weights.
    """
    weight = 1.0

    # Apply downweight for common names
    if _is_downweighted_name(name):
        weight *= DOWNWEIGHT_FACTOR
    elif _is_test_name(name):
        weight *= TEST_WEIGHT_FACTOR

    # Longer names are generally more specific
    if len(name) >= 15:
        weight += 0.1
    elif len(name) >= 10:
        weight += 0.05

    # CamelCase or snake_case with multiple parts = more descriptive
    parts = name.replace("_", " ").split()
    if len(parts) >= 2:
        weight += 0.05 * min(len(parts) - 1, 3)

    # Cap at reasonable range
    return min(max(weight, 0.3), 1.2)


def extract_structural_pairs(
    mubase_path: Path,
    repo_name: str,
    max_pairs_per_type: int = 500,
    frameworks: list[str] | None = None,
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
        frameworks: Detected frameworks for this repo (optional, will detect if None)

    Returns:
        List of TrainingPair objects
    """
    from mu.kernel import MUbase
    from mu.sigma.frameworks import detect_frameworks

    pairs: list[TrainingPair] = []

    # Detect frameworks if not provided
    if frameworks is None:
        frameworks = detect_frameworks(mubase_path)

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

        # Build connection graph for smarter negative sampling
        node_connections = _build_connection_graph(db)

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
                node_connections=node_connections,
                frameworks=frameworks,
            )
            pairs.extend(edge_pairs)

        # Extract same-file pairs
        same_file_pairs = _extract_same_file_pairs(
            db,
            repo_name,
            all_nodes,
            all_node_names,
            max_pairs=max_pairs_per_type,
            node_connections=node_connections,
            frameworks=frameworks,
        )
        pairs.extend(same_file_pairs)

        db.close()

    except Exception as e:
        logger.error(f"Error extracting structural pairs: {e}")

    logger.info(f"Extracted {len(pairs)} structural pairs from {repo_name}")
    return pairs


def _build_connection_graph(db: MUbase) -> dict[str, set[str]]:
    """Build a graph of node connections for negative sampling.

    Returns dict mapping node name -> set of connected node names.
    """
    connections: dict[str, set[str]] = {}

    try:
        result = db.conn.execute(
            """
            SELECT n1.name, n2.name
            FROM edges e
            JOIN nodes n1 ON e.source_id = n1.id
            JOIN nodes n2 ON e.target_id = n2.id
            """
        ).fetchall()

        for source_name, target_name in result:
            if source_name not in connections:
                connections[source_name] = set()
            if target_name not in connections:
                connections[target_name] = set()
            connections[source_name].add(target_name)
            connections[target_name].add(source_name)

    except Exception as e:
        logger.debug(f"Error building connection graph: {e}")

    return connections


def _extract_edge_pairs(
    db: MUbase,
    edge_type: str,
    pair_type: PairType,
    repo_name: str,
    all_nodes: dict[str, str],
    all_node_names: list[str],
    max_pairs: int = 500,
    node_connections: dict[str, set[str]] | None = None,
    frameworks: list[str] | None = None,
) -> list[TrainingPair]:
    """Extract pairs for a specific edge type."""
    pairs: list[TrainingPair] = []
    frameworks = frameworks or []

    # Filter to non-excluded node names for negatives
    quality_node_names = [n for n in all_node_names if not _is_excluded_name(n)]

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
            [edge_type, max_pairs * 3],  # Fetch more to account for filtering
        ).fetchall()

        for _source_id, _target_id, source_name, target_name in result:
            if len(pairs) >= max_pairs:
                break

            # Skip low-quality pairs
            if not _is_high_quality_pair(source_name, target_name):
                continue

            # Get hard negative (different node, not connected)
            negative = _get_hard_negative(
                source_name,
                target_name,
                quality_node_names,
                node_connections=node_connections,
            )
            if not negative:
                continue

            # Compute weight based on pair type and node specificity
            base_weight = PAIR_WEIGHTS[pair_type]
            specificity = (
                _compute_specificity_weight(source_name) + _compute_specificity_weight(target_name)
            ) / 2
            final_weight = base_weight * specificity

            pairs.append(
                TrainingPair(
                    anchor=source_name,
                    positive=target_name,
                    negative=negative,
                    pair_type=pair_type,
                    weight=round(final_weight, 3),
                    source_repo=repo_name,
                    frameworks=frameworks,
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
    node_connections: dict[str, set[str]] | None = None,
    frameworks: list[str] | None = None,
) -> list[TrainingPair]:
    """Extract pairs for entities in the same file."""
    pairs: list[TrainingPair] = []
    frameworks = frameworks or []

    # Filter to non-excluded node names for negatives
    quality_node_names = [n for n in all_node_names if not _is_excluded_name(n)]

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

                    # Skip low-quality pairs
                    if not _is_high_quality_pair(anchor, positive):
                        continue

                    negative = _get_hard_negative(
                        anchor,
                        positive,
                        quality_node_names,
                        node_connections=node_connections,
                    )
                    if not negative:
                        continue

                    # Compute weight based on pair type and node specificity
                    base_weight = PAIR_WEIGHTS[PairType.SAME_FILE]
                    specificity = (
                        _compute_specificity_weight(anchor) + _compute_specificity_weight(positive)
                    ) / 2
                    final_weight = base_weight * specificity

                    pairs.append(
                        TrainingPair(
                            anchor=anchor,
                            positive=positive,
                            negative=negative,
                            pair_type=PairType.SAME_FILE,
                            weight=round(final_weight, 3),
                            source_repo=repo_name,
                            frameworks=frameworks,
                        )
                    )

    except Exception as e:
        logger.debug(f"Error extracting same-file pairs: {e}")

    return pairs


def _get_hard_negative(
    anchor: str,
    positive: str,
    all_node_names: list[str],
    max_attempts: int = 20,
    node_connections: dict[str, set[str]] | None = None,
) -> str | None:
    """Get a hard negative from the same codebase.

    Hard negatives are nodes that are NOT semantically related to anchor/positive.
    Uses connection graph to avoid accidentally picking connected nodes as negatives.

    Args:
        anchor: The anchor node name
        positive: The positive node name
        all_node_names: Pool of candidate negative nodes
        max_attempts: Maximum random sampling attempts
        node_connections: Optional dict mapping node names to their connected nodes
    """
    exclude = {anchor, positive}

    # Also exclude directly connected nodes if we have connection info
    if node_connections:
        exclude.update(node_connections.get(anchor, set()))
        exclude.update(node_connections.get(positive, set()))

    # Try to find a good negative
    for _ in range(max_attempts):
        negative = random.choice(all_node_names)
        if negative in exclude:
            continue
        # Skip if too similar in name (likely related)
        if _names_too_similar(anchor, negative) or _names_too_similar(positive, negative):
            continue
        return negative

    # Fallback: just find any non-excluded node
    for _ in range(max_attempts):
        negative = random.choice(all_node_names)
        if negative not in exclude:
            return negative

    return None


def _names_too_similar(name1: str, name2: str) -> bool:
    """Check if two names are too similar (likely semantically related)."""
    n1, n2 = name1.lower(), name2.lower()
    # One contains the other
    if n1 in n2 or n2 in n1:
        return True
    # Share a significant common prefix (e.g., UserService, UserRepository)
    common_prefix_len = 0
    for c1, c2 in zip(n1, n2, strict=False):
        if c1 == c2:
            common_prefix_len += 1
        else:
            break
    if common_prefix_len >= 4 and common_prefix_len >= min(len(n1), len(n2)) * 0.5:
        return True
    return False


def extract_qa_pairs(
    qa_pairs: list[QAPair],
    repo_name: str,
    all_node_names: list[str] | None = None,
    frameworks: list[str] | None = None,
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
        frameworks: Detected frameworks for this repo

    Returns:
        List of TrainingPair objects
    """
    pairs: list[TrainingPair] = []
    frameworks = frameworks or []

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
                    frameworks=frameworks,
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
                        frameworks=frameworks,
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
