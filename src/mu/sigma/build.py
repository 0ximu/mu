"""MU graph building for MU-SIGMA.

Builds .mubase graph databases for repositories using MU's infrastructure.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from mu.sigma.config import SigmaConfig
from mu.sigma.models import BuildResult

logger = logging.getLogger(__name__)


def build_mubase(
    repo_path: Path,
    output_dir: Path,
    repo_name: str,
    config: SigmaConfig | None = None,
) -> BuildResult:
    """Build .mubase for a repository.

    Uses MU's kernel infrastructure to build the code graph.

    Args:
        repo_path: Path to cloned repository
        output_dir: Directory to store .mubase file
        repo_name: Name of repository (owner/repo)
        config: Optional pipeline configuration

    Returns:
        BuildResult with graph statistics
    """
    from mu.kernel import MUbase
    from mu.parser import parse_file
    from mu.parser.models import ModuleDef
    from mu.scanner import scan_codebase_auto

    start_time = time.time()
    safe_name = repo_name.replace("/", "__")
    mubase_path = output_dir / f"{safe_name}.mubase"

    # Check if already exists
    if config and config.pipeline.skip_existing_mubase and mubase_path.exists():
        try:
            db = MUbase(mubase_path, read_only=True)
            # Count nodes and edges directly
            node_result = db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()
            edge_result = db.conn.execute("SELECT COUNT(*) FROM edges").fetchone()
            node_count = node_result[0] if node_result else 0
            edge_count = edge_result[0] if edge_result else 0
            db.close()

            # Extract entity names for LLM prompts
            classes, functions, module_names = _extract_entity_names(mubase_path)

            return BuildResult(
                repo_name=repo_name,
                mubase_path=mubase_path,
                node_count=node_count,
                edge_count=edge_count,
                classes=classes,
                functions=functions,
                modules=module_names,
                success=True,
                duration_seconds=time.time() - start_time,
            )
        except Exception as e:
            logger.warning(f"Existing mubase corrupt, rebuilding: {e}")

    try:
        output_dir.mkdir(parents=True, exist_ok=True)

        # Scan repository
        from mu.config import MUConfig

        mu_config = MUConfig()
        scan_result = scan_codebase_auto(repo_path, mu_config)

        if scan_result.stats.total_files == 0:
            return BuildResult(
                repo_name=repo_name,
                mubase_path=None,
                success=False,
                error="No supported files found",
                duration_seconds=time.time() - start_time,
            )

        # Parse all files
        parsed_modules: list[ModuleDef] = []
        for file_info in scan_result.files:
            try:
                parsed = parse_file(
                    Path(file_info.path),
                    file_info.language,
                )
                if parsed.module:
                    parsed_modules.append(parsed.module)
            except Exception as e:
                logger.debug(f"Failed to parse {file_info.path}: {e}")
                continue

        if not parsed_modules:
            return BuildResult(
                repo_name=repo_name,
                mubase_path=None,
                success=False,
                error="No modules parsed successfully",
                duration_seconds=time.time() - start_time,
            )

        # Create mubase and build graph
        if mubase_path.exists():
            mubase_path.unlink()

        db = MUbase(mubase_path)
        try:
            db.build(parsed_modules, repo_path)

            # Count resulting nodes and edges
            node_result = db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()
            edge_result = db.conn.execute("SELECT COUNT(*) FROM edges").fetchone()
            node_count = node_result[0] if node_result else 0
            edge_count = edge_result[0] if edge_result else 0
        finally:
            db.close()

        if node_count < 10:
            return BuildResult(
                repo_name=repo_name,
                mubase_path=None,
                node_count=node_count,
                success=False,
                error=f"Too few nodes ({node_count}), skipping",
                duration_seconds=time.time() - start_time,
            )

        # Extract entity names for LLM prompts
        classes, functions, module_names = _extract_entity_names(mubase_path)

        return BuildResult(
            repo_name=repo_name,
            mubase_path=mubase_path,
            node_count=node_count,
            edge_count=edge_count,
            classes=classes,
            functions=functions,
            modules=module_names,
            success=True,
            duration_seconds=time.time() - start_time,
        )

    except Exception as e:
        logger.error(f"Failed to build mubase for {repo_name}: {e}")
        return BuildResult(
            repo_name=repo_name,
            mubase_path=None,
            success=False,
            error=str(e),
            duration_seconds=time.time() - start_time,
        )


def _extract_entity_names(mubase_path: Path) -> tuple[list[str], list[str], list[str]]:
    """Extract class, function, and module names from mubase.

    Returns:
        Tuple of (classes, functions, modules) name lists
    """
    from mu.kernel import MUbase

    classes: list[str] = []
    functions: list[str] = []
    modules: list[str] = []

    try:
        db = MUbase(mubase_path, read_only=True)

        # Get classes
        result = db.conn.execute(
            "SELECT name FROM nodes WHERE type = 'class' ORDER BY name LIMIT 100"
        ).fetchall()
        classes = [row[0] for row in result]

        # Get functions
        result = db.conn.execute(
            "SELECT name FROM nodes WHERE type = 'function' ORDER BY name LIMIT 100"
        ).fetchall()
        functions = [row[0] for row in result]

        # Get modules
        result = db.conn.execute(
            "SELECT name FROM nodes WHERE type = 'module' ORDER BY name LIMIT 50"
        ).fetchall()
        modules = [row[0] for row in result]

        db.close()

    except Exception as e:
        logger.warning(f"Failed to extract entity names: {e}")

    return classes, functions, modules


def get_graph_summary(mubase_path: Path) -> dict[str, list[str]]:
    """Get graph summary for LLM context.

    Returns dict with classes, functions, modules lists.
    """
    classes, functions, modules = _extract_entity_names(mubase_path)
    return {
        "classes": classes,
        "functions": functions,
        "modules": modules,
    }


def get_all_node_names(mubase_path: Path) -> set[str]:
    """Get all node names from mubase.

    Used for validating LLM-generated node references.
    """
    from mu.kernel import MUbase

    names: set[str] = set()

    try:
        db = MUbase(mubase_path, read_only=True)
        result = db.conn.execute("SELECT name FROM nodes").fetchall()
        names = {row[0] for row in result}
        db.close()
    except Exception as e:
        logger.warning(f"Failed to get node names: {e}")

    return names
