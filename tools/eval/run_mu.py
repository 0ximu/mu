#!/usr/bin/env python3
"""Run MU eval tasks and emit baseline artifacts."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import score  # noqa: E402


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def git_commit_short(cwd: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(cwd),
            text=True,
        )
        return out.strip()
    except Exception:
        return "unknown"


def sigma_repo_to_file(repo: str) -> str:
    return repo.replace("/", "__") + ".mubase"


def ensure_sigma_workspace(
    repo: str,
    sigma_mubase_dir: Path,
    workspace_root: Path,
) -> Path:
    mubase_name = sigma_repo_to_file(repo)
    mubase_source = sigma_mubase_dir / mubase_name
    if not mubase_source.exists():
        raise FileNotFoundError(f"Missing sigma MUbase: {mubase_source}")

    repo_root = workspace_root / repo.replace("/", "__")
    mu_dir = repo_root / ".mu"
    mu_dir.mkdir(parents=True, exist_ok=True)

    link_path = mu_dir / "mubase"
    if link_path.exists() or link_path.is_symlink():
        if link_path.is_symlink() and link_path.resolve() == mubase_source.resolve():
            return repo_root
        link_path.unlink()

    os.symlink(mubase_source.resolve(), link_path)
    return repo_root


def resolve_project_root(
    task: dict[str, Any],
    repo_roots: dict[str, str],
    workspace_root: Path,
    sigma_mubase_dir: Path,
    sigma_workspace_root: Path,
) -> Path:
    if task.get("repo") in repo_roots:
        return Path(repo_roots[task["repo"]]).resolve()

    source = task.get("repo_source", "local")
    if source == "sigma_mubase":
        root = ensure_sigma_workspace(task["repo"], sigma_mubase_dir, sigma_workspace_root)
        repo_roots[task["repo"]] = str(root)
        return root

    project_root = task.get("project_root", ".")
    root = (workspace_root / project_root).resolve()
    repo_roots[task.get("repo", project_root)] = str(root)
    return root


def build_command(mu_bin: str, task: dict[str, Any]) -> list[str]:
    tool = task.get("tool")
    params = task.get("params") or {}

    if tool == "search":
        query = task.get("query") or task.get("question")
        if not query:
            raise ValueError(f"Task {task.get('id')} is missing query")
        limit = str(params.get("limit", 10))
        threshold = str(params.get("threshold", 0.1))
        return [
            mu_bin,
            "search",
            query,
            "--limit",
            limit,
            "--threshold",
            threshold,
            "--format",
            "json",
        ]

    if tool == "grok":
        query = task.get("query") or task.get("question")
        if not query:
            raise ValueError(f"Task {task.get('id')} is missing query")
        depth = str(params.get("depth", 2))
        return [mu_bin, "grok", query, "--depth", depth, "--format", "json"]

    if tool == "impact":
        symbol = task.get("symbol")
        if not symbol:
            expected = task.get("expected_nodes") or []
            if expected:
                symbol = expected[0]
            else:
                raise ValueError(f"Task {task.get('id')} is missing symbol")
        return [mu_bin, "impact", symbol, "--format", "json"]

    if tool == "wtf":
        target = task.get("target")
        if not target:
            raise ValueError(f"Task {task.get('id')} is missing target")
        return [mu_bin, "wtf", target, "--format", "json"]

    if tool == "sus":
        path_arg = task.get("path", ".")
        threshold = str(task.get("threshold", 1))
        cmd = [mu_bin, "sus", path_arg, "--threshold", threshold, "--format", "json"]
        if task.get("include_generated"):
            cmd.append("--include-generated")
        return cmd

    if tool == "muql":
        query = task.get("query") or task.get("question")
        if not query:
            raise ValueError(f"Task {task.get('id')} is missing query")
        limit = int((task.get("params") or {}).get("limit", 10))
        sql = build_muql_from_question(query, limit=limit)
        return [mu_bin, "q", sql, "--format", "json"]

    raise ValueError(f"Unsupported tool '{tool}' in task {task.get('id')}")


def sql_escape(value: str) -> str:
    return value.replace("'", "''")


def build_muql_from_question(question: str, limit: int = 10) -> str:
    stopwords = {
        "what",
        "where",
        "when",
        "which",
        "who",
        "how",
        "does",
        "is",
        "are",
        "the",
        "a",
        "an",
        "in",
        "of",
        "to",
        "for",
        "and",
        "or",
        "with",
        "without",
        "that",
        "this",
        "these",
        "those",
        "between",
        "across",
        "from",
        "into",
        "used",
        "use",
        "implementation",
        "class",
        "function",
        "method",
        "module",
        "code",
    }

    words = re.findall(r"[A-Za-z_][A-Za-z0-9_\\-]*", question.lower())
    keywords = []
    for word in words:
        if len(word) < 4 or word in stopwords:
            continue
        cleaned = word.strip("_-")
        if cleaned and cleaned not in keywords:
            keywords.append(cleaned)
        if len(keywords) >= 6:
            break

    if not keywords:
        # Last-resort fallback to broad query if extraction failed.
        return (
            "SELECT id, type, name, file_path, line_start, line_end "
            f"FROM nodes LIMIT {max(1, int(limit))}"
        )

    clauses = [f"LOWER(name) LIKE '%{sql_escape(keyword)}%'" for keyword in keywords]
    score_expr = " + ".join(
        [
            f"(CASE WHEN LOWER(name) LIKE '%{sql_escape(keyword)}%' THEN 1 ELSE 0 END)"
            for keyword in keywords
        ]
    )
    where_sql = " OR ".join(clauses)
    safe_limit = max(1, int(limit))

    return (
        "SELECT id, type, name, file_path, line_start, line_end, complexity, "
        f"({score_expr}) AS score "
        "FROM nodes "
        f"WHERE {where_sql} "
        "ORDER BY score DESC, complexity DESC, name ASC "
        f"LIMIT {safe_limit}"
    )


def run_once(cmd: list[str], cwd: Path, timeout_s: int) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        duration_ms = (time.perf_counter() - start) * 1000.0

        status = "ok"
        error = None
        parsed_json = None

        if proc.returncode != 0:
            status = "command_error"
            error = f"exit={proc.returncode}"
        else:
            try:
                parsed_json = json.loads(proc.stdout)
            except json.JSONDecodeError as exc:
                status = "parse_error"
                error = f"json_decode_error: {exc}"

        return {
            "status": status,
            "duration_ms": duration_ms,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "return_code": proc.returncode,
            "error": error,
            "parsed_json": parsed_json,
        }

    except subprocess.TimeoutExpired as exc:
        duration_ms = (time.perf_counter() - start) * 1000.0
        return {
            "status": "timeout",
            "duration_ms": duration_ms,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "return_code": None,
            "error": f"timeout after {timeout_s}s",
            "parsed_json": None,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MU eval tasks")
    parser.add_argument(
        "--tasks",
        default="data/eval/tasks.v1.json",
        help="Tasks JSON file",
    )
    parser.add_argument(
        "--mu-bin",
        default="target/debug/mu",
        help="Path to MU CLI binary",
    )
    parser.add_argument(
        "--results-root",
        default="data/eval/results",
        help="Root output directory",
    )
    parser.add_argument(
        "--workspace-root",
        default=".",
        help="Workspace root used for local tasks",
    )
    parser.add_argument(
        "--sigma-mubase-dir",
        default="data/sigma/mubases",
        help="Directory containing sigma *.mubase files",
    )
    parser.add_argument(
        "--sigma-workspace-root",
        default="/tmp/mu-eval-sigma",
        help="Temp directory where sigma task workspaces are created",
    )
    parser.add_argument("--runs", type=int, default=3, help="Runs per task")
    parser.add_argument(
        "--retries",
        type=int,
        default=1,
        help="Retries after a failed attempt",
    )
    parser.add_argument(
        "--timeout-s",
        type=int,
        default=25,
        help="Per-task timeout in seconds",
    )
    parser.add_argument(
        "--sample",
        type=int,
        help="Optional: run only the first N tasks",
    )
    parser.add_argument(
        "--run-file",
        help="Optional explicit run output file path",
    )
    parser.add_argument(
        "--summary-file",
        help="Optional explicit summary output file path",
    )
    parser.add_argument(
        "--name",
        default="mu_baseline",
        help="Output artifact base name",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    workspace_root = Path(args.workspace_root).resolve()
    tasks_path = Path(args.tasks).resolve()
    mu_bin = str(Path(args.mu_bin).resolve())
    sigma_mubase_dir = Path(args.sigma_mubase_dir).resolve()
    sigma_workspace_root = Path(args.sigma_workspace_root).resolve()
    sigma_workspace_root.mkdir(parents=True, exist_ok=True)

    task_doc = json.loads(tasks_path.read_text())
    tasks = list(task_doc.get("tasks", []))
    if args.sample is not None:
        tasks = tasks[: args.sample]

    commit = git_commit_short(workspace_root)
    result_dir = Path(args.results_root).resolve() / commit
    result_dir.mkdir(parents=True, exist_ok=True)

    run_file = (
        Path(args.run_file).resolve()
        if args.run_file
        else result_dir / f"{args.name}.raw.json"
    )
    summary_file = (
        Path(args.summary_file).resolve()
        if args.summary_file
        else result_dir / f"{args.name}.json"
    )

    repo_roots: dict[str, str] = {}
    run_results: list[dict[str, Any]] = []

    print(
        f"Running {len(tasks)} tasks x {args.runs} runs (retries={args.retries}, timeout={args.timeout_s}s)"
    )

    for idx, task in enumerate(tasks, start=1):
        task_id = task.get("id", f"task-{idx}")
        try:
            project_root = resolve_project_root(
                task,
                repo_roots,
                workspace_root,
                sigma_mubase_dir,
                sigma_workspace_root,
            )
            command = build_command(mu_bin, task)
        except Exception as exc:
            run_results.append(
                {
                    "task_id": task_id,
                    "repo": task.get("repo"),
                    "category": task.get("category"),
                    "tool": task.get("tool"),
                    "expected_nodes": task.get("expected_nodes", []),
                    "expected_fields": task.get("expected_fields", []),
                    "project_root": None,
                    "run_results": [
                        {
                            "run_index": 1,
                            "status": "setup_error",
                            "error": str(exc),
                            "duration_ms": 0.0,
                            "stdout": "",
                            "stderr": "",
                            "parsed_json": None,
                            "return_code": None,
                            "attempts": [],
                        }
                    ],
                }
            )
            print(f"[{idx}/{len(tasks)}] {task_id}: setup_error ({exc})")
            continue

        task_runs: list[dict[str, Any]] = []
        for run_index in range(1, args.runs + 1):
            attempts: list[dict[str, Any]] = []
            final_result: dict[str, Any] | None = None

            timeout_s = int(task.get("timeout_s", args.timeout_s))
            for _ in range(args.retries + 1):
                result = run_once(command, project_root, timeout_s)
                attempts.append(
                    {
                        "status": result["status"],
                        "error": result.get("error"),
                        "duration_ms": result.get("duration_ms"),
                        "return_code": result.get("return_code"),
                    }
                )
                final_result = result
                if result["status"] == "ok":
                    break

            assert final_result is not None
            final_result["run_index"] = run_index
            final_result["attempts"] = attempts
            task_runs.append(final_result)

        run_results.append(
            {
                "task_id": task_id,
                "repo": task.get("repo"),
                "category": task.get("category"),
                "tool": task.get("tool"),
                "expected_nodes": task.get("expected_nodes", []),
                "expected_fields": task.get("expected_fields", []),
                "project_root": str(project_root),
                "command": command,
                "run_results": task_runs,
            }
        )

        ok_runs = sum(1 for run in task_runs if run.get("status") == "ok")
        print(f"[{idx}/{len(tasks)}] {task_id}: ok_runs={ok_runs}/{args.runs}")

    run_doc = {
        "schema_version": "mu_eval_run_v1",
        "generated_at": now_iso(),
        "git_commit": commit,
        "config": {
            "tasks_file": str(tasks_path),
            "mu_bin": mu_bin,
            "runs": args.runs,
            "retries": args.retries,
            "timeout_s": args.timeout_s,
            "sigma_mubase_dir": str(sigma_mubase_dir),
            "sigma_workspace_root": str(sigma_workspace_root),
            "name": args.name,
        },
        "results": run_results,
    }

    run_file.parent.mkdir(parents=True, exist_ok=True)
    run_file.write_text(json.dumps(run_doc, indent=2) + "\n")

    summary = score.compute_summary(run_doc, source_path=str(run_file))
    summary_file.parent.mkdir(parents=True, exist_ok=True)
    summary_file.write_text(json.dumps(summary, indent=2) + "\n")

    print(f"Wrote run file: {run_file}")
    print(f"Wrote summary: {summary_file}")

    metrics = summary.get("metrics", {})
    print("Metrics:")
    print(f"  recall_at_1: {metrics.get('recall_at_1')}")
    print(f"  recall_at_5: {metrics.get('recall_at_5')}")
    print(f"  first_correct_rank: {metrics.get('first_correct_rank')}")
    print(f"  artifact_noise_ratio: {metrics.get('artifact_noise_ratio')}")
    print(f"  p50_latency_ms: {metrics.get('p50_latency_ms')}")
    print(f"  p95_latency_ms: {metrics.get('p95_latency_ms')}")
    print(f"  avg_output_tokens: {metrics.get('avg_output_tokens')}")


if __name__ == "__main__":
    main()
