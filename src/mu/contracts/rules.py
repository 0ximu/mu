"""Rule evaluators for MU Contracts.

This module provides the RuleEvaluator protocol and implementations for
each rule type: query, analyze, dependency, and pattern.
"""

from __future__ import annotations

import json
from fnmatch import fnmatch
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from mu.contracts.models import (
    EvaluationResult,
    Expectation,
    ExpectationType,
    Rule,
)

if TYPE_CHECKING:
    from mu.kernel.mubase import MUbase


def check_expectation(
    result_count: int,
    expect: Expectation,
    result_value: int | None = None,
) -> bool:
    """Check if a result meets an expectation.

    Args:
        result_count: Number of results returned.
        expect: The expectation to check.
        result_value: Optional single value (for aggregates like COUNT).

    Returns:
        True if expectation is met.
    """
    match expect.type:
        case ExpectationType.EMPTY:
            return result_count == 0
        case ExpectationType.NOT_EMPTY:
            return result_count > 0
        case ExpectationType.COUNT:
            return result_count == (expect.value or 0)
        case ExpectationType.MAX:
            value = result_value if result_value is not None else result_count
            return value <= (expect.value or 0)
        case ExpectationType.MIN:
            value = result_value if result_value is not None else result_count
            return value >= (expect.value or 0)
    return False


@runtime_checkable
class RuleEvaluator(Protocol):
    """Protocol for rule evaluators."""

    @property
    def rule_type(self) -> str:
        """Return the rule type this evaluator handles."""
        ...

    def evaluate(
        self,
        mubase: MUbase,
        rule: Rule,
        expect: Expectation,
    ) -> EvaluationResult:
        """Evaluate a rule against the database.

        Args:
            mubase: The MUbase database.
            rule: Rule definition with params.
            expect: Expected outcome.

        Returns:
            EvaluationResult with passed flag and violation details.
        """
        ...


class QueryRuleEvaluator:
    """Evaluate MUQL query-based rules."""

    @property
    def rule_type(self) -> str:
        return "query"

    def evaluate(
        self,
        mubase: MUbase,
        rule: Rule,
        expect: Expectation,
    ) -> EvaluationResult:
        """Execute MUQL query and check expectation."""
        from mu.kernel.muql import MUQLEngine

        muql = rule.params.get("muql", "")
        if not muql:
            return EvaluationResult(
                passed=False,
                details=[{"error": "No MUQL query specified"}],
            )

        engine = MUQLEngine(mubase)
        result = engine.execute(muql)

        if not result.is_success:
            return EvaluationResult(
                passed=False,
                details=[{"error": result.error}],
            )

        # For MAX/MIN with aggregates, check first row value
        result_value = None
        if expect.type in (ExpectationType.MAX, ExpectationType.MIN):
            if result.rows and len(result.rows[0]) > 0:
                try:
                    result_value = int(result.rows[0][0])
                except (ValueError, TypeError):
                    pass

        passed = check_expectation(result.row_count, expect, result_value)

        # Convert rows to details
        details = result.as_dicts()

        return EvaluationResult(
            passed=passed,
            details=details,
            row_count=result.row_count,
        )


