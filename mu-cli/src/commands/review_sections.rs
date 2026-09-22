//! Review sections that answer the cross-service questions a compiler cannot:
//! which message contracts a change touches and who consumes them, and who
//! constructs a class whose constructor signature changed.
//!
//! Both exist because of shipped gateway incidents. The contract section is
//! the one output reviewers of PR #3364 / #3416 would have wanted. The
//! constructor section is for 2026-08-08, when two green PRs merged into a red
//! dev because target-typed `new(...)` call sites in tests defeated a grep.

use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::path::Path;

use serde::Serialize;

use crate::commands::diff::SemanticChange;
use crate::engine::storage::MUbase;

// ============================================================================
// Message contracts
// ============================================================================

/// One publisher or consumer of a message contract.
#[derive(Debug, Clone, Serialize, PartialEq, Eq, PartialOrd, Ord)]
pub struct ContractParty {
    pub service: String,
    pub symbol: String,
    pub file_path: String,
}

/// A changed type that has publish or subscribe edges in the index.
#[derive(Debug, Clone, Serialize)]
pub struct ContractImpact {
    pub name: String,
    pub file_path: String,
    pub change_type: String,
    pub publishers: Vec<ContractParty>,
    pub consumers: Vec<ContractParty>,
    /// Publishers/consumers living under test paths, counted not listed.
    pub test_references: usize,
}

/// Service name from a repo-relative path. `src/dominaite-gateway-order/...`
/// gives `dominaite-gateway-order`; a `.Tests` suffix is stripped so a test
/// project groups with the service it tests.
pub fn service_of(path: &str) -> String {
    let skip = [
        "src", "tests", "test", "lib", "app", "apps", "services", ".",
    ];
    let seg = path
        .split('/')
        .find(|s| !s.is_empty() && !skip.contains(s))
        .unwrap_or("");
    let seg = seg.strip_suffix(".Tests").unwrap_or(seg);
    if seg.contains('.') {
        // A file directly under the root; no service to speak of.
        return String::from("(root)");
    }
    seg.to_string()
}

/// Test code by path convention: a `tests/` or `test/` segment, or a
/// `*.Tests` project directory.
pub fn is_test_path(path: &str) -> bool {
    path.split('/')
        .any(|s| s == "tests" || s == "test" || s == "__tests__" || s.ends_with(".Tests"))
}

/// Changed (type name, file, change kind) candidates for contract lookup.
/// A change to a member counts as a modification of its parent type.
fn candidate_types(changes: &[SemanticChange]) -> BTreeMap<(String, String), String> {
    let type_kinds = ["class", "record", "struct", "interface"];
    let mut out: BTreeMap<(String, String), String> = BTreeMap::new();
    for c in changes {
        let Some(file) = c.file_path.as_deref() else {
            continue;
        };
        if type_kinds.contains(&c.entity_type.as_str()) {
            out.entry((bare_name(c).to_string(), file.to_string()))
                .and_modify(|k| {
                    if k == "modified" {
                        *k = c.change_type.clone();
                    }
                })
                .or_insert_with(|| c.change_type.clone());
        } else if let Some(parent) = &c.parent_name {
            out.entry((parent.clone(), file.to_string()))
                .or_insert_with(|| "modified".to_string());
        }
    }
    out
}

/// Look up publishers and consumers for every changed type. Types with no
/// publish/subscribe edge are not contracts and are skipped.
pub fn message_contracts(mubase: &MUbase, changes: &[SemanticChange]) -> Vec<ContractImpact> {
    let mut out = Vec::new();
    for ((name, file), change_type) in candidate_types(changes) {
        let rows = match mubase.query_params(
            "SELECT e.type, n.name, n.file_path FROM edges e
             JOIN nodes n ON n.id = e.source_id
             WHERE e.type IN ('publishes', 'subscribes')
               AND (e.target_id = 'msg:' || ?1
                    OR e.target_id IN (SELECT id FROM nodes WHERE name = ?1
                                       AND (file_path = ?2 OR file_path LIKE '%/' || ?2)))
             LIMIT 500",
            &[&name as &dyn duckdb::ToSql, &file as &dyn duckdb::ToSql],
        ) {
            Ok(r) => r.rows,
            Err(_) => continue,
        };
        if rows.is_empty() {
            continue;
        }
        let mut publishers = BTreeSet::new();
        let mut consumers = BTreeSet::new();
        let mut test_references = 0usize;
        for row in &rows {
            let edge = row.first().and_then(|v| v.as_str()).unwrap_or("");
            let symbol = row.get(1).and_then(|v| v.as_str()).unwrap_or("");
            let path = row.get(2).and_then(|v| v.as_str()).unwrap_or("");
            if is_test_path(path) {
                test_references += 1;
                continue;
            }
            let party = ContractParty {
                service: service_of(path),
                symbol: symbol.to_string(),
                file_path: path.to_string(),
            };
            match edge {
                "publishes" => {
                    publishers.insert(party);
                }
                "subscribes" => {
                    consumers.insert(party);
                }
                _ => {}
            }
        }
        out.push(ContractImpact {
            name,
            file_path: file,
            change_type,
            publishers: publishers.into_iter().collect(),
            consumers: consumers.into_iter().collect(),
            test_references,
        });
    }
    out
}

