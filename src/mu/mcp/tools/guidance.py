"""Guidance tools: patterns and warnings."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mu.client import DaemonError
from mu.mcp.models import (
    PatternInfo,
    PatternsOutput,
    WarningInfo,
    WarningsOutput,
)
from mu.mcp.tools._utils import find_mubase, get_client
from mu.paths import MU_DIR, MUBASE_FILE


def mu_patterns(
    category: str | None = None,
    refresh: bool = False,
    limit: int = 10,
    include_examples: bool = False,
) -> PatternsOutput:
    """Get detected codebase patterns.

    Analyzes the codebase to detect recurring patterns including:
    - Naming conventions (file/function/class naming)
    - Error handling patterns
    - Import organization
    - Architectural patterns (services, repositories)
    - Testing patterns
    - API patterns

    Args:
        category: Optional filter by category. Valid categories:
                  error_handling, state_management, api, naming,
                  testing, components, imports, architecture, async, logging
        refresh: Force re-analysis (bypass cached patterns)
        limit: Maximum number of patterns to return (default 10)
        include_examples: Include code examples in output (default False)

    Returns:
        PatternsOutput with detected patterns and examples

    Examples:
        - mu_patterns() - Get all detected patterns
        - mu_patterns("naming") - Get naming convention patterns only
        - mu_patterns("error_handling") - Get error handling patterns
        - mu_patterns(refresh=True) - Force re-analysis
    """
    from pathlib import Path

    cwd = str(Path.cwd())

    # Try daemon first
    try:
        client = get_client()
        with client:
            result = client.patterns(category=category, refresh=refresh, cwd=cwd)

        patterns_info = [
            PatternInfo(
                name=p.get("name", ""),
                category=p.get("category", ""),
                description=p.get("description", ""),
                frequency=p.get("frequency", 0),
                confidence=p.get("confidence", 0.0),
                examples=p.get("examples", []) if include_examples else [],
                anti_patterns=p.get("anti_patterns", []),
            )
            for p in result.get("patterns", [])
        ]

        # Sort by confidence and limit
        patterns_info.sort(key=lambda p: p.confidence, reverse=True)
        patterns_info = patterns_info[:limit]

        return PatternsOutput(
            patterns=patterns_info,
            total_patterns=result.get("total_patterns", len(patterns_info)),
            categories_found=result.get("categories_found", []),
            detection_time_ms=result.get("detection_time_ms", 0.0),
        )
    except DaemonError:
        # Daemon not running - fall back to direct database access
        mubase_path = find_mubase()
        if not mubase_path:
            raise DaemonError(
                f"No {MU_DIR}/{MUBASE_FILE} found. Run 'mu daemon start .' first."
            ) from None

        from mu.intelligence import PatternCategory, PatternDetector
        from mu.kernel import MUbase

        # We need write access to save patterns, so don't use read_only mode
        db = MUbase(mubase_path, read_only=False)
        try:
            # Check for cached patterns unless refresh requested
            if not refresh and db.has_patterns():
                stored_patterns = db.get_patterns(category)
                if stored_patterns:
                    categories_found = list({p.category.value for p in stored_patterns})

                    # Sort by confidence and limit
                    stored_patterns = sorted(
                        stored_patterns, key=lambda p: p.confidence, reverse=True
                    )[:limit]

                    patterns_info = [
                        PatternInfo(
                            name=p.name,
                            category=p.category.value,
                            description=p.description,
                            frequency=p.frequency,
                            confidence=p.confidence,
                            examples=[e.to_dict() for e in p.examples] if include_examples else [],
                            anti_patterns=p.anti_patterns,
                        )
                        for p in stored_patterns
                    ]

                    return PatternsOutput(
                        patterns=patterns_info,
                        total_patterns=len(patterns_info),
                        categories_found=categories_found,
                        detection_time_ms=0.0,
                    )

            # Run pattern detection
            detector = PatternDetector(db)

            cat_enum = None
            if category:
                try:
                    cat_enum = PatternCategory(category)
                except ValueError:
                    valid_cats = [c.value for c in PatternCategory]
                    raise ValueError(
                        f"Invalid category: {category}. Valid categories: {valid_cats}"
                    ) from None

            detect_result = detector.detect(category=cat_enum, refresh=refresh)

            # Save patterns for future use (only if detecting all)
            if not category:
                db.save_patterns(detect_result.patterns)

            # Sort by confidence and limit
            sorted_patterns = sorted(
                detect_result.patterns, key=lambda p: p.confidence, reverse=True
            )[:limit]

            patterns_info = [
                PatternInfo(
                    name=p.name,
                    category=p.category.value,
                    description=p.description,
                    frequency=p.frequency,
                    confidence=p.confidence,
                    examples=[e.to_dict() for e in p.examples] if include_examples else [],
                    anti_patterns=p.anti_patterns,
                )
                for p in sorted_patterns
            ]

            return PatternsOutput(
                patterns=patterns_info,
                total_patterns=detect_result.total_patterns,
                categories_found=detect_result.categories_found,
                detection_time_ms=detect_result.detection_time_ms,
            )
        finally:
            db.close()


def mu_warn(target: str) -> WarningsOutput:
    """Get proactive warnings about a target before modification.

    Analyzes a file or node to identify potential issues that should be
    considered before making changes. Returns warnings about:
    - High impact: Many files depend on this (>10 dependents)
    - Stale code: Not modified in >6 months
    - Security sensitive: Contains auth/crypto/secrets logic
    - No tests: No test coverage detected
    - High complexity: Cyclomatic complexity >20
    - Deprecated: Marked as deprecated in code

    Args:
        target: File path or node ID to analyze
                Examples: "src/auth.py", "AuthService", "cls:src/auth.py:AuthService"

    Returns:
        WarningsOutput with all detected warnings and risk score

    Examples:
        - mu_warn("src/auth.py") - Check auth module before modifying
        - mu_warn("AuthService") - Check a specific class
        - mu_warn("mod:src/payments.py") - Check by node ID

    Use Cases:
        - Before modifying critical code: Check impact and risks
        - PR review: Understand what you're touching
        - New to codebase: Get context before changes
    """
    from pathlib import Path

    cwd = str(Path.cwd())

    # Try daemon first
    try:
        client = get_client()
        with client:
            result = client.warn(target=target, cwd=cwd)

        warnings_info = [
            WarningInfo(
                category=w.get("category", ""),
                level=w.get("level", ""),
                message=w.get("message", ""),
                details=w.get("details"),
            )
            for w in result.get("warnings", [])
        ]

        return WarningsOutput(
            target=result.get("target", target),
            target_type=result.get("target_type", "unknown"),
            warnings=warnings_info,
            summary=result.get("summary", ""),
            risk_score=result.get("risk_score", 0.0),
            analysis_time_ms=result.get("analysis_time_ms", 0.0),
        )
    except DaemonError:
        # Daemon not running - fall back to direct database access
        mubase_path = find_mubase()
        if not mubase_path:
            raise DaemonError(
                f"No {MU_DIR}/{MUBASE_FILE} found. Run 'mu daemon start .' first."
            ) from None

        from mu.intelligence.warnings import ProactiveWarningGenerator
        from mu.kernel import MUbase

        db = MUbase(mubase_path, read_only=True)
        # mubase_path is .mu/mubase, so parent.parent is the project root
        project_root = mubase_path.parent.parent
        try:
            generator = ProactiveWarningGenerator(db, root_path=project_root)
            analyze_result = generator.analyze(target)

            warnings_info = [
                WarningInfo(
                    category=w.category.value,
                    level=w.level,
                    message=w.message,
                    details=w.details,
                )
                for w in analyze_result.warnings
            ]

            return WarningsOutput(
                target=analyze_result.target,
                target_type=analyze_result.target_type,
                warnings=warnings_info,
                summary=analyze_result.summary,
                risk_score=analyze_result.risk_score,
                analysis_time_ms=analyze_result.analysis_time_ms,
            )
        finally:
            db.close()


def register_guidance_tools(mcp: FastMCP) -> None:
    """Register guidance tools with FastMCP server."""
    mcp.tool()(mu_patterns)
    mcp.tool()(mu_warn)
