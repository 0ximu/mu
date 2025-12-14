# MU Rust Native: Product Requirements Document

**Version:** 1.0
**Date:** 2024-12-12
**Author:** Claude + Yavor
**Status:** Draft

---

## Executive Summary

MU (Machine Understanding) is a semantic compression tool that translates codebases into token-efficient representations for LLM comprehension. Currently implemented as a Python CLI with Rust performance extensions, this PRD defines the path to a **pure Rust implementation** that delivers:

- **20x faster startup** (2s → 0.1s)
- **10x smaller memory footprint** (200MB → 20MB)
- **Single binary distribution** (no Python, no dependencies)
- **Embedded code-trained embedding model** (mu-sigma-v2)

**Codename:** Project Divine

---

## Problem Statement

### Current Pain Points

| Issue | Impact | Root Cause |
|-------|--------|------------|
| 2s startup time | Every command feels sluggish | Python interpreter + import chain |
| 350MB distribution | Slow downloads, storage concerns | PyInstaller + PyTorch + dependencies |
| Complex installation | User friction, support burden | Python version requirements, venv, pip |
| Model configuration | Users get wrong embeddings | Fallback to generic model instead of mu-sigma |
| Memory bloat | Daemon can't stay resident | Python baseline memory overhead |

### User Feedback

> "I love the tool but waiting 2 seconds for `mu status` is painful"

> "Can't I just download a binary?"

> "Why do I need Python 3.11?"

---

## Vision

**One binary. Instant startup. Zero configuration.**

```bash
# Installation
curl -sSL https://mu.dev/install | sh

# Usage (all commands < 200ms)
mu bootstrap                    # Index codebase
mu search "authentication"      # Semantic search
mu grok "how does auth work"    # Extract context
mu yolo AuthService            # Impact analysis
mu serve                        # Start daemon
```

The mu-sigma embedding model is bundled. No downloads, no configuration, no "which model?" confusion.

---

## Goals & Non-Goals

### Goals

1. **G1: Instant CLI** - All commands complete in <200ms (excluding network/disk I/O)
2. **G2: Single Binary** - One executable, all platforms, no runtime dependencies
3. **G3: Embedded Intelligence** - mu-sigma-v2 model bundled, semantic search works out-of-box
4. **G4: Feature Parity** - All existing mu commands work identically
5. **G5: Native MCP** - MCP server in Rust, same protocol, faster response

### Non-Goals

- N1: GPU inference (CPU is fast enough for our use case)
- N2: Training new models (separate tooling, Python is fine)
- N3: Breaking API changes (existing .mubase files remain compatible)
- N4: Windows ARM support (initial release: x64 only)

---

## Success Metrics

| Metric | Current | Target | Method |
|--------|---------|--------|--------|
| Cold start time | 2.0s | 0.15s | `time mu status` |
| Binary size | 350MB | 150MB | `ls -la mu` |
| Memory (idle daemon) | 180MB | 25MB | `ps aux` RSS |
| Installation time | 5min | 30s | End-to-end timing |
| `mu search` latency | 1.9s | 0.2s | Benchmark suite |
| `mu grok` latency | 2.5s | 0.3s | Benchmark suite |

---

## Architecture

### Current Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     mu (Python CLI)                         │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐   │
│  │    Click    │ │    Rich     │ │ sentence-transformers│   │
│  │   (CLI)     │ │  (output)   │ │   (embeddings)      │   │
│  └──────┬──────┘ └──────┬──────┘ └──────────┬──────────┘   │
│         │               │                    │              │
│         └───────────────┼────────────────────┘              │
│                         │                                   │
│                         ▼                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              mu-core (_core.abi3.so)                 │   │
│  │   Scanner │ Parser │ Graph │ Differ │ Incremental   │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌──────────┐   ┌───────────┐   ┌───────────┐
        │ .mubase  │   │ mu-daemon │   │  DuckDB   │
        │ (graph)  │   │  (Rust)   │   │           │
        └──────────┘   └───────────┘   └───────────┘
