"""Analysis tools: deps, impact, diff."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from mu.client import DaemonError
from mu.mcp.models import (
    DepsResult,
    ImpactResult,
    NodeInfo,
    ReviewDiffOutput,
    SemanticDiffOutput,
    ViolationInfo,
)
from mu.mcp.tools._utils import find_mubase, resolve_node_id
from mu.paths import MU_DIR, MUBASE_FILE


def mu_deps(
    node_name: str,
    depth: int = 2,
    direction: str = "outgoing",
) -> DepsResult:
    """Show dependencies of a code node.

    Finds what a node depends on (outgoing) or what depends on it (incoming).

    Args:
        node_name: Name or ID of the node (e.g., "AuthService", "mod:src/auth.py")
        depth: How many levels deep to traverse (default 2)
        direction: "outgoing" (what it uses), "incoming" (what uses it), or "both"

    Returns:
        List of dependent nodes
    """
    from mu.mcp.tools._utils import get_client

    cwd = str(Path.cwd())

    # Try daemon first
    try:
        client = get_client()
        with client:
            # First verify the node exists
            node_data = client.find_node(node_name, cwd=cwd)
            if node_data is None:
                raise ValueError(f"Node not found: {node_name}")

            result = client.deps(node_name, depth=depth, direction=direction, cwd=cwd)

        # Daemon returns list of node IDs, convert to NodeInfo via query
        dep_ids = result.get("dependencies", [])
        if not dep_ids:
            return DepsResult(
                node_id=result.get("node_id", node_name),
                direction=direction,
                dependencies=[],
            )

        # Fetch node details for each dependency
        deps = []
        for dep_id in dep_ids[:100]:  # Limit to 100
            try:
                node_data = client.node(dep_id, cwd=cwd)
                deps.append(
                    NodeInfo(
                        id=node_data.get("id", dep_id),
                        type=node_data.get("type", "unknown"),
                        name=node_data.get("name", ""),
                        qualified_name=node_data.get("qualified_name"),
                        file_path=node_data.get("file_path"),
                        line_start=node_data.get("line_start"),
                        line_end=node_data.get("line_end"),
                        complexity=node_data.get("complexity", 0),
                    )
                )
            except DaemonError:
                # Node not found, include ID only
                deps.append(
                    NodeInfo(
                        id=dep_id,
                        type="unknown",
                        name=dep_id.split(":")[-1] if ":" in dep_id else dep_id,
                    )
                )

        return DepsResult(
            node_id=result.get("node_id", node_name),
            direction=direction,
            dependencies=deps,
        )
    except DaemonError:
        pass  # Fall through to local mode

    # Fallback to local mode
    mubase_path = find_mubase()
    if not mubase_path:
        raise DaemonError(f"No {MU_DIR}/{MUBASE_FILE} found. Run 'mu kernel build .' first.")

    from mu.kernel import MUbase
    from mu.kernel.graph import GraphManager

    db = MUbase(mubase_path, read_only=True)
    root_path = mubase_path.parent.parent
    try:
        gm = GraphManager(db.conn)
        gm.load()

        resolved_id = resolve_node_id(db, node_name, root_path)

        if not gm.has_node(resolved_id):
            # Check if resolution failed (returned original name)
            if resolved_id == node_name and not node_name.startswith(("mod:", "cls:", "fn:")):
                raise ValueError(f"Node not found: {node_name}")
            # Node exists in DB but not in graph (edge case)
            raise ValueError(f"Node '{resolved_id}' not found in dependency graph")

        # Use GraphManager methods based on direction
        if direction == "outgoing":
            # Get what this node depends on (ancestors)
            dep_ids = gm.ancestors(resolved_id)
        elif direction == "incoming":
            # Get what depends on this node (impact)
            dep_ids = gm.impact(resolved_id)
        else:
            # Both directions
            ancestors = set(gm.ancestors(resolved_id))
            impacted = set(gm.impact(resolved_id))
            dep_ids = list(ancestors | impacted)

        # Limit results to avoid overwhelming output
        dep_ids = dep_ids[:100]

        # Convert IDs to NodeInfo
        deps = []
        for dep_id in dep_ids:
            node = db.get_node(dep_id)
            if node:
                deps.append(
                    NodeInfo(
                        id=node.id,
                        type=node.type.value if hasattr(node.type, "value") else str(node.type),
                        name=node.name,
                        qualified_name=node.qualified_name,
                        file_path=node.file_path,
                        line_start=node.line_start,
                        line_end=node.line_end,
                        complexity=node.complexity or 0,
                    )
                )

        return DepsResult(
            node_id=resolved_id,
            direction=direction,
            dependencies=deps,
        )
    finally:
        db.close()


def mu_impact(node_id: str, edge_types: list[str] | None = None) -> ImpactResult:
    """Find downstream impact of changing a node.

    "If I change X, what might break?"

    Uses BFS traversal via Rust petgraph: O(V + E)

    Args:
        node_id: Node ID or name (e.g., "mod:src/auth.py", "AuthService")
        edge_types: Optional list of edge types to follow (imports, calls, inherits, contains)

    Returns:
        List of node IDs that would be impacted by changes to this node

    Raises:
        ValueError: If node_id does not exist in the graph

    Examples:
        - mu_impact("mod:src/auth.py") - What breaks if auth.py changes?
        - mu_impact("AuthService", ["imports"]) - Only follow import edges
    """
    from mu.mcp.tools._utils import get_client

    cwd = str(Path.cwd())

    # Try daemon first
    try:
        client = get_client()
        with client:
            result = client.impact(node_id, edge_types=edge_types, cwd=cwd)

        return ImpactResult(
            node_id=result.get("node_id", node_id),
            impacted_nodes=result.get("impacted_nodes", []),
            count=result.get("count", 0),
        )
    except DaemonError:
        pass  # Fall through to local mode

    # Fallback to local mode
    mubase_path = find_mubase()
    if not mubase_path:
        raise DaemonError(
            f"No {MU_DIR}/{MUBASE_FILE} found. Run 'mu kernel build .' first."
        )

    from mu.kernel import MUbase
    from mu.kernel.graph import GraphManager

    db = MUbase(mubase_path, read_only=True)
    root_path = mubase_path.parent.parent
    try:
        gm = GraphManager(db.conn)
        gm.load()

        resolved_id = resolve_node_id(db, node_id, root_path)

        if not gm.has_node(resolved_id):
            raise ValueError(f"Node not found: {node_id}")

        impacted = gm.impact(resolved_id, edge_types)

        return ImpactResult(
            node_id=resolved_id,
            impacted_nodes=impacted,
            count=len(impacted),
        )
    finally:
        db.close()


def mu_semantic_diff(
    base_ref: str,
    head_ref: str,
    path: str = ".",
) -> SemanticDiffOutput:
    """Compare two git refs and return semantic changes.

    Returns structured diff with:
    - Added/removed/modified functions, classes, methods
    - Breaking change detection
    - Human-readable summary

    Args:
        base_ref: Base git ref (e.g., "main", "HEAD~1")
        head_ref: Head git ref (e.g., "feature-branch", "HEAD")
        path: Path to codebase (default: current directory)

    Returns:
        SemanticDiffOutput with changes, breaking_changes, summary_text

    Example:
        result = mu_semantic_diff("main", "HEAD")
        if result.has_breaking_changes:
            for bc in result.breaking_changes:
                print(f"BREAKING: {bc['change_type']} {bc['entity_name']}")
    """
    from mu.assembler import assemble
    from mu.config import MUConfig
    from mu.diff import SemanticDiffer, semantic_diff_modules
    from mu.diff.git_utils import compare_refs
    from mu.parser import parse_file
    from mu.parser.models import ModuleDef
    from mu.reducer import reduce_codebase
    from mu.reducer.rules import TransformationRules
    from mu.scanner import scan_codebase_auto

    root_path = Path(path).resolve()

    try:
        config = MUConfig.load()
    except Exception:
        config = MUConfig()

    rules = TransformationRules(
        strip_stdlib_imports=True,
        strip_relative_imports=False,
        strip_dunder_methods=True,
        strip_property_getters=True,
        strip_empty_methods=True,
        include_docstrings=False,
        include_decorators=True,
        include_type_annotations=True,
    )

    def normalize_path(p: str, *worktree_paths: Path) -> str:
        """Strip worktree prefix to get relative path."""
        if not p:
            return p

        for worktree_path in worktree_paths:
            worktree_str = str(worktree_path)
            if p.startswith(worktree_str):
                p_path = Path(p)
                try:
                    rel = p_path.relative_to(worktree_path)
                    return str(rel)
                except ValueError:
                    pass

        p_path = Path(p)
        parts = p_path.parts
        for i, part in enumerate(parts):
            if part.startswith("worktree-") or part.startswith("mu-diff-"):
                if i + 1 < len(parts):
                    return str(Path(*parts[i + 1 :]))

        return p

    def process_version(version_path: Path) -> tuple[Any, list[ModuleDef]]:
        scan_result = scan_codebase_auto(version_path, config)
        if scan_result.stats.total_files == 0:
            return None, []

        modules: list[ModuleDef] = []
        for file_info in scan_result.files:
            full_path = version_path / file_info.path
            parse_result = parse_file(full_path, file_info.language, display_path=file_info.path)
            if parse_result.success and parse_result.module is not None:
                modules.append(parse_result.module)

        reduced = reduce_codebase(modules, version_path, rules)
        assembled = assemble(modules, reduced, version_path)
        return assembled, modules

    with compare_refs(root_path, base_ref, head_ref) as (
        base_path,
        target_path,
        _base_git_ref,
        _target_git_ref,
    ):
        base_assembled, base_modules = process_version(base_path)
        target_assembled, target_modules = process_version(target_path)

        if base_assembled is None or target_assembled is None:
            return SemanticDiffOutput(
                base_ref=base_ref,
                head_ref=head_ref,
                changes=[],
                breaking_changes=[],
                summary_text="No supported files found in one or both refs",
                has_breaking_changes=False,
                total_changes=0,
            )

        # Try Rust semantic diff first
        rust_result = None
        try:
            rust_result = semantic_diff_modules(base_modules, target_modules)
        except TypeError:
            pass

        if rust_result is not None:
            changes = [
                {
                    "entity_type": c.entity_type,
                    "entity_name": c.entity_name,
                    "change_type": c.change_type,
                    "details": c.details,
                    "module_path": normalize_path(c.module_path, base_path, target_path),
                    "is_breaking": c.is_breaking,
                }
                for c in rust_result.changes
            ]
            breaking_changes = [
                {
                    "entity_type": c.entity_type,
                    "entity_name": c.entity_name,
                    "change_type": c.change_type,
                    "details": c.details,
                    "module_path": normalize_path(c.module_path, base_path, target_path),
                }
                for c in rust_result.breaking_changes
            ]
            return SemanticDiffOutput(
                base_ref=base_ref,
                head_ref=head_ref,
                changes=changes,
                breaking_changes=breaking_changes,
                summary_text=rust_result.summary.text(),
                has_breaking_changes=len(breaking_changes) > 0,
                total_changes=len(changes),
            )

        # Fallback to Python differ
        differ = SemanticDiffer(base_assembled, target_assembled, base_ref, head_ref)
        result = differ.diff()

        changes = []
        breaking_changes = []

        for mod_diff in result.module_diffs:
            norm_path = normalize_path(mod_diff.path, base_path, target_path)

            for func_name in mod_diff.added_functions:
                changes.append(
                    {
                        "entity_type": "function",
                        "entity_name": func_name,
                        "change_type": "added",
                        "details": f"New function in {norm_path}",
                        "module_path": norm_path,
                        "is_breaking": False,
                    }
                )

            for func_name in mod_diff.removed_functions:
                change = {
                    "entity_type": "function",
                    "entity_name": func_name,
                    "change_type": "removed",
                    "details": f"Function removed from {norm_path}",
                    "module_path": norm_path,
                    "is_breaking": True,
                }
                changes.append(change)
                breaking_changes.append(change)

            for cls_name in mod_diff.added_classes:
                changes.append(
                    {
                        "entity_type": "class",
                        "entity_name": cls_name,
                        "change_type": "added",
                        "details": f"New class in {norm_path}",
                        "module_path": norm_path,
                        "is_breaking": False,
                    }
                )

            for cls_name in mod_diff.removed_classes:
                change = {
                    "entity_type": "class",
                    "entity_name": cls_name,
                    "change_type": "removed",
                    "details": f"Class removed from {norm_path}",
                    "module_path": norm_path,
                    "is_breaking": True,
                }
                changes.append(change)
                breaking_changes.append(change)

        summary_lines = [f"Comparing {base_ref} -> {head_ref}:"]
        summary_lines.append(f"  Total changes: {len(changes)}")
        if breaking_changes:
            summary_lines.append(f"  Breaking changes: {len(breaking_changes)}")

        return SemanticDiffOutput(
            base_ref=base_ref,
            head_ref=head_ref,
            changes=changes,
            breaking_changes=breaking_changes,
            summary_text="\n".join(summary_lines),
            has_breaking_changes=len(breaking_changes) > 0,
            total_changes=len(changes),
        )


def mu_review_diff(
    base_ref: str,
    head_ref: str,
    path: str = ".",
    validate_patterns: bool = True,
    pattern_category: str | None = None,
) -> ReviewDiffOutput:
    """Perform a comprehensive code review of changes between git refs.

    Combines semantic diff analysis with pattern validation to provide
    actionable review feedback. This is the recommended tool for PR reviews.

    **Analysis includes:**
    - Semantic changes: Added/removed/modified functions, classes, methods
    - Breaking change detection: Removed public APIs, signature changes
    - Pattern validation: Check new code follows codebase conventions
    - Review summary: Human-readable feedback with recommendations

    Args:
        base_ref: Base git ref (e.g., "main", "develop", "HEAD~5")
        head_ref: Head git ref (e.g., "HEAD", "feature-branch")
        path: Path to codebase (default: current directory)
        validate_patterns: Whether to run pattern validation (default True)
        pattern_category: Optional category to validate (all if None).
                         Valid: naming, architecture, testing, imports,
                         error_handling, api, async, logging

    Returns:
        ReviewDiffOutput with comprehensive review including:
        - Semantic changes and breaking change warnings
        - Pattern violations with fix suggestions
        - Overall review summary and recommendations

    Examples:
        # Review PR against main
        mu_review_diff("main", "HEAD")

        # Review last 3 commits
        mu_review_diff("HEAD~3", "HEAD")

        # Review with naming conventions only
        mu_review_diff("develop", "feature-branch", pattern_category="naming")

        # Skip pattern validation (just semantic diff)
        mu_review_diff("main", "HEAD", validate_patterns=False)

    Use Cases:
        - PR review: Automated review before merge
        - Pre-commit: Check your changes before committing
        - Code audit: Review large changes for issues
        - Learning: Understand what patterns to follow
    """
    start_time = time.time()

    # Get semantic diff
    diff_result = mu_semantic_diff(base_ref, head_ref, path)

    # Pattern validation is deprecated (validator removed)
    violations: list[ViolationInfo] = []
    patterns_checked: list[str] = []
    files_checked: list[str] = []
    error_count = 0
    warning_count = 0
    info_count = 0
    patterns_valid = True
    _ = validate_patterns
    _ = pattern_category

    # Generate review summary
    summary_parts = []
    summary_parts.append(f"# Code Review: {base_ref} -> {head_ref}")
    summary_parts.append("")

    summary_parts.append("## Semantic Changes")
    if diff_result.total_changes == 0:
        summary_parts.append("No semantic changes detected.")
    else:
        summary_parts.append(f"- Total changes: {diff_result.total_changes}")

        added = [c for c in diff_result.changes if c.get("change_type") == "added"]
        removed = [c for c in diff_result.changes if c.get("change_type") == "removed"]
        modified = [
            c for c in diff_result.changes if c.get("change_type") not in ("added", "removed")
        ]

        if added:
            summary_parts.append(f"- Added: {len(added)}")
        if removed:
            summary_parts.append(f"- Removed: {len(removed)}")
        if modified:
            summary_parts.append(f"- Modified: {len(modified)}")

    summary_parts.append("")

    if diff_result.has_breaking_changes:
        summary_parts.append("## Breaking Changes Detected")
        for bc in diff_result.breaking_changes[:5]:
            entity = bc.get("entity_name", "unknown")
            change_type = bc.get("change_type", "modified")
            summary_parts.append(f"- **{entity}**: {change_type}")
        if len(diff_result.breaking_changes) > 5:
            summary_parts.append(f"  ... and {len(diff_result.breaking_changes) - 5} more")
        summary_parts.append("")

    if validate_patterns:
        summary_parts.append("## Pattern Validation")
        if not files_checked:
            summary_parts.append("No files to validate (no .mubase or no changed files).")
        elif patterns_valid and not violations:
            summary_parts.append("All changes follow codebase patterns.")
        summary_parts.append("")

    summary_parts.append("## Recommendation")
    if diff_result.has_breaking_changes:
        summary_parts.append(
            "**Review breaking changes carefully** before merging. "
            "Ensure downstream code is updated."
        )
    elif error_count > 0:
        summary_parts.append(
            "**Address pattern violations** before merging. "
            "New code should follow established conventions."
        )
    elif warning_count > 0:
        summary_parts.append(
            "**Consider addressing warnings** for consistency. Changes are otherwise acceptable."
        )
    else:
        summary_parts.append("**Looks good!** No blocking issues found.")

    review_summary = "\n".join(summary_parts)
    review_time_ms = (time.time() - start_time) * 1000

    return ReviewDiffOutput(
        base_ref=base_ref,
        head_ref=head_ref,
        changes=diff_result.changes,
        breaking_changes=diff_result.breaking_changes,
        has_breaking_changes=diff_result.has_breaking_changes,
        total_changes=diff_result.total_changes,
        violations=violations,
        patterns_checked=patterns_checked,
        files_checked=files_checked,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        patterns_valid=patterns_valid,
        review_summary=review_summary,
        review_time_ms=review_time_ms,
    )


def register_analysis_tools(mcp: FastMCP) -> None:
    """Register analysis tools with FastMCP server."""
    mcp.tool()(mu_deps)
    mcp.tool()(mu_impact)
    mcp.tool()(mu_semantic_diff)
    mcp.tool()(mu_review_diff)
