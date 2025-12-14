# PRD: MU V2 Audit Fixes

**Version**: 1.0
**Date**: 2024-12-13
**Status**: Draft
**Author**: Code Audit

---

## Executive Summary

This PRD addresses four bugs discovered during a comprehensive code audit of the MU V2 codebase. These issues range from critical (broken dependency graph for TypeScript projects) to cosmetic (incorrect schema version display). Fixing these issues will significantly improve MU's reliability for modern TypeScript/JavaScript projects and provide consistent behavior across daemon and standalone modes.

---

## Problem Statement

### Issue 1: MUQL Virtual Table Inconsistency

**Priority**: P1 (Medium)
**Symptom**: `SELECT * FROM functions` fails in standalone mode, only `SELECT * FROM nodes` works.

**Root Cause**: In standalone mode (daemon not running), queries starting with SQL keywords bypass the MUQL parser entirely. The `try_convert_terse_to_sql` function returns `NotTerse`, and the query goes directly to DuckDB unchanged. The MUQL parser (which correctly rewrites `FROM functions` to `FROM nodes WHERE type = 'function'`) only runs when the daemon is active.

**Location**: `mu-cli/src/commands/query.rs:94-103, 268-284`

**Impact**:
- Users get different behavior depending on whether daemon is running
- Documentation examples fail in standalone mode
- Confusing error messages ("table functions does not exist")

---

### Issue 2: Vibe Check Wrong Context

**Priority**: P1 (Medium)
**Symptom**: `mu vibe src/hooks/useAuth.ts` shows issues from unrelated files.

**Root Cause**: Only `load_nodes_from_path()` (used for naming checks) filters by the specified path. All other check functions (`check_api_patterns`, `check_test_coverage`, `check_imports`, `check_circular_imports`, `check_async_patterns`) query the ENTIRE database without path filtering.

**Location**: `mu-cli/src/commands/vibes/vibe.rs:174-406, 458, 505-514`

**Impact**:
- Misleading output showing issues from unrelated files
- Cannot focus vibe check on specific directories or files
- CI usage is unreliable for targeted checks

---

### Issue 3: TypeScript Path Aliases Not Supported

**Priority**: P0 (Critical)
**Symptom**: `mu deps` and `mu ancestors` return almost nothing despite many imports.

**Root Cause**: TypeScript path aliases are not supported. All `@/...` imports (common in Next.js/TypeScript projects) are incorrectly resolved as `ext:@/lib/...` (external) instead of `mod:src/lib/...` (internal module). The resolver doesn't read `tsconfig.json` to understand path aliases.

**Location**: `mu-cli/src/commands/bootstrap.rs:528-530, 636-655`

**Impact**:
- Dependency graph is fundamentally broken for modern TypeScript projects
- `mu deps`, `mu ancestors`, `mu impact` return incomplete/empty results
- Makes MU essentially unusable for Next.js, Vite, and most modern TS projects
- Affects majority of TypeScript codebases using path aliases

**Evidence**: In a typical Next.js project, 251 imports to `ext:@/lib/logger` should be `mod:src/lib/logger.ts`.

---

### Issue 4: Schema Version Display Bug

**Priority**: P2 (Low)
**Symptom**: `mu doctor` shows "Schema version: unknown".

**Root Cause**: Type mismatch. `SCHEMA_VERSION` is stored as `"1.0.0"` (semver string), but `get_schema_version()` tries to parse it as `i32`. Parsing fails, returns `None`, displays "unknown".

**Location**:
- `mu-daemon/src/storage/schema.rs:153` - stores `"1.0.0"`
- `mu-cli/src/commands/doctor.rs:227-235, 315` - expects integer

**Impact**:
- Cosmetic issue only
- Users cannot verify schema compatibility
- Recommendations for schema upgrades may be incorrect

---

## Requirements

### R1: Consistent MUQL Virtual Tables (Issue 1)

#### R1.1: Virtual Table Rewriting in Standalone Mode
- Standalone mode MUST rewrite virtual table names (`functions`, `classes`, `modules`) to `nodes` with appropriate `WHERE type = '...'` clause
- Behavior MUST be identical whether daemon is running or not

