#!/usr/bin/env python3
"""Score MU eval runs.

Computes:
- recall_at_1
- recall_at_5
- first_correct_rank
- artifact_noise_ratio
- p50_latency_ms
- p95_latency_ms
- avg_output_tokens
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MISS_RANK_PENALTY = 10

ARTIFACT_REGEXES = [
    re.compile(r"(^|/)coverage(/|$)", re.IGNORECASE),
    re.compile(r"(^|/)dist(/|$)", re.IGNORECASE),
    re.compile(r"(^|/)build(/|$)", re.IGNORECASE),
    re.compile(r"(^|/)node_modules(/|$)", re.IGNORECASE),
    re.compile(r"(^|/)bin(/|$)", re.IGNORECASE),
    re.compile(r"(^|/)obj(/|$)", re.IGNORECASE),
    re.compile(r"\.min\.js$", re.IGNORECASE),
    re.compile(r"\.designer\.cs$", re.IGNORECASE),
    re.compile(r"\.generated\.", re.IGNORECASE),
    re.compile(r"/migrations/.*snapshot\.cs$", re.IGNORECASE),
    re.compile(r"\.g\.cs$", re.IGNORECASE),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = (len(ordered) - 1) * p
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return ordered[lo]
    fraction = idx - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * fraction


def approx_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "", value.lower())


def names_match(expected: str, actual: str) -> bool:
    e = normalize_name(expected)
    a = normalize_name(actual)
    if not e or not a:
        return False
    if a == e:
        return True
    if a.endswith(e):
        return True
    if len(e) >= 6 and e in a:
        return True
    return False


def is_artifact_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(regex.search(normalized) for regex in ARTIFACT_REGEXES)


def pick_representative_run(run_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not run_results:
        return None
    successful = [
        run
        for run in run_results
        if run.get("status") == "ok" and isinstance(run.get("parsed_json"), dict)
    ]
    if not successful:
        return run_results[0]
    if len(successful) == 1:
        return successful[0]

    med = statistics.median(float(run.get("duration_ms", 0.0)) for run in successful)
    return min(successful, key=lambda run: abs(float(run.get("duration_ms", 0.0)) - med))


def extract_candidates(tool: str, parsed: dict[str, Any]) -> tuple[list[str], list[str]]:
    names: list[str] = []
    file_paths: list[str] = []

    def add_name(value: Any) -> None:
        if isinstance(value, str) and value:
            names.append(value)

    def add_path(value: Any) -> None:
        if isinstance(value, str) and value:
            file_paths.append(value)

    if tool == "search":
        for row in parsed.get("results", []):
            if isinstance(row, dict):
                add_name(row.get("name"))
                add_path(row.get("file_path"))
    elif tool == "grok":
        for row in parsed.get("contexts", []):
            if isinstance(row, dict):
                add_name(row.get("name"))
                add_path(row.get("file_path"))
    elif tool == "impact":
        for row in parsed.get("affected_nodes", []):
            if isinstance(row, dict):
                add_name(row.get("name"))
                add_path(row.get("file_path"))
    elif tool == "sus":
        for row in parsed.get("results", []):
            if isinstance(row, dict):
                add_name(row.get("target"))
                add_path(row.get("file_path"))
    elif tool == "wtf":
        add_path(parsed.get("file_path"))
    elif tool == "muql":
        columns = parsed.get("columns", [])
        rows = parsed.get("rows", [])
        if isinstance(columns, list) and isinstance(rows, list):
            try:
                name_idx = columns.index("name")
            except ValueError:
                name_idx = 2
            try:
                path_idx = columns.index("file_path")
            except ValueError:
                path_idx = 3

            for row in rows:
                if not isinstance(row, list):
                    continue
                if 0 <= name_idx < len(row):
                    add_name(row[name_idx])
                if 0 <= path_idx < len(row):
                    add_path(row[path_idx])

    return names, file_paths


def first_correct_rank(expected_nodes: list[str], predicted_names: list[str]) -> int | None:
    for idx, predicted in enumerate(predicted_names, start=1):
        if any(names_match(expected, predicted) for expected in expected_nodes):
            return idx
    return None


def compute_summary(run_doc: dict[str, Any], source_path: str | None = None) -> dict[str, Any]:
    task_total = 0
    task_succeeded = 0
    task_failed = 0

    eval_task_count = 0
    recall1_hits = 0
    recall5_hits = 0
    rank_values: list[float] = []

    artifact_total = 0
    artifact_count = 0

    output_token_values: list[float] = []
    latency_values: list[float] = []

    non_retrieval_checks = 0
    non_retrieval_passes = 0

    for task in run_doc.get("results", []):
        task_total += 1
        rep = pick_representative_run(task.get("run_results", []))

        if rep is None:
            task_failed += 1
            continue

        status = rep.get("status")
        tool = task.get("tool", "")
        parsed = rep.get("parsed_json") if isinstance(rep.get("parsed_json"), dict) else None

        if status == "ok" and parsed is not None:
            task_succeeded += 1
            latency_values.append(float(rep.get("duration_ms", 0.0)))
            output_token_values.append(float(approx_tokens(rep.get("stdout", ""))))

            expected_fields = task.get("expected_fields") or []
            if isinstance(expected_fields, list) and expected_fields:
                non_retrieval_checks += 1
                if all(field in parsed for field in expected_fields):
                    non_retrieval_passes += 1

            names, file_paths = extract_candidates(tool, parsed)
            artifact_total += len(file_paths)
            artifact_count += sum(1 for path in file_paths if is_artifact_path(path))

            expected_nodes = task.get("expected_nodes") or []
            if isinstance(expected_nodes, list) and expected_nodes:
                eval_task_count += 1
                rank = first_correct_rank(expected_nodes, names)
                if rank == 1:
                    recall1_hits += 1
                if rank is not None and rank <= 5:
                    recall5_hits += 1
                rank_values.append(float(rank if rank is not None else MISS_RANK_PENALTY))
        else:
            task_failed += 1

    recall_at_1 = (recall1_hits / eval_task_count) if eval_task_count else None
    recall_at_5 = (recall5_hits / eval_task_count) if eval_task_count else None
    first_rank = statistics.mean(rank_values) if rank_values else None
    artifact_ratio = (artifact_count / artifact_total) if artifact_total else 0.0
    avg_tokens = statistics.mean(output_token_values) if output_token_values else None

    summary = {
        "schema_version": "mu_eval_score_v1",
        "generated_at": now_iso(),
        "source_run_file": source_path,
        "git_commit": run_doc.get("git_commit"),
        "counts": {
            "task_total": task_total,
            "task_succeeded": task_succeeded,
            "task_failed": task_failed,
            "evaluable_task_count": eval_task_count,
            "artifact_paths_total": artifact_total,
            "artifact_paths_flagged": artifact_count,
            "non_retrieval_checks": non_retrieval_checks,
            "non_retrieval_passes": non_retrieval_passes,
        },
        "metrics": {
            "recall_at_1": recall_at_1,
            "recall_at_5": recall_at_5,
            "first_correct_rank": first_rank,
            "artifact_noise_ratio": artifact_ratio,
            "p50_latency_ms": percentile(latency_values, 0.50),
            "p95_latency_ms": percentile(latency_values, 0.95),
            "avg_output_tokens": avg_tokens,
            "success_rate": (task_succeeded / task_total) if task_total else 0.0,
            "non_retrieval_pass_rate": (
                (non_retrieval_passes / non_retrieval_checks)
                if non_retrieval_checks
                else None
            ),
        },
    }

    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score MU eval run output")
    parser.add_argument("--run-file", required=True, help="Path to run file (JSON)")
    parser.add_argument("--out", help="Optional output JSON path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_file = Path(args.run_file)
    run_doc = json.loads(run_file.read_text())

    summary = compute_summary(run_doc, source_path=str(run_file))

    rendered = json.dumps(summary, indent=2) + "\n"
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