class AnalyzeRuleEvaluator:
    """Evaluate built-in analysis rules."""

    @property
    def rule_type(self) -> str:
        return "analyze"

    def evaluate(
        self,
        mubase: MUbase,
        rule: Rule,
        expect: Expectation,
    ) -> EvaluationResult:
        """Execute built-in analysis and check expectation."""
        analysis = rule.params.get("analysis", "")

        match analysis:
            case "circular":
                return self._analyze_circular(mubase, expect)
            case "complexity":
                threshold = rule.params.get("threshold", 500)
                return self._analyze_complexity(mubase, expect, threshold)
            case "coupling":
                threshold = rule.params.get("threshold", 20)
                return self._analyze_coupling(mubase, expect, threshold)
            case "unused":
                return self._analyze_unused(mubase, expect)
            case "hotspots":
                threshold = rule.params.get("threshold", 5)
                return self._analyze_hotspots(mubase, expect, threshold)
            case _:
                return EvaluationResult(
                    passed=False,
                    details=[{"error": f"Unknown analysis type: {analysis}"}],
                )

    def _analyze_circular(
        self,
        mubase: MUbase,
        expect: Expectation,
    ) -> EvaluationResult:
        """Find circular dependencies (bidirectional imports)."""
        sql = """
            SELECT DISTINCT
                n1.name as from_name,
                n1.file_path as from_path,
                n2.name as to_name,
                n2.file_path as to_path
            FROM edges e1
            JOIN edges e2 ON e1.source_id = e2.target_id
                         AND e1.target_id = e2.source_id
            JOIN nodes n1 ON e1.source_id = n1.id
            JOIN nodes n2 ON e1.target_id = n2.id
            WHERE e1.type = 'imports'
            LIMIT 50
        """
        cursor = mubase.conn.execute(sql)
        rows = cursor.fetchall()

        details = [
            {
                "from": row[0],
                "from_path": row[1],
                "to": row[2],
                "to_path": row[3],
            }
            for row in rows
        ]
        passed = check_expectation(len(details), expect)

        return EvaluationResult(
            passed=passed,
            details=details,
            row_count=len(details),
        )

    def _analyze_complexity(
        self,
        mubase: MUbase,
        expect: Expectation,
        threshold: int,
    ) -> EvaluationResult:
        """Find functions/classes exceeding complexity threshold."""
        sql = """
            SELECT name, type, file_path, complexity
            FROM nodes
            WHERE complexity > ?
            ORDER BY complexity DESC
            LIMIT 100
        """
        cursor = mubase.conn.execute(sql, [threshold])
        rows = cursor.fetchall()

        details = [
            {
                "name": row[0],
                "type": row[1],
                "path": row[2],
                "complexity": row[3],
            }
            for row in rows
        ]
        passed = check_expectation(len(details), expect)

        return EvaluationResult(
            passed=passed,
            details=details,
            row_count=len(details),
        )

    def _analyze_coupling(
        self,
        mubase: MUbase,
        expect: Expectation,
        threshold: int,
    ) -> EvaluationResult:
        """Find modules with high dependency counts (afferent + efferent)."""
        sql = """
            WITH outgoing AS (
                SELECT source_id as id, COUNT(*) as out_count
                FROM edges WHERE type = 'imports'
                GROUP BY source_id
            ),
            incoming AS (
                SELECT target_id as id, COUNT(*) as in_count
                FROM edges WHERE type = 'imports'
                GROUP BY target_id
            )
            SELECT
                n.name,
                n.file_path,
                COALESCE(o.out_count, 0) as efferent,
                COALESCE(i.in_count, 0) as afferent,
                COALESCE(o.out_count, 0) + COALESCE(i.in_count, 0) as total
            FROM nodes n
            LEFT JOIN outgoing o ON n.id = o.id
            LEFT JOIN incoming i ON n.id = i.id
            WHERE n.type = 'module'
            AND (COALESCE(o.out_count, 0) + COALESCE(i.in_count, 0)) > ?
            ORDER BY total DESC
            LIMIT 50
        """
        cursor = mubase.conn.execute(sql, [threshold])
        rows = cursor.fetchall()

        details = [
            {
                "name": row[0],
                "path": row[1],
                "efferent": row[2],
                "afferent": row[3],
                "total": row[4],
            }
            for row in rows
        ]
        passed = check_expectation(len(details), expect)

        return EvaluationResult(
            passed=passed,
            details=details,
            row_count=len(details),
        )

    def _analyze_unused(
        self,
        mubase: MUbase,
        expect: Expectation,
    ) -> EvaluationResult:
        """Find nodes with no dependents (not imported by anything)."""
        sql = """
            SELECT n.name, n.type, n.file_path
            FROM nodes n
            LEFT JOIN edges e ON n.id = e.target_id AND e.type = 'imports'
            WHERE n.type = 'module'
            AND e.id IS NULL
            AND n.file_path NOT LIKE '%test%'
            AND n.file_path NOT LIKE '%__init__%'
            LIMIT 100
        """
        cursor = mubase.conn.execute(sql)
        rows = cursor.fetchall()

        details = [
            {
                "name": row[0],
                "type": row[1],
                "path": row[2],
            }
            for row in rows
        ]
        passed = check_expectation(len(details), expect)

        return EvaluationResult(
            passed=passed,
            details=details,
            row_count=len(details),
        )

    def _analyze_hotspots(
        self,
        mubase: MUbase,
        expect: Expectation,
        threshold: int,
    ) -> EvaluationResult:
        """Find modules that are both highly depended on AND have high complexity."""
        sql = """
            WITH dependents AS (
                SELECT target_id as id, COUNT(*) as dep_count
                FROM edges WHERE type = 'imports'
                GROUP BY target_id
            )
            SELECT
                n.name,
                n.file_path,
                n.complexity,
                COALESCE(d.dep_count, 0) as dependents
            FROM nodes n
            LEFT JOIN dependents d ON n.id = d.id
            WHERE n.type = 'module'
            AND n.complexity > 100
            AND COALESCE(d.dep_count, 0) >= ?
            ORDER BY n.complexity * COALESCE(d.dep_count, 0) DESC
            LIMIT 50
        """
        cursor = mubase.conn.execute(sql, [threshold])
        rows = cursor.fetchall()

        details = [
            {
                "name": row[0],
                "path": row[1],
                "complexity": row[2],
                "dependents": row[3],
            }
            for row in rows
        ]
        passed = check_expectation(len(details), expect)

        return EvaluationResult(
            passed=passed,
            details=details,
            row_count=len(details),
        )


