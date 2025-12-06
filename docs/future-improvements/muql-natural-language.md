# Natural Language Interface for MUQL

**Area**: MUQL / Query Language
**Status**: Deferred
**Added**: 2025-12-06

## Problem

MUQL uses SQL-like syntax which is precise and predictable, but has a learning curve:

```sql
SELECT name FROM functions WHERE complexity > 500
SHOW dependencies OF AuthService DEPTH 2
FIND functions CALLING Redis
```

Users might prefer more natural queries like:
- "what functions have complexity over 500?"
- "what does AuthService depend on?"
- "which functions call Redis?"

## Options

### A) LLM Translation Layer
Natural language → LLM → MUQL → execution

**Pros**: Most flexible, handles ambiguity
**Cons**: Slower (LLM round-trip), requires API key, non-deterministic

### B) Simplified Syntax
Drop boilerplate, keep structure:
```
functions where complexity > 500
deps of AuthService depth 2
callers of process_payment
```

**Pros**: Fast, deterministic, still parseable with Lark
**Cons**: Still requires learning syntax

### C) CLI Aliases
Common queries as CLI flags:
```bash
mu find functions --calling Redis
mu show deps AuthService --depth 2
mu analyze circular
```

**Pros**: Familiar CLI UX, tab-completion
**Cons**: Less flexible than full query language

### D) Hybrid
Accept both precise MUQL and natural queries:
```
> what calls Redis?              # natural → LLM → MUQL
> FIND functions CALLING Redis   # direct execution
```

**Pros**: Best of both worlds
**Cons**: Implementation complexity

## Tradeoffs Summary

| Approach | Speed | Flexibility | Learning Curve |
|----------|-------|-------------|----------------|
| SQL-like (current) | Fast | High | Medium |
| LLM translation | Slow | Very High | Low |
| Simplified syntax | Fast | Medium | Low |
| CLI aliases | Fast | Low | Very Low |
| Hybrid | Variable | Very High | Low |

## Decision

Deferred until we get user feedback on MUQL adoption. If users struggle with the syntax, prioritize option D (hybrid) or B (simplified syntax).