#### R1.2: Supported Virtual Tables

| Virtual Table | Rewrite To |
|--------------|------------|
| `functions` | `nodes WHERE type = 'function'` |
| `classes` | `nodes WHERE type = 'class'` |
| `modules` | `nodes WHERE type = 'module'` |

#### R1.3: Column Preservation
- All columns from the original query MUST be preserved
- `SELECT name, complexity FROM functions` -> `SELECT name, complexity FROM nodes WHERE type = 'function'`

#### R1.4: WHERE Clause Merging
- Existing WHERE clauses MUST be preserved and merged
- `SELECT * FROM functions WHERE complexity > 10` -> `SELECT * FROM nodes WHERE type = 'function' AND complexity > 10`

---

### R2: Path-Filtered Vibe Checks (Issue 2)

#### R2.1: Consistent Path Filtering
- ALL vibe check functions MUST respect the path parameter
- If path is specified, only files matching that path pattern should be checked

#### R2.2: Functions to Update

| Function | Current | Required |
|----------|---------|----------|
| `check_naming_conventions` | Filtered | Keep as-is |
| `check_circular_imports` | Full DB | Add path filter |
| `check_test_coverage` | Full DB | Add path filter |
| `check_imports` | Full DB | Add path filter |
| `check_api_patterns` | Full DB | Add path filter |
| `check_async_patterns` | Full DB | Add path filter |

#### R2.3: Path Matching
- Path filter MUST use `LIKE '%{path}%'` pattern matching (consistent with current naming check)
- Special case: `.` means entire project (no filter)

---

### R3: TypeScript Path Alias Support (Issue 3)

#### R3.1: tsconfig.json Detection
- During bootstrap, detect and parse `tsconfig.json` in project root
- Also check for `jsconfig.json` (JavaScript projects)
- Handle `extends` to resolve inherited configurations

#### R3.2: Path Alias Resolution
- Parse `compilerOptions.paths` from tsconfig
- Resolve `compilerOptions.baseUrl` relative to tsconfig location
- Support common patterns:
  - `"@/*": ["src/*"]`
  - `"@components/*": ["src/components/*"]`
  - `"~/*": ["./src/*"]`
  - `"#/*": ["./src/*"]`

#### R3.3: Import Resolution Order
1. Check if import matches a path alias pattern
2. If match, resolve using alias mapping + baseUrl
3. If no match, fall back to existing resolution logic

#### R3.4: Supported Alias Patterns

| Pattern | Example Import | Resolution |
|---------|---------------|------------|
| `@/*` | `@/lib/logger` | `src/lib/logger.ts` |
| `@components/*` | `@components/Button` | `src/components/Button.tsx` |
| `~/utils/*` | `~/utils/format` | `src/utils/format.ts` |

#### R3.5: Extension Resolution
When resolving aliased imports without extensions:
1. Try exact path
2. Try `.ts`, `.tsx`, `.js`, `.jsx` extensions
3. Try `index.ts`, `index.tsx`, `index.js`, `index.jsx` in directory

#### R3.6: Cache Configuration
- Cache parsed tsconfig per project to avoid re-parsing on each import
- Invalidate cache on tsconfig.json modification

---

### R4: Schema Version Display Fix (Issue 4)

#### R4.1: Version Handling
- `get_schema_version()` MUST handle semver strings (e.g., "1.0.0")
- Display the actual stored version string

#### R4.2: Version Compatibility Check
- Define current expected schema version as semver constant
- Compare using semver semantics (major.minor.patch)
- Show warning if major version differs

#### R4.3: Doctor Output Examples
```
[OK] Schema version: 1.0.0 (current)
[!!] Schema version: 0.9.0 (outdated, current: 1.0.0)
[!!] Schema version: 2.0.0 (newer than CLI)
```

---

## Technical Design

### Issue 1: MUQL Virtual Table Rewriting

**File**: `mu-cli/src/commands/query.rs`

