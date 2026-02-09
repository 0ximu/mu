#!/usr/bin/env python3
"""Render MU eval summary report (single run or baseline vs candidate)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

TRACKED_METRICS = [
    "recall_at_1",
    "recall_at_5",
    "first_correct_rank",
    "artifact_noise_ratio",
    "p50_latency_ms",
    "p95_latency_ms",
    "avg_output_tokens",
    "success_rate",
]


def load_summary(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def metric_delta(name: str, base_value: Any, cand_value: Any) -> str:
    if base_value is None or cand_value is None:
        return "-"
    delta = float(cand_value) - float(base_value)
    sign = "+" if delta >= 0 else ""
    if name in {"recall_at_1", "recall_at_5", "success_rate"}:
        return f"{sign}{delta:.4f}"
    if name in {"artifact_noise_ratio", "first_correct_rank", "p50_latency_ms", "p95_latency_ms", "avg_output_tokens"}:
        return f"{sign}{delta:.4f}"
    return f"{sign}{delta:.4f}"


def regression_warnings(base: dict[str, Any], cand: dict[str, Any]) -> list[str]:
    base_metrics = base.get("metrics", {})
    cand_metrics = cand.get("metrics", {})
    warnings: list[str] = []

    if (
        base_metrics.get("artifact_noise_ratio") is not None
        and cand_metrics.get("artifact_noise_ratio") is not None
        and cand_metrics["artifact_noise_ratio"] > base_metrics["artifact_noise_ratio"]
    ):
        warnings.append("artifact_noise_ratio regressed (higher is worse)")

    if (
        base_metrics.get("recall_at_5") is not None
        and cand_metrics.get("recall_at_5") is not None
        and cand_metrics["recall_at_5"] < base_metrics["recall_at_5"]
    ):
        warnings.append("recall_at_5 regressed (lower is worse)")

    if (
        base_metrics.get("p95_latency_ms") is not None
        and cand_metrics.get("p95_latency_ms") is not None
        and cand_metrics["p95_latency_ms"] > base_metrics["p95_latency_ms"]
    ):
        warnings.append("p95_latency_ms regressed (higher is worse)")

    return warnings


def render_single(summary: dict[str, Any], label: str) -> str:
    lines = []
    lines.append(f"# MU Eval Report: {label}")
    lines.append("")
    lines.append(f"- Commit: `{summary.get('git_commit')}`")
    counts = summary.get("counts", {})
    lines.append(
        f"- Tasks: {counts.get('task_succeeded', 0)}/{counts.get('task_total', 0)} succeeded"
    )
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    for metric in TRACKED_METRICS:
        lines.append(f"| `{metric}` | {fmt(summary.get('metrics', {}).get(metric))} |")
    return "\n".join(lines)


def render_diff(base: dict[str, Any], cand: dict[str, Any], baseline_label: str, candidate_label: str) -> str:
    lines = []
    lines.append("# MU Eval Comparison")
    lines.append("")
    lines.append(f"- Baseline ({baseline_label}): `{base.get('git_commit')}`")
    lines.append(f"- Candidate ({candidate_label}): `{cand.get('git_commit')}`")
    lines.append("")
    lines.append("| Metric | Baseline | Candidate | Delta |")
    lines.append("|---|---:|---:|---:|")

    base_metrics = base.get("metrics", {})
    cand_metrics = cand.get("metrics", {})
    for metric in TRACKED_METRICS:
        b = base_metrics.get(metric)
        c = cand_metrics.get(metric)
        lines.append(f"| `{metric}` | {fmt(b)} | {fmt(c)} | {metric_delta(metric, b, c)} |")

    warnings = regression_warnings(base, cand)
    lines.append("")
    if warnings:
        lines.append("## Regressions")
        for warning in warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("## Regressions")
        lines.append("- none")

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate MU eval report")
    parser.add_argument("--summary", help="Single summary JSON path")
    parser.add_argument("--baseline", help="Baseline summary JSON path")
    parser.add_argument("--candidate", help="Candidate summary JSON path")
    parser.add_argument("--label", default="run", help="Label for --summary mode")
    parser.add_argument("--baseline-label", default="baseline")
    parser.add_argument("--candidate-label", default="candidate")
    parser.add_argument("--out", help="Optional output markdown path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.summary and (args.baseline or args.candidate):
        raise SystemExit("Use either --summary or --baseline/--candidate")

    if args.summary:
        rendered = render_single(load_summary(args.summary), args.label)
    else:
        if not args.baseline or not args.candidate:
            raise SystemExit("Provide --summary OR both --baseline and --candidate")
        rendered = render_diff(
            load_summary(args.baseline),
            load_summary(args.candidate),
            args.baseline_label,
            args.candidate_label,
        )

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered + "\n")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