```

### Target Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      mu (Rust Binary)                       │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                    mu-cli (clap)                     │   │
│  │   Commands │ Output │ Config │ Progress │ Colors    │   │
│  └──────────────────────┬──────────────────────────────┘   │
│                         │                                   │
│  ┌──────────────────────┼──────────────────────────────┐   │
│  │                  mu-core (lib)                       │   │
│  │   Scanner │ Parser │ Graph │ Differ │ Incremental   │   │
│  └──────────────────────┬──────────────────────────────┘   │
│                         │                                   │
│  ┌──────────────────────┼──────────────────────────────┐   │
│  │               mu-embeddings (candle)                 │   │
│  │   Model Loading │ Tokenizer │ Inference │ Pooling   │   │
│  │            [mu-sigma-v2 weights embedded]            │   │
│  └──────────────────────┬──────────────────────────────┘   │
│                         │                                   │
│  ┌──────────────────────┼──────────────────────────────┐   │
│  │                mu-server (axum)                      │   │
│  │   HTTP API │ WebSocket │ MCP Protocol │ File Watch  │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                        ┌──────────┐
                        │ .mubase  │
                        │ (DuckDB) │
                        └──────────┘
```

### Crate Structure

```
mu/
├── Cargo.toml              # Workspace root
├── mu-cli/                 # Binary crate
│   ├── Cargo.toml
│   └── src/
│       ├── main.rs         # Entry point
│       ├── commands/       # CLI commands (clap)
│       │   ├── mod.rs
│       │   ├── bootstrap.rs
│       │   ├── search.rs
│       │   ├── grok.rs
│       │   ├── deps.rs
│       │   ├── query.rs
│       │   └── vibes.rs    # yolo, sus, wtf, etc.
│       ├── output/         # Terminal output (colored, tables)
│       └── config.rs       # .murc.toml handling
│
├── mu-core/                # Existing - scanner, parser, graph
│   └── ...
│
├── mu-embeddings/          # NEW - embedding inference
│   ├── Cargo.toml
│   ├── src/
│   │   ├── lib.rs
│   │   ├── model.rs        # Model loading & inference
│   │   ├── tokenizer.rs    # BERT tokenizer
│   │   └── pooling.rs      # Mean pooling
│   └── models/
│       └── mu-sigma-v2/    # Embedded at compile time
│           ├── config.json
│           ├── tokenizer.json
│           └── model.safetensors
│
├── mu-server/              # HTTP/MCP server
│   ├── Cargo.toml
│   └── src/
│       ├── lib.rs
│       ├── http.rs         # REST API (axum)
│       ├── mcp.rs          # MCP protocol
│       └── watch.rs        # File watcher
│
├── mu-storage/             # Database layer
│   ├── Cargo.toml
│   └── src/
│       ├── lib.rs
│       ├── mubase.rs       # Graph storage
│       ├── embeddings.rs   # Vector storage
│       └── queries.rs      # MUQL execution
│
└── mu-daemon/              # Existing - to be merged into mu-server
    └── ...
```

---

## Feature Requirements

### P0: Core CLI (Must Have)

| ID | Feature | Description | Acceptance Criteria |
|----|---------|-------------|---------------------|
| F1 | `mu bootstrap` | Index codebase into .mubase | Identical output to Python version |
| F2 | `mu status` | Show graph stats and status | <50ms response time |
| F3 | `mu search` | Semantic code search | Uses embedded mu-sigma-v2 |
| F4 | `mu grok` | Extract relevant context | Token-efficient MU output |
| F5 | `mu q` | MUQL query interface | Full MUQL compatibility |
| F6 | `mu deps` | Dependency analysis | Petgraph-backed traversal |
| F7 | `mu read` | Read node source | Syntax highlighted output |

### P0: Vibe Commands (Must Have)

| ID | Feature | Description | Acceptance Criteria |
|----|---------|-------------|---------------------|
| V1 | `mu yolo` | Impact analysis | Shows affected nodes |
| V2 | `mu sus` | Risk assessment | Risk score + warnings |
| V3 | `mu wtf` | Git archaeology | Origin + evolution |
| V4 | `mu grok` | Context extraction | MU format output |
| V5 | `mu omg` | OMEGA compression | S-expression output |
| V6 | `mu vibe` | Pattern conformance | Pass/fail + suggestions |
| V7 | `mu zen` | Cache cleanup | Interactive or --yes |

