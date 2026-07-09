//! Heuristic summary generator for V3 search.
//!
//! Generates searchable text summaries from parsed node data + graph edges.
//! No LLM calls — uses only tree-sitter data + edge relationships.
//! The key insight: encoding callers/callees as text makes graph info BM25-searchable.

use super::storage::Node;
use super::storage::NodeType;

/// Generate a heuristic summary from parsed node data + graph edges.
/// No LLM calls. Uses only what tree-sitter extracted + edge relationships.
///
/// `edges` is a slice of (source_id, target_id, edge_type) tuples for the ENTIRE graph.
pub fn generate_heuristic_summary(node: &Node, edges: &[(String, String, String)]) -> String {
    match node.node_type {
        NodeType::Function => summarize_function(node, edges),
        NodeType::Class => summarize_class(node, edges),
        NodeType::Module => summarize_module(node, edges),
        NodeType::External => format!("External dependency {}", node.name),
        NodeType::Message => summarize_message(node, edges),
    }
}

fn summarize_function(node: &Node, edges: &[(String, String, String)]) -> String {
    let mut parts = Vec::new();

    // 1. First meaningful line from source (docstring or description)
    if let Some(ref source) = node.source_text {
        if let Some(first_line) = extract_doc_line(source) {
            parts.push(first_line);
        }
    }

    // 2. Signature line
    if let Some(ref source) = node.source_text {
        if let Some(sig) = extract_signature(source) {
            parts.push(sig);
        }
    }

    // 3. Return type from properties
    if let Some(ref props) = node.properties {
        if let Some(ret) = props.get("return_type").and_then(|v| v.as_str()) {
            parts.push(format!("Returns {}", ret));
        }
    }

    // 4. Callees (what this function calls) — max 10
    let callees: Vec<&str> = edges
        .iter()
        .filter(|(src, _, kind)| src == &node.id && kind == "calls")
        .map(|(_, tgt, _)| extract_short_name(tgt))
        .take(10)
        .collect();
    if !callees.is_empty() {
        parts.push(format!("Calls: {}", callees.join(", ")));
    }

    // 5. Callers (what calls this function) — with high-fanout cap
    // >50 callers → truncate to 5 + "(and N more)" to keep search_text focused
    let total_callers = edges
        .iter()
        .filter(|(_, tgt, kind)| tgt == &node.id && kind == "calls")
        .count();
    let caller_cap = if total_callers > 50 { 5 } else { 10 };
    let callers: Vec<&str> = edges
        .iter()
        .filter(|(_, tgt, kind)| tgt == &node.id && kind == "calls")
        .map(|(src, _, _)| extract_short_name(src))
        .take(caller_cap)
        .collect();
    if !callers.is_empty() {
        let suffix = if total_callers > 50 {
            format!(" (and {} more)", total_callers - caller_cap)
        } else {
            String::new()
        };
        parts.push(format!("Called by: {}{}", callers.join(", "), suffix));
    }

    // 6. Location
    if let Some(ref path) = node.file_path {
        parts.push(format!("In {}", path));
    }

    if parts.is_empty() {
        format!("Function {}", node.name)
    } else {
        parts.join(". ")
    }
}