// ============================================================================
// Constructor changes
// ============================================================================

/// A source location that constructs or registers a class.
#[derive(Debug, Clone, Serialize, PartialEq, Eq, PartialOrd, Ord)]
pub struct Site {
    pub file_path: String,
    pub line: u32,
}

/// Where a class with a changed constructor gets constructed.
#[derive(Debug, Clone, Serialize)]
pub struct ConstructorChange {
    pub class_name: String,
    pub file_path: String,
    pub description: Option<String>,
    /// `new ClassName(` sites. Exact.
    pub explicit_sites: Vec<Site>,
    /// `new(` on a line that names the class. Probable, a human confirms.
    pub target_typed_sites: Vec<Site>,
    /// `.AddX<..ClassName..>` DI registrations. The container resolves the
    /// new parameters at runtime, so these need the new dependencies registered.
    pub di_registrations: Vec<Site>,
    /// Files with a construction site that this diff does not touch. These
    /// are the ones that turn dev red after the merge.
    pub files_outside_diff: Vec<String>,
}

/// Constructor sites found in one file's text.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct CtorSites {
    pub explicit: Vec<u32>,
    pub target_typed: Vec<u32>,
    pub di: Vec<u32>,
}

fn is_ident_char(c: char) -> bool {
    c.is_alphanumeric() || c == '_'
}

/// Whole-word containment.
pub fn contains_word(line: &str, word: &str) -> bool {
    let mut start = 0;
    while let Some(pos) = line[start..].find(word) {
        let at = start + pos;
        let end = at + word.len();
        let before_ok = at == 0 || !is_ident_char(line[..at].chars().next_back().unwrap());
        let after_ok = end == line.len() || !is_ident_char(line[end..].chars().next().unwrap());
        if before_ok && after_ok {
            return true;
        }
        start = at + word.len().max(1);
    }
    false
}

/// `new ClassName(` / `new ClassName<` / `new ClassName {` on this line.
fn has_explicit_new(line: &str, class_name: &str) -> bool {
    let mut start = 0;
    while let Some(pos) = line[start..].find("new ") {
        let rest = line[start + pos + 4..].trim_start();
        if let Some(after) = rest.strip_prefix(class_name) {
            let next = after.trim_start().chars().next();
            let ident_continues = after.chars().next().map(is_ident_char).unwrap_or(false);
            if !ident_continues && matches!(next, Some('(') | Some('<') | Some('{')) {
                return true;
            }
        }
        start += pos + 4;
    }
    false
}

/// `new(` or `new (` on this line.
fn has_target_typed_new(line: &str) -> bool {
    let mut start = 0;
    while let Some(pos) = line[start..].find("new") {
        let at = start + pos;
        let before_ok = at == 0 || !is_ident_char(line[..at].chars().next_back().unwrap());
        let after = line[at + 3..].trim_start();
        if before_ok && after.starts_with('(') {
            return true;
        }
        start = at + 3;
    }
    false
}

/// `.AddScoped<IFoo, Foo>()`, `.AddSingleton<Foo>()`, `.AddHostedService<Foo>()`.
fn has_di_registration(line: &str, class_name: &str) -> bool {
    let Some(pos) = line.find(".Add") else {
        return false;
    };
    let Some(lt) = line[pos..].find('<') else {
        return false;
    };
    let Some(gt) = line[pos + lt..].find('>') else {
        return false;
    };
    contains_word(&line[pos + lt..pos + lt + gt], class_name)
}

/// Scan one file's text for places that construct or register `class_name`.
pub fn find_ctor_sites(content: &str, class_name: &str) -> CtorSites {
    let mut out = CtorSites::default();
    for (i, line) in content.lines().enumerate() {
        let n = i as u32 + 1;
        let trimmed = line.trim_start();
        if trimmed.starts_with("//") {
            continue;
        }
        if has_di_registration(line, class_name) {
            out.di.push(n);
            continue;
        }
        if has_explicit_new(line, class_name) {
            out.explicit.push(n);
        } else if has_target_typed_new(line) && contains_word(line, class_name) {
            out.target_typed.push(n);
        }
    }
    out
}