### P1: Server & Integration (Should Have)

| ID | Feature | Description | Acceptance Criteria |
|----|---------|-------------|---------------------|
| S1 | `mu serve` | Start HTTP daemon | localhost:8432 default |
| S2 | `mu serve --mcp` | MCP server mode | stdio transport |
| S3 | Hot reload | Watch for file changes | <100ms incremental update |
| S4 | REST API | HTTP endpoints | OpenAPI spec compatible |

### P2: Advanced (Nice to Have)

| ID | Feature | Description | Acceptance Criteria |
|----|---------|-------------|---------------------|
| A1 | `mu diff` | Semantic diff | Between git refs |
| A2 | `mu patterns` | Pattern detection | Cached results |
| A3 | `mu export` | Multi-format export | mermaid, d2, json |
| A4 | `mu history` | Node history | Git-linked snapshots |

---

## Technical Specifications

### Embedding Model Integration

**Approach:** Embed mu-sigma-v2 weights directly in binary using `include_bytes!`

```rust
// mu-embeddings/src/model.rs
use candle_core::{Device, Tensor};
use candle_nn::VarBuilder;
use candle_transformers::models::bert::{BertModel, Config};

const MODEL_BYTES: &[u8] = include_bytes!("../models/mu-sigma-v2/model.safetensors");
const CONFIG_BYTES: &[u8] = include_bytes!("../models/mu-sigma-v2/config.json");
const TOKENIZER_BYTES: &[u8] = include_bytes!("../models/mu-sigma-v2/tokenizer.json");

pub struct MuSigmaModel {
    model: BertModel,
    tokenizer: Tokenizer,
    device: Device,
}

impl MuSigmaModel {
    pub fn load() -> Result<Self> {
        let device = Device::Cpu;  // CPU is fast enough
        let config: Config = serde_json::from_slice(CONFIG_BYTES)?;
        let vb = VarBuilder::from_buffered_safetensors(MODEL_BYTES, &device)?;
        let model = BertModel::load(vb, &config)?;
        let tokenizer = Tokenizer::from_bytes(TOKENIZER_BYTES)?;

        Ok(Self { model, tokenizer, device })
    }

    pub fn embed(&self, text: &str) -> Result<Vec<f32>> {
        let tokens = self.tokenizer.encode(text)?;
        let input = Tensor::new(&tokens[..], &self.device)?;
        let output = self.model.forward(&input)?;
        let pooled = mean_pooling(&output)?;
        Ok(pooled.to_vec1()?)
    }
}
```

**Binary Size Impact:**
- model.safetensors: 91MB
- Compressed in binary: ~60MB (LTO + compression)
- Total binary: ~80MB

### CLI Framework (clap)

