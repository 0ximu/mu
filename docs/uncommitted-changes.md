# Uncommitted change log — 2025-12-07

## Tooling, docs, and workflows
- `.claude/CLAUDE.md`, `CLAUDE.md`: rewrote the “Essential Commands” section to mandate running every CLI and dev command through `uv run`, covering install, test, lint, cache, search, and daemon actions so sandboxes always use the curated virtualenv.
- `.github/workflows/build-binary.yml`, `.github/workflows/ci.yml`, `.github/workflows/publish.yml`: replaced ad-hoc `pip` bootstrap steps with `astral-sh/setup-uv` plus `uv sync`, and ensured build/test stages execute through `uv run pyinstaller` or `uv run pytest` for parity with local workflows.
- `README.md`: made `uv sync` the primary install path, updated pytest/mypy/ruff examples to `uv run …`, and retained legacy pip instructions as an alternative.
- `pyproject.toml`: defined a `[dependency-groups] dev` bundle plus `[tool.uv]` defaults so `uv sync` only pulls dev tooling by default, and declared the local `mu-core` source for the `rust` optional dependency; generated the first `uv.lock` to pin every resolver output.

## Rust core and daemon
- `mu-core/Cargo.toml`: renamed the lib crate to `mu_core`, compiled it as both `cdylib` and `rlib`, and made the PyO3 extension-module feature optional so the crate can link into pure-Rust binaries.
- `mu-core/src/scanner.rs`: refactored `scan_directory_internal` to return `Result<ScanResult, String>` and let the Python wrapper translate IO errors into `PyFileNotFoundError`, enabling reuse from the Rust daemon.
- New `mu-daemon/` crate: end-to-end Rust daemon (`mu-daemon/src/main.rs`) with CLI flags (`--port`, `--mcp`, `--no-watch`, etc.), HTTP + MCP servers (`server/`), DuckDB-backed storage layer (`storage/`), build pipeline that reuses `mu-core` scanners/parsers for full and incremental graph builds (`build/pipeline.rs`), MUQL execution engine (`muql/`), semantic context extractor (`context/`), and filesystem watcher for live graph refreshes (`watcher/`). Ships with its own `Cargo.toml`/`Cargo.lock`.

## Python agent
- `src/mu/agent/providers.py` (new): introduced a provider abstraction that normalizes Anthropic and OpenAI calls into a shared `LLMResponse`, maps MU tools onto each API’s schema, and handles assistant/tool result bridging.
- `src/mu/agent/models.py`, `src/mu/agent/cli.py`: default model switched to `gpt-5-nano-2025-08-07`, CLI help text updated accordingly.
- `src/mu/agent/core.py`: replaced direct Anthropic dependency with the provider abstraction, plumbed provider-specific tool call formatting, enforced a single-tool strategy (one retry if necessary), and unified error handling/token tracking.
- `src/mu/agent/prompt.py`: rewrote the system prompt + examples to explicitly enforce “one tool call then answer”, steering the agent toward the right MU tool for each question archetype.