```rust
/// Rewrite virtual table names to nodes table with type filter
fn rewrite_virtual_tables(sql: &str) -> String {
    // Pattern: FROM functions/classes/modules (case-insensitive)
    let re = regex::Regex::new(
        r"(?i)\bFROM\s+(functions|classes|modules)\b(\s+WHERE\s+|\s*$|\s+ORDER|\s+LIMIT|\s+GROUP)"
    ).unwrap();

    re.replace_all(sql, |caps: &regex::Captures| {
        let table = caps.get(1).unwrap().as_str().to_lowercase();
        let suffix = caps.get(2).map(|m| m.as_str()).unwrap_or("");

        let node_type = match table.as_str() {
            "functions" => "function",
            "classes" => "class",
            "modules" => "module",
            _ => return caps.get(0).unwrap().as_str().to_string(),
        };

        // Handle WHERE merging
        if suffix.to_uppercase().contains("WHERE") {
            format!("FROM nodes WHERE type = '{}' AND ", node_type)
        } else {
            format!("FROM nodes WHERE type = '{}'{}", node_type, suffix)
        }
    }).to_string()
}

// Apply in execute_query_direct:
fn execute_query_direct(query_str: &str) -> Result<QueryResult> {
    let final_query = match try_convert_terse_to_sql(query_str) {
        TerseParseResult::Sql(sql) => sql,
        TerseParseResult::NotTerse => rewrite_virtual_tables(query_str),  // NEW
        TerseParseResult::RequiresDaemon(suggestion) => {
            return Err(anyhow::anyhow!(
                "Graph operations require the daemon.\n\nStart daemon: mu serve\nOr use SQL: {}",
                suggestion
            ));
        }
    };

    let final_query = normalize_type_in_sql(&final_query);
    // ... rest of function
}
```

---

### Issue 2: Path-Filtered Vibe Checks

**File**: `mu-cli/src/commands/vibes/vibe.rs`

```rust
/// Build a path filter clause for SQL queries
fn path_filter_clause(path: &str, column: &str) -> String {
    if path == "." {
        String::new()
    } else {
        format!(" AND {} LIKE '%{}%'", column, path.replace("'", "''"))
    }
}

// Update each check function to accept and use path parameter:

fn check_circular_imports(conn: &Connection, path: &str) -> Result<Vec<VibeIssue>> {
    let path_filter = path_filter_clause(path, "n.file_path");

    let query = format!(r#"
        WITH RECURSIVE import_path(source, target, path, depth) AS (
            SELECT e.source_id, e.target_id, ARRAY[e.source_id, e.target_id], 1
            FROM edges e
            JOIN nodes n ON e.source_id = n.id
            WHERE e.type = 'imports'
              AND n.file_path IS NOT NULL
              {}

            UNION ALL

            SELECT ip.source, e.target_id, list_append(ip.path, e.target_id), ip.depth + 1
            FROM import_path ip
            JOIN edges e ON ip.target = e.source_id
            WHERE e.type = 'imports'
              AND ip.depth < 10
              AND NOT list_contains(ip.path, e.target_id)
        )
        SELECT DISTINCT source, target, path
        FROM import_path
        WHERE source = target AND depth > 1
        LIMIT 50
    "#, path_filter);
    // ... rest of function
}

fn check_test_coverage(conn: &Connection, path: &str) -> Result<Vec<VibeIssue>> {
    let path_filter = path_filter_clause(path, "file_path");

    let source_funcs_query = format!(r#"
        SELECT DISTINCT file_path, name
        FROM nodes
        WHERE type = 'function'
          AND file_path IS NOT NULL
          AND file_path NOT LIKE '%test%'
          AND file_path NOT LIKE '%__pycache__%'
          AND name NOT LIKE '__%'
          {}
        ORDER BY file_path
        LIMIT 100
    "#, path_filter);
    // ... rest of function
}

// Similarly update: check_imports, check_api_patterns, check_async_patterns

// Update run() to pass path to all functions:
pub async fn run(path: &str, format: OutputFormat, convention_override: Option<&str>) -> Result<()> {
    // ...
    let circular_issues = check_circular_imports(&conn, path)?;  // Add path param
    let test_issues = check_test_coverage(&conn, path)?;          // Add path param
    let import_issues = check_imports(&conn, path)?;              // Add path param
    let api_issues = check_api_patterns(&conn, path)?;            // Add path param
    let async_issues = check_async_patterns(&conn, path)?;        // Add path param
    // ...
}
```