```rust
// mu-cli/src/main.rs
use clap::{Parser, Subcommand};

#[derive(Parser)]
#[command(name = "mu")]
#[command(about = "Machine Understanding for Codebases")]
#[command(version)]
struct Cli {
    #[command(subcommand)]
    command: Commands,

    #[arg(short, long, global = true)]
    verbose: bool,

    #[arg(short, long, global = true)]
    quiet: bool,

    #[arg(long, global = true, value_enum, default_value = "table")]
    format: OutputFormat,
}

#[derive(Subcommand)]
enum Commands {
    /// Initialize MU for a codebase
    Bootstrap {
        #[arg(default_value = ".")]
        path: PathBuf,

        #[arg(long)]
        embed: bool,
    },

    /// Show status and statistics
    Status,

    /// Semantic search for code
    Search {
        query: String,

        #[arg(short, long, default_value = "10")]
        limit: usize,
    },

    /// Extract relevant context
    Grok {
        question: Option<String>,

        #[arg(short, long, default_value = "8000")]
        tokens: usize,
    },

    /// Execute MUQL query
    #[command(name = "q")]
    Query {
        query: String,
    },

    // Vibe commands
    /// Impact analysis - what breaks if I change this?
    Yolo { target: String },

    /// Risk assessment before modification
    Sus { target: String },

    /// Git archaeology - why does this exist?
    Wtf { target: String },

    /// OMEGA compressed context
    Omg { question: String },

    /// Pattern conformance check
    Vibe { path: PathBuf },

    /// Clean up caches
    Zen {
        #[arg(short, long)]
        yes: bool,
    },

    /// Start daemon server
    Serve {
        #[arg(long, default_value = "8432")]
        port: u16,

        #[arg(long)]
        mcp: bool,
    },

    // ... more commands
}

fn main() -> Result<()> {
    let cli = Cli::parse();

    match cli.command {
        Commands::Bootstrap { path, embed } => cmd::bootstrap(path, embed),
        Commands::Status => cmd::status(),
        Commands::Search { query, limit } => cmd::search(&query, limit),
        Commands::Grok { question, tokens } => cmd::grok(question, tokens),
        Commands::Query { query } => cmd::query(&query),
        Commands::Yolo { target } => cmd::yolo(&target),
        Commands::Sus { target } => cmd::sus(&target),
        Commands::Wtf { target } => cmd::wtf(&target),
        Commands::Omg { question } => cmd::omg(&question),
        Commands::Vibe { path } => cmd::vibe(&path),
        Commands::Zen { yes } => cmd::zen(yes),
        Commands::Serve { port, mcp } => cmd::serve(port, mcp),
    }
}
```

### Output Formatting

```rust
// mu-cli/src/output/mod.rs
use colored::Colorize;
use tabled::{Table, Style};

pub enum Output {
    Table(Vec<Row>),
    Json(serde_json::Value),
    Mu(String),
    Plain(String),
}

impl Output {
    pub fn print(&self, format: OutputFormat, no_color: bool) {
        match (self, format) {
            (Output::Table(rows), OutputFormat::Table) => {
                let table = Table::new(rows).with(Style::rounded());
                println!("{}", table);
            }
            (Output::Table(rows), OutputFormat::Json) => {
                println!("{}", serde_json::to_string_pretty(rows).unwrap());
            }
            (Output::Mu(text), _) => {
                if no_color {
                    println!("{}", text);
                } else {
                    print_mu_highlighted(text);
                }
            }
            // ...
        }
    }
}

fn print_mu_highlighted(text: &str) {
    for line in text.lines() {
        if line.starts_with('!') {
            println!("{}", line.blue().bold());
        } else if line.starts_with('$') {
            println!("{}", line.green());
        } else if line.starts_with('#') {
            println!("{}", line.yellow());
        } else if line.starts_with("::") {
            println!("{}", line.dimmed());
        } else {
            println!("{}", line);
        }
    }
}
```

### MCP Server Implementation

