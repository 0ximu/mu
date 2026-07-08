//! Auto-configuration: detect codebase patterns and generate `.mu/config.toml`.
//!
//! Runs once per codebase via `mu_configure`, persists forever. All MU tools
//! read this config to apply test dampening, oracle exclusions, and enrichment
//! priorities.

use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;

use crate::engine::storage::MUbase;

// ============================================================================
// Config structs
// ============================================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AutoConfig {
    pub filters: FilterConfig,
    pub codebase: CodebaseConfig,
    pub enrichment: EnrichmentConfig,
    pub oracle: OracleConfig,
    #[serde(default)]
    pub domain_concepts: HashMap<String, String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FilterConfig {
    pub test_patterns: Vec<String>,
    pub generated_patterns: Vec<String>,
    // Deprecated: node_category replaces query-time dampening.
    // Kept for backward compat with existing .mu/config.toml files.
    pub search_test_dampening: f32,
    // Deprecated: node_category replaces query-time dampening.
    #[serde(default = "default_auxiliary_dampening")]
    pub auxiliary_dampening: f32,
}

fn default_auxiliary_dampening() -> f32 { 0.7 }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CodebaseConfig {
    pub primary_language: String,
    pub frameworks: Vec<String>,
    pub services: Vec<String>,
    pub estimated_size: String,
    #[serde(default)]
    pub auxiliary_services: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EnrichmentConfig {
    pub priority_nodes: Vec<String>,
    pub auto_enrich_top_n: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OracleConfig {
    pub exclude_patterns: Vec<String>,
    pub test_budget_cap: f32,
}

impl Default for AutoConfig {
    fn default() -> Self {
        Self {
            filters: FilterConfig {
                test_patterns: vec![
                    "*/test/*".into(),
                    "*/tests/*".into(),
                    "*_test.*".into(),
                    "test_*".into(),
                    "*Tests.cs".into(),
                    "*Test.cs".into(),
                ],
                generated_patterns: vec![
                    "*.Designer.cs".into(),
                    "*/Migrations/*.cs".into(),
                    "*/obj/*".into(),
                    "*/bin/*".into(),
                ],
                search_test_dampening: 0.3,
                auxiliary_dampening: 0.7,
            },
            codebase: CodebaseConfig {
                primary_language: "unknown".into(),
                frameworks: Vec::new(),
                services: Vec::new(),
                estimated_size: "unknown".into(),
                auxiliary_services: Vec::new(),
            },
            enrichment: EnrichmentConfig {
                priority_nodes: Vec::new(),
                auto_enrich_top_n: 50,
            },
            oracle: OracleConfig {
                exclude_patterns: vec![
                    "*/Migrations/*.cs".into(),
                    "*.Designer.cs".into(),
                    "*/obj/*".into(),
                ],
                test_budget_cap: 0.1,
            },
            domain_concepts: HashMap::new(),
        }
    }
}

impl AutoConfig {
    /// Load config from `.mu/config.toml`. Returns None if file doesn't exist.
    pub fn load(project_root: &Path) -> Option<Self> {
        let path = project_root.join(".mu").join("config.toml");
        let content = std::fs::read_to_string(&path).ok()?;
        toml::from_str(&content).ok()
    }

    /// Save config to `.mu/config.toml`.
    pub fn save(&self, project_root: &Path) -> Result<()> {
        let path = project_root.join(".mu").join("config.toml");
        let content = toml::to_string_pretty(self)?;
        std::fs::write(&path, content)?;
        Ok(())
    }

    /// Auto-detect everything and build a config from the mubase.
    pub fn generate(mubase: &MUbase) -> Result<Self> {
        let test_patterns = detect_test_patterns(mubase)?;
        let generated_patterns = detect_generated_patterns(mubase)?;
        let primary_language = detect_primary_language(mubase)?;
        let frameworks = detect_frameworks(mubase)?;
        let services = detect_services(mubase)?;
        let size = estimate_size(mubase)?;
        let core_nodes = detect_core_abstractions(mubase)?;

        // Build oracle exclusions from generated patterns + common noise
        let mut exclude_patterns = generated_patterns.clone();
        // Always exclude obj/bin if not already present
        for p in &["*/obj/*", "*/bin/*"] {
            let s = p.to_string();
            if !exclude_patterns.contains(&s) {
                exclude_patterns.push(s);
            }
        }

        Ok(Self {
            filters: FilterConfig {
                test_patterns,
                generated_patterns,
                search_test_dampening: 0.3,
                auxiliary_dampening: 0.7,
            },
            codebase: CodebaseConfig {
                primary_language,
                frameworks,
                services,
                estimated_size: size,
                auxiliary_services: Vec::new(),
            },
            enrichment: EnrichmentConfig {
                priority_nodes: core_nodes,
                auto_enrich_top_n: 50,
            },
            oracle: OracleConfig {
                exclude_patterns,
                test_budget_cap: 0.1,
            },
            domain_concepts: HashMap::new(),
        })
    }
}

// ============================================================================
// Node classification
// ============================================================================

/// Classify a node's file path into a category.
/// Priority: generated > test > infrastructure > production.
/// Uses config patterns if available, falls back to hardcoded patterns.
pub fn classify_node(file_path: Option<&str>, config: Option<&AutoConfig>) -> &'static str {
    let Some(path) = file_path else { return "production" };
    let lower = path.to_lowercase();

    // 1. Generated (most specific — check first)
    if let Some(cfg) = config {
        if is_excluded_path(path, &cfg.oracle.exclude_patterns) {
            return "generated";
        }
    } else {
        // Hardcoded fallbacks
        if (lower.contains("/migrations/") && lower.ends_with(".cs"))
            || lower.contains("/obj/")
            || lower.ends_with(".designer.cs")
            || lower.contains(".generated.")
        {
            return "generated";
        }
    }

    // 2. Test
    if let Some(cfg) = config {
        if is_test_path(path, &cfg.filters.test_patterns) {
            return "test";
        }
    }
    // Always check hardcoded test patterns as fallback
    if lower.contains("/test/") || lower.contains("/tests/")
        || lower.starts_with("tests/")
        || lower.contains(".tests/") || lower.contains(".tests.")
        || lower.contains("/__tests__/") || lower.contains("/spec/")
        || lower.ends_with("tests.cs") || lower.ends_with("test.cs")
        || lower.ends_with("_test.py") || lower.ends_with("_test.go")
        || lower.ends_with("_test.rs") || lower.ends_with(".test.ts")
        || lower.ends_with(".test.tsx") || lower.ends_with(".test.js")
        || lower.ends_with(".spec.ts") || lower.ends_with(".spec.js")
        || path.rsplit('/').next().is_some_and(|f| f.starts_with("test_") && f.ends_with(".py"))
    {
        return "test";
    }

    // 3. Infrastructure (auxiliary services)
    if let Some(cfg) = config {
        if is_auxiliary_service(path, &cfg.codebase.auxiliary_services) {
            return "infrastructure";
        }
    }

    "production"
}

// ============================================================================
// Detection functions
// ============================================================================

/// A glob-style pattern name plus the predicate that detects it.
type PatternCheck = (&'static str, fn(&str) -> bool);

/// Detect test file patterns by scanning all file_paths in the mubase.
pub fn detect_test_patterns(mubase: &MUbase) -> Result<Vec<String>> {
    let result = mubase.query(
        "SELECT DISTINCT file_path FROM nodes WHERE file_path IS NOT NULL",
    )?;

    let paths: Vec<String> = result.rows.iter()
        .filter_map(|r| r.first().and_then(|v| v.as_str()).map(|s| s.to_string()))
        .collect();

    let pattern_checks: &[PatternCheck] = &[
        ("*/test/*", |p: &str| p.to_lowercase().contains("/test/")),
        ("*/tests/*", |p: &str| p.to_lowercase().contains("/tests/")),
        ("tests/*", |p: &str| p.to_lowercase().starts_with("tests/")),
        ("*.Tests/*", |p: &str| { let l = p.to_lowercase(); l.contains(".tests/") || l.contains(".tests.") }),
        ("*/spec/*", |p: &str| p.to_lowercase().contains("/spec/")),
        ("*/specs/*", |p: &str| p.to_lowercase().contains("/specs/")),
        ("*/__tests__/*", |p: &str| p.contains("/__tests__/")),
        ("*Test.cs", |p: &str| p.ends_with("Test.cs")),
        ("*Tests.cs", |p: &str| p.ends_with("Tests.cs")),
        ("*_test.py", |p: &str| p.ends_with("_test.py")),
        ("*_test.go", |p: &str| p.ends_with("_test.go")),
        ("test_*.py", |p: &str| {
            p.rsplit('/').next().is_some_and(|f| f.starts_with("test_") && f.ends_with(".py"))
        }),
        ("*.test.ts", |p: &str| p.ends_with(".test.ts")),
        ("*.test.tsx", |p: &str| p.ends_with(".test.tsx")),
        ("*.spec.ts", |p: &str| p.ends_with(".spec.ts")),
        ("*.test.js", |p: &str| p.ends_with(".test.js")),
        ("*.spec.js", |p: &str| p.ends_with(".spec.js")),
        ("*_test.rs", |p: &str| p.ends_with("_test.rs")),
        ("*/fixtures/*", |p: &str| p.to_lowercase().contains("/fixtures/")),
        ("*/mocks/*", |p: &str| p.to_lowercase().contains("/mocks/")),
    ];

    let mut matched = Vec::new();
    for (pattern, checker) in pattern_checks {
        if paths.iter().any(|p| checker(p)) {
            matched.push(pattern.to_string());
        }
    }

    Ok(matched)
}

/// Detect generated file patterns.
pub fn detect_generated_patterns(mubase: &MUbase) -> Result<Vec<String>> {
    let result = mubase.query(
        "SELECT DISTINCT file_path FROM nodes WHERE file_path IS NOT NULL",
    )?;

    let paths: Vec<String> = result.rows.iter()
        .filter_map(|r| r.first().and_then(|v| v.as_str()).map(|s| s.to_string()))
        .collect();

    let pattern_checks: &[PatternCheck] = &[
        ("*.Designer.cs", |p: &str| p.ends_with(".Designer.cs")),
        ("*/Migrations/*.cs", |p: &str| {
            p.to_lowercase().contains("/migrations/") && p.ends_with(".cs")
        }),
        ("*/obj/*", |p: &str| p.to_lowercase().contains("/obj/")),
        ("*/bin/*", |p: &str| p.to_lowercase().contains("/bin/")),
        ("*.generated.*", |p: &str| {
            let lower = p.to_lowercase();
            lower.contains(".generated.")
        }),
        ("*/auto_generated/*", |p: &str| p.to_lowercase().contains("/auto_generated/")),
    ];

    let mut matched = Vec::new();
    for (pattern, checker) in pattern_checks {
        if paths.iter().any(|p| checker(p)) {
            matched.push(pattern.to_string());
        }
    }

    // Also check source_text first 5 lines for auto-generated markers
    let marker_result = mubase.query(
        "SELECT DISTINCT file_path FROM nodes
         WHERE source_text IS NOT NULL
           AND (
             source_text LIKE '%auto-generated%'
             OR source_text LIKE '%do not edit%'
             OR source_text LIKE '%auto generated%'
             OR source_text LIKE '%autogenerated%'
           )
         LIMIT 100",
    )?;

    if !marker_result.rows.is_empty() {
        // Derive patterns from detected auto-generated files
        for row in &marker_result.rows {
            if let Some(path) = row.first().and_then(|v| v.as_str()) {
                // Extract the extension-based pattern
                if let Some(ext) = path.rsplit('.').next() {
                    let pattern = format!("*.generated.{}", ext);
                    if !matched.contains(&pattern) {
                        // Only add if it's actually a generated extension pattern
                        if path.contains(".generated.") {
                            matched.push(pattern);
                        }
                    }
                }
            }
        }
    }

    Ok(matched)
}

/// Detect frameworks by looking at external nodes and import edge targets.
///
/// Filters results by primary language so a C# codebase with a tiny Python
/// script doesn't report `sqlalchemy` as a primary framework.
pub fn detect_frameworks(mubase: &MUbase) -> Result<Vec<String>> {
    let primary_lang = detect_primary_language(mubase)?;

    // Check both explicit external nodes and import edge targets
    let result = mubase.query(
        "SELECT DISTINCT name FROM nodes WHERE type = 'external'
         UNION
         SELECT DISTINCT target_id FROM edges WHERE type = 'imports'",
    )?;

    let externals: Vec<String> = result.rows.iter()
        .filter_map(|r| r.first().and_then(|v| v.as_str()).map(|s| s.to_string()))
        .collect();

    // (match_strings, framework_name, language)
    let framework_map: &[(&[&str], &str, &[&str])] = &[
        (&["Microsoft.EntityFrameworkCore"], "ef-core", &["csharp"]),
        (&["MassTransit"], "masstransit", &["csharp"]),
        (&["Microsoft.Azure.Functions"], "azure-functions", &["csharp"]),
        (&["Microsoft.AspNetCore"], "aspnet-core", &["csharp"]),
        (&["fastapi", "FastAPI"], "fastapi", &["python"]),
        (&["sqlalchemy", "SQLAlchemy"], "sqlalchemy", &["python"]),
        (&["django", "Django"], "django", &["python"]),
        (&["flask", "Flask"], "flask", &["python"]),
        (&["rmcp"], "mcp-server", &["rust"]),
        (&["react", "React"], "react", &["typescript", "javascript"]),
        (&["next", "Next"], "nextjs", &["typescript", "javascript"]),
        (&["express", "Express"], "express", &["typescript", "javascript"]),
        (&["axum"], "axum", &["rust"]),
        (&["actix_web", "actix-web"], "actix-web", &["rust"]),
        (&["tokio"], "tokio", &["rust"]),
        (&["serde"], "serde", &["rust"]),
        (&["duckdb"], "duckdb", &["rust", "python"]),
        (&["petgraph"], "petgraph", &["rust"]),
        (&["tree_sitter", "tree-sitter"], "tree-sitter", &["rust"]),
    ];

    let mut detected = Vec::new();
    for (names, framework, langs) in framework_map {
        let matched = names.iter().any(|name| externals.iter().any(|e| e.contains(name)));
        if matched && langs.contains(&primary_lang.as_str()) {
            detected.push(framework.to_string());
        }
    }

    detected.sort();
    detected.dedup();
    Ok(detected)
}

/// Detect the primary language by counting nodes per file extension.
pub fn detect_primary_language(mubase: &MUbase) -> Result<String> {
    let result = mubase.query(
        "SELECT
            CASE
                WHEN file_path LIKE '%.rs' THEN 'rust'
                WHEN file_path LIKE '%.py' THEN 'python'
                WHEN file_path LIKE '%.ts' THEN 'typescript'
                WHEN file_path LIKE '%.tsx' THEN 'typescript'
                WHEN file_path LIKE '%.js' THEN 'javascript'
                WHEN file_path LIKE '%.jsx' THEN 'javascript'
                WHEN file_path LIKE '%.go' THEN 'go'
                WHEN file_path LIKE '%.java' THEN 'java'
                WHEN file_path LIKE '%.cs' THEN 'csharp'
                WHEN file_path LIKE '%.kt' THEN 'kotlin'
                WHEN file_path LIKE '%.swift' THEN 'swift'
                WHEN file_path LIKE '%.rb' THEN 'ruby'
                WHEN file_path LIKE '%.php' THEN 'php'
                WHEN file_path LIKE '%.c' THEN 'c'
                WHEN file_path LIKE '%.cpp' OR file_path LIKE '%.cc' THEN 'cpp'
                ELSE 'other'
            END AS lang,
            COUNT(*) AS cnt
         FROM nodes
         WHERE file_path IS NOT NULL AND type != 'external'
         GROUP BY lang
         ORDER BY cnt DESC
         LIMIT 1",
    )?;

    Ok(result.rows.first()
        .and_then(|r| r.first().and_then(|v| v.as_str()))
        .unwrap_or("unknown")
        .to_string())
}

/// Detect services by looking for project manifest files and directory structure patterns.
///
/// Strategy:
/// 1. Find directories containing project manifests (.csproj, Cargo.toml, package.json, etc.)
/// 2. Also detect repeated naming patterns in directory structure (e.g. src/gateway-*)
/// 3. Filter out noise directories with < 5 nodes
pub fn detect_services(mubase: &MUbase) -> Result<Vec<String>> {
    let result = mubase.query(
        "SELECT DISTINCT file_path FROM nodes WHERE file_path IS NOT NULL AND type != 'external'",
    )?;

    let paths: Vec<String> = result
        .rows
        .iter()
        .filter_map(|r| r.first().and_then(|v| v.as_str()).map(|s| s.to_string()))
        .collect();

    // Build node counts per directory prefix (first 2 levels)
    let mut prefix_counts: HashMap<String, usize> = HashMap::new();
    for path in &paths {
        let parts: Vec<&str> = path.split('/').collect();
        // Try 2-level prefix first (e.g. "src/dominaite-gateway-api"), then 1-level
        for depth in [2, 1] {
            if parts.len() > depth {
                let prefix = parts[..depth].join("/");
                *prefix_counts.entry(prefix).or_insert(0) += 1;
            }
        }
    }

    // Strategy 1: directories containing project manifest files
    let manifest_result = mubase.query(
        "SELECT DISTINCT file_path FROM nodes
         WHERE file_path IS NOT NULL
           AND (
             file_path LIKE '%.csproj'
             OR file_path LIKE '%/Cargo.toml'
             OR file_path LIKE '%/package.json'
             OR file_path LIKE '%/pyproject.toml'
             OR file_path LIKE '%/go.mod'
             OR file_path LIKE '%/Program.cs'
           )",
    )?;

    let mut service_dirs: Vec<String> = Vec::new();
    for row in &manifest_result.rows {
        if let Some(path) = row.first().and_then(|v| v.as_str()) {
            // Get the directory containing the manifest
            let parts: Vec<&str> = path.split('/').collect();
            if parts.len() >= 2 {
                // For 2-level paths like "src/my-service/Foo.csproj", use "src/my-service"
                // For 1-level paths like "my-service/Cargo.toml", use "my-service"
                let dir = if parts.len() >= 3 {
                    // Use first 2 components
                    format!("{}/{}", parts[0], parts[1])
                } else {
                    parts[0].to_string()
                };

                // Skip common non-service dirs
                let skip = ["src", "lib", "pkg", "cmd", "internal", "vendor"];
                if !skip.contains(&dir.as_str()) && !service_dirs.contains(&dir) {
                    // Check node count — must have >= 5 nodes to be a real service
                    let count = prefix_counts.get(&dir).copied().unwrap_or(0);
                    if count >= 5 {
                        service_dirs.push(dir);
                    }
                }
            }
        }
    }

    // Strategy 2: detect repeated naming patterns at the 2-level prefix
    // e.g. if we see src/gateway-api, src/gateway-payments, src/gateway-identity
    // those share "src/gateway-" prefix — all are services
    let two_level_prefixes: Vec<(&String, &usize)> = prefix_counts
        .iter()
        .filter(|(k, _)| k.contains('/'))
        .collect();

    // Group by common prefix (everything before the last hyphen or dot)
    let mut pattern_groups: HashMap<String, Vec<String>> = HashMap::new();
    for (prefix, _count) in &two_level_prefixes {
        // Try to find a shared naming pattern
        // e.g. "src/dominaite-gateway-api" → stem "src/dominaite-gateway-"
        let parts: Vec<&str> = prefix.split('/').collect();
        if parts.len() == 2 {
            let name = parts[1];
            // Find the last hyphen to get the "family" prefix
            if let Some(pos) = name.rfind('-') {
                let family = format!("{}/{}", parts[0], &name[..=pos]);
                pattern_groups
                    .entry(family)
                    .or_default()
                    .push(prefix.to_string());
            }
        }
    }

    // If a pattern group has 3+ members, they're all services
    for members in pattern_groups.values() {
        if members.len() >= 3 {
            for dir in members {
                let count = prefix_counts.get(dir).copied().unwrap_or(0);
                if count >= 5 && !service_dirs.contains(dir) {
                    service_dirs.push(dir.clone());
                }
            }
        }
    }

    service_dirs.sort();
    Ok(service_dirs)
}

/// Detect top-N core abstractions by importance, excluding test/generated code.
pub fn detect_core_abstractions(mubase: &MUbase) -> Result<Vec<String>> {
    let result = mubase.query(
        "SELECT id FROM nodes
         WHERE type IN ('class', 'function')
           AND importance_score > 0
           AND node_category = 'production'
         ORDER BY importance_score DESC
         LIMIT 20",
    )?;

    Ok(result.rows.iter()
        .filter_map(|r| r.first().and_then(|v| v.as_str()).map(|s| s.to_string()))
        .collect())
}

/// Estimate codebase size by node count.
pub fn estimate_size(mubase: &MUbase) -> Result<String> {
    let result = mubase.query(
        "SELECT COUNT(*) FROM nodes WHERE type != 'external'",
    )?;

    let count = result.rows.first()
        .and_then(|r| r.first())
        .and_then(|v| v.as_i64())
        .unwrap_or(0);

    Ok(if count < 500 {
        "small"
    } else if count < 5000 {
        "medium"
    } else {
        "large"
    }.to_string())
}

// ============================================================================
// Pattern matching helpers
// ============================================================================

/// Simple glob matching: `*` matches any sequence of chars, `?` matches one char.
/// Supports patterns like `*/test/*`, `*.Designer.cs`, `*_test.py`.
pub fn matches_glob(path: &str, pattern: &str) -> bool {
    glob_match(path.as_bytes(), pattern.as_bytes())
}

fn glob_match(text: &[u8], pattern: &[u8]) -> bool {
    let mut ti = 0;
    let mut pi = 0;
    let mut star_pi = usize::MAX;
    let mut star_ti = 0;

    while ti < text.len() {
        if pi < pattern.len() && (pattern[pi] == b'?' || pattern[pi] == text[ti]) {
            ti += 1;
            pi += 1;
        } else if pi < pattern.len() && pattern[pi] == b'*' {
            star_pi = pi;
            star_ti = ti;
            pi += 1;
        } else if star_pi != usize::MAX {
            pi = star_pi + 1;
            star_ti += 1;
            ti = star_ti;
        } else {
            return false;
        }
    }

    while pi < pattern.len() && pattern[pi] == b'*' {
        pi += 1;
    }

    pi == pattern.len()
}

/// Check if a file path matches any pattern in a config's test patterns.
pub fn is_test_path(path: &str, patterns: &[String]) -> bool {
    let lower = path.to_lowercase();
    patterns.iter().any(|p| matches_glob(&lower, &p.to_lowercase()))
}

/// Check if a file path matches any pattern in a config's oracle exclude patterns.
pub fn is_excluded_path(path: &str, patterns: &[String]) -> bool {
    let lower = path.to_lowercase();
    patterns.iter().any(|p| matches_glob(&lower, &p.to_lowercase()))
}

// ============================================================================
// Question generation (discovery mode)
// ============================================================================

/// Generate data-driven questions by analyzing the config and graph structure.
pub fn generate_questions(config: &AutoConfig, mubase: &MUbase) -> Result<Vec<String>> {
    let mut questions = Vec::new();

    // 1. Services with ambiguous/auxiliary-sounding names
    let aux_hints = ["chatagent", "tool", "script", "util", "helper", "sample", "demo", "example"];
    for service in &config.codebase.services {
        let lower = service.to_lowercase();
        if aux_hints.iter().any(|h| lower.contains(h)) {
            questions.push(format!(
                "Is '{}' a core service or auxiliary/experimental? This affects search ranking.",
                service
            ));
        }
    }

    // 2. Services sharing a keyword — possible disambiguation needed
    if config.codebase.services.len() >= 2 {
        let mut word_to_services: HashMap<String, Vec<&str>> = HashMap::new();
        for service in &config.codebase.services {
            // Extract meaningful words from service path (skip common prefixes like src/)
            let name = service.rsplit('/').next().unwrap_or(service);
            for word in name.split(&['-', '_', '.'][..]) {
                let w = word.to_lowercase();
                if w.len() >= 4 && !["src", "main", "test", "core"].contains(&w.as_str()) {
                    word_to_services.entry(w).or_default().push(service.as_str());
                }
            }
        }
        let total_services = config.codebase.services.len();
        for (word, svcs) in &word_to_services {
            if svcs.len() < 2 {
                continue;
            }

            // Skip namespace prefixes: keyword in >80% of services is just a shared prefix
            if total_services >= 3 && svcs.len() as f64 / total_services as f64 > 0.8 {
                continue;
            }

            // Skip test-project siblings: "src/foo" + "tests/foo.Tests" are the same domain
            let is_test_sibling = svcs.len() == 2 && svcs.iter().any(|s| {
                let lower = s.to_lowercase();
                lower.contains("/test") || lower.ends_with(".tests") || lower.ends_with(".test")
            });
            if is_test_sibling {
                continue;
            }

            questions.push(format!(
                "I found '{}' in multiple services: {}. Are these separate domains or the same concept?",
                word,
                svcs.join(", ")
            ));
        }
    }

    // 3. Top priority nodes dominated by a single file
    let mut file_counts: HashMap<String, usize> = HashMap::new();
    for nid in config.enrichment.priority_nodes.iter().take(20) {
        // node_ids look like "fn:path/to/file.rs:func_name" — extract the file part
        if let Some(rest) = nid.split_once(':').map(|(_, r)| r) {
            if let Some(file) = rest.rsplit_once(':').map(|(f, _)| f) {
                *file_counts.entry(file.to_string()).or_insert(0) += 1;
            }
        }
    }
    for (file, count) in &file_counts {
        if *count > 3 {
            questions.push(format!(
                "Top priority nodes are dominated by {} ({} of top 20). Are there other critical files I'm missing?",
                file, count
            ));
        }
    }

    // 4. High in-degree nodes not in priority list
    let high_dep_result = mubase.query(
        "SELECT n.name, COUNT(*) as dep_count
         FROM edges e
         JOIN nodes n ON e.target_id = n.id
         WHERE n.type IN ('class', 'function', 'interface')
           AND n.node_category = 'production'
         GROUP BY n.name, n.id
         ORDER BY dep_count DESC
         LIMIT 10",
    );

    if let Ok(result) = high_dep_result {
        let priority_names: Vec<String> = config.enrichment.priority_nodes.iter()
            .filter_map(|nid| nid.rsplit(':').next().map(|s| s.to_string()))
            .collect();

        let mut missing: Vec<String> = Vec::new();
        for row in &result.rows {
            if let (Some(name), Some(count)) = (
                row.first().and_then(|v| v.as_str()),
                row.get(1).and_then(|v| v.as_i64()),
            ) {
                if !priority_names.iter().any(|pn| pn == name) {
                    missing.push(format!("{} ({} deps)", name, count));
                }
            }
        }
        if !missing.is_empty() {
            let display: Vec<&str> = missing.iter().take(5).map(|s| s.as_str()).collect();
            questions.push(format!(
                "These types have the most dependents but aren't in the priority list: {}. Should any be added?",
                display.join(", ")
            ));
        }
    }

    // 5. Ask about test handling
    questions.push(
        "Should test projects be completely excluded from search or just dampened (current: dampened 0.3x)?".to_string()
    );

    Ok(questions)
}

/// Find high-importance nodes that would benefit from enrichment (no summary yet).
pub fn suggest_enrichment_nodes(mubase: &MUbase) -> Result<Vec<String>> {
    let result = mubase.query(
        "SELECT id FROM nodes
         WHERE type IN ('class', 'function', 'interface')
           AND importance_score > 0
           AND (summary_text IS NULL OR summary_text = '')
           AND node_category = 'production'
         ORDER BY importance_score DESC
         LIMIT 30",
    )?;

    Ok(result.rows.iter()
        .filter_map(|r| r.first().and_then(|v| v.as_str()).map(|s| s.to_string()))
        .collect())
}

// ============================================================================
// Corrections (interactive mode)
// ============================================================================

/// Apply LLM corrections to an existing config.
///
/// Parses a JSON corrections object and merges into the config.
/// Supported keys:
/// - `service_classifications`: `{"svc": "auxiliary"|"core"}` — moves services to auxiliary list
/// - `domain_concepts`: `{"keyword": "description"}` — adds domain disambiguation
/// - `add_priority_nodes`: `["Name1", "Name2"]` — resolves names to node_ids and appends
/// - `remove_priority_nodes`: `["Name1"]` — removes matching entries
/// - `test_handling`: `"dampen"` | `"exclude"` — adjusts test dampening (0.3 vs 0.0)
/// - `auxiliary_dampening`: float — override the auxiliary service dampening factor
pub fn apply_corrections(config: &mut AutoConfig, corrections_json: &str, mubase: &MUbase) -> Result<String> {
    let corrections: serde_json::Value = serde_json::from_str(corrections_json)
        .map_err(|e| anyhow::anyhow!("invalid corrections JSON: {}", e))?;

    let mut applied = Vec::new();

    // service_classifications
    if let Some(obj) = corrections.get("service_classifications").and_then(|v| v.as_object()) {
        for (svc, classification) in obj {
            let class_str = classification.as_str().unwrap_or("core");
            if class_str == "auxiliary" {
                if !config.codebase.auxiliary_services.contains(svc) {
                    config.codebase.auxiliary_services.push(svc.clone());
                }
                applied.push(format!("Classified '{}' as auxiliary", svc));
            } else {
                // Remove from auxiliary if reclassified as core
                config.codebase.auxiliary_services.retain(|s| s != svc);
                applied.push(format!("Classified '{}' as core", svc));
            }
        }
    }

    // domain_concepts
    if let Some(obj) = corrections.get("domain_concepts").and_then(|v| v.as_object()) {
        for (keyword, description) in obj {
            let desc = description.as_str().unwrap_or("");
            config.domain_concepts.insert(keyword.clone(), desc.to_string());
            applied.push(format!("Added domain concept: '{}'", keyword));
        }
    }

    // add_priority_nodes — resolve names to full node_ids
    if let Some(arr) = corrections.get("add_priority_nodes").and_then(|v| v.as_array()) {
        for name_val in arr {
            if let Some(name) = name_val.as_str() {
                // Look up the node by name to get the full node_id
                let lookup = mubase.query_params(
                    "SELECT id FROM nodes
                     WHERE name = ?1
                       AND type IN ('class', 'function', 'interface')
                       AND node_category = 'production'
                     ORDER BY importance_score DESC
                     LIMIT 1",
                    &[&name as &dyn duckdb::ToSql],
                );
                if let Ok(result) = lookup {
                    if let Some(node_id) = result.rows.first()
                        .and_then(|r| r.first().and_then(|v| v.as_str()))
                    {
                        if !config.enrichment.priority_nodes.contains(&node_id.to_string()) {
                            config.enrichment.priority_nodes.push(node_id.to_string());
                            applied.push(format!("Added priority node: {} ({})", name, node_id));
                        }
                    } else {
                        applied.push(format!("Could not find node for '{}'", name));
                    }
                }
            }
        }
    }

    // remove_priority_nodes
    if let Some(arr) = corrections.get("remove_priority_nodes").and_then(|v| v.as_array()) {
        for name_val in arr {
            if let Some(name) = name_val.as_str() {
                let before = config.enrichment.priority_nodes.len();
                config.enrichment.priority_nodes.retain(|nid| {
                    nid.rsplit(':').next() != Some(name)
                });
                let removed = before - config.enrichment.priority_nodes.len();
                if removed > 0 {
                    applied.push(format!("Removed priority node: {}", name));
                }
            }
        }
    }

    // test_handling
    if let Some(handling) = corrections.get("test_handling").and_then(|v| v.as_str()) {
        match handling {
            "exclude" => {
                config.filters.search_test_dampening = 0.0;
                applied.push("Test handling: exclude (dampening=0.0)".to_string());
            }
            _ => {
                config.filters.search_test_dampening = 0.3;
                applied.push("Test handling: dampen (dampening=0.3)".to_string());
            }
        }
    }

    // auxiliary_dampening override
    if let Some(val) = corrections.get("auxiliary_dampening").and_then(|v| v.as_f64()) {
        config.filters.auxiliary_dampening = val as f32;
        applied.push(format!("Auxiliary dampening set to {}", val));
    }

    if applied.is_empty() {
        Ok("No corrections applied — check the JSON format.".to_string())
    } else {
        Ok(format!("Applied {} corrections:\n{}", applied.len(), applied.iter()
            .map(|a| format!("- {}", a))
            .collect::<Vec<_>>()
            .join("\n")))
    }
}

// ============================================================================
// Auxiliary service helpers
// ============================================================================

/// Check if a file path belongs to an auxiliary service.
pub fn is_auxiliary_service(file_path: &str, auxiliary_services: &[String]) -> bool {
    let lower = file_path.to_lowercase();
    auxiliary_services.iter().any(|svc| lower.starts_with(&svc.to_lowercase()))
}

// ============================================================================
// Summary formatter
// ============================================================================

/// Human-readable summary of the auto-detected config (post-save).
pub fn format_summary(config: &AutoConfig) -> String {
    let mut out = String::new();

    out.push_str("# MU Auto-Configuration\n\n");

    // Codebase section
    out.push_str("## Codebase\n");
    out.push_str(&format!("- Language: {}\n", config.codebase.primary_language));
    out.push_str(&format!("- Size: {}\n", config.codebase.estimated_size));
    if !config.codebase.frameworks.is_empty() {
        out.push_str(&format!("- Frameworks: {}\n", config.codebase.frameworks.join(", ")));
    }
    if !config.codebase.services.is_empty() {
        out.push_str(&format!("- Services: {}\n", config.codebase.services.join(", ")));
    }
    if !config.codebase.auxiliary_services.is_empty() {
        out.push_str(&format!("- Auxiliary services: {}\n", config.codebase.auxiliary_services.join(", ")));
    }
    out.push('\n');

    // Domain concepts
    if !config.domain_concepts.is_empty() {
        out.push_str("## Domain Concepts\n");
        for (keyword, desc) in &config.domain_concepts {
            out.push_str(&format!("- **{}**: {}\n", keyword, desc));
        }
        out.push('\n');
    }

    // Filters section
    out.push_str("## Filters\n");
    out.push_str(&format!("- Test dampening: {}\n", config.filters.search_test_dampening));
    out.push_str(&format!("- Auxiliary dampening: {}\n", config.filters.auxiliary_dampening));
    if !config.filters.test_patterns.is_empty() {
        out.push_str(&format!("- Test patterns ({}): {}\n",
            config.filters.test_patterns.len(),
            config.filters.test_patterns.join(", ")));
    }
    if !config.filters.generated_patterns.is_empty() {
        out.push_str(&format!("- Generated patterns ({}): {}\n",
            config.filters.generated_patterns.len(),
            config.filters.generated_patterns.join(", ")));
    }
    out.push('\n');

    // Oracle section
    out.push_str("## Oracle\n");
    out.push_str(&format!("- Test budget cap: {}%\n", (config.oracle.test_budget_cap * 100.0) as u32));
    if !config.oracle.exclude_patterns.is_empty() {
        out.push_str(&format!("- Exclude patterns ({}): {}\n",
            config.oracle.exclude_patterns.len(),
            config.oracle.exclude_patterns.join(", ")));
    }
    out.push('\n');

    // Enrichment section
    out.push_str("## Enrichment\n");
    out.push_str(&format!("- Top-N for auto-enrich: {}\n", config.enrichment.auto_enrich_top_n));
    out.push_str(&format!("- Priority nodes: {}\n", config.enrichment.priority_nodes.len()));
    if !config.enrichment.priority_nodes.is_empty() {
        for nid in config.enrichment.priority_nodes.iter().take(10) {
            out.push_str(&format!("  - {}\n", nid));
        }
        if config.enrichment.priority_nodes.len() > 10 {
            out.push_str(&format!("  - ... and {} more\n",
                config.enrichment.priority_nodes.len() - 10));
        }
    }

    out.push_str("\nConfig saved to `.mu/config.toml`\n");
    out
}

/// Format the discovery-mode output: draft config + questions + enrichment suggestions.
///
/// This is returned when mu_configure is called with no corrections.
pub fn format_discovery_summary(
    config: &AutoConfig,
    questions: &[String],
    enrichment_ids: &[String],
) -> String {
    let mut out = String::new();

    out.push_str("# MU Auto-Configuration (DRAFT — review and correct)\n\n");

    // Detected structure (same as format_summary minus the "saved" footer)
    out.push_str("## Detected Structure\n");
    out.push_str(&format!("- Language: {}\n", config.codebase.primary_language));
    out.push_str(&format!("- Size: {}\n", config.codebase.estimated_size));
    if !config.codebase.frameworks.is_empty() {
        out.push_str(&format!("- Frameworks: {}\n", config.codebase.frameworks.join(", ")));
    }
    if !config.codebase.services.is_empty() {
        out.push_str(&format!("- Services ({}): {}\n",
            config.codebase.services.len(),
            config.codebase.services.join(", ")));
    }
    out.push_str(&format!("- Test dampening: {}\n", config.filters.search_test_dampening));
    out.push_str(&format!("- Priority nodes: {}\n", config.enrichment.priority_nodes.len()));
    if !config.enrichment.priority_nodes.is_empty() {
        for nid in config.enrichment.priority_nodes.iter().take(10) {
            out.push_str(&format!("  - {}\n", nid));
        }
        if config.enrichment.priority_nodes.len() > 10 {
            out.push_str(&format!("  - ... and {} more\n",
                config.enrichment.priority_nodes.len() - 10));
        }
    }
    out.push('\n');

    // Questions for review
    if !questions.is_empty() {
        out.push_str("## Questions for Review\n");
        for (i, q) in questions.iter().enumerate() {
            out.push_str(&format!("{}. {}\n", i + 1, q));
        }
        out.push('\n');
    }

    // Enrichment suggestions
    if !enrichment_ids.is_empty() {
        out.push_str("## Suggested Enrichment Targets\n");
        out.push_str("These high-importance nodes have no summary yet. Run `mu_enrich` to improve search quality.\n");
        for nid in enrichment_ids.iter().take(15) {
            out.push_str(&format!("- {}\n", nid));
        }
        if enrichment_ids.len() > 15 {
            out.push_str(&format!("- ... and {} more\n", enrichment_ids.len() - 15));
        }
        out.push('\n');
    }

    // Correction instructions
    out.push_str("## To apply corrections\n");
    out.push_str("Call `mu_configure` with a `corrections` parameter (JSON):\n");
    out.push_str("```json\n");
    out.push_str("{\n");
    out.push_str("  \"service_classifications\": {\"service-name\": \"auxiliary\"},\n");
    out.push_str("  \"domain_concepts\": {\"keyword\": \"disambiguation description\"},\n");
    out.push_str("  \"add_priority_nodes\": [\"ClassName\", \"function_name\"],\n");
    out.push_str("  \"remove_priority_nodes\": [\"OldName\"],\n");
    out.push_str("  \"test_handling\": \"dampen\"\n");
    out.push_str("}\n");
    out.push_str("```\n");

    out
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_matches_glob_star() {
        assert!(matches_glob("src/test/foo.rs", "*/test/*"));
        assert!(matches_glob("src/tests/bar.rs", "*/tests/*"));
        assert!(!matches_glob("src/testing/foo.rs", "*/test/*"));
    }

    #[test]
    fn test_matches_glob_extension() {
        assert!(matches_glob("Foo.Designer.cs", "*.Designer.cs"));
        assert!(matches_glob("src/Models/Foo.Designer.cs", "*.Designer.cs"));
        assert!(!matches_glob("src/Models/FooDesigner.cs", "*.Designer.cs"));
    }

    #[test]
    fn test_matches_glob_suffix() {
        assert!(matches_glob("PaymentServiceTests.cs", "*Tests.cs"));
        assert!(matches_glob("src/PaymentServiceTests.cs", "*Tests.cs"));
        assert!(!matches_glob("src/PaymentService.cs", "*Tests.cs"));
    }

    #[test]
    fn test_matches_glob_prefix() {
        assert!(matches_glob("test_search.py", "test_*"));
        assert!(!matches_glob("my_test.py", "test_*"));
    }

    #[test]
    fn test_matches_glob_middle_pattern() {
        assert!(matches_glob("src/Migrations/20240101_Init.cs", "*/Migrations/*.cs"));
        assert!(!matches_glob("src/Migrations/readme.md", "*/Migrations/*.cs"));
    }

    #[test]
    fn test_matches_glob_double_star_like() {
        assert!(matches_glob("a/b/obj/c/d", "*/obj/*"));
    }

    #[test]
    fn test_is_test_path() {
        let patterns = vec!["*/test/*".into(), "*Tests.cs".into(), "*_test.py".into()];
        assert!(is_test_path("src/test/foo.rs", &patterns));
        assert!(is_test_path("PaymentServiceTests.cs", &patterns));
        assert!(is_test_path("search_test.py", &patterns));
        assert!(!is_test_path("src/engine/search.rs", &patterns));
    }

    #[test]
    fn test_is_excluded_path() {
        let patterns = vec!["*/Migrations/*.cs".into(), "*/obj/*".into()];
        assert!(is_excluded_path("src/Migrations/Init.cs", &patterns));
        assert!(is_excluded_path("project/obj/Debug/foo.dll", &patterns));
        assert!(!is_excluded_path("src/Services/Foo.cs", &patterns));
    }

    #[test]
    fn test_default_config_has_sane_values() {
        let cfg = AutoConfig::default();
        assert_eq!(cfg.filters.search_test_dampening, 0.3);
        assert_eq!(cfg.filters.auxiliary_dampening, 0.7);
        assert_eq!(cfg.oracle.test_budget_cap, 0.1);
        assert!(!cfg.filters.test_patterns.is_empty());
        assert!(cfg.codebase.auxiliary_services.is_empty());
        assert!(cfg.domain_concepts.is_empty());
    }

    #[test]
    fn test_config_roundtrip_toml() {
        let cfg = AutoConfig::default();
        let toml_str = toml::to_string_pretty(&cfg).unwrap();
        let parsed: AutoConfig = toml::from_str(&toml_str).unwrap();
        assert_eq!(parsed.filters.search_test_dampening, cfg.filters.search_test_dampening);
        assert_eq!(parsed.codebase.primary_language, cfg.codebase.primary_language);
        assert_eq!(parsed.oracle.test_budget_cap, cfg.oracle.test_budget_cap);
        assert_eq!(parsed.enrichment.auto_enrich_top_n, cfg.enrichment.auto_enrich_top_n);
    }

    #[test]
    fn test_estimate_size_labels() {
        // These are just the string labels — the actual detection needs a DB
        assert_eq!("small", if 100 < 500 { "small" } else { "other" });
        assert_eq!("medium", if 2000 < 5000 { "medium" } else { "other" });
        assert_eq!("large", if 10000 >= 5000 { "large" } else { "other" });
    }

    #[test]
    fn test_format_summary_output() {
        let cfg = AutoConfig::default();
        let summary = format_summary(&cfg);
        assert!(summary.contains("# MU Auto-Configuration"));
        assert!(summary.contains("Language: unknown"));
        assert!(summary.contains("Test dampening: 0.3"));
        assert!(summary.contains("config.toml"));
    }

    #[test]
    fn test_load_returns_none_for_missing_file() {
        let tmp = tempfile::tempdir().unwrap();
        assert!(AutoConfig::load(tmp.path()).is_none());
    }

    #[test]
    fn test_save_and_load_roundtrip() {
        let tmp = tempfile::tempdir().unwrap();
        std::fs::create_dir_all(tmp.path().join(".mu")).unwrap();
        let cfg = AutoConfig::default();
        cfg.save(tmp.path()).unwrap();
        let loaded = AutoConfig::load(tmp.path()).unwrap();
        assert_eq!(loaded.filters.search_test_dampening, 0.3);
        assert_eq!(loaded.filters.auxiliary_dampening, 0.7);
        assert_eq!(loaded.codebase.primary_language, "unknown");
        assert!(loaded.codebase.auxiliary_services.is_empty());
        assert!(loaded.domain_concepts.is_empty());
    }

    #[test]
    fn test_save_and_load_with_new_fields() {
        let tmp = tempfile::tempdir().unwrap();
        std::fs::create_dir_all(tmp.path().join(".mu")).unwrap();
        let mut cfg = AutoConfig::default();
        cfg.codebase.auxiliary_services = vec!["src/chatagent".into()];
        cfg.domain_concepts.insert("compliance".into(), "Two domains: KYC and NAV".into());
        cfg.save(tmp.path()).unwrap();
        let loaded = AutoConfig::load(tmp.path()).unwrap();
        assert_eq!(loaded.codebase.auxiliary_services, vec!["src/chatagent"]);
        assert_eq!(loaded.domain_concepts.get("compliance").unwrap(), "Two domains: KYC and NAV");
    }

    #[test]
    fn test_backward_compat_load_without_new_fields() {
        // Config files from before this change won't have domain_concepts etc.
        let tmp = tempfile::tempdir().unwrap();
        std::fs::create_dir_all(tmp.path().join(".mu")).unwrap();
        let old_toml = r#"
[filters]
test_patterns = ["*/test/*"]
generated_patterns = ["*.Designer.cs"]
search_test_dampening = 0.3

[codebase]
primary_language = "csharp"
frameworks = ["ef-core"]
services = ["src/api"]
estimated_size = "large"

[enrichment]
priority_nodes = ["class:src/Foo.cs:Foo"]
auto_enrich_top_n = 50

[oracle]
exclude_patterns = ["*/obj/*"]
test_budget_cap = 0.1
"#;
        std::fs::write(tmp.path().join(".mu/config.toml"), old_toml).unwrap();
        let loaded = AutoConfig::load(tmp.path()).unwrap();
        assert_eq!(loaded.filters.auxiliary_dampening, 0.7); // default
        assert!(loaded.codebase.auxiliary_services.is_empty()); // default
        assert!(loaded.domain_concepts.is_empty()); // default
    }

    #[test]
    fn test_is_auxiliary_service() {
        let aux = vec!["src/gateway-chatagent".into(), "tools/scripts".into()];
        assert!(is_auxiliary_service("src/gateway-chatagent/main.py", &aux));
        assert!(is_auxiliary_service("tools/scripts/build.sh", &aux));
        assert!(!is_auxiliary_service("src/gateway-api/Program.cs", &aux));
    }

    #[test]
    fn test_discovery_summary_format() {
        let cfg = AutoConfig::default();
        let questions = vec![
            "Is 'chatagent' core or auxiliary?".into(),
            "Should test files be excluded?".into(),
        ];
        let enrichment = vec!["fn:src/main.rs:main".into()];
        let summary = format_discovery_summary(&cfg, &questions, &enrichment);
        assert!(summary.contains("DRAFT"));
        assert!(summary.contains("Questions for Review"));
        assert!(summary.contains("chatagent"));
        assert!(summary.contains("Suggested Enrichment"));
        assert!(summary.contains("corrections"));
    }

    #[test]
    #[ignore = "Requires real .mu/mubase at project root"]
    fn test_generate_on_real_mubase() {
        let mubase_path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent().unwrap()
            .join(".mu/mubase");
        if !mubase_path.exists() {
            eprintln!("Skipping: no mubase at {:?}", mubase_path);
            return;
        }
        let mubase = MUbase::open_read_only(&mubase_path).unwrap();
        let config = AutoConfig::generate(&mubase).unwrap();

        // MU's own codebase should be detected as Rust
        assert_eq!(config.codebase.primary_language, "rust");
        // Should detect rmcp as a framework
        assert!(config.codebase.frameworks.contains(&"mcp-server".to_string()),
            "Expected mcp-server framework, got: {:?}", config.codebase.frameworks);
        // Should have some priority nodes
        assert!(!config.enrichment.priority_nodes.is_empty());
        // Should be medium or large
        assert!(config.codebase.estimated_size == "medium" || config.codebase.estimated_size == "large",
            "Expected medium/large, got: {}", config.codebase.estimated_size);

        eprintln!("{}", format_summary(&config));
    }
}
