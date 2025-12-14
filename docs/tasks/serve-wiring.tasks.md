# `mu serve` CLI Wiring - Task Breakdown

## Business Context

**Problem**: The `mu serve` command in the Rust CLI (`mu-cli`) is a stub that returns "not implemented", but the daemon functionality (`mu-daemon`) already exists as a complete library with HTTP server, MCP server, and file watcher capabilities.

**Outcome**: Users can start the MU daemon directly from the `mu` CLI with `mu serve` (HTTP mode) or `mu serve --mcp` (MCP mode for Claude Code integration).

**Users**: Developers using MU for code intelligence, AI assistants (Claude Code) that need MCP integration.

## Existing Patterns Found

| Pattern | File | Relevance |
|---------|------|-----------|
| CLI command structure | `mu-cli/src/commands/bootstrap.rs:209` | How async commands use mu_daemon library |
| Output formatting | `mu-cli/src/output/mod.rs:180-222` | `TableDisplay` trait + `Output::new()` pattern |
| Daemon state setup | `mu-daemon/src/main.rs:60-141` | How to initialize `AppState` with MUbase + Graph |
| HTTP server creation | `mu-daemon/src/server/http.rs:23-63` | `create_router(state)` returns Router |
| MCP server run | `mu-daemon/src/server/mcp.rs:16-62` | `mcp::run_stdio(state)` for MCP mode |
| File watcher | `mu-daemon/src/watcher/mod.rs:24-93` | `watch_directory(root, state)` spawned task |
| mu_daemon library exports | `mu-daemon/src/lib.rs:14-19` | `server`, `storage`, `build`, `watcher` modules |

## Architecture Decision

**Approach: Library Integration (NOT subprocess)**

The `mu-daemon` crate already exposes its functionality as a library via `lib.rs`. The `mu-cli` already has `mu-daemon = { workspace = true }` as a dependency. This enables direct integration without spawning a subprocess.

**Key Insight**: The pattern in `mu-daemon/src/main.rs` shows exactly how to:
1. Open/create MUbase database
2. Load graph into memory
3. Create `AppState` with all shared components
4. Start HTTP server OR MCP server based on `--mcp` flag
5. Optionally start file watcher

## Task Breakdown

### Task 1: Define ServeResult Output Struct

**File(s)**: `/Users/imu/Dev/work/mu/mu-cli/src/commands/serve.rs`

**Pattern**: Follow `BootstrapResult` in `/Users/imu/Dev/work/mu/mu-cli/src/commands/bootstrap.rs:22-35`

**Implementation**:
- Create `ServeResult` struct with fields:
  - `success: bool`
  - `mode: String` (http/mcp)
  - `port: Option<u16>` (only for HTTP)
  - `address: Option<String>` (listening address)
  - `root_path: String`
  - `mubase_path: String`
  - `node_count: usize`
  - `edge_count: usize`
  - `message: String`
- Implement `TableDisplay` trait with colored output
- Implement `to_mu()` for MU format

**Acceptance**:
- [x] `ServeResult` struct defined with Serialize derive
- [x] `TableDisplay` implemented with success/error colors
- [x] `to_mu()` returns valid MU format

**Status**: COMPLETE

---

### Task 2: Implement State Initialization Helper

**File(s)**: `/Users/imu/Dev/work/mu/mu-cli/src/commands/serve.rs`

**Pattern**: Follow `/Users/imu/Dev/work/mu/mu-daemon/src/main.rs:71-141`

**Implementation**:
- Create `async fn initialize_state(root: &Path) -> Result<(AppState, PathBuf, PathBuf)>`
- Handle mubase path resolution (new `.mu/mubase` vs legacy `.mubase`)
- Create `.mu/` directory if needed
- Open MUbase with `mu_daemon::storage::MUbase::open()`
- Load graph with `mubase.load_graph()`
- Create broadcast channel for events
- Create `ProjectManager`
- Return `AppState` plus root and mubase paths

**Acceptance**:
- [x] Function handles both new and legacy mubase paths
- [x] Creates `.mu/` directory if missing
- [x] Returns properly configured `AppState`
- [x] Error handling for missing database with helpful message