fn summarize_class(node: &Node, edges: &[(String, String, String)]) -> String {
    let mut parts = Vec::new();

    // Docstring
    if let Some(ref source) = node.source_text {
        if let Some(doc) = extract_doc_line(source) {
            parts.push(doc);
        }
    }

    // Class/struct declaration line
    if let Some(ref source) = node.source_text {
        for line in source.lines() {
            let t = line.trim();
            if t.contains("class ")
                || t.contains("struct ")
                || t.contains("trait ")
                || t.contains("interface ")
                || t.contains("enum ")
            {
                parts.push(t.to_string());
                break;
            }
        }
    }

    // Methods (from "contains" edges)
    let methods: Vec<&str> = edges
        .iter()
        .filter(|(src, _, kind)| src == &node.id && kind == "contains")
        .map(|(_, tgt, _)| extract_short_name(tgt))
        .take(15)
        .collect();
    if !methods.is_empty() {
        parts.push(format!("Methods: {}", methods.join(", ")));
    }

    // Inheritance
    let inherits: Vec<&str> = edges
        .iter()
        .filter(|(src, _, kind)| src == &node.id && kind == "inherits")
        .map(|(_, tgt, _)| extract_short_name(tgt))
        .collect();
    if !inherits.is_empty() {
        parts.push(format!("Extends: {}", inherits.join(", ")));
    }

    // Used by (imports or uses edges pointing to this class)
    let users: Vec<&str> = edges
        .iter()
        .filter(|(_, tgt, kind)| tgt == &node.id && (kind == "uses" || kind == "imports"))
        .map(|(src, _, _)| extract_short_name(src))
        .take(10)
        .collect();
    if !users.is_empty() {
        parts.push(format!("Used by: {}", users.join(", ")));
    }

    if let Some(ref path) = node.file_path {
        parts.push(format!("In {}", path));
    }

    if parts.is_empty() {
        format!("Class {}", node.name)
    } else {
        parts.join(". ")
    }
}

fn summarize_module(node: &Node, edges: &[(String, String, String)]) -> String {
    let mut parts = Vec::new();

    // First line of source if it looks like a docstring
    if let Some(ref source) = node.source_text {
        if let Some(doc) = extract_doc_line(source) {
            parts.push(doc);
        }
    }

    // Contains (exported symbols)
    let exports: Vec<&str> = edges
        .iter()
        .filter(|(src, _, kind)| src == &node.id && kind == "contains")
        .map(|(_, tgt, _)| extract_short_name(tgt))
        .take(20)
        .collect();
    if !exports.is_empty() {
        parts.push(format!("Contains: {}", exports.join(", ")));
    }

    if let Some(ref path) = node.file_path {
        parts.push(format!("File: {}", path));
    }

    if parts.is_empty() {
        format!("Module {}", node.name)
    } else {
        parts.join(". ")
    }
}

fn summarize_message(node: &Node, edges: &[(String, String, String)]) -> String {
    let mut parts = Vec::new();

    parts.push(format!("Message type {}", node.name));

    // Publishers
    let publishers: Vec<&str> = edges
        .iter()
        .filter(|(_, tgt, kind)| tgt == &node.id && kind == "publishes")
        .map(|(src, _, _)| extract_short_name(src))
        .take(10)
        .collect();
    if !publishers.is_empty() {
        parts.push(format!("Published by: {}", publishers.join(", ")));
    }

    // Subscribers
    let subscribers: Vec<&str> = edges
        .iter()
        .filter(|(_, tgt, kind)| tgt == &node.id && kind == "subscribes")
        .map(|(src, _, _)| extract_short_name(src))
        .take(10)
        .collect();
    if !subscribers.is_empty() {
        parts.push(format!("Consumed by: {}", subscribers.join(", ")));
    }

    parts.join(". ")
}

/// Materialize search_text from summary + identity fields.
/// This is what gets indexed by FTS.
pub fn build_search_text(node: &Node, summary_text: Option<&str>) -> String {
    let mut parts = Vec::new();
    if let Some(summary) = summary_text {
        parts.push(summary.to_string());
    }
    parts.push(node.name.clone());
    // The FTS tokenizer splits on non-alphanumerics only, so a camelCase name
    // like "DominaiteAuthMiddleware" is a single opaque token and the query
    // "auth middleware" can never match it. Index the split words too.
    let split = split_identifier_words(&node.name);
    if split.to_lowercase() != node.name.to_lowercase() {
        parts.push(split);
    }
    if let Some(ref qn) = node.qualified_name {
        parts.push(qn.clone());
    }
    if let Some(ref path) = node.file_path {
        parts.push(path.clone());
    }
    parts.join(" | ")
}