class DependencyRuleEvaluator:
    """Evaluate dependency restriction rules (A should not depend on B)."""

    @property
    def rule_type(self) -> str:
        return "dependency"

    def evaluate(
        self,
        mubase: MUbase,
        rule: Rule,
        expect: Expectation,
    ) -> EvaluationResult:
        """Find imports matching from/to patterns."""
        from_pattern = rule.params.get("from", "")
        to_pattern = rule.params.get("to", "")
        exceptions = rule.params.get("except", [])

        if not from_pattern or not to_pattern:
            return EvaluationResult(
                passed=False,
                details=[{"error": "Dependency rule requires 'from' and 'to' patterns"}],
            )

        # Find all import edges
        sql = """
            SELECT
                s.file_path as source_path,
                s.name as source_name,
                t.file_path as target_path,
                t.name as target_name
            FROM edges e
            JOIN nodes s ON e.source_id = s.id
            JOIN nodes t ON e.target_id = t.id
            WHERE e.type = 'imports'
        """
        cursor = mubase.conn.execute(sql)
        rows = cursor.fetchall()

        # Filter by patterns
        violations = []
        for row in rows:
            source_path = row[0] or ""
            target_path = row[2] or ""

            # Check if matches the forbidden pattern
            if fnmatch(source_path, from_pattern) and fnmatch(target_path, to_pattern):
                # Check exceptions
                is_exception = any(
                    fnmatch(source_path, exc) or fnmatch(target_path, exc) for exc in exceptions
                )
                if not is_exception:
                    violations.append(
                        {
                            "from": f"{row[1]} ({source_path})",
                            "to": f"{row[3]} ({target_path})",
                            "source_path": source_path,
                            "target_path": target_path,
                        }
                    )

        passed = check_expectation(len(violations), expect)

        return EvaluationResult(
            passed=passed,
            details=violations,
            row_count=len(violations),
        )


class PatternRuleEvaluator:
    """Evaluate pattern-based rules (all X must have Y)."""

    @property
    def rule_type(self) -> str:
        return "pattern"

    def evaluate(
        self,
        mubase: MUbase,
        rule: Rule,
        expect: Expectation,
    ) -> EvaluationResult:
        """Find nodes matching pattern and check must_have requirements."""
        match_pattern = rule.params.get("match")
        node_type = rule.params.get("node_type", "").lower()
        name_pattern = rule.params.get("name_pattern")
        must_have = rule.params.get("must_have", {})

        # Build query to find matching nodes
        conditions = []
        params: list[Any] = []

        if match_pattern:
            # Convert glob to SQL LIKE
            sql_pattern = match_pattern.replace("*", "%").replace("?", "_")
            conditions.append("file_path LIKE ?")
            params.append(sql_pattern)

        if node_type:
            conditions.append("type = ?")
            params.append(node_type)

        if name_pattern:
            # Convert glob to SQL LIKE
            sql_name = name_pattern.replace("*", "%").replace("?", "_")
            conditions.append("name LIKE ?")
            params.append(sql_name)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT id, name, type, file_path, properties FROM nodes WHERE {where}"

        cursor = mubase.conn.execute(sql, params)
        rows = cursor.fetchall()

        # Check must_have requirements
        violations = []
        for row in rows:
            node_id, name, node_type_val, path, props_json = row

            # Parse properties
            try:
                props = json.loads(props_json) if props_json else {}
            except (json.JSONDecodeError, TypeError):
                props = {}

            # Check required decorator
            if "decorator" in must_have:
                required_decorator = must_have["decorator"]
                decorators = props.get("decorators", [])
                # Normalize: @decorator or decorator
                required_normalized = (
                    required_decorator[1:]
                    if required_decorator.startswith("@")
                    else required_decorator
                )
                has_decorator = any(
                    d == required_decorator
                    or d == required_normalized
                    or d == f"@{required_normalized}"
                    for d in decorators
                )
                if not has_decorator:
                    violations.append(
                        {
                            "node": name,
                            "path": path,
                            "type": node_type_val,
                            "missing": f"decorator {required_decorator}",
                        }
                    )

            # Check required annotation
            if "annotation" in must_have:
                required_annotation = must_have["annotation"]
                annotations = props.get("annotations", [])
                if required_annotation not in annotations:
                    violations.append(
                        {
                            "node": name,
                            "path": path,
                            "type": node_type_val,
                            "missing": f"annotation {required_annotation}",
                        }
                    )

            # Check required base class
            if "inherits" in must_have:
                required_base = must_have["inherits"]
                bases = props.get("bases", [])
                if required_base not in bases:
                    violations.append(
                        {
                            "node": name,
                            "path": path,
                            "type": node_type_val,
                            "missing": f"inheritance from {required_base}",
                        }
                    )

        passed = check_expectation(len(violations), expect)

        return EvaluationResult(
            passed=passed,
            details=violations,
            row_count=len(violations),
        )