---

### Issue 3: TypeScript Path Alias Support

**New File**: `mu-cli/src/tsconfig.rs`

```rust
use serde::Deserialize;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

#[derive(Debug, Deserialize)]
struct TsConfig {
    #[serde(rename = "compilerOptions")]
    compiler_options: Option<CompilerOptions>,
    extends: Option<String>,
}

#[derive(Debug, Deserialize)]
struct CompilerOptions {
    #[serde(rename = "baseUrl")]
    base_url: Option<String>,
    paths: Option<HashMap<String, Vec<String>>>,
}

#[derive(Debug, Clone)]
pub struct PathAliasResolver {
    root: PathBuf,
    base_url: PathBuf,
    aliases: Vec<(String, String)>,  // (pattern_prefix, replacement_prefix)
}

impl PathAliasResolver {
    /// Load from tsconfig.json or jsconfig.json
    pub fn from_project(root: &Path) -> Option<Self> {
        let config_path = Self::find_config(root)?;
        let content = std::fs::read_to_string(&config_path).ok()?;

        // Strip comments (tsconfig allows them)
        let content = Self::strip_json_comments(&content);

        let config: TsConfig = serde_json::from_str(&content).ok()?;

        // Handle extends (follow chain)
        let mut final_config = config;
        if let Some(ref extends) = final_config.extends {
            if let Some(base) = Self::load_extended_config(&config_path, extends) {
                // Merge: child overrides parent
                if final_config.compiler_options.is_none() {
                    final_config.compiler_options = base.compiler_options;
                } else if let Some(ref mut child_opts) = final_config.compiler_options {
                    if let Some(base_opts) = base.compiler_options {
                        if child_opts.base_url.is_none() {
                            child_opts.base_url = base_opts.base_url;
                        }
                        if child_opts.paths.is_none() {
                            child_opts.paths = base_opts.paths;
                        }
                    }
                }
            }
        }

        let opts = final_config.compiler_options?;
        let paths = opts.paths?;

        if paths.is_empty() {
            return None;
        }

        let config_dir = config_path.parent().unwrap_or(root);
        let base_url = opts
            .base_url
            .map(|b| config_dir.join(b))
            .unwrap_or_else(|| config_dir.to_path_buf());

        let mut aliases = Vec::new();
        for (pattern, replacements) in paths {
            // "@/*" -> "@/", "src/*" -> "src/"
            let prefix = pattern.trim_end_matches('*').to_string();
            if let Some(replacement) = replacements.first() {
                let repl_prefix = replacement.trim_end_matches('*').to_string();
                aliases.push((prefix, repl_prefix));
            }
        }

        // Sort by prefix length descending (more specific first)
        aliases.sort_by(|a, b| b.0.len().cmp(&a.0.len()));

        Some(Self {
            root: root.to_path_buf(),
            base_url,
            aliases,
        })
    }

    fn find_config(root: &Path) -> Option<PathBuf> {
        let tsconfig = root.join("tsconfig.json");
        if tsconfig.exists() {
            return Some(tsconfig);
        }

        let jsconfig = root.join("jsconfig.json");
        if jsconfig.exists() {
            return Some(jsconfig);
        }

        None
    }

    fn strip_json_comments(content: &str) -> String {
        // Simple comment stripping (// and /* */)
        let mut result = String::new();
        let mut in_string = false;
        let mut in_single_comment = false;
        let mut in_multi_comment = false;
        let mut chars = content.chars().peekable();

        while let Some(c) = chars.next() {
            if in_single_comment {
                if c == '\n' {
                    in_single_comment = false;
                    result.push(c);
                }
                continue;
            }

            if in_multi_comment {
                if c == '*' && chars.peek() == Some(&'/') {
                    chars.next();
                    in_multi_comment = false;
                }
                continue;
            }

            if c == '"' && !in_string {
                in_string = true;
                result.push(c);
            } else if c == '"' && in_string {
                in_string = false;
                result.push(c);
            } else if !in_string && c == '/' {
                if chars.peek() == Some(&'/') {
                    chars.next();
                    in_single_comment = true;
                } else if chars.peek() == Some(&'*') {
                    chars.next();
                    in_multi_comment = true;
                } else {
                    result.push(c);
                }
            } else {
                result.push(c);
            }
        }

        result
    }

    fn load_extended_config(config_path: &Path, extends: &str) -> Option<TsConfig> {
        let config_dir = config_path.parent()?;
        let extended_path = config_dir.join(extends);
        let content = std::fs::read_to_string(&extended_path).ok()?;
        let content = Self::strip_json_comments(&content);
        serde_json::from_str(&content).ok()
    }

    /// Resolve an import path using aliases
    pub fn resolve(&self, import_path: &str) -> Option<String> {
        for (prefix, replacement) in &self.aliases {
            if import_path.starts_with(prefix) {
                let remainder = &import_path[prefix.len()..];
                let resolved_path = self.base_url.join(replacement).join(remainder);

                // Try to find actual file with extensions
                if let Some(final_path) = self.resolve_with_extensions(&resolved_path) {
                    // Make relative to root
                    let rel_path = final_path
                        .strip_prefix(&self.root)
                        .unwrap_or(&final_path)
                        .to_string_lossy()
                        .to_string();
                    return Some(format!("mod:{}", rel_path));
                }

                // Fallback: assume .ts extension
                let rel_path = resolved_path
                    .strip_prefix(&self.root)
                    .unwrap_or(&resolved_path)
                    .to_string_lossy()
                    .to_string();

                let final_path = if rel_path.contains('.') {
                    rel_path
                } else {
                    format!("{}.ts", rel_path)
                };

                return Some(format!("mod:{}", final_path));
            }
        }
        None
    }

    fn resolve_with_extensions(&self, base_path: &Path) -> Option<PathBuf> {
        // Try exact path
        if base_path.exists() && base_path.is_file() {
            return Some(base_path.to_path_buf());
        }

        // Try with extensions
        let extensions = [".ts", ".tsx", ".js", ".jsx"];
        for ext in &extensions {
            let with_ext = base_path.with_extension(&ext[1..]);
            if with_ext.exists() && with_ext.is_file() {
                return Some(with_ext);
            }
        }

        // Try index files
        let index_files = ["index.ts", "index.tsx", "index.js", "index.jsx"];
        for index in &index_files {
            let index_path = base_path.join(index);
            if index_path.exists() && index_path.is_file() {
                return Some(index_path);
            }
        }

        None
    }
}
```

