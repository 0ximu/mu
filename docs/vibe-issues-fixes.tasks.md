# Vibe Issues Fixes - Task Breakdown

## Business Context
**Problem**: MU's vibe check and analysis commands produce false positives and miss valid use cases, reducing user trust in the tooling.
**Outcome**: More accurate analysis with fewer false positives, making MU's checks suitable for CI pipelines.
**Users**: Developers using `mu vibe`, `mu sus`, and `mu path` commands.

## Validated Issues Summary

| Issue | File | Validated | Priority |
|-------|------|-----------|----------|
| React component naming | `conventions.rs:160-172` | YES | High |
| Cross-boundary paths | `graph.rs:194-248` | YES | High |
| Config validation | `config.rs:214-229` | YES | Medium |
| Smarter sus calibration | `sus.rs:488-509` | YES | Medium |

## Existing Patterns Found

| Pattern | File | Relevance |
|---------|------|-----------|
| Language detection | `conventions.rs:684-721` | Already has tsx/jsx detection - can extend |
| C# test method special case | `vibe.rs:138-145` | Example of entity-type exception handling |
| Warning levels | `sus.rs:20-27` | Existing 3-tier system (Info/Warn/Error) |
| Test detection | `sus.rs:587-634` | Pattern for checking test coverage |
| Config defaults fallback | `config.rs:214-229` | Current silent fallback pattern |

---

## Task Breakdown

### Task 1: Fix React Component Naming Convention

**File(s)**: `mu-cli/src/commands/vibes/conventions.rs`

**Problem**: TypeScript modules default to `camelCase`, but React component files (PascalCase filename in `.tsx`/`.jsx`) are correctly PascalCase.

**Pattern**: Follow the C# test method exception in `vibe.rs:138-145`

**Implementation**:
```rust
// Add new function in conventions.rs
pub fn convention_for_entity_with_context(
    language: &str,
    entity: EntityType,
    file_path: Option<&str>
) -> NamingConvention {
    // Detect React component files: .tsx/.jsx with PascalCase filename
    if let Some(path) = file_path {
        if (path.ends_with(".tsx") || path.ends_with(".jsx"))
            && entity == EntityType::Module
        {
            // Check if filename starts with uppercase (React component convention)
            if let Some(filename) = path.split('/').last() {
                if filename.chars().next().map(|c| c.is_uppercase()).unwrap_or(false) {
                    return NamingConvention::PascalCase;
                }
            }
        }
    }
    convention_for_entity(language, entity)
}
```

**Acceptance**:
- [ ] React component files (`ChatRoute.tsx`, `App.jsx`) use PascalCase for modules
- [ ] Regular TypeScript files still use camelCase for modules
- [ ] Add tests in `conventions.rs` tests module covering React components
- [ ] `cargo test -p mu-cli` passes

**Tests to Add**:
```rust
#[test]
fn test_react_component_convention() {
    // PascalCase .tsx files should expect PascalCase
    assert_eq!(
        convention_for_entity_with_context("typescript", EntityType::Module, Some("src/ChatRoute.tsx")),
        NamingConvention::PascalCase
    );
    // Regular .ts files should expect camelCase
    assert_eq!(
        convention_for_entity_with_context("typescript", EntityType::Module, Some("src/utils.ts")),
        NamingConvention::CamelCase
    );
}
```

---

### Task 2: Update Vibe Check to Use Context-Aware Convention

**File(s)**: `mu-cli/src/commands/vibes/vibe.rs`

**Problem**: `check_naming_conventions()` calls `convention_for()` without file context.

**Pattern**: Similar to how C# test methods are handled at `vibe.rs:138-145`

**Implementation**:
Update line 148-149 in `vibe.rs`:
```rust
// Before
let expected_convention = convention_override
    .unwrap_or_else(|| convention_for(language, entity_type));

// After
let expected_convention = convention_override
    .unwrap_or_else(|| convention_for_entity_with_context(
        language,
        entity_type.parse().unwrap_or(EntityType::Variable),
        node.file_path.as_deref()
    ));
```

**Acceptance**:
- [ ] `mu vibe` no longer flags React component files as naming violations
- [ ] Convention override still works when specified
- [ ] Existing tests pass

---

### Task 3: Add Config Validation with User Feedback

**File(s)**: `mu-cli/src/config.rs`

**Problem**: Parse errors silently fall back to defaults - users don't see their config is broken.

**Pattern**: Use existing `tracing::warn!` but add user-visible CLI feedback

**Implementation**:
```rust
// Add new method to MuConfig
impl MuConfig {
    /// Load config with strict validation - returns error on parse failure
    pub fn load_strict(root: &Path) -> Result<Self, ConfigError> {
        let config_path = root.join(".murc.toml");
        if !config_path.exists() {
            return Ok(Self::default());
        }

        let content = std::fs::read_to_string(&config_path)
            .map_err(|e| ConfigError::ReadError(config_path.clone(), e))?;

        toml::from_str(&content).map_err(|e| ConfigError::ParseError {
            path: config_path,
            error: e.to_string(),
            suggestion: suggest_config_fix(&e),
        })
    }
}

#[derive(Debug, thiserror::Error)]
pub enum ConfigError {
    #[error("Failed to read config file {0}: {1}")]
    ReadError(PathBuf, std::io::Error),

    #[error("Failed to parse {path}: {error}\n  Hint: {suggestion}")]
    ParseError {
        path: PathBuf,
        error: String,
        suggestion: String,
    },
}

fn suggest_config_fix(error: &toml::de::Error) -> String {
    let msg = error.to_string();
    if msg.contains("expected array") {
        "Use array syntax: languages = [\"python\", \"rust\"]".to_string()
    } else if msg.contains("expected string") {
        "Use quotes around string values".to_string()
    } else {
        "Check TOML syntax at https://toml.io".to_string()
    }
}
```

