//! Output formatting for compressed codebase.

use super::models::{
    CompressedClass, CompressedCodebase, CompressedFunction, CompressedModule, DetailLevel,
    DomainOverview, FolderNode,
};
use crate::output::TableDisplay;

impl CompressedCodebase {
    /// Generate MU format output
    pub fn to_mu_format(&self, detail: DetailLevel) -> String {
        let mut out = String::new();

        // Header
        out.push_str(&self.format_header());
        out.push('\n');

        // Domain overview (medium+)
        if detail >= DetailLevel::Medium {
            if let Some(ref domain) = self.domain {
                out.push_str(&self.format_domain_overview(domain));
                out.push('\n');
            }
        }

        // Hierarchical tree
        out.push_str(&self.format_tree(&self.tree, 0, detail));

        // Hot paths (medium+)
        if detail >= DetailLevel::Medium && !self.hot_paths.is_empty() {
            out.push('\n');
            out.push_str(&self.format_hot_paths());
        }

        // Relationship clusters (high only)
        if detail == DetailLevel::High && !self.relationship_clusters.is_empty() {
            out.push('\n');
            out.push_str(&self.format_relationship_clusters());
        }

        out
    }

    fn format_header(&self) -> String {
        let mut out = String::new();
        out.push_str("# MU v2.0 - Compressed Codebase\n");
        out.push_str(&format!("# source: {}\n", self.source));
        out.push_str(&format!(
            "# {} modules, {} classes, {} functions",
            self.stats.total_modules, self.stats.total_classes, self.stats.total_functions
        ));
        if self.stats.has_graph {
            out.push_str(&format!(", {} edges", self.stats.total_edges));
        } else {
            out.push_str(" (no graph - run `mu bootstrap` for relationships)");
        }
        out.push('\n');
        out
    }

    fn format_domain_overview(&self, domain: &DomainOverview) -> String {
        let mut out = String::new();
        out.push_str("\n## Domain Overview\n");

        // Domain name and purpose
        if let Some(ref name) = domain.domain_name {
            out.push_str(&format!("@ {}\n", name));
        }
        if let Some(ref purpose) = domain.purpose {
            out.push_str(&format!(":: {}\n", purpose));
        }

        // Core entities with relationships
        if !domain.entities.is_empty() {
            out.push_str("\n### Core Entities\n");
            for entity in &domain.entities {
                let stars = "★".repeat(entity.importance as usize);
                out.push_str(&format!("$ {}  [{}]\n", entity.name, stars));

                // Attributes (limit to 8)
                if !entity.attributes.is_empty() {
                    let attrs: Vec<_> = entity.attributes.iter().take(8).cloned().collect();
                    out.push_str(&format!("  @attrs [{}]\n", attrs.join(", ")));
                }

                // Outgoing relationships
                if !entity.outgoing_rels.is_empty() {
                    let rels: Vec<String> = entity
                        .outgoing_rels
                        .iter()
                        .map(|r| format!("{} ({})", r.target, r.rel_type))
                        .collect();
                    out.push_str(&format!("  → {}\n", rels.join(", ")));
                }

                // Incoming relationships (just names)
                if !entity.incoming_rels.is_empty() {
                    let rels: Vec<String> = entity
                        .incoming_rels
                        .iter()
                        .map(|r| r.target.clone())
                        .collect();
                    out.push_str(&format!("  ← {}\n", rels.join(", ")));
                }
            }
        }

        // State flows
        if !domain.flows.is_empty() {
            out.push_str("\n### Flows\n");
            for flow in &domain.flows {
                out.push_str(&format!("@ {}: {}\n", flow.name, flow.states.join(" → ")));
            }
        }

        // Integrations
        if !domain.integrations.is_empty() {
            out.push_str(&format!(
                "\n@external [{}]\n",
                domain.integrations.join(", ")
            ));
        }

        // Tech stack
        if !domain.tech_stack.is_empty() {
            out.push_str(&format!("@tech [{}]\n", domain.tech_stack.join(", ")));
        }

        out
    }