/// Split a camelCase / PascalCase / snake_case identifier into space-separated
/// lowercase words: "DominaiteAuthMiddleware" -> "dominaite auth middleware",
/// "parse_config" -> "parse config", "HTTPServer" -> "http server".
pub fn split_identifier_words(name: &str) -> String {
    let mut words: Vec<String> = Vec::new();
    let mut current = String::new();
    let chars: Vec<char> = name.chars().collect();

    for (i, &c) in chars.iter().enumerate() {
        if !c.is_alphanumeric() {
            if !current.is_empty() {
                words.push(std::mem::take(&mut current));
            }
            continue;
        }
        if c.is_uppercase() && !current.is_empty() {
            let prev_lower = chars[i - 1].is_lowercase() || chars[i - 1].is_numeric();
            // Split at lower->Upper, and inside acronym runs at Upper followed
            // by lower ("HTTPServer" -> "HTTP" + "Server").
            let next_lower = chars.get(i + 1).is_some_and(|n| n.is_lowercase());
            if prev_lower || (chars[i - 1].is_uppercase() && next_lower) {
                words.push(std::mem::take(&mut current));
            }
        }
        current.push(c.to_ascii_lowercase());
    }
    if !current.is_empty() {
        words.push(current);
    }
    words.join(" ")
}

/// Compute a hash of the node's source_text for staleness detection.
/// This is NODE-level (not file-level) — a comment change elsewhere in the file
/// must not invalidate every symbol in that file.
pub fn compute_code_hash(source_text: &str) -> String {
    use std::collections::hash_map::DefaultHasher;
    use std::hash::{Hash, Hasher};
    let mut hasher = DefaultHasher::new();
    source_text.hash(&mut hasher);
    format!("{:016x}", hasher.finish())
}

// -- Helpers --

/// Extract the short name from a node ID like "fn:path/to/file.rs:ClassName.method_name"
fn extract_short_name(node_id: &str) -> &str {
    // Get the last segment after ':'
    node_id.rsplit(':').next().unwrap_or(node_id)
}

/// Extract first meaningful doc line from source text.
/// Skips lines that look like code (contain '(' or start with keywords).
fn extract_doc_line(source: &str) -> Option<String> {
    let first_line = source.lines().next()?.trim();

    // Skip if it looks like code rather than documentation
    let code_prefixes = [
        "fn ",
        "pub ",
        "def ",
        "func ",
        "class ",
        "struct ",
        "trait ",
        "interface ",
        "impl ",
        "async ",
        "static ",
        "private ",
        "protected ",
        "public ",
        "import ",
        "from ",
        "use ",
        "package ",
        "module ",
        "//!",
        "///",
        "//",
        "#!",
        "/*",
        "\"\"\"",
        "'''",
    ];

    // If it starts with a doc comment marker, strip it and use the content
    if first_line.starts_with("///") || first_line.starts_with("//!") {
        let content = first_line
            .trim_start_matches('/')
            .trim_start_matches('!')
            .trim();
        if content.len() > 5 {
            return Some(content.to_string());
        }
        return None;
    }

    if first_line.starts_with("\"\"\"") || first_line.starts_with("'''") {
        let content = first_line
            .trim_start_matches('"')
            .trim_start_matches('\'')
            .trim_end_matches('"')
            .trim_end_matches('\'')
            .trim();
        if content.len() > 5 {
            return Some(content.to_string());
        }
        return None;
    }

    // Skip if it looks like code
    for prefix in &code_prefixes {
        if first_line.starts_with(prefix) {
            return None;
        }
    }

    // Skip if too short or contains '(' (likely a function signature)
    if first_line.len() <= 5 || first_line.contains('(') {
        return None;
    }

    Some(first_line.to_string())
}

