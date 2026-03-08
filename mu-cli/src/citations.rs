//! Numbered citation system for MCP/API responses.
//!
//! Replaces verbose file paths with `[1]`, `[2]` references
//! and appends a References section at the end of output.

use std::collections::HashMap;

pub struct CitationIndex {
    refs: Vec<(String, Option<usize>)>, // (file_path, line_number)
    lookup: HashMap<String, usize>,     // key -> 1-indexed citation number
}

impl CitationIndex {
    pub fn new() -> Self {
        Self {
            refs: Vec::new(),
            lookup: HashMap::new(),
        }
    }

    /// Register a file reference and return "[N]" string.
    /// Same file+line combo reuses the same number.
    pub fn cite(&mut self, file_path: &str, line: Option<usize>) -> String {
        let key = match line {
            Some(l) => format!("{}:{}", file_path, l),
            None => file_path.to_string(),
        };
        if let Some(&n) = self.lookup.get(&key) {
            format!("[{}]", n)
        } else {
            let n = self.refs.len() + 1;
            self.refs.push((file_path.to_string(), line));
            self.lookup.insert(key, n);
            format!("[{}]", n)
        }
    }

    /// Render the references section. Returns empty string if no refs.
    pub fn render(&self) -> String {
        if self.refs.is_empty() {
            return String::new();
        }
        let mut out = String::from("\n## References\n");
        for (i, (path, line)) in self.refs.iter().enumerate() {
            match line {
                Some(l) => out.push_str(&format!("[{}] {}:{}\n", i + 1, path, l)),
                None => out.push_str(&format!("[{}] {}\n", i + 1, path)),
            }
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cite_same_file_twice_returns_same_number() {
        let mut idx = CitationIndex::new();
        let first = idx.cite("src/main.rs", None);
        let second = idx.cite("src/main.rs", None);
        assert_eq!(first, "[1]");
        assert_eq!(second, "[1]");
    }

    #[test]
    fn cite_different_files_returns_incrementing_numbers() {
        let mut idx = CitationIndex::new();
        assert_eq!(idx.cite("src/a.rs", None), "[1]");
        assert_eq!(idx.cite("src/b.rs", None), "[2]");
        assert_eq!(idx.cite("src/c.rs", None), "[3]");
    }

    #[test]
    fn cite_with_line_numbers() {
        let mut idx = CitationIndex::new();
        assert_eq!(idx.cite("src/lib.rs", Some(10)), "[1]");
        assert_eq!(idx.cite("src/lib.rs", Some(20)), "[2]");
        // Same file+line reuses number
        assert_eq!(idx.cite("src/lib.rs", Some(10)), "[1]");
        // Same file, no line is a different key
        assert_eq!(idx.cite("src/lib.rs", None), "[3]");
    }

    #[test]
    fn render_empty_returns_empty_string() {
        let idx = CitationIndex::new();
        assert_eq!(idx.render(), "");
    }

    #[test]
    fn render_with_refs_produces_references_section() {
        let mut idx = CitationIndex::new();
        idx.cite("src/main.rs", None);
        idx.cite("src/lib.rs", Some(42));

        let rendered = idx.render();
        assert!(rendered.contains("## References"));
        assert!(rendered.contains("[1] src/main.rs\n"));
        assert!(rendered.contains("[2] src/lib.rs:42\n"));
    }
}