    fn format_tree(&self, node: &FolderNode, depth: usize, detail: DetailLevel) -> String {
        let mut out = String::new();
        let indent = "  ".repeat(depth);

        // Output folder header if not root
        if depth > 0 && !node.name.is_empty() {
            let header_prefix = "#".repeat(depth.min(3) + 1);
            out.push_str(&format!("\n{}{} {}/\n", indent, header_prefix, node.path));
        }

        // Output modules in this folder
        for module in &node.modules {
            out.push_str(&self.format_module(module, depth + 1, detail));
        }

        // Recurse into children
        for child in node.children.values() {
            out.push_str(&self.format_tree(child, depth + 1, detail));
        }

        out
    }

    fn format_module(
        &self,
        module: &CompressedModule,
        depth: usize,
        detail: DetailLevel,
    ) -> String {
        let mut out = String::new();
        let indent = "  ".repeat(depth);

        // Module header
        out.push_str(&format!("{}! {}\n", indent, module.path));

        // Classes
        for class in &module.classes {
            out.push_str(&self.format_class(class, depth + 1, detail));
        }

        // Top-level functions
        for func in &module.functions {
            out.push_str(&self.format_function(func, depth + 1, detail));
        }

        out
    }

    fn format_class(&self, class: &CompressedClass, depth: usize, detail: DetailLevel) -> String {
        let mut out = String::new();
        let indent = "  ".repeat(depth);

        // Class header with inheritance
        let bases_str = if !class.bases.is_empty() {
            format!(" < {}", class.bases.join(", "))
        } else {
            String::new()
        };
        out.push_str(&format!("{}$ {}{}\n", indent, class.name, bases_str));

        // Relationships (medium+)
        if detail >= DetailLevel::Medium {
            if !class.uses.is_empty() {
                out.push_str(&format!("{}  → {}\n", indent, class.uses.join(", ")));
            }
            if !class.used_by.is_empty() {
                out.push_str(&format!("{}  ← {}\n", indent, class.used_by.join(", ")));
            }
        }

        // Methods
        for method in &class.methods {
            out.push_str(&self.format_function(method, depth + 1, detail));
        }

        out
    }

    fn format_function(
        &self,
        func: &CompressedFunction,
        depth: usize,
        detail: DetailLevel,
    ) -> String {
        let mut out = String::new();
        let indent = "  ".repeat(depth);

        // Function line
        let hot_marker = if func.is_hot {
            if func.complexity > 30 || func.call_count > 10 {
                " ★★"
            } else {
                " ★"
            }
        } else {
            ""
        };

        let complexity_str = if func.complexity > 0 {
            format!("  c={}", func.complexity)
        } else {
            String::new()
        };

        let call_str = if func.call_count > 0 {
            format!(" calls={}", func.call_count)
        } else {
            String::new()
        };

        out.push_str(&format!(
            "{}# {}{}{}{}{}\n",
            indent, func.name, func.signature, complexity_str, call_str, hot_marker
        ));

        // Docstring for hot functions (medium+)
        if detail >= DetailLevel::Medium && func.is_hot {
            if let Some(ref doc) = func.docstring {
                out.push_str(&format!("{}  :: {}\n", indent, doc));
            }
        }

        out
    }

    fn format_hot_paths(&self) -> String {
        let mut out = String::new();
        out.push_str("## Hot Paths (complexity > 20 or calls > 5)\n");

        for hp in &self.hot_paths {
            let call_str = if hp.call_count > 0 {
                format!("  calls={}", hp.call_count)
            } else {
                String::new()
            };
            out.push_str(&format!(
                "  # {}  c={}{}\n",
                hp.qualified_name, hp.complexity, call_str
            ));
            out.push_str(&format!("    | {}\n", hp.file_path));
        }

        out
    }

    fn format_relationship_clusters(&self) -> String {
        let mut out = String::new();
        out.push_str("## Relationship Clusters\n");

        for cluster in &self.relationship_clusters {
            out.push_str(&format!(
                "\n### {} ({} relationships)\n",
                cluster.entity, cluster.relationship_count
            ));

            for rel in &cluster.outgoing {
                out.push_str(&format!("  → {} [{}]\n", rel.target, rel.edge_type));
            }

            for rel in &cluster.incoming {
                out.push_str(&format!("  ← {} [{}]\n", rel.target, rel.edge_type));
            }
        }

        out
    }
}

impl TableDisplay for super::models::CompressResult {
    fn to_table(&self) -> String {
        self.content.clone()
    }

    fn to_mu(&self) -> String {
        self.content.clone()
    }
}