/// Extract signature line from source text.
fn extract_signature(source: &str) -> Option<String> {
    let sig_prefixes = [
        "fn ",
        "pub fn ",
        "pub async fn ",
        "async fn ",
        "pub(crate) fn ",
        "pub(super) fn ",
        "def ",
        "async def ",
        "func ",
        "public func ",
        "private func ",
        "function ",
        "export function ",
        "async function ",
        "public ",
        "private ",
        "protected ",
    ];

    for line in source.lines() {
        let trimmed = line.trim();
        for prefix in &sig_prefixes {
            if trimmed.starts_with(prefix) {
                return Some(trimmed.to_string());
            }
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::storage::Node;

    fn edge(src: &str, tgt: &str, kind: &str) -> (String, String, String) {
        (src.to_string(), tgt.to_string(), kind.to_string())
    }

    #[test]
    fn test_function_with_callers_and_callees() {
        let node = Node::function(
            "src/service.rs",
            "process",
            None,
            10,
            50,
            5,
            Some(
                "/// Processes incoming requests\npub fn process(req: Request) -> Response {"
                    .to_string(),
            ),
        );

        let edges = vec![
            // process calls validate and save
            edge(
                "fn:src/service.rs:process",
                "fn:src/validate.rs:validate",
                "calls",
            ),
            edge("fn:src/service.rs:process", "fn:src/db.rs:save", "calls"),
            // handler calls process
            edge(
                "fn:src/handler.rs:handler",
                "fn:src/service.rs:process",
                "calls",
            ),
        ];

        let summary = generate_heuristic_summary(&node, &edges);
        assert!(
            summary.contains("Processes incoming requests"),
            "should have doc line"
        );
        assert!(
            summary.contains("pub fn process(req: Request) -> Response {"),
            "should have signature"
        );
        assert!(
            summary.contains("Calls: validate, save"),
            "should list callees"
        );
        assert!(
            summary.contains("Called by: handler"),
            "should list callers"
        );
        assert!(
            summary.contains("In src/service.rs"),
            "should have location"
        );
    }

    #[test]
    fn test_function_with_return_type_property() {
        let node = {
            let mut n = Node::function("src/lib.rs", "get_count", None, 1, 5, 1, None);
            n.properties = Some(serde_json::json!({"return_type": "usize"}));
            n
        };

        let summary = generate_heuristic_summary(&node, &[]);
        assert!(
            summary.contains("Returns usize"),
            "should include return type from properties"
        );
        assert!(summary.contains("In src/lib.rs"), "should have location");
    }

    #[test]
    fn test_function_no_source_fallback() {
        let node = Node {
            id: "fn:x:bare".to_string(),
            node_type: NodeType::Function,
            name: "bare".to_string(),
            qualified_name: None,
            file_path: None,
            line_start: None,
            line_end: None,
            complexity: 0,
            properties: None,
            source_text: None,
            summary_text: None,
            summary_source: None,
            summary_code_hash: None,
            importance_score: 0.0,
            search_text: None,
            summary_updated_at: None,
            node_category: "production".to_string(),
        };

        let summary = generate_heuristic_summary(&node, &[]);
        assert_eq!(summary, "Function bare");
    }

    #[test]
    fn test_class_with_methods_and_inheritance() {
        let node = Node::class(
            "src/models.rs",
            "UserService",
            10,
            100,
            Some("class UserService extends BaseService {".to_string()),
        );

        let edges = vec![
            edge(
                "cls:src/models.rs:UserService",
                "fn:src/models.rs:UserService.create",
                "contains",
            ),
            edge(
                "cls:src/models.rs:UserService",
                "fn:src/models.rs:UserService.delete",
                "contains",
            ),
            edge(
                "cls:src/models.rs:UserService",
                "cls:src/base.rs:BaseService",
                "inherits",
            ),
            edge(
                "mod:src/handler.rs",
                "cls:src/models.rs:UserService",
                "uses",
            ),
        ];

        let summary = generate_heuristic_summary(&node, &edges);
        assert!(
            summary.contains("class UserService extends BaseService {"),
            "should have declaration"
        );
        assert!(
            summary.contains("Methods: UserService.create, UserService.delete"),
            "should list methods"
        );
        assert!(
            summary.contains("Extends: BaseService"),
            "should list parent"
        );
        assert!(
            summary.contains("Used by: src/handler.rs"),
            "should list users"
        );
        assert!(summary.contains("In src/models.rs"), "should have location");
    }

    #[test]
    fn test_class_empty_fallback() {
        let node = Node {
            id: "cls:x:Empty".to_string(),
            node_type: NodeType::Class,
            name: "Empty".to_string(),
            qualified_name: None,
            file_path: None,
            line_start: None,
            line_end: None,
            complexity: 0,
            properties: None,
            source_text: None,
            summary_text: None,
            summary_source: None,
            summary_code_hash: None,
            importance_score: 0.0,
            search_text: None,
            summary_updated_at: None,
            node_category: "production".to_string(),
        };

        let summary = generate_heuristic_summary(&node, &[]);
        assert_eq!(summary, "Class Empty");
    }

    #[test]
    fn test_module_with_exports() {
        let node = Node::module("src/utils.py");

        let edges = vec![
            edge("mod:src/utils.py", "fn:src/utils.py:helper", "contains"),
            edge("mod:src/utils.py", "cls:src/utils.py:Config", "contains"),
        ];

        let summary = generate_heuristic_summary(&node, &edges);
        assert!(
            summary.contains("Contains: helper, Config"),
            "should list exports"
        );
        assert!(
            summary.contains("File: src/utils.py"),
            "should have file path"
        );
    }

    #[test]
    fn test_module_empty_fallback() {
        let node = Node {
            id: "mod:empty.py".to_string(),
            node_type: NodeType::Module,
            name: "empty".to_string(),
            qualified_name: None,
            file_path: None,
            line_start: None,
            line_end: None,
            complexity: 0,
            properties: None,
            source_text: None,
            summary_text: None,
            summary_source: None,
            summary_code_hash: None,
            importance_score: 0.0,
            search_text: None,
            summary_updated_at: None,
            node_category: "production".to_string(),
        };

        let summary = generate_heuristic_summary(&node, &[]);
        assert_eq!(summary, "Module empty");
    }

    #[test]
    fn test_external_node() {
        let node = Node::external("serde_json");
        let summary = generate_heuristic_summary(&node, &[]);
        assert_eq!(summary, "External dependency serde_json");
    }

    #[test]
    fn test_message_with_pub_sub() {
        let node = Node::message("OrderCreated", Some("Orders"));

        let edges = vec![
            edge(
                "fn:src/orders.rs:OrderService.create",
                "msg:Orders:OrderCreated",
                "publishes",
            ),
            edge(
                "fn:src/billing.rs:BillingHandler.handle",
                "msg:Orders:OrderCreated",
                "subscribes",
            ),
            edge(
                "fn:src/shipping.rs:ShipHandler.handle",
                "msg:Orders:OrderCreated",
                "subscribes",
            ),
        ];

        let summary = generate_heuristic_summary(&node, &edges);
        assert!(
            summary.contains("Message type OrderCreated"),
            "should have message type"
        );
        assert!(
            summary.contains("Published by: OrderService.create"),
            "should list publisher"
        );
        assert!(
            summary.contains("Consumed by: BillingHandler.handle, ShipHandler.handle"),
            "should list subscribers"
        );
    }

    #[test]
    fn test_build_search_text() {
        let node = Node::function("src/lib.rs", "do_stuff", None, 1, 10, 1, None);
        let text = build_search_text(&node, Some("Does important stuff"));
        assert_eq!(
            text,
            "Does important stuff | do_stuff | do stuff | src/lib.rs:do_stuff | src/lib.rs"
        );
    }

    #[test]
    fn test_build_search_text_no_summary() {
        let node = Node::function("src/lib.rs", "do_stuff", None, 1, 10, 1, None);
        let text = build_search_text(&node, None);
        assert_eq!(
            text,
            "do_stuff | do stuff | src/lib.rs:do_stuff | src/lib.rs"
        );
    }

    #[test]
    fn test_compute_code_hash_deterministic() {
        let source = "fn main() { println!(\"hello\"); }";
        let h1 = compute_code_hash(source);
        let h2 = compute_code_hash(source);
        assert_eq!(h1, h2);
        assert_eq!(h1.len(), 16, "hash should be 16 hex chars");
    }

    #[test]
    fn test_compute_code_hash_different_input() {
        let h1 = compute_code_hash("fn main() {}");
        let h2 = compute_code_hash("fn main() { todo!() }");
        assert_ne!(h1, h2);
    }

    #[test]
    fn test_high_fanout_caller_cap() {
        let node = Node::function("src/util.rs", "log", None, 1, 5, 1, None);

        // Generate 60 callers
        let edges: Vec<(String, String, String)> = (0..60)
            .map(|i| {
                edge(
                    &format!("fn:src/caller_{}.rs:call_{}", i, i),
                    "fn:src/util.rs:log",
                    "calls",
                )
            })
            .collect();

        let summary = generate_heuristic_summary(&node, &edges);
        assert!(
            summary.contains("Called by:"),
            "should have Called by section"
        );
        assert!(
            summary.contains("(and 55 more)"),
            "should show truncation with remaining count"
        );

        // Should only list 5 callers when >50
        let called_by_section = summary
            .split("Called by: ")
            .nth(1)
            .unwrap()
            .split('.')
            .next()
            .unwrap();
        let listed_callers: Vec<&str> = called_by_section
            .split(" (and ")
            .next()
            .unwrap()
            .split(", ")
            .collect();
        assert_eq!(
            listed_callers.len(),
            5,
            "should cap at 5 callers when total > 50"
        );
    }

    #[test]
    fn test_extract_doc_line_rust_doc() {
        let source = "/// Handles user authentication\npub fn authenticate() {}";
        let doc = extract_doc_line(source);
        assert_eq!(doc, Some("Handles user authentication".to_string()));
    }

    #[test]
    fn test_extract_doc_line_python_docstring() {
        let source = "\"\"\"Handles user authentication\"\"\"\ndef authenticate():";
        let doc = extract_doc_line(source);
        assert_eq!(doc, Some("Handles user authentication".to_string()));
    }

    #[test]
    fn test_extract_doc_line_skips_code() {
        let source = "pub fn authenticate() {}";
        let doc = extract_doc_line(source);
        assert_eq!(doc, None);
    }

    #[test]
    fn test_extract_signature_rust() {
        let source = "/// Does stuff\npub async fn do_it(x: i32) -> Result<()> {";
        let sig = extract_signature(source);
        assert_eq!(
            sig,
            Some("pub async fn do_it(x: i32) -> Result<()> {".to_string())
        );
    }

    #[test]
    fn test_extract_signature_python() {
        let source = "# comment\ndef process(self, data):";
        let sig = extract_signature(source);
        assert_eq!(sig, Some("def process(self, data):".to_string()));
    }

    #[test]
    fn test_split_identifier_words() {
        assert_eq!(
            split_identifier_words("DominaiteAuthMiddleware"),
            "dominaite auth middleware"
        );
        assert_eq!(split_identifier_words("parse_config"), "parse config");
        assert_eq!(split_identifier_words("HTTPServer"), "http server");
        assert_eq!(split_identifier_words("simple"), "simple");
        assert_eq!(split_identifier_words("SendEmailAsync"), "send email async");
    }

    #[test]
    fn test_search_text_contains_split_name_words() {
        // The q5 eval failure: "authentication middleware" could never match
        // DominaiteAuthMiddleware because the camelCase name was one FTS token.
        let node = crate::engine::storage::Node::class(
            "common/Auth/DominaiteAuthMiddleware.cs",
            "DominaiteAuthMiddleware",
            22,
            1500,
            None,
        );
        let text = build_search_text(&node, None);
        assert!(text.contains("dominaite auth middleware"));
    }
}