**Status**: COMPLETE

---

### Task 3: Implement `--status` Flag Handler

**File(s)**: `/Users/imu/Dev/work/mu/mu-cli/src/commands/serve.rs`

**Pattern**: Follow `/Users/imu/Dev/work/mu/mu-cli/src/commands/status.rs` for output

**Implementation**:
- Create `async fn run_status(format: OutputFormat) -> Result<()>`
- Check if daemon PID file exists at `.mu/daemon.pid`
- If exists, check if process is running
- Report running/stopped status with port info
- Show graph stats if running

**Acceptance**:
- [x] Detects daemon PID file
- [x] Verifies process is actually running
- [x] Shows helpful message if not running
- [x] Colored output for running (green) vs stopped (yellow)

**Status**: COMPLETE

---

### Task 4: Implement `--stop` Flag Handler

**File(s)**: `/Users/imu/Dev/work/mu/mu-cli/src/commands/serve.rs`

**Implementation**:
- Create `async fn run_stop(format: OutputFormat) -> Result<()>`
- Read PID from `.mu/daemon.pid`
- Send SIGTERM to process (Unix) or equivalent (Windows placeholder)
- Wait briefly for clean shutdown
- Remove PID file
- Report success/failure

**Acceptance**:
- [x] Reads PID from daemon.pid file
- [x] Sends graceful shutdown signal
- [x] Handles "not running" case gracefully
- [x] Cleans up PID file on success

**Status**: COMPLETE

---

### Task 5: Implement HTTP Server Mode (Foreground)

**File(s)**: `/Users/imu/Dev/work/mu/mu-cli/src/commands/serve.rs`

**Pattern**: Follow `/Users/imu/Dev/work/mu/mu-daemon/src/main.rs:168-176`

**Implementation**:
- Create `async fn run_http_foreground(port: u16, state: AppState, format: OutputFormat) -> Result<()>`
- Use `mu_daemon::server::create_router(state)` to get router
- Bind to `0.0.0.0:{port}` using `tokio::net::TcpListener`
- Optionally start file watcher in background task
- Print startup message with address
- Run server with `axum::serve(listener, router).await`

**Acceptance**:
- [x] Server starts on specified port
- [x] Prints listening address on startup
- [x] File watcher runs in background
- [x] Handles Ctrl+C gracefully

**Status**: COMPLETE

---

### Task 6: Implement MCP Server Mode

**File(s)**: `/Users/imu/Dev/work/mu/mu-cli/src/commands/serve.rs`

**Pattern**: Follow `/Users/imu/Dev/work/mu/mu-daemon/src/main.rs:164-167`

**Implementation**:
- Create `async fn run_mcp(state: AppState) -> Result<()>`
- Call `mu_daemon::server::mcp::run_stdio(state).await`
- No logging to stdout (MCP uses stdio for protocol)
- Log to stderr if verbose

**Acceptance**:
- [x] MCP server starts on stdio
- [x] No stdout pollution (only JSON-RPC messages)
- [x] Handles EOF gracefully
- [x] Compatible with Claude Code MCP integration

**Status**: COMPLETE

---

### Task 7: Wire Up Main `run()` Function

**File(s)**: `/Users/imu/Dev/work/mu/mu-cli/src/commands/serve.rs`

**Pattern**: Follow existing `run()` signature

**Implementation**:
- Handle mutually exclusive flags: `--status`, `--stop`, or serve
- For serve mode, determine foreground vs background (deferred)
- Call appropriate handler based on `--mcp` flag
- Use `initialize_state()` helper
- Format output appropriately

```rust
pub async fn run(
    port: u16,
    mcp: bool,
    foreground: bool,
    stop: bool,
    status: bool,
    format: OutputFormat,
) -> anyhow::Result<()> {
    // Handle status check
    if status {
        return run_status(format).await;
    }

    // Handle stop request
    if stop {
        return run_stop(format).await;
    }

    // Initialize state
    let root = std::env::current_dir()?;
    let (state, root_path, mubase_path) = initialize_state(&root).await?;

    // Start appropriate server
    if mcp {
        run_mcp(state).await
    } else {
        run_http_foreground(port, state, format).await
    }
}
```

