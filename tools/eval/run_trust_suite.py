#!/usr/bin/env python3
"""Run MCP trust regression suite for phase-1 fixes."""

from __future__ import annotations

import argparse
import json
import os
import select
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


def run_cmd(cmd: list[str], cwd: Path, timeout_s: int = 120) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(cmd)}\n"
            f"cwd: {cwd}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    return proc


class McpJsonlClient:
    def __init__(self, mu_bin: str, project_root: Path):
        self.mu_bin = mu_bin
        self.project_root = project_root
        self.proc: subprocess.Popen[str] | None = None
        self._buffer = ""
        self._next_id = 1

    def __enter__(self) -> "McpJsonlClient":
        self.proc = subprocess.Popen(
            [self.mu_bin, "mcp", str(self.project_root)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._initialize()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def _send(self, message: dict[str, Any]) -> None:
        assert self.proc is not None and self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def _read_message(self, timeout_s: float = 8.0) -> dict[str, Any]:
        assert self.proc is not None and self.proc.stdout is not None and self.proc.stderr is not None
        stdout_fd = self.proc.stdout.fileno()
        stderr_fd = self.proc.stderr.fileno()

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            remaining = max(0.01, deadline - time.time())
            ready, _, _ = select.select([stdout_fd, stderr_fd], [], [], min(0.2, remaining))
            for fd in ready:
                chunk = os.read(fd, 8192)
                if not chunk:
                    continue
                text = chunk.decode("utf-8", errors="replace")
                if fd == stderr_fd:
                    # Keep stderr non-blocking for diagnostics if the process fails.
                    continue

                self._buffer += text
                while "\n" in self._buffer:
                    line, self._buffer = self._buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        return json.loads(line)
                    except json.JSONDecodeError:
                        continue

        raise TimeoutError("Timed out waiting for MCP response")

    def _request(self, method: str, params: dict[str, Any], timeout_s: float = 8.0) -> dict[str, Any]:
        req_id = self._next_id
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            msg = self._read_message(timeout_s=max(0.1, deadline - time.time()))
            if msg.get("id") == req_id:
                return msg
        raise TimeoutError(f"Timed out waiting for response id={req_id}")

    def _initialize(self) -> None:
        init = self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mu-trust-suite", "version": "0.1"},
            },
            timeout_s=10.0,
        )
        if "error" in init:
            raise RuntimeError(f"MCP initialize failed: {init['error']}")
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        resp = self._request("tools/call", {"name": name, "arguments": arguments}, timeout_s=20.0)
        if "error" in resp:
            raise RuntimeError(f"MCP tools/call error: {resp['error']}")
        result = resp.get("result", {})
        content = result.get("content", [])
        text = ""
        if content and isinstance(content, list):
            first = content[0]
            if isinstance(first, dict):
                text = first.get("text", "")
        return {
            "is_error": bool(result.get("isError", False)),
            "text": text,
            "raw": result,
        }


@dataclass
class Assertion:
    label: str
    passed: bool
    details: str


def assert_contains(text: str, needle: str) -> Assertion:
    ok = needle in text
    return Assertion(f"contains:{needle}", ok, "" if ok else f"missing '{needle}'")


def assert_not_contains(text: str, needle: str) -> Assertion:
    ok = needle not in text
    return Assertion(f"not_contains:{needle}", ok, "" if ok else f"unexpected '{needle}'")


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def bootstrap_repo(mu_bin: str, root: Path) -> None:
    run_cmd(
        [mu_bin, "bootstrap", ".", "--force", "--no-embed", "--no-hnsw", "--strict", "--format", "json"],
        cwd=root,
        timeout_s=180,
    )


def setup_impact_repo(mu_bin: str, root: Path) -> None:
    write_file(root / "src" / "service.py", "class TransactionService:\n    pass\n\nref = TransactionService\n")
    write_file(root / "coverage" / "report.py", "TransactionService\n")
    write_file(root / "dist" / "bundle.js", "const x = 'TransactionService';\n")
    write_file(root / "build" / "generated.py", "TransactionService\n")
    write_file(root / "node_modules" / "pkg" / "index.js", "TransactionService\n")
    write_file(root / "custom" / "ignored.py", "TransactionService\n")
    write_file(root / "ignored_artifact.py", "TransactionService\n")
    write_file(root / ".gitignore", "ignored_artifact.py\n")
    write_file(
        root / ".murc.toml",
        """[impact]
exclude = ["custom/**", ".mu/**"]
respect_gitignore = true
""",
    )
    run_cmd(["git", "init"], cwd=root)
    bootstrap_repo(mu_bin, root)


def setup_nested_git_repo(mu_bin: str, root: Path) -> None:
    gateway = root / "gateway"
    write_file(gateway / "src" / "main.py", "def handler():\n    return 42\n")

    run_cmd(["git", "init"], cwd=gateway)
    run_cmd(["git", "add", "."], cwd=gateway)
    run_cmd(
        [
            "git",
            "-c",
            "user.name=MU Trust",
            "-c",
            "user.email=trust@example.com",
            "commit",
            "-m",
            "init",
        ],
        cwd=gateway,
    )

    bootstrap_repo(mu_bin, root)


def setup_sus_repo(mu_bin: str, root: Path) -> None:
    write_file(
        root / "src" / "real.py",
        """def process(value):
    total = 0
    if value > 0:
        for i in range(value):
            if i % 2 == 0:
                total += i
            else:
                total -= i
    else:
        while value < 0:
            total += value
            value += 1
    return total
""",
    )
    write_file(
        root / "src" / "generated.generated.py",
        """def generated_calc(items):
    acc = 0
    for item in items:
        if item > 0:
            acc += item
        else:
            acc -= item
    return acc
""",
    )
    bootstrap_repo(mu_bin, root)


