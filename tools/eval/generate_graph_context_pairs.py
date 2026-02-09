#!/usr/bin/env python3
"""Generate graph-context-augmented sigma training pairs.

This script takes existing sigma triplets (anchor/positive/negative symbols) and
adds neighborhood summaries extracted from each repo's MU graph.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import run_mu  # noqa: E402


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


@dataclass(frozen=True)
class NodeMeta:
    node_id: str
    node_type: str
    name: str
    file_path: str | None


@dataclass
class RepoGraphCache:
    nodes_by_name: dict[str, list[NodeMeta]]
    out_edges: dict[str, list[tuple[str, str, str]]]
    in_edges: dict[str, list[tuple[str, str, str]]]


def sql_escape(value: str) -> str:
    return value.replace("'", "''")


T = TypeVar("T")


def chunked(items: list[T], size: int) -> list[list[T]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def run_muql(mu_bin: str, project_root: Path, sql: str, timeout_s: int = 60) -> dict[str, Any]:
    proc = subprocess.run(
        [mu_bin, "q", sql, "--format", "json"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"mu q failed (exit {proc.returncode})\n"
            f"cwd={project_root}\n"
            f"sql={sql}\n"
            f"stderr={proc.stderr}\n"
            f"stdout={proc.stdout}\n"
        )
    return json.loads(proc.stdout)


def fetch_nodes(mu_bin: str, project_root: Path, names: list[str]) -> list[NodeMeta]:
    if not names:
        return []

    rows: list[NodeMeta] = []
    for chunk in chunked(sorted(set(names)), 200):
        in_sql = ", ".join(f"'{sql_escape(name.lower())}'" for name in chunk)
        sql = (
            "SELECT id, type, name, file_path "
            "FROM nodes "
            f"WHERE LOWER(name) IN ({in_sql})"
        )
        result = run_muql(mu_bin, project_root, sql)
        for row in result.get("rows", []):
            if not isinstance(row, list) or len(row) < 3:
                continue
            rows.append(
                NodeMeta(
                    node_id=str(row[0]),
                    node_type=str(row[1]),
                    name=str(row[2]),
                    file_path=str(row[3]) if len(row) > 3 and row[3] is not None else None,
                )
            )
    return rows


def fetch_edges(
    mu_bin: str,
    project_root: Path,
    node_ids: list[str],
) -> list[tuple[str, str, str, str, str]]:
    if not node_ids:
        return []

    edge_rows: list[tuple[str, str, str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    edge_types = "'calls','imports','contains','uses','inherits','references'"
    for chunk in chunked(node_ids, 200):
        in_sql = ", ".join(f"'{sql_escape(node_id)}'" for node_id in chunk)
        sql = (
            "SELECT e.source_id, e.target_id, e.type, s.name, t.name "
            "FROM edges e "
            "JOIN nodes s ON s.id = e.source_id "
            "JOIN nodes t ON t.id = e.target_id "
            f"WHERE e.type IN ({edge_types}) "
            f"AND (e.source_id IN ({in_sql}) OR e.target_id IN ({in_sql}))"
        )
        result = run_muql(mu_bin, project_root, sql)
        for row in result.get("rows", []):
            if not isinstance(row, list) or len(row) < 5:
                continue
            key = (str(row[0]), str(row[1]), str(row[2]))
            if key in seen:
                continue
            seen.add(key)
            edge_rows.append((str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4])))
    return edge_rows


def type_priority(node_type: str) -> int:
    order = {
        "function": 0,
        "class": 1,
        "module": 2,
        "doc": 3,
        "external": 4,
    }
    return order.get(node_type, 5)


def resolve_symbol(
    symbol: str,
    nodes_by_name: dict[str, list[NodeMeta]],
    out_edges: dict[str, list[tuple[str, str, str]]],
    in_edges: dict[str, list[tuple[str, str, str]]],
) -> NodeMeta | None:
    candidates = nodes_by_name.get(symbol.lower(), [])
    if not candidates:
        return None

    def score(node: NodeMeta) -> tuple[int, int]:
        degree = len(out_edges.get(node.node_id, [])) + len(in_edges.get(node.node_id, []))
        return (type_priority(node.node_type), -degree)

    return sorted(candidates, key=score)[0]


def summarize_node(
    node: NodeMeta | None,
    out_edges: dict[str, list[tuple[str, str, str]]],
    in_edges: dict[str, list[tuple[str, str, str]]],
    max_neighbors: int = 4,
) -> str:
    if node is None:
        return "symbol: unresolved"

    def collect(
        edges: list[tuple[str, str, str]],
        wanted: set[str],
        idx_name: int,
    ) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for edge in edges:
            if edge[1] not in wanted:
                continue
            name = edge[idx_name].strip()
            if not name or name in seen:
                continue
            seen.add(name)
            out.append(name)
            if len(out) >= max_neighbors:
                break
        return out

    out = out_edges.get(node.node_id, [])
    inn = in_edges.get(node.node_id, [])

    depends_on = collect(out, {"imports", "uses"}, 2)
    calls = collect(out, {"calls"}, 2)
    called_by = collect(inn, {"calls"}, 0)
    contains = collect(out, {"contains"}, 2)
    contained_in = collect(inn, {"contains"}, 0)

    lines = [
        f"symbol: {node.name}",
        f"type: {node.node_type}",
        f"file: {node.file_path or '(unknown)'}",
    ]
    if depends_on:
        lines.append("depends_on: " + ", ".join(depends_on))
    if calls:
        lines.append("calls: " + ", ".join(calls))
    if called_by:
        lines.append("called_by: " + ", ".join(called_by))
    if contains:
        lines.append("contains: " + ", ".join(contains))
    if contained_in:
        lines.append("contained_in: " + ", ".join(contained_in))
    return "\n".join(lines)


def enrich_symbol_text(symbol: str, summary: str) -> str:
    return f"{symbol}\n[graph_context]\n{summary}"


def build_repo_cache(
    mu_bin: str,
    repo_root: Path,
    symbol_names: list[str],
) -> RepoGraphCache:
    nodes = fetch_nodes(mu_bin, repo_root, symbol_names)
    nodes_by_name: dict[str, list[NodeMeta]] = defaultdict(list)
    for node in nodes:
        nodes_by_name[node.name.lower()].append(node)

    node_ids = [node.node_id for node in nodes]
    edges = fetch_edges(mu_bin, repo_root, node_ids)

    out_edges: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    in_edges: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for source_id, target_id, edge_type, source_name, target_name in edges:
        out_edges[source_id].append((source_name, edge_type, target_name))
        in_edges[target_id].append((source_name, edge_type, target_name))

    return RepoGraphCache(nodes_by_name=nodes_by_name, out_edges=out_edges, in_edges=in_edges)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate graph-context sigma training pairs")
    parser.add_argument(
        "--pairs",
        default="data/sigma/training/training_pairs.json",
        help="Path to baseline training pairs JSON",
    )
    parser.add_argument("--mu-bin", default="target/debug/mu")
    parser.add_argument("--sigma-mubase-dir", default="data/sigma/mubases")
    parser.add_argument("--sigma-workspace-root", default="/tmp/mu-eval-sigma")
    parser.add_argument(
        "--max-pairs",
        type=int,
        default=4000,
        help="Max number of pairs to process (deterministic sample)",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--out",
        default="data/sigma/training/training_pairs.graph.v1.json",
        help="Output JSON path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cwd = Path.cwd()

    pairs_path = Path(args.pairs).resolve()
    if not pairs_path.exists():
        raise SystemExit(f"Pairs file not found: {pairs_path}")

    mu_bin = str(Path(args.mu_bin).resolve())
    sigma_mubase_dir = Path(args.sigma_mubase_dir).resolve()
    sigma_workspace_root = Path(args.sigma_workspace_root).resolve()
    sigma_workspace_root.mkdir(parents=True, exist_ok=True)

    pairs: list[dict[str, Any]] = json.loads(pairs_path.read_text())
    if not isinstance(pairs, list):
        raise SystemExit("Expected pairs JSON to be a list")

    random.seed(args.seed)
    sample = pairs
    if args.max_pairs > 0 and len(pairs) > args.max_pairs:
        sample = random.sample(pairs, args.max_pairs)

    by_repo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sample:
        repo = row.get("source_repo")
        if isinstance(repo, str) and repo:
            by_repo[repo].append(row)

    generated_pairs: list[dict[str, Any]] = []
    pair_type_counts: Counter[str] = Counter()
    resolved_all = 0

    print(f"Generating graph-context pairs for {len(sample)} rows across {len(by_repo)} repos")

    for idx, (repo, rows) in enumerate(sorted(by_repo.items()), start=1):
        repo_root = run_mu.ensure_sigma_workspace(
            repo=repo,
            sigma_mubase_dir=sigma_mubase_dir,
            workspace_root=sigma_workspace_root,
        )
        symbols: list[str] = []
        for row in rows:
            for key in ("anchor", "positive", "negative"):
                value = row.get(key)
                if isinstance(value, str) and value:
                    symbols.append(value)
        cache = build_repo_cache(mu_bin, repo_root, symbols)

        for row in rows:
            anchor = str(row.get("anchor", ""))
            positive = str(row.get("positive", ""))
            negative = str(row.get("negative", ""))
            pair_type = str(row.get("pair_type", "unknown"))
            pair_type_counts[pair_type] += 1

            anchor_node = resolve_symbol(anchor, cache.nodes_by_name, cache.out_edges, cache.in_edges)
            positive_node = resolve_symbol(
                positive, cache.nodes_by_name, cache.out_edges, cache.in_edges
            )
            negative_node = resolve_symbol(
                negative, cache.nodes_by_name, cache.out_edges, cache.in_edges
            )

            anchor_summary = summarize_node(anchor_node, cache.out_edges, cache.in_edges)
            positive_summary = summarize_node(positive_node, cache.out_edges, cache.in_edges)
            negative_summary = summarize_node(negative_node, cache.out_edges, cache.in_edges)

            resolved_triplet = anchor_node is not None and positive_node is not None and negative_node is not None
            if resolved_triplet:
                resolved_all += 1

            generated_pairs.append(
                {
                    **row,
                    "anchor_text": anchor,
                    "positive_text": positive,
                    "negative_text": negative,
                    "anchor_text_graph": enrich_symbol_text(anchor, anchor_summary),
                    "positive_text_graph": enrich_symbol_text(positive, positive_summary),
                    "negative_text_graph": enrich_symbol_text(negative, negative_summary),
                    "graph_context": {
                        "anchor_node_id": anchor_node.node_id if anchor_node else None,
                        "positive_node_id": positive_node.node_id if positive_node else None,
                        "negative_node_id": negative_node.node_id if negative_node else None,
                        "resolved_triplet": resolved_triplet,
                    },
                }
            )

        print(
            f"[{idx}/{len(by_repo)}] {repo}: rows={len(rows)} nodes={sum(len(v) for v in cache.nodes_by_name.values())}"
        )

    out_doc = {
        "schema_version": "sigma_training_graph_context_v1",
        "generated_at": now_iso(),
        "git_commit": git_commit_short(cwd),
        "config": {
            "pairs_file": str(pairs_path),
            "mu_bin": mu_bin,
            "sigma_mubase_dir": str(sigma_mubase_dir),
            "sigma_workspace_root": str(sigma_workspace_root),
            "max_pairs": args.max_pairs,
            "seed": args.seed,
        },
        "summary": {
            "input_pairs": len(pairs),
            "processed_pairs": len(sample),
            "generated_pairs": len(generated_pairs),
            "resolved_triplet_count": resolved_all,
            "resolved_triplet_rate": (resolved_all / len(generated_pairs)) if generated_pairs else 0.0,
            "pair_type_counts": dict(sorted(pair_type_counts.items())),
        },
        "pairs": generated_pairs,
    }

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_doc, indent=2) + "\n")

    print(f"Wrote graph-context pairs: {out_path}")
    print(
        f"Resolved triplets: {resolved_all}/{len(generated_pairs)} "
        f"({out_doc['summary']['resolved_triplet_rate']:.3f})"
    )


if __name__ == "__main__":
    main()
