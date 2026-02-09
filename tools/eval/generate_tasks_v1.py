#!/usr/bin/env python3
"""Generate data/eval/tasks.v1.json from sigma QA pairs + local MU tasks."""

from __future__ import annotations

import json
from pathlib import Path

SELECTED_SIGMA_FILES = [
    "TanStack__query.json",
    "openai__whisper.json",
    "pallets__flask.json",
    "psf__requests.json",
    "fastapi__fastapi.json",
    "vuejs__vue.json",
    "reduxjs__redux.json",
    "pydantic__pydantic.json",
]

CATEGORY_CYCLE = [
    "exact_lookup",
    "flow_understanding",
    "impact_analysis",
    "task_planning",
]


def build_sigma_tasks(root: Path) -> list[dict]:
    tasks: list[dict] = []

    for file_name in SELECTED_SIGMA_FILES:
        records = json.loads((root / file_name).read_text())
        accepted = [
            row
            for row in records
            if row.get("validation_status") == "accepted" and row.get("valid_nodes")
        ]
        accepted = sorted(accepted, key=lambda row: row["question"].lower())

        for idx, row in enumerate(accepted[:8], start=1):
            category = CATEGORY_CYCLE[(idx - 1) % len(CATEGORY_CYCLE)]
            tasks.append(
                {
                    "id": f"sigma-{row['repo_name'].replace('/', '__')}-{idx:02d}",
                    "repo": row["repo_name"],
                    "repo_source": "sigma_mubase",
                    "category": category,
                    "tool": "muql",
                    "query": row["question"],
                    "expected_nodes": row.get("valid_nodes", [])[:8],
                    "notes": row.get("reasoning", "")[:220],
                    "timeout_s": 20,
                    "params": {"limit": 10, "threshold": 0.1, "depth": 2},
                }
            )

    return tasks


def build_local_tasks() -> list[dict]:
    return [
        {
            "id": "mu-local-01",
            "repo": "mu",
            "repo_source": "local",
            "project_root": ".",
            "category": "exact_lookup",
            "tool": "search",
            "query": "MuConfig",
            "expected_nodes": ["MuConfig"],
            "timeout_s": 20,
            "params": {"limit": 10, "threshold": 0.1},
        },
        {
            "id": "mu-local-02",
            "repo": "mu",
            "repo_source": "local",
            "project_root": ".",
            "category": "flow_understanding",
            "tool": "grok",
            "query": "How is MU configuration loaded and merged",
            "expected_nodes": ["MuConfig", "load", "load_strict"],
            "timeout_s": 20,
            "params": {"depth": 2},
        },
        {
            "id": "mu-local-03",
            "repo": "mu",
            "repo_source": "local",
            "project_root": ".",
            "category": "impact_analysis",
            "tool": "impact",
            "symbol": "MuConfig",
            "expected_nodes": ["load", "load_strict", "ignore_patterns"],
            "timeout_s": 20,
            "params": {},
        },
        {
            "id": "mu-local-04",
            "repo": "mu",
            "repo_source": "local",
            "project_root": ".",
            "category": "task_planning",
            "tool": "grok",
            "query": "What code paths should be changed to add a new MCP tool parameter",
            "expected_nodes": ["MuMcpServer", "GrokParams", "MuConfig"],
            "timeout_s": 20,
            "params": {"depth": 2},
        },
        {
            "id": "mu-local-05",
            "repo": "mu",
            "repo_source": "local",
            "project_root": ".",
            "category": "git_archaeology",
            "tool": "wtf",
            "target": "mu-cli/src/config.rs",
            "expected_fields": ["origin_commit", "contributors", "evolution_summary"],
            "timeout_s": 20,
            "params": {},
        },
        {
            "id": "mu-local-06",
            "repo": "mu",
            "repo_source": "local",
            "project_root": ".",
            "category": "git_archaeology",
            "tool": "wtf",
            "target": "mu-cli/src/commands/mcp/server.rs",
            "expected_fields": ["origin_commit", "contributors", "evolution_summary"],
            "timeout_s": 20,
            "params": {},
        },
        {
            "id": "mu-local-07",
            "repo": "mu",
            "repo_source": "local",
            "project_root": ".",
            "category": "quality_security_scan_relevance",
            "tool": "sus",
            "path": ".",
            "threshold": 1,
            "expected_fields": ["results", "suspicious_count"],
            "timeout_s": 20,
            "params": {},
        },
        {
            "id": "mu-local-08",
            "repo": "mu",
            "repo_source": "local",
            "project_root": ".",
            "category": "quality_security_scan_relevance",
            "tool": "sus",
            "path": ".",
            "threshold": 2,
            "expected_fields": ["results", "suspicious_count"],
            "timeout_s": 20,
            "params": {},
        },
    ]


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    sigma_root = repo_root / "data" / "sigma" / "qa_pairs"

    tasks = build_sigma_tasks(sigma_root)
    tasks.extend(build_local_tasks())

    doc = {
        "schema_version": "tasks.v1",
        "description": "MU eval dataset: 72 tasks across 9 repos (8 sigma + local mu)",
        "categories": [
            "exact_lookup",
            "flow_understanding",
            "impact_analysis",
            "task_planning",
            "git_archaeology",
            "quality_security_scan_relevance",
        ],
        "task_count": len(tasks),
        "repos": sorted({task["repo"] for task in tasks}),
        "tasks": tasks,
    }

    out_path = repo_root / "data" / "eval" / "tasks.v1.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"Wrote {out_path} ({len(tasks)} tasks)")

    sigma_tasks = [task for task in tasks if task.get("repo_source") == "sigma_mubase"]
    sigma_doc = {
        "schema_version": "tasks.v1",
        "description": "MU eval dataset (sigma-only slice for cross-ref comparisons)",
        "categories": doc["categories"],
        "task_count": len(sigma_tasks),
        "repos": sorted({task["repo"] for task in sigma_tasks}),
        "tasks": sigma_tasks,
    }
    sigma_out = repo_root / "data" / "eval" / "tasks.sigma.v1.json"
    sigma_out.write_text(json.dumps(sigma_doc, indent=2) + "\n")
    print(f"Wrote {sigma_out} ({len(sigma_tasks)} tasks)")


if __name__ == "__main__":
    main()