**Update**: `mu-cli/src/commands/bootstrap.rs`

```rust
use crate::tsconfig::PathAliasResolver;

// In run() function, after config loading:
let alias_resolver = PathAliasResolver::from_project(&root);

// Update resolve_import to use resolver:
fn resolve_import(
    import_path: &str,
    source_file: &str,
    alias_resolver: Option<&PathAliasResolver>,
) -> String {
    // Try path alias first
    if let Some(resolver) = alias_resolver {
        if let Some(resolved) = resolver.resolve(import_path) {
            return resolved;
        }
    }

    // TypeScript/JS style imports (./foo, ../foo)
    if is_typescript_style_import(import_path) {
        return resolve_typescript_import(import_path, source_file);
    }

    // Python style relative imports (..foo, .foo)
    if import_path.starts_with('.') {
        return resolve_python_import(import_path, source_file);
    }

    // Absolute imports
    let path = import_path.replace('.', "/");
    if import_path.contains('.') {
        format!("mod:{}", path)
    } else {
        format!("ext:{}", import_path)
    }
}

// Update call site in node/edge building:
for import in &module.imports {
    let target_id = resolve_import(&import.module, rel_path, alias_resolver.as_ref());
    edges.push(mu_daemon::storage::Edge::imports(&module_id, &target_id));
}
```

---

### Issue 4: Schema Version Fix

**File**: `mu-cli/src/commands/doctor.rs`