**Acceptance**:
- [ ] `load_strict()` returns meaningful error on invalid TOML
- [ ] Error includes suggestion for common mistakes
- [ ] `mu bootstrap --strict` uses strict config loading
- [ ] Default `mu bootstrap` still uses lenient loading (backwards compatible)

---

### Task 4: Smarter Sus Calibration for Security Code

**File(s)**: `mu-cli/src/commands/vibes/sus.rs`

**Problem**: Auth/security code is always flagged as Error-level suspicious, even when it's expected and tested.

**Pattern**: Use existing `check_for_tests()` function at `sus.rs:587`

**Implementation**:
```rust
// Modify the security check at lines 488-509

// Check 3: Security sensitive (auth, crypto, password, token, secret, key)
let security_keywords = [/* existing keywords */];
let is_security_sensitive = security_keywords.iter()
    .any(|kw| node_name.contains(kw) || file_path_str.to_lowercase().contains(kw));

if is_security_sensitive {
    // Check if security code has tests
    let has_security_tests = check_for_tests(conn, node_id, file_path_str)?;

    if has_security_tests {
        // Expected security code with tests - just note it exists
        warnings.push(SusWarning {
            level: WarningLevel::Info,  // Changed from Error
            category: "security".to_string(),
            message: "Security-sensitive code (auth/crypto) with test coverage".to_string(),
            suggestion: None,
        });
        risk_score += 1;  // Lower score when tested
    } else {
        // Security code WITHOUT tests - this is concerning
        warnings.push(SusWarning {
            level: WarningLevel::Error,
            category: "security sensitive".to_string(),
            message: "Security-sensitive code WITHOUT test coverage".to_string(),
            suggestion: Some("Critical: Add security tests before modifying.".to_string()),
        });
        risk_score += 4;  // Higher score when untested
    }
}
```

**Acceptance**:
- [ ] Auth code WITH tests shows as Info, not Error
- [ ] Auth code WITHOUT tests shows as Error (higher risk)
- [ ] Risk score reflects test coverage status
- [ ] Add tests for both scenarios

---

### Task 5: Add Bidirectional Path Search (Quick Win)

**File(s)**: `mu-cli/src/commands/graph.rs`

**Problem**: `shortest_path()` only searches in outgoing direction, missing reverse paths.

**Pattern**: Use existing BFS infrastructure at `graph.rs:250-302`

**Implementation**:
```rust
/// Find shortest path between two nodes (bidirectional)
pub fn shortest_path(
    &self,
    from_id: &str,
    to_id: &str,
    edge_types: Option<&[String]>,
) -> Option<Vec<String>> {
    // Try forward direction first
    if let Some(path) = self.shortest_path_directed(from_id, to_id, edge_types, Direction::Outgoing) {
        return Some(path);
    }

    // Try reverse direction (what if edges go the other way?)
    if let Some(mut path) = self.shortest_path_directed(to_id, from_id, edge_types, Direction::Outgoing) {
        path.reverse();
        return Some(path);
    }

    // Try undirected (treat all edges as bidirectional)
    self.shortest_path_undirected(from_id, to_id, edge_types)
}

fn shortest_path_directed(
    &self,
    from_id: &str,
    to_id: &str,
    edge_types: Option<&[String]>,
    direction: Direction,
) -> Option<Vec<String>> {
    // Move existing implementation here
}

fn shortest_path_undirected(
    &self,
    from_id: &str,
    to_id: &str,
    edge_types: Option<&[String]>,
) -> Option<Vec<String>> {
    // BFS treating edges as undirected
}
```

**Acceptance**:
- [ ] `mu path A B` finds path even if edges are A<-B
- [ ] Existing tests still pass
- [ ] Add test for bidirectional case

---

## Dependencies

```
Task 1 (conventions.rs)
    └── Task 2 (vibe.rs) - uses new function from Task 1

Task 3 (config.rs) - independent

Task 4 (sus.rs) - independent

Task 5 (graph.rs) - independent
```

**Parallel execution**: Tasks 1+2 together, then Tasks 3, 4, 5 can run in parallel.

## Edge Cases

1. **React Component Naming**:
   - Files like `index.tsx` (lowercase) should remain camelCase
   - Only PascalCase filenames trigger React component detection

2. **Config Validation**:
   - Empty config file should use defaults, not error
   - Missing file should use defaults (existing behavior)

3. **Sus Calibration**:
   - Files that ARE test files shouldn't be flagged for missing tests
   - Security code in test files should be treated differently

4. **Bidirectional Path**:
   - Self-loops should return single-element path
   - Disconnected nodes should return None, not error

## Security Considerations

- **Task 3 (Config)**: Error messages should not leak filesystem paths in production logs
- **Task 4 (Sus)**: Don't reduce scrutiny for code that CLAIMS to have tests but doesn't actually

## Testing Checklist

```bash
# After all tasks
cargo fmt
cargo clippy
cargo test -p mu-cli

# Manual verification
mu vibe src/components/ChatRoute.tsx  # Should not flag naming
mu sus src/auth/                       # Should show Info if tests exist
mu path FrontendService BackendService # Should find path if connected
```