**Acceptance**:
- [x] All flag combinations handled correctly
- [x] Status/stop work independently
- [x] HTTP mode starts on correct port
- [x] MCP mode starts on stdio
- [x] Errors have helpful messages

**Status**: COMPLETE

---

### Task 8: Add File Watcher Integration

**File(s)**: `/Users/imu/Dev/work/mu/mu-cli/src/commands/serve.rs`

**Pattern**: Follow `/Users/imu/Dev/work/mu/mu-daemon/src/main.rs:153-162`

**Implementation**:
- In HTTP mode, spawn file watcher as background task
- Use `mu_daemon::watcher::watch_directory(root, state).await`
- Handle watcher errors (log but don't crash)
- Skip watcher in MCP mode (per daemon pattern)

**Acceptance**:
- [x] File watcher starts in HTTP mode
- [x] Skipped in MCP mode
- [x] Errors logged but don't crash server
- [x] Hot reload works (<100ms incremental update goal)

**Status**: COMPLETE

---

## Implementation Summary

All tasks have been completed. The `mu serve` command is now fully implemented in `/Users/imu/Dev/work/mu/mu-cli/src/commands/serve.rs`.

**Key implementation details:**
- Uses mu-daemon library directly (no subprocess)
- State initialization follows mu-daemon/src/main.rs pattern exactly
- HTTP mode with file watcher runs on configurable port (default 9120)
- MCP mode runs on stdio with no stdout pollution
- PID file management for status/stop functionality
- Platform-specific process management (Unix libc, Windows tasklist/taskkill)
- Comprehensive error messages guiding users to recovery steps

**Dependencies added to mu-cli/Cargo.toml:**
- `axum = { version = "0.7", features = ["ws"] }`
- `libc = "0.2"` (Unix only via target cfg)

---

## Dependencies

```
Task 1 (Output struct)
    |
    v
Task 2 (State init) -----> Task 7 (Main run)
    |                           |
    +---> Task 5 (HTTP) --------+
    |                           |
    +---> Task 6 (MCP) ---------+
    |
    +---> Task 8 (Watcher)

Task 3 (--status) -----> Task 7 (independent)
Task 4 (--stop) -------> Task 7 (independent)
```

- Tasks 1-2 should be done first (foundation)
- Tasks 3-4 can be done in parallel (independent flags)
- Tasks 5-6 can be done in parallel (different modes)
- Task 7 integrates everything
- Task 8 enhances Task 5

## Edge Cases

1. **No mubase exists**: Show helpful message directing user to run `mu bootstrap` first
2. **Port already in use**: Catch bind error and suggest different port
3. **Daemon already running**: Detect via PID file, warn user
4. **Corrupted mubase**: Handle DuckDB errors gracefully
5. **Permission errors**: Clear error message for PID file / port binding

## Security Considerations

- HTTP server binds to `0.0.0.0` by default - document this
- PID file should be in project directory, not /tmp (project isolation)
- No secrets in daemon communication (local-only by default)

## Testing Notes

- HTTP mode can be tested with curl: `curl http://localhost:8432/health`
- MCP mode can be tested with JSON-RPC messages on stdin
- Watcher can be tested by modifying files and checking for graph updates

## Implementation Order (Recommended)

1. Task 1 - Output struct (30 min)
2. Task 2 - State initialization (1 hour)
3. Task 5 - HTTP foreground mode (1 hour)
4. Task 7 - Wire up main run() (30 min)
5. Task 6 - MCP mode (30 min)
6. Task 8 - File watcher (30 min)
7. Task 3 - Status flag (30 min)
8. Task 4 - Stop flag (30 min)

**Total estimated effort**: ~5 hours

## Out of Scope (Deferred)

- Background daemon mode (daemonization is complex, defer to Phase 2)
- Systemd/launchd integration
- Windows service support
- TLS/HTTPS support
- Authentication/authorization
