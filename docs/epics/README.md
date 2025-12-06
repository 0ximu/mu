# MU Epics - Implementation Roadmap

This directory contains the sharded PRD for the MU Divine Edition. Each epic represents a self-contained feature set with detailed implementation plans.

## Current State

**Completed**: MU Kernel (Phase 0)
- Graph schema with DuckDB storage
- Node/Edge models and serialization
- GraphBuilder converting ModuleDef to graph
- MUbase class with CRUD and recursive queries
- CLI commands: `mu kernel init/build/stats/query/deps`
- 30 tests passing

## Epic Overview

| # | Epic | Priority | Complexity | Dependencies | Status |
|---|------|----------|------------|--------------|--------|
| 1 | [Vector Layer](01-vector-layer.md) | P1 | Medium | Kernel | Ready |
| 2 | [MUQL Parser](02-muql-parser.md) | P1 | High | Kernel | Ready |
| 3 | [Smart Context](03-smart-context.md) | P1 | Medium-High | Vector Layer | Blocked |
| 4 | [Temporal Layer](04-temporal-layer.md) | P2 | High | Kernel | Ready |
| 5 | [Export Formats](05-export-formats.md) | P2 | Medium | Kernel | Ready |
| 6 | [Daemon Mode](06-daemon-mode.md) | P3 | High | Kernel, Export | Blocked |
| 7 | [MU Contracts](07-mu-contracts.md) | P3 | Medium | MUQL | Blocked |
| 8 | [Visualization](08-visualization.md) | P4 | High | Export, Daemon | Blocked |
| 9 | [IDE Integration](09-ide-integration.md) | P4 | High | Daemon, Smart Context | Blocked |

## Recommended Execution Order

### Sprint 1: Core Query Capabilities
1. **Epic 1: Vector Layer** - Enables semantic search
2. **Epic 2: MUQL Parser** - Query language for graph

### Sprint 2: Intelligence & History
3. **Epic 3: Smart Context** - AI context extraction
4. **Epic 4: Temporal Layer** - Git-linked history

### Sprint 3: Integration & Output
5. **Epic 5: Export Formats** - Multiple output formats
6. **Epic 6: Daemon Mode** - Real-time updates

### Sprint 4: Ecosystem
7. **Epic 7: MU Contracts** - Architecture verification
8. **Epic 8: Visualization** - Web-based graph UI
9. **Epic 9: IDE Integration** - VS Code extension

## Dependency Graph

```
                    ┌─────────────┐
                    │   Kernel    │ (COMPLETE)
                    │   (Done)    │
                    └──────┬──────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
           ▼               ▼               ▼
    ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
    │   Vector    │ │    MUQL     │ │  Temporal   │
    │  (Epic 1)   │ │  (Epic 2)   │ │  (Epic 4)   │
    └──────┬──────┘ └──────┬──────┘ └─────────────┘
           │               │
           ▼               ▼
    ┌─────────────┐ ┌─────────────┐
    │   Smart     │ │  Contracts  │
    │  Context    │ │  (Epic 7)   │
    │  (Epic 3)   │ └─────────────┘
    └──────┬──────┘
           │
           │       ┌─────────────┐
           │       │   Export    │
           │       │  (Epic 5)   │
           │       └──────┬──────┘
           │               │
           └───────┬───────┘
                   │
                   ▼
            ┌─────────────┐
            │   Daemon    │
            │  (Epic 6)   │
            └──────┬──────┘
                   │
       ┌───────────┴───────────┐
       │                       │
       ▼                       ▼
┌─────────────┐         ┌─────────────┐
│    Viz      │         │     IDE     │
│  (Epic 8)   │         │  (Epic 9)   │
└─────────────┘         └─────────────┘
```

## Quick Reference

### Epic 1: Vector Layer
- Embedding generation (OpenAI + local)
- Semantic similarity search
- `mu kernel embed`, `mu kernel search`

### Epic 2: MUQL Parser
- SQL-like query language
- SELECT, SHOW, FIND, PATH, ANALYZE
- `mu query "<MUQL>"`

### Epic 3: Smart Context
- Question-aware context extraction
- Entity + Vector + Graph signals
- `mu context "<question>"`

### Epic 4: Temporal Layer
- Git-linked snapshots
- History and blame
- `mu kernel snapshot`, `mu kernel history`

### Epic 5: Export Formats
- MU text, JSON, Mermaid, D2, Cytoscape
- `mu kernel export --format <fmt>`

### Epic 6: Daemon Mode
- File watcher, incremental updates
- HTTP/WebSocket API
- `mu daemon start`

### Epic 7: MU Contracts
- Architecture rules in YAML
- CI/CD integration
- `mu contracts verify`

### Epic 8: Visualization
- Web-based Cytoscape.js UI
- Filtering, search, time-travel
- `mu viz`

### Epic 9: IDE Integration
- VS Code extension
- CodeLens, decorations, commands
- Marketplace: `mu-vscode`

## Effort Estimates

| Epic | Implementation Days | Test Days | Total |
|------|---------------------|-----------|-------|
| 1 | 3 | 1 | 4 |
| 2 | 4 | 1 | 5 |
| 3 | 4 | 1 | 5 |
| 4 | 4 | 1 | 5 |
| 5 | 3 | 1 | 4 |
| 6 | 4 | 1 | 5 |
| 7 | 4 | 1 | 5 |
| 8 | 5 | 1 | 6 |
| 9 | 5 | 1 | 6 |
| **Total** | **36** | **9** | **45 days** |

## Getting Started

To begin implementation:

1. **Choose an epic** from the "Ready" status above
2. **Read the full epic document** for detailed specs
3. **Follow the implementation plan** phases
4. **Run tests** after each phase
5. **Update status** when complete

Each epic includes:
- User stories with acceptance criteria
- Technical design with code examples
- Implementation plan with phases
- CLI/API interface specifications
- Testing strategy
- Success criteria
- Risks and mitigations
