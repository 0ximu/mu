# Rust MUQL Implementation Gaps

This document tracks MUQL features available in the Python implementation but not yet in the Rust daemon.

## Status Summary

| Feature | Python | Rust | Fixable | Priority |
|---------|--------|------|---------|----------|
| Basic SELECT | ✅ | ✅ | N/A | - |
| WHERE clause | ✅ | ✅ | N/A | - |
| ORDER BY | ✅ | ✅ | N/A | - |
| LIMIT | ✅ | ✅ | N/A | - |
| COUNT(*) | ✅ | ✅ | N/A | - |
| AVG/MAX/MIN/SUM | ✅ | ✅ | N/A | - |
| GROUP BY | ✅ | ✅ | N/A | - |
| HAVING | ✅ | ✅ | N/A | - |
| AS (column alias) | ✅ | ✅ | N/A | - |
| SHOW TABLES | ✅ | ❌ | Yes | Low |
| SHOW COLUMNS | ✅ | ❌ | Yes | Low |
| HISTORY OF | ✅ | ❌ | Yes | Medium |
| BLAME | ✅ | ❌ | Yes | Medium |
| AT (temporal) | ✅ | ❌ | Yes | Low |
| BETWEEN (temporal) | ✅ | ❌ | Yes | Low |
| CONTAINS comparison | ✅ | ❌ | Yes | Low |
| FIND MUTATING | ✅ | ❌ | Yes | Low |

## Detailed Gap Analysis

### 1. ~~GROUP BY Clause~~ ✅ IMPLEMENTED

**Status:** Implemented in Rust daemon.

**Example:**
```sql
SELECT type, COUNT(*) FROM nodes GROUP BY type
SELECT file_path, AVG(complexity) FROM functions GROUP BY file_path
SELECT file_path, type, COUNT(*) FROM functions GROUP BY file_path, type
```

---

### 2. ~~HAVING Clause~~ ✅ IMPLEMENTED

**Status:** Implemented in Rust daemon. Supports aggregate expressions in conditions.

**Example:**
```sql
SELECT type, COUNT(*) FROM nodes GROUP BY type HAVING COUNT(*) > 10
SELECT file_path, AVG(complexity) AS avg_complexity FROM functions GROUP BY file_path HAVING AVG(complexity) > 10
```

---

### 3. ~~Column Aliases (AS)~~ ✅ IMPLEMENTED

**Status:** Implemented in Rust daemon.

**Example:**
```sql
SELECT name AS function_name, complexity AS cyclo FROM functions
SELECT COUNT(*) AS total FROM classes
SELECT file_path, AVG(complexity) AS avg_complexity FROM functions GROUP BY file_path
```

---

### 4. SHOW TABLES / SHOW COLUMNS (Low Priority)

**Python Grammar:**
```lark
show_tables_query: SHOW_KW TABLES_KW
show_columns_query: SHOW_KW COLUMNS_KW FROM_KW node_type
```

**Example:**
```sql
SHOW TABLES
SHOW COLUMNS FROM functions
```

**Current Workaround:** Use `DESCRIBE TABLES` or `DESCRIBE functions` (already implemented)

**Fix Location:** `mu-daemon/src/muql/grammar.pest`

**Implementation Notes:**
- Simple alias to existing DESCRIBE functionality
- Low priority since DESCRIBE works

---

### 5. Temporal Queries (Medium Priority)

**Python Grammar:**
```lark
temporal_clause: at_clause | between_clause
at_clause: AT_KW commit_ref
between_clause: BETWEEN_KW commit_ref AND_KW commit_ref
history_query: HISTORY_KW OF_KW node_ref [limit_clause]
blame_query: BLAME_KW node_ref
```

**Examples:**
```sql
SELECT * FROM functions AT "abc123"
SELECT * FROM classes BETWEEN "v1.0" AND "HEAD"
HISTORY OF MUbase LIMIT 10
BLAME cli
```

**Fix Location:** Multiple files in `mu-daemon/src/muql/`

**Implementation Notes:**
- Requires temporal data in MUbase (snapshots table)
- HISTORY requires git integration
- BLAME requires git blame parsing
- Consider deferring until temporal module is stable

---

### 6. CONTAINS Comparison (Low Priority)

**Python Grammar:**
```lark
comparison: IDENTIFIER CONTAINS_KW value -> contains_comparison
```

**Example:**
```sql
SELECT * FROM functions WHERE name CONTAINS "test"
```

**Current Workaround:** Use LIKE with wildcards
```sql
SELECT * FROM functions WHERE name LIKE '%test%'
```

**Fix Location:** `mu-daemon/src/muql/grammar.pest`

**Implementation Notes:**
- Syntactic sugar for `LIKE '%value%'`
- Low priority since LIKE works

---

### 7. FIND MUTATING (Low Priority)

**Python Grammar:**
```lark
find_condition: MUTATING_KW node_ref -> find_mutating
```

**Example:**
```sql
FIND functions MUTATING user_state
```

**Fix Location:** `mu-daemon/src/muql/grammar.pest` and `mu-daemon/src/muql/executor.rs`

**Implementation Notes:**
- Requires mutation tracking in graph edges
- Depends on parser detecting state mutations
- Low priority, rarely used

---

## Implementation Approach

### ✅ Completed

1. **GROUP BY + HAVING** - Implemented with aggregate expression support in conditions
2. **AS (alias)** - Implemented for both regular fields and aggregate functions

### Quick Wins (1-2 hours each)

1. **SHOW TABLES/COLUMNS** - Map to existing DESCRIBE handlers

### Medium Effort (4-8 hours each)

1. **HISTORY OF** - Needs snapshot queries, git log parsing
2. **BLAME** - Needs git blame integration
3. **AT/BETWEEN** - Needs temporal join logic

### Deferred

1. **CONTAINS** - LIKE works fine as workaround
2. **FIND MUTATING** - Needs mutation detection in parser

---

## Testing Strategy

For each fix:

1. Add grammar rule to `grammar.pest`
2. Update parser structs in `parser.rs`
3. Update planner in `planner.rs` (if SQL generation)
4. Update executor in `executor.rs` (if graph operation)
5. Add unit test in `parser.rs` `#[cfg(test)]` module
6. Add integration test verifying round-trip

Example test:
```rust
#[test]
fn test_parse_group_by() {
    let q = parse("SELECT type, COUNT(*) FROM nodes GROUP BY type").unwrap();
    match q {
        Query::Select(s) => {
            assert!(!s.group_by.is_empty());
            assert_eq!(s.group_by[0], "type");
        }
        _ => panic!("Expected Select query"),
    }
}
```

---

## Workarounds

Until remaining gaps are fixed, users can:

1. **SHOW TABLES** - Use `DESCRIBE TABLES` instead
2. **CONTAINS** - Use `LIKE '%value%'` instead
3. **Temporal** - Use Python daemon or direct MUbase queries

---

## References

- Python Grammar: `src/mu/kernel/muql/grammar.lark`
- Python Parser: `src/mu/kernel/muql/parser.py`
- Rust Grammar: `mu-daemon/src/muql/grammar.pest`
- Rust Parser: `mu-daemon/src/muql/parser.rs`
- Rust Planner: `mu-daemon/src/muql/planner.rs`
- Rust Executor: `mu-daemon/src/muql/executor.rs`