/// Symbol name without the `Parent.` prefix the differ adds for display.
pub fn bare_name(change: &SemanticChange) -> &str {
    match &change.parent_name {
        Some(p) => change
            .entity_name
            .strip_prefix(p.as_str())
            .and_then(|r| r.strip_prefix('.'))
            .unwrap_or(&change.entity_name),
        None => &change.entity_name,
    }
}

/// Changed constructors: a modified method named like its parent class whose
/// parameters changed. Constructors are the only methods named like the class.
fn changed_constructors(changes: &[SemanticChange]) -> Vec<(String, String, Option<String>)> {
    let mut seen = HashSet::new();
    let mut out = Vec::new();
    for c in changes {
        if c.entity_type != "method" || c.change_type != "modified" {
            continue;
        }
        if c.parent_name.as_deref() != Some(bare_name(c)) {
            continue;
        }
        let params_changed = c
            .description
            .as_deref()
            .map(|d| d.contains("param"))
            .unwrap_or(false);
        if !params_changed {
            continue;
        }
        let Some(file) = c.file_path.clone() else {
            continue;
        };
        let name = bare_name(c).to_string();
        if seen.insert((name.clone(), file.clone())) {
            out.push((name, file, c.description.clone()));
        }
    }
    out
}

/// Walk the working tree (same extension as the class file) and collect
/// construction sites for every changed constructor.
pub fn constructor_changes(
    project_root: &Path,
    changes: &[SemanticChange],
    changed_files: &[String],
) -> Vec<ConstructorChange> {
    let ctors = changed_constructors(changes);
    if ctors.is_empty() {
        return Vec::new();
    }
    let changed: HashSet<&str> = changed_files.iter().map(|s| s.as_str()).collect();

    let exts: BTreeSet<String> = ctors
        .iter()
        .filter_map(|(_, f, _)| {
            Path::new(f)
                .extension()
                .map(|e| e.to_string_lossy().to_string())
        })
        .collect();
    let options = mu_core::scanner::ScanOptions {
        extensions: Some(exts.into_iter().collect()),
        ..Default::default()
    };
    let files = match mu_core::scanner::scan_with_options(&project_root.to_string_lossy(), options)
    {
        Ok(r) => r.files,
        Err(_) => return Vec::new(),
    };

    let mut results: Vec<ConstructorChange> = ctors
        .into_iter()
        .map(|(class_name, file_path, description)| ConstructorChange {
            class_name,
            file_path,
            description,
            explicit_sites: Vec::new(),
            target_typed_sites: Vec::new(),
            di_registrations: Vec::new(),
            files_outside_diff: Vec::new(),
        })
        .collect();

    for f in &files {
        let Ok(content) = std::fs::read_to_string(project_root.join(&f.path)) else {
            continue;
        };
        for r in results.iter_mut() {
            if !content.contains(r.class_name.as_str()) {
                continue;
            }
            let sites = find_ctor_sites(&content, &r.class_name);
            let push = |v: &mut Vec<Site>, lines: &[u32]| {
                v.extend(lines.iter().map(|&line| Site {
                    file_path: f.path.clone(),
                    line,
                }))
            };
            push(&mut r.explicit_sites, &sites.explicit);
            push(&mut r.target_typed_sites, &sites.target_typed);
            push(&mut r.di_registrations, &sites.di);
            let constructs = !sites.explicit.is_empty() || !sites.target_typed.is_empty();
            if constructs && !changed.contains(f.path.as_str()) && f.path != r.file_path {
                r.files_outside_diff.push(f.path.clone());
            }
        }
    }
    for r in results.iter_mut() {
        r.explicit_sites.sort();
        r.target_typed_sites.sort();
        r.di_registrations.sort();
        r.files_outside_diff.sort();
        r.files_outside_diff.dedup();
    }
    results
}

// ============================================================================
// Rendering
// ============================================================================

fn files_of(sites: &[Site]) -> usize {
    sites
        .iter()
        .map(|s| s.file_path.as_str())
        .collect::<BTreeSet<_>>()
        .len()
}