```rust
/// Current expected schema version (semver)
const CURRENT_SCHEMA_VERSION: &str = "1.0.0";

/// Get database schema version as string
fn get_schema_version(conn: &Connection) -> Option<String> {
    conn.query_row(
        "SELECT value FROM metadata WHERE key = 'schema_version'",
        [],
        |row| row.get::<_, String>(0),
    )
    .ok()
}

/// Parse major version from semver string
fn parse_major_version(version: &str) -> Option<u32> {
    version.split('.').next().and_then(|s| s.parse().ok())
}

/// Compare versions and determine status
fn compare_versions(stored: &str, current: &str) -> (&'static str, bool) {
    let stored_major = parse_major_version(stored);
    let current_major = parse_major_version(current);

    match (stored_major, current_major) {
        (Some(s), Some(c)) if s == c => ("current", false),
        (Some(s), Some(c)) if s < c => ("outdated", true),
        (Some(s), Some(c)) if s > c => ("newer than CLI", false),
        _ => ("unknown format", false),
    }
}

// In run() function, update schema version check:
match get_schema_version(&conn) {
    Some(version) => {
        let (status, needs_rebuild) = compare_versions(&version, CURRENT_SCHEMA_VERSION);

        if status == "current" {
            checks.push(CheckItem::ok(
                "Schema version",
                format!("{} ({})", version, status),
            ));
        } else {
            checks.push(CheckItem::warning(
                "Schema version",
                format!("{} ({}, current: {})", version, status, CURRENT_SCHEMA_VERSION),
            ));
            if needs_rebuild {
                recommendations.push("Rebuild database: mu bootstrap --force".to_string());
            }
        }
    }
    None => {
        checks.push(CheckItem::warning("Schema version", "not found"));
    }
}
```

---

## Testing Requirements

### Issue 1 Tests

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_virtual_table_rewrite_functions() {
        let sql = "SELECT * FROM functions";
        let rewritten = rewrite_virtual_tables(sql);
        assert!(rewritten.contains("FROM nodes"));
        assert!(rewritten.contains("type = 'function'"));
    }

    #[test]
    fn test_virtual_table_rewrite_with_where() {
        let sql = "SELECT * FROM functions WHERE complexity > 10";
        let rewritten = rewrite_virtual_tables(sql);
        assert!(rewritten.contains("type = 'function' AND complexity > 10"));
    }

    #[test]
    fn test_virtual_table_rewrite_classes() {
        let sql = "SELECT name FROM classes LIMIT 10";
        let rewritten = rewrite_virtual_tables(sql);
        assert!(rewritten.contains("type = 'class'"));
        assert!(rewritten.contains("LIMIT 10"));
    }

    #[test]
    fn test_virtual_table_preserves_case() {
        let sql = "SELECT Name, Complexity FROM FUNCTIONS";
        let rewritten = rewrite_virtual_tables(sql);
        assert!(rewritten.contains("Name, Complexity"));
    }
}
```

### Issue 2 Tests

```rust
#[test]
fn test_path_filter_clause_root() {
    assert_eq!(path_filter_clause(".", "file_path"), "");
}

#[test]
fn test_path_filter_clause_specific() {
    let clause = path_filter_clause("src/hooks", "file_path");
    assert_eq!(clause, " AND file_path LIKE '%src/hooks%'");
}

#[test]
fn test_path_filter_escapes_quotes() {
    let clause = path_filter_clause("src/user's", "file_path");
    assert!(clause.contains("user''s"));
}
```

### Issue 3 Tests

```rust
#[test]
fn test_path_alias_resolution_basic() {
    let resolver = PathAliasResolver {
        root: PathBuf::from("/project"),
        base_url: PathBuf::from("/project"),
        aliases: vec![("@/".to_string(), "src/".to_string())],
    };

    let result = resolver.resolve("@/lib/logger");
    assert_eq!(result, Some("mod:src/lib/logger.ts".to_string()));
}

#[test]
fn test_path_alias_no_match() {
    let resolver = PathAliasResolver {
        root: PathBuf::from("/project"),
        base_url: PathBuf::from("/project"),
        aliases: vec![("@/".to_string(), "src/".to_string())],
    };

    let result = resolver.resolve("react");
    assert_eq!(result, None);
}