```rust
// mu-server/src/mcp.rs
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};

pub struct McpServer {
    mubase: Arc<MuBase>,
    embeddings: Arc<MuSigmaModel>,
}

impl McpServer {
    pub async fn run_stdio(self) -> Result<()> {
        let stdin = BufReader::new(tokio::io::stdin());
        let mut stdout = tokio::io::stdout();
        let mut lines = stdin.lines();

        while let Some(line) = lines.next_line().await? {
            let request: McpRequest = serde_json::from_str(&line)?;
            let response = self.handle_request(request).await?;
            let json = serde_json::to_string(&response)?;
            stdout.write_all(json.as_bytes()).await?;
            stdout.write_all(b"\n").await?;
            stdout.flush().await?;
        }

        Ok(())
    }

    async fn handle_request(&self, req: McpRequest) -> Result<McpResponse> {
        match req.method.as_str() {
            "tools/list" => self.list_tools(),
            "tools/call" => self.call_tool(&req.params).await,
            _ => Err(McpError::MethodNotFound),
        }
    }

    fn list_tools(&self) -> Result<McpResponse> {
        Ok(McpResponse::tools(vec![
            Tool::new("mu_status", "Get MU status and statistics"),
            Tool::new("mu_bootstrap", "Initialize MU for a codebase"),
            Tool::new("mu_search", "Semantic code search"),
            Tool::new("mu_context", "Extract relevant context"),
            Tool::new("mu_deps", "Show dependencies"),
            Tool::new("mu_impact", "Impact analysis"),
            Tool::new("mu_query", "Execute MUQL query"),
            Tool::new("mu_warn", "Get warnings before modification"),
            Tool::new("mu_patterns", "Detect codebase patterns"),
        ]))
    }

    async fn call_tool(&self, params: &McpParams) -> Result<McpResponse> {
        match params.name.as_str() {
            "mu_status" => {
                let stats = self.mubase.stats()?;
                Ok(McpResponse::json(stats))
            }
            "mu_search" => {
                let query = params.get_string("query")?;
                let limit = params.get_usize("limit").unwrap_or(10);
                let results = self.search(&query, limit).await?;
                Ok(McpResponse::json(results))
            }
            "mu_context" => {
                let question = params.get_string("question")?;
                let max_tokens = params.get_usize("max_tokens").unwrap_or(8000);
                let context = self.extract_context(&question, max_tokens).await?;
                Ok(McpResponse::json(context))
            }
            // ... other tools
            _ => Err(McpError::ToolNotFound),
        }
    }
}
```

---

## Migration Path

### Phase 1: Foundation (Week 1)

**Goal:** Rust CLI skeleton with basic commands

| Task | Owner | Days |
|------|-------|------|
| Create mu-cli crate with clap | Dev | 1 |
| Port `mu status` command | Dev | 0.5 |
| Port `mu bootstrap` command | Dev | 1 |
| Port `mu q` (MUQL) command | Dev | 1 |
| Output formatting (table, json, mu) | Dev | 1 |
| Integration tests | Dev | 0.5 |

**Deliverable:** `mu status`, `mu bootstrap`, `mu q` working in Rust

### Phase 2: Embeddings (Week 2)

**Goal:** mu-sigma-v2 running natively in Rust

| Task | Owner | Days |
|------|-------|------|
| Create mu-embeddings crate | Dev | 0.5 |
| Integrate candle for inference | Dev | 2 |
| Embed model weights in binary | Dev | 0.5 |
| Port `mu search` command | Dev | 1 |
| Port `mu grok` command | Dev | 1 |
| Benchmark vs Python | Dev | 0.5 |

**Deliverable:** Semantic search working with embedded model

### Phase 3: Vibes & Graph (Week 3)

**Goal:** All vibe commands and graph operations

| Task | Owner | Days |
|------|-------|------|
| Port `mu yolo` (impact) | Dev | 0.5 |
| Port `mu sus` (warnings) | Dev | 0.5 |
| Port `mu wtf` (archaeology) | Dev | 0.5 |
| Port `mu omg` (OMEGA) | Dev | 1 |
| Port `mu vibe` (patterns) | Dev | 0.5 |
| Port `mu deps`, `mu ancestors` | Dev | 0.5 |
| Port `mu cycles`, `mu related` | Dev | 0.5 |
| Port `mu patterns` | Dev | 1 |

**Deliverable:** Full vibe command suite

### Phase 4: Server & MCP (Week 4)

**Goal:** Daemon and MCP server in Rust

| Task | Owner | Days |
|------|-------|------|
| Merge mu-daemon into mu-server | Dev | 1 |
| Port HTTP API (axum) | Dev | 1 |
| Implement MCP protocol | Dev | 2 |
| File watcher integration | Dev | 0.5 |
| Claude Code integration test | Dev | 0.5 |

**Deliverable:** `mu serve` and `mu serve --mcp` working

### Phase 5: Polish & Release (Week 5)

**Goal:** Production-ready release

| Task | Owner | Days |
|------|-------|------|
| Binary builds (CI/CD) | Dev | 1 |
| Cross-compilation (linux, darwin, windows) | Dev | 1 |
| Install script | Dev | 0.5 |
| Documentation update | Dev | 1 |
| Benchmarks & comparison | Dev | 0.5 |
| Release v1.0.0 | Dev | 1 |

