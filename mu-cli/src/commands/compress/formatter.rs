//! Output formatting for compressed codebase.

use super::budget::{self, PercentileTable};
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

    /// Render at a budget degradation level (see `budget` module docs).
    /// Level 0 is the full output at `detail`; levels 1-3 drop detail by
    /// importance. Returns the content and the number of symbols whose
    /// names were omitted entirely.
    pub fn to_mu_format_level(&self, detail: DetailLevel, level: u8) -> (String, usize) {
        match level {
            0 => (self.to_mu_format(detail), 0),
            1 => (self.format_level1(detail), 0),
            2 => self.format_level2(detail),
            _ => self.format_level3(detail),
        }
    }

    /// Header + domain overview (+ hot paths). These sections are bounded
    /// in size, so the budget estimator renders them to measure them.
    pub(super) fn fixed_sections(&self, detail: DetailLevel, include_hot: bool) -> String {
        let mut out = String::new();
        out.push_str(&self.format_header());
        out.push('\n');
        if detail >= DetailLevel::Medium {
            if let Some(ref domain) = self.domain {
                out.push_str(&self.format_domain_overview(domain));
                out.push('\n');
            }
        }
        if include_hot && detail >= DetailLevel::Medium && !self.hot_paths.is_empty() {
            out.push('\n');
            out.push_str(&self.format_hot_paths());
        }
        out
    }

    /// Rendered size of the relationship clusters section (bounded: top 10
    /// entities). Used by the budget estimator.
    pub(super) fn clusters_section_len(&self) -> usize {
        if self.relationship_clusters.is_empty() {
            0
        } else {
            self.format_relationship_clusters().len()
        }
    }

    /// Level 1: full detail only for functions at or above median
    /// importance; below-median functions keep their names in compact
    /// comma-separated lists. Nothing is omitted entirely.
    fn format_level1(&self, detail: DetailLevel) -> String {
        let median = budget::median_function_importance(self);
        let mut out = self.fixed_sections(detail, false);
        out.push_str(&Self::format_tree_with(
            &self.tree,
            0,
            &mut |module, depth| self.format_module_l1(module, depth, detail, median),
        ));
        if detail >= DetailLevel::Medium && !self.hot_paths.is_empty() {
            out.push('\n');
            out.push_str(&self.format_hot_paths());
        }
        out
    }

    /// Level 2: per module, only the top-5 symbols by importance plus an
    /// explicit "+ N more symbols" count.
    fn format_level2(&self, detail: DetailLevel) -> (String, usize) {
        let pct = PercentileTable::new(budget::symbol_importances(self));
        let mut omitted = 0usize;
        let mut out = self.fixed_sections(detail, false);
        let tree = Self::format_tree_with(&self.tree, 0, &mut |module, depth| {
            self.format_module_l2(module, depth, &pct, &mut omitted)
        });
        out.push_str(&tree);
        (out, omitted)
    }

    /// Level 3: directory skeleton with per-directory counts and top-3
    /// symbols by importance.
    fn format_level3(&self, detail: DetailLevel) -> (String, usize) {
        let pct = PercentileTable::new(budget::symbol_importances(self));
        let mut omitted = 0usize;
        let mut out = self.fixed_sections(detail, false);
        out.push_str("\n## Directory Skeleton\n");
        Self::format_skeleton_dir(&self.tree, &pct, &mut out, &mut omitted);
        (out, omitted)
    }

    /// Generic tree recursion: folder headers plus a per-module renderer.
    fn format_tree_with(
        node: &FolderNode,
        depth: usize,
        render_module: &mut dyn FnMut(&CompressedModule, usize) -> String,
    ) -> String {
        let mut out = String::new();
        let indent = "  ".repeat(depth);

        if depth > 0 && !node.name.is_empty() {
            let header_prefix = "#".repeat(depth.min(3) + 1);
            out.push_str(&format!("\n{}{} {}/\n", indent, header_prefix, node.path));
        }

        for module in &node.modules {
            out.push_str(&render_module(module, depth + 1));
        }

        for child in node.children.values() {
            out.push_str(&Self::format_tree_with(child, depth + 1, render_module));
        }

        out
    }

    fn format_module_l1(
        &self,
        module: &CompressedModule,
        depth: usize,
        detail: DetailLevel,
        median: f32,
    ) -> String {
        let mut out = String::new();
        let indent = "  ".repeat(depth);
        out.push_str(&format!("{}! {}\n", indent, module.path));

        for class in &module.classes {
            out.push_str(&self.format_class_header(class, depth + 1, detail));
            let mut compact: Vec<&str> = Vec::new();
            for method in &class.methods {
                if method.importance >= median {
                    out.push_str(&self.format_function(method, depth + 2, detail));
                } else {
                    compact.push(&method.name);
                }
            }
            if !compact.is_empty() {
                let inner = "  ".repeat(depth + 2);
                out.push_str(&format!("{}# {}\n", inner, compact.join(", ")));
            }
        }

        let mut compact: Vec<&str> = Vec::new();
        for func in &module.functions {
            if func.importance >= median {
                out.push_str(&self.format_function(func, depth + 1, detail));
            } else {
                compact.push(&func.name);
            }
        }
        if !compact.is_empty() {
            let inner = "  ".repeat(depth + 1);
            out.push_str(&format!("{}# {}\n", inner, compact.join(", ")));
        }

        out
    }

    fn format_module_l2(
        &self,
        module: &CompressedModule,
        depth: usize,
        pct: &PercentileTable,
        omitted: &mut usize,
    ) -> String {
        struct Symbol<'a> {
            display: String,
            importance: f32,
            tiebreak: u32,
            name: &'a str,
        }

        let indent = "  ".repeat(depth);
        let mut out = format!("{}! {}\n", indent, module.path);

        let mut symbols: Vec<Symbol> = Vec::new();
        for class in &module.classes {
            symbols.push(Symbol {
                display: format!("$ {} ({} methods)", class.name, class.methods.len()),
                importance: class.importance,
                tiebreak: class.methods.len() as u32,
                name: &class.name,
            });
            for method in &class.methods {
                symbols.push(Symbol {
                    display: format!("# {}.{}{}", class.name, method.name, method.signature),
                    importance: method.importance,
                    tiebreak: method.complexity + 2 * method.call_count,
                    name: &method.name,
                });
            }
        }
        for func in &module.functions {
            symbols.push(Symbol {
                display: format!("# {}{}", func.name, func.signature),
                importance: func.importance,
                tiebreak: func.complexity + 2 * func.call_count,
                name: &func.name,
            });
        }

        let total = symbols.len();
        symbols.sort_unstable_by(|a, b| {
            b.importance
                .total_cmp(&a.importance)
                .then(b.tiebreak.cmp(&a.tiebreak))
                .then(a.name.cmp(b.name))
        });

        for sym in symbols.iter().take(5) {
            out.push_str(&indent);
            out.push_str("  ");
            out.push_str(&sym.display);
            if sym.importance > 0.0 {
                out.push_str(&format!("  imp=p{}", pct.rank(sym.importance)));
            }
            out.push('\n');
        }
        if total > 5 {
            *omitted += total - 5;
            out.push_str(&format!("{}  + {} more symbols\n", indent, total - 5));
        }

        out
    }

    fn format_skeleton_dir(
        node: &FolderNode,
        pct: &PercentileTable,
        out: &mut String,
        omitted: &mut usize,
    ) {
        if !node.modules.is_empty() {
            let module_count = node.modules.len();
            let mut class_count = 0usize;
            let mut func_count = 0usize;
            // (name, importance, tiebreak)
            let mut symbols: Vec<(&str, f32, u32)> = Vec::new();

            for module in &node.modules {
                class_count += module.classes.len();
                for class in &module.classes {
                    func_count += class.methods.len();
                    symbols.push((&class.name, class.importance, class.methods.len() as u32));
                    for method in &class.methods {
                        symbols.push((
                            &method.name,
                            method.importance,
                            method.complexity + 2 * method.call_count,
                        ));
                    }
                }
                func_count += module.functions.len();
                for func in &module.functions {
                    symbols.push((
                        &func.name,
                        func.importance,
                        func.complexity + 2 * func.call_count,
                    ));
                }
            }

            symbols.sort_unstable_by(|a, b| {
                b.1.total_cmp(&a.1).then(b.2.cmp(&a.2)).then(a.0.cmp(b.0))
            });

            let top: Vec<String> = symbols
                .iter()
                .take(3)
                .map(|(name, importance, _)| {
                    if *importance > 0.0 {
                        format!("{} p{}", name, pct.rank(*importance))
                    } else {
                        (*name).to_string()
                    }
                })
                .collect();

            *omitted += symbols.len().saturating_sub(top.len());

            let dir = if node.path.is_empty() {
                "./".to_string()
            } else {
                format!("{}/", node.path)
            };
            out.push_str(&format!(
                "{}  ({} modules, {} classes, {} functions)",
                dir, module_count, class_count, func_count
            ));
            if !top.is_empty() {
                out.push_str(&format!(" | top: {}", top.join(", ")));
            }
            out.push('\n');
        }

        for child in node.children.values() {
            Self::format_skeleton_dir(child, pct, out, omitted);
        }
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
        let mut out = self.format_class_header(class, depth, detail);

        // Methods
        for method in &class.methods {
            out.push_str(&self.format_function(method, depth + 1, detail));
        }

        out
    }

    /// Class header line with inheritance plus relationship lines (medium+),
    /// without methods. Shared by the full and level-1 renderers.
    fn format_class_header(
        &self,
        class: &CompressedClass,
        depth: usize,
        detail: DetailLevel,
    ) -> String {
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
}