#[test]
fn test_path_alias_multiple_patterns() {
    let resolver = PathAliasResolver {
        root: PathBuf::from("/project"),
        base_url: PathBuf::from("/project"),
        aliases: vec![
            ("@components/".to_string(), "src/components/".to_string()),
            ("@/".to_string(), "src/".to_string()),
        ],
    };

    // More specific pattern should match first
    let result = resolver.resolve("@components/Button");
    assert_eq!(result, Some("mod:src/components/Button.ts".to_string()));
}
```

### Issue 4 Tests

```rust
#[test]
fn test_version_comparison_current() {
    let (status, needs_rebuild) = compare_versions("1.0.0", "1.0.0");
    assert_eq!(status, "current");
    assert!(!needs_rebuild);
}

#[test]
fn test_version_comparison_outdated() {
    let (status, needs_rebuild) = compare_versions("0.9.0", "1.0.0");
    assert_eq!(status, "outdated");
    assert!(needs_rebuild);
}

#[test]
fn test_version_comparison_newer() {
    let (status, needs_rebuild) = compare_versions("2.0.0", "1.0.0");
    assert_eq!(status, "newer than CLI");
    assert!(!needs_rebuild);
}

#[test]
fn test_parse_major_version() {
    assert_eq!(parse_major_version("1.0.0"), Some(1));
    assert_eq!(parse_major_version("2.5.3"), Some(2));
    assert_eq!(parse_major_version("invalid"), None);
}
```

---

## Implementation Plan

### Phase 1: Critical Fix (Issue 3)

**Estimated Effort**: 4-6 hours

1. Create `mu-cli/src/tsconfig.rs` module
2. Implement `PathAliasResolver` struct
3. Add tsconfig.json/jsconfig.json parsing with `extends` support
4. Integrate into `resolve_import` function in bootstrap.rs
5. Add unit tests
6. Test with real Next.js project

### Phase 2: Medium Priority Fixes (Issues 1 & 2)

**Estimated Effort**: 2-3 hours each

#### Issue 1: Virtual Table Rewriting
1. Add `rewrite_virtual_tables()` function to query.rs
2. Integrate into `execute_query_direct()`
3. Handle WHERE clause merging
4. Add unit tests

#### Issue 2: Path-Filtered Vibe Checks
1. Add `path_filter_clause()` helper function
2. Update all check functions to accept path parameter
3. Update `run()` to pass path to all functions
4. Add unit tests

### Phase 3: Low Priority Fix (Issue 4)

**Estimated Effort**: 1 hour

1. Change `get_schema_version()` to return `Option<String>`
2. Add `compare_versions()` function
3. Update schema version display logic
4. Add unit tests

---

## Success Metrics

| Metric | Before | After |
|--------|--------|-------|
| `mu deps` completeness (TS project with path aliases) | ~5% | >95% |
| `SELECT * FROM functions` works in standalone mode | No | Yes |
| `mu vibe src/hooks` only shows hook issues | No | Yes |
| `mu doctor` shows correct schema version | No | Yes |

---

## Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| tsconfig parsing breaks on edge cases | Medium | Medium | Handle extends chains, validate with multiple real projects |
| Virtual table rewriting breaks complex queries | Low | Medium | Limit to simple FROM clauses, recommend daemon for complex queries |
| Path filter changes vibe output significantly | Medium | Low | Document behavior change |

---

## Open Questions

1. **Issue 3**: Should we support `paths` in nested tsconfig (e.g., `packages/app/tsconfig.json` in monorepo)?
2. **Issue 1**: Should we support JOINs with virtual tables, or require daemon for those?
3. **Issue 2**: Should `--all` flag bypass path filtering for explicit "check everything" behavior?

---

## File Reference

| Issue | Primary Files |
|-------|---------------|
| Issue 1 | `mu-cli/src/commands/query.rs` |
| Issue 2 | `mu-cli/src/commands/vibes/vibe.rs` |
| Issue 3 | `mu-cli/src/commands/bootstrap.rs`, `mu-cli/src/tsconfig.rs` (new) |
| Issue 4 | `mu-cli/src/commands/doctor.rs` |