**Deliverable:** Published binaries for all platforms

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| candle model loading issues | Medium | High | Fallback to ONNX Runtime |
| Binary size too large | Low | Medium | Use model compression, lazy load |
| MUQL compatibility gaps | Medium | High | Comprehensive test suite from Python |
| MCP protocol edge cases | Low | Medium | Test against Claude Code directly |
| Cross-platform issues | Medium | Medium | CI builds on all targets |

---

## Alternatives Considered

### Alternative 1: Keep Python, Optimize Startup

**Approach:** Use `nuitka` or pre-compiled bytecode
**Rejected because:** Still 500ms+ startup, still needs Python runtime

### Alternative 2: Python + Rust Hybrid Distribution

**Approach:** Ship PyInstaller bundle + separate Rust daemon
**Rejected because:** Complex installation, two binaries, version sync issues

### Alternative 3: ONNX Runtime Instead of candle

**Approach:** Use ort crate with ONNX model
**Consideration:** Viable fallback if candle has issues
**Decision:** Try candle first (native Rust), fall back to ort if needed

---

## Appendix A: Benchmark Targets

```
Command                 Python (current)    Rust (target)    Speedup
─────────────────────────────────────────────────────────────────────
mu status               1.8s                0.05s            36x
mu search "auth"        1.9s                0.15s            13x
mu grok "auth flow"     2.5s                0.25s            10x
mu yolo Service.cs      1.5s                0.10s            15x
mu q "SELECT..."        1.2s                0.04s            30x
mu bootstrap (1k files) 8.0s                2.0s             4x
─────────────────────────────────────────────────────────────────────
Binary size             350MB               80MB             4x smaller
Memory (daemon)         180MB               25MB             7x smaller
```

---

## Appendix B: Dependency Inventory

### Rust Crates

```toml
[workspace.dependencies]
# CLI
clap = { version = "4", features = ["derive", "env"] }
colored = "2"
tabled = "0.15"
indicatif = "0.17"  # Progress bars

# Async
tokio = { version = "1", features = ["full"] }
futures = "0.3"

# HTTP
axum = { version = "0.7", features = ["ws"] }
tower = "0.5"
tower-http = { version = "0.6", features = ["cors", "trace"] }

# ML (candle)
candle-core = "0.8"
candle-nn = "0.8"
candle-transformers = "0.8"
tokenizers = "0.20"  # HuggingFace tokenizers

# Database
duckdb = { version = "1.1", features = ["bundled"] }

# Parsing
tree-sitter = "0.24"
tree-sitter-python = "0.23"
tree-sitter-typescript = "0.23"
# ... other grammars

# Graph
petgraph = "0.6"

# Serialization
serde = { version = "1", features = ["derive"] }
serde_json = "1"
toml = "0.8"

# Utilities
thiserror = "2"
anyhow = "1"
tracing = "0.1"
tracing-subscriber = "0.3"
chrono = { version = "0.4", features = ["serde"] }
```

---

## Appendix C: File Count & Effort Estimate

### Python Files to Port

```
src/mu/
├── cli.py                 # → mu-cli/src/main.rs
├── commands/              # → mu-cli/src/commands/
│   ├── core.py           #    bootstrap, status, search, etc.
│   ├── vibes/            #    yolo, sus, wtf, grok, omg, vibe, zen
│   ├── query.py          #    MUQL commands
│   ├── graph.py          #    deps, impact, cycles, ancestors
│   ├── patterns.py       #    Pattern detection
│   ├── serve.py          #    Daemon management
│   └── mcp/              #    MCP server commands
├── kernel/               # → mu-storage/ (partially, DuckDB ops)
├── mcp/                  # → mu-server/src/mcp.rs
├── extras/embeddings/    # → mu-embeddings/
└── output.py             # → mu-cli/src/output/
```

**Estimated Lines of Rust:** ~8,000-10,000
**Estimated Effort:** 4-5 weeks for one developer

---

## Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Product | | | |
| Engineering | | | |
| Design | | | |

---

*This document is a living artifact. Updates will be tracked in version control.*