/// Plain-text rendering shared by the table output.
pub fn render_text(contracts: &[ContractImpact], ctors: &[ConstructorChange]) -> String {
    let mut out = String::new();
    if !contracts.is_empty() {
        out.push_str(&format!(
            "MESSAGE CONTRACTS TOUCHED ({})\n",
            contracts.len()
        ));
        out.push_str(&format!("{}\n", "-".repeat(60)));
        for c in contracts {
            out.push_str(&format!(
                "  {} [{}]  {}\n",
                c.name, c.change_type, c.file_path
            ));
            for p in &c.publishers {
                out.push_str(&format!(
                    "    publishes   {:<34} {}  ({})\n",
                    p.service, p.symbol, p.file_path
                ));
            }
            for p in &c.consumers {
                out.push_str(&format!(
                    "    subscribes  {:<34} {}  ({})\n",
                    p.service, p.symbol, p.file_path
                ));
            }
            if c.consumers.is_empty() {
                out.push_str("    subscribes  (no consumer in index)\n");
            }
            if c.test_references > 0 {
                out.push_str(&format!("    tests: {} references\n", c.test_references));
            }
        }
        out.push('\n');
    }
    if !ctors.is_empty() {
        out.push_str(&format!("CONSTRUCTOR CHANGES ({})\n", ctors.len()));
        out.push_str(&format!("{}\n", "-".repeat(60)));
        for c in ctors {
            out.push_str(&format!(
                "  {}  {}  ({})\n",
                c.class_name,
                c.file_path,
                c.description.as_deref().unwrap_or("signature changed")
            ));
            out.push_str(&format!(
                "    new {}(            {} sites in {} files\n",
                c.class_name,
                c.explicit_sites.len(),
                files_of(&c.explicit_sites)
            ));
            out.push_str(&format!(
                "    target-typed new(   {} sites in {} files (line names the type; confirm by hand)\n",
                c.target_typed_sites.len(),
                files_of(&c.target_typed_sites)
            ));
            out.push_str(&format!(
                "    DI registrations    {}\n",
                c.di_registrations.len()
            ));
            if !c.files_outside_diff.is_empty() {
                out.push_str("    construction sites NOT in this diff:\n");
                for f in c.files_outside_diff.iter().take(12) {
                    out.push_str(&format!("      {}\n", f));
                }
                if c.files_outside_diff.len() > 12 {
                    out.push_str(&format!(
                        "      ... {} more\n",
                        c.files_outside_diff.len() - 12
                    ));
                }
            }
        }
        out.push('\n');
    }
    out
}