def setup_find_repo(mu_bin: str, root: Path) -> None:
    write_file(
        root / "src" / "TransactionService.py",
        """class TransactionService:
    def execute(self):
        return True
""",
    )
    bootstrap_repo(mu_bin, root)


def run_case_impact(mu_bin: str, root: Path) -> dict[str, Any]:
    setup_impact_repo(mu_bin, root)
    with McpJsonlClient(mu_bin, root) as client:
        response = client.call_tool("mu_impact", {"symbol": "TransactionService"})

    text = response["text"]
    assertions = [
        assert_contains(text, "src/service.py"),
        assert_not_contains(text, "coverage/report.py"),
        assert_not_contains(text, "dist/bundle.js"),
        assert_not_contains(text, "build/generated.py"),
        assert_not_contains(text, "node_modules/pkg/index.js"),
        assert_not_contains(text, "custom/ignored.py"),
        assert_not_contains(text, "ignored_artifact.py"),
    ]
    return case_result("impact_filters_artifacts", assertions, response)


def run_case_wtf(mu_bin: str, root: Path) -> dict[str, Any]:
    setup_nested_git_repo(mu_bin, root)
    with McpJsonlClient(mu_bin, root) as client:
        response = client.call_tool("mu_wtf", {"file": "gateway/src/main.py"})

    text = response["text"]
    gateway_root = str((root / "gateway").resolve())
    assertions = [
        assert_contains(text, f"Git root: {gateway_root}"),
        assert_contains(text, "Git tracked: Yes"),
        assert_not_contains(text, "No git repository for file path"),
    ]
    return case_result("wtf_nested_git_root", assertions, response)


def run_case_sus(mu_bin: str, root: Path) -> dict[str, Any]:
    setup_sus_repo(mu_bin, root)
    with McpJsonlClient(mu_bin, root) as client:
        default_resp = client.call_tool("mu_sus", {"min_complexity": 1})
        include_resp = client.call_tool("mu_sus", {"min_complexity": 1, "include_generated": True})

    default_text = default_resp["text"]
    include_text = include_resp["text"]

    assertions = [
        assert_contains(default_text, "src/real.py"),
        assert_not_contains(default_text, "src/generated.generated.py"),
        assert_contains(include_text, "src/generated.generated.py"),
    ]
    return case_result(
        "sus_generated_default_excluded",
        assertions,
        {
            "default": default_resp,
            "include_generated": include_resp,
        },
    )


def run_case_find(mu_bin: str, root: Path) -> dict[str, Any]:
    setup_find_repo(mu_bin, root)
    with McpJsonlClient(mu_bin, root) as client:
        response = client.call_tool("mu_find", {"symbol": "TransactionService"})

    text = response["text"]
    assertions = [
        assert_contains(text, "$TransactionService [class]"),
        assert_not_contains(text, "[module]"),
        assert_not_contains(text, ":1-0"),
    ]
    return case_result("find_module_suppression_and_invalid_range", assertions, response)


def case_result(case_id: str, assertions: list[Assertion], response: Any) -> dict[str, Any]:
    passed = all(assertion.passed for assertion in assertions)
    return {
        "id": case_id,
        "passed": passed,
        "assertions": [
            {
                "label": assertion.label,
                "passed": assertion.passed,
                "details": assertion.details,
            }
            for assertion in assertions
        ],
        "response": response,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MCP trust regression suite")
    parser.add_argument("--mu-bin", default="target/debug/mu")
    parser.add_argument("--workspace", default="/tmp/mu-trust-suite")
    parser.add_argument("--results-root", default="data/eval/results")
    parser.add_argument("--name", default="trust_suite_post_phase1")
    parser.add_argument(
        "--run-file",
        help="Optional explicit output JSON path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    cwd = Path.cwd()
    mu_bin = str(Path(args.mu_bin).resolve())
    workspace = Path(args.workspace).resolve()
    commit = git_commit_short(cwd)

    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    start = time.perf_counter()
    results: list[dict[str, Any]] = []

    cases = [
        ("impact_filters_artifacts", run_case_impact),
        ("wtf_nested_git_root", run_case_wtf),
        ("sus_generated_default_excluded", run_case_sus),
        ("find_module_suppression_and_invalid_range", run_case_find),
    ]

    for case_id, runner in cases:
        case_root = workspace / case_id
        case_root.mkdir(parents=True, exist_ok=True)
        try:
            result = runner(mu_bin, case_root)
        except Exception as exc:
            result = {
                "id": case_id,
                "passed": False,
                "assertions": [
                    {
                        "label": "runner_exception",
                        "passed": False,
                        "details": str(exc),
                    }
                ],
                "response": None,
            }
        results.append(result)
        print(f"{case_id}: {'PASS' if result['passed'] else 'FAIL'}")

    duration_ms = (time.perf_counter() - start) * 1000.0
    passed_count = sum(1 for result in results if result.get("passed"))

    doc = {
        "schema_version": "trust_suite_result_v1",
        "generated_at": now_iso(),
        "git_commit": commit,
        "mu_bin": mu_bin,
        "workspace": str(workspace),
        "duration_ms": duration_ms,
        "summary": {
            "total_cases": len(results),
            "passed_cases": passed_count,
            "failed_cases": len(results) - passed_count,
            "pass_rate": (passed_count / len(results)) if results else 0.0,
        },
        "results": results,
    }

    out_file = (
        Path(args.run_file).resolve()
        if args.run_file
        else Path(args.results_root).resolve() / commit / f"{args.name}.json"
    )
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(doc, indent=2) + "\n")

    print(f"Wrote trust suite result: {out_file}")
    print(
        f"Summary: {passed_count}/{len(results)} passed"
    )

    if passed_count != len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