/// Markdown rendering for MCP and PR comments.
pub fn render_markdown(contracts: &[ContractImpact], ctors: &[ConstructorChange]) -> String {
    let mut md = String::new();
    if !contracts.is_empty() {
        md.push_str("## Message contracts touched\n\n");
        for c in contracts {
            md.push_str(&format!(
                "- `{}` ({}) `{}`\n",
                c.name, c.change_type, c.file_path
            ));
            for p in &c.publishers {
                md.push_str(&format!(
                    "  - publishes: **{}** `{}` ({})\n",
                    p.service, p.symbol, p.file_path
                ));
            }
            for p in &c.consumers {
                md.push_str(&format!(
                    "  - subscribes: **{}** `{}` ({})\n",
                    p.service, p.symbol, p.file_path
                ));
            }
            if c.consumers.is_empty() {
                md.push_str("  - subscribes: no consumer in index\n");
            }
            if c.test_references > 0 {
                md.push_str(&format!("  - tests: {} references\n", c.test_references));
            }
        }
        md.push('\n');
    }
    if !ctors.is_empty() {
        md.push_str("## Constructor changes\n\n");
        for c in ctors {
            md.push_str(&format!(
                "- `{}` `{}` ({})\n",
                c.class_name,
                c.file_path,
                c.description.as_deref().unwrap_or("signature changed")
            ));
            md.push_str(&format!(
                "  - `new {}(`: {} sites in {} files\n",
                c.class_name,
                c.explicit_sites.len(),
                files_of(&c.explicit_sites)
            ));
            md.push_str(&format!(
                "  - target-typed `new(`: {} sites in {} files (line names the type; confirm by hand)\n",
                c.target_typed_sites.len(),
                files_of(&c.target_typed_sites)
            ));
            md.push_str(&format!(
                "  - DI registrations: {}\n",
                c.di_registrations.len()
            ));
            if !c.files_outside_diff.is_empty() {
                md.push_str("  - construction sites NOT in this diff:\n");
                for f in c.files_outside_diff.iter().take(12) {
                    md.push_str(&format!("    - `{}`\n", f));
                }
            }
        }
        md.push('\n');
    }
    md
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn service_of_uses_the_first_meaningful_segment() {
        assert_eq!(
            service_of("src/dominaite-gateway-order/Services/OrderService.cs"),
            "dominaite-gateway-order"
        );
        assert_eq!(
            service_of("tests/dominaite-gateway-order.Tests/X.cs"),
            "dominaite-gateway-order"
        );
        assert_eq!(service_of("Program.cs"), "(root)");
    }

    #[test]
    fn test_paths_are_recognised_by_convention() {
        assert!(is_test_path("tests/dominaite-gateway-order.Tests/X.cs"));
        assert!(is_test_path("src/foo/__tests__/x.ts"));
        assert!(!is_test_path(
            "src/dominaite-gateway-order/Services/OrderService.cs"
        ));
    }

    #[test]
    fn explicit_new_matches_whole_type_only() {
        assert!(has_explicit_new(
            "var s = new OrderService(a, b);",
            "OrderService"
        ));
        assert!(has_explicit_new(
            "return new OrderService<T> { X = 1 };",
            "OrderService"
        ));
        assert!(has_explicit_new("_x = new OrderService {", "OrderService"));
        assert!(!has_explicit_new(
            "var s = new OrderServiceTests();",
            "OrderService"
        ));
        assert!(!has_explicit_new(
            "var s = new IOrderService();",
            "OrderService"
        ));
    }

    #[test]
    fn target_typed_new_needs_the_type_on_the_line() {
        let src = "private readonly OrderService _sut = new(\n    a,\n    b);\nOtherService o = new(1);\nvar renewed = Renew(x);\n";
        let s = find_ctor_sites(src, "OrderService");
        assert_eq!(s.target_typed, vec![1]);
        assert!(s.explicit.is_empty());
    }

    #[test]
    fn di_registration_is_separated_from_construction() {
        let src = "services.AddScoped<IOrderService, OrderService>();\nservices.AddSingleton<OrderService>();\nvar s = new OrderService(1);\n// var t = new OrderService(2);\n";
        let s = find_ctor_sites(src, "OrderService");
        assert_eq!(s.di, vec![1, 2]);
        assert_eq!(s.explicit, vec![3]);
        assert!(s.target_typed.is_empty(), "comment lines are skipped");
    }

    fn change(
        kind: &str,
        ty: &str,
        name: &str,
        parent: Option<&str>,
        desc: Option<&str>,
    ) -> SemanticChange {
        // The differ displays members as `Parent.name`; mirror that here.
        let entity_name = match parent {
            Some(p) => format!("{p}.{name}"),
            None => name.to_string(),
        };
        SemanticChange {
            change_type: kind.into(),
            entity_type: ty.into(),
            entity_name,
            file_path: Some("src/svc/Svc.cs".into()),
            is_breaking: false,
            description: desc.map(String::from),
            parent_name: parent.map(String::from),
        }
    }

    #[test]
    fn only_constructors_with_parameter_changes_count() {
        let changes = vec![
            change(
                "modified",
                "method",
                "Svc",
                Some("Svc"),
                Some("2 param changes"),
            ),
            change(
                "modified",
                "method",
                "Svc",
                Some("Svc"),
                Some("complexity: 1 -> 2"),
            ),
            change(
                "modified",
                "method",
                "Run",
                Some("Svc"),
                Some("1 param changes"),
            ),
            change("added", "method", "Svc", Some("Svc"), None),
        ];
        let ctors = changed_constructors(&changes);
        assert_eq!(ctors.len(), 1);
        assert_eq!(ctors[0].0, "Svc");
    }

    #[test]
    fn bare_name_strips_the_display_prefix() {
        assert_eq!(
            bare_name(&change("modified", "method", "Svc", Some("Svc"), None)),
            "Svc"
        );
        assert_eq!(
            bare_name(&change("added", "class", "Svc", None, None)),
            "Svc"
        );
    }

    #[test]
    fn member_changes_roll_up_to_their_parent_type() {
        let changes = vec![
            change("added", "method", "Amount", Some("OrderCreatedEvent"), None),
            change("added", "class", "NewEvent", None, None),
        ];
        let c = candidate_types(&changes);
        assert_eq!(
            c.get(&(
                "OrderCreatedEvent".to_string(),
                "src/svc/Svc.cs".to_string()
            ))
            .map(String::as_str),
            Some("modified")
        );
        assert_eq!(
            c.get(&("NewEvent".to_string(), "src/svc/Svc.cs".to_string()))
                .map(String::as_str),
            Some("added")
        );
    }
}
