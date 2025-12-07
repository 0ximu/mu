//! Change types and result structures for semantic diff.

use pyo3::prelude::*;
use pyo3::types::PyDict;
use serde::{Deserialize, Serialize};

/// Type of change detected.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum ChangeType {
    Added,
    Removed,
    Modified,
    Renamed,
}

impl ChangeType {
    pub fn as_str(&self) -> &'static str {
        match self {
            ChangeType::Added => "added",
            ChangeType::Removed => "removed",
            ChangeType::Modified => "modified",
            ChangeType::Renamed => "renamed",
        }
    }
}

/// Type of code entity that changed.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum EntityType {
    Module,
    Function,
    Class,
    Method,
    Parameter,
    Import,
    Attribute,
    Constant,
}

impl EntityType {
    pub fn as_str(&self) -> &'static str {
        match self {
            EntityType::Module => "module",
            EntityType::Function => "function",
            EntityType::Class => "class",
            EntityType::Method => "method",
            EntityType::Parameter => "parameter",
            EntityType::Import => "import",
            EntityType::Attribute => "attribute",
            EntityType::Constant => "constant",
        }
    }
}

/// A single semantic change to a code entity.
#[pyclass]
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EntityChange {
    /// Type of change (added, removed, modified, renamed)
    #[pyo3(get)]
    pub change_type: String,

    /// Type of entity (function, class, method, parameter, etc.)
    #[pyo3(get)]
    pub entity_type: String,

    /// Name of the entity
    #[pyo3(get)]
    pub entity_name: String,

    /// File path where the entity is located
    #[pyo3(get)]
    pub file_path: String,

    /// Parent entity name (e.g., class name for methods)
    #[pyo3(get)]
    pub parent_name: Option<String>,

    /// Human-readable details about the change
    #[pyo3(get)]
    pub details: Option<String>,

    /// Old signature (for functions/methods)
    #[pyo3(get)]
    pub old_signature: Option<String>,

    /// New signature (for functions/methods)
    #[pyo3(get)]
    pub new_signature: Option<String>,

    /// Whether this is a breaking API change
    #[pyo3(get)]
    pub is_breaking: bool,
}

#[pymethods]
impl EntityChange {
    #[new]
    #[pyo3(signature = (change_type, entity_type, entity_name, file_path, parent_name=None, details=None, old_signature=None, new_signature=None, is_breaking=false))]
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        change_type: String,
        entity_type: String,
        entity_name: String,
        file_path: String,
        parent_name: Option<String>,
        details: Option<String>,
        old_signature: Option<String>,
        new_signature: Option<String>,
        is_breaking: bool,
    ) -> Self {
        Self {
            change_type,
            entity_type,
            entity_name,
            file_path,
            parent_name,
            details,
            old_signature,
            new_signature,
            is_breaking,
        }
    }

    /// Convert to Python dict.
    fn to_dict(&self, py: Python<'_>) -> PyResult<PyObject> {
        let dict = PyDict::new_bound(py);
        dict.set_item("change_type", &self.change_type)?;
        dict.set_item("entity_type", &self.entity_type)?;
        dict.set_item("entity_name", &self.entity_name)?;
        dict.set_item("file_path", &self.file_path)?;
        dict.set_item("parent_name", &self.parent_name)?;
        dict.set_item("details", &self.details)?;
        dict.set_item("old_signature", &self.old_signature)?;
        dict.set_item("new_signature", &self.new_signature)?;
        dict.set_item("is_breaking", self.is_breaking)?;
        Ok(dict.into())
    }

    /// Get fully qualified entity name.
    fn full_name(&self) -> String {
        match &self.parent_name {
            Some(parent) => format!("{}.{}", parent, self.entity_name),
            None => self.entity_name.clone(),
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "EntityChange({}: {} {} in {})",
            self.change_type, self.entity_type, self.entity_name, self.file_path
        )
    }
}

impl EntityChange {
    /// Create a new change with ChangeType and EntityType enums.
    pub fn create(
        change_type: ChangeType,
        entity_type: EntityType,
        entity_name: String,
        file_path: String,
    ) -> Self {
        let is_breaking = matches!(change_type, ChangeType::Removed);
        Self {
            change_type: change_type.as_str().to_string(),
            entity_type: entity_type.as_str().to_string(),
            entity_name,
            file_path,
            parent_name: None,
            details: None,
            old_signature: None,
            new_signature: None,
            is_breaking,
        }
    }

    /// Set parent name.
    pub fn with_parent(mut self, parent: &str) -> Self {
        self.parent_name = Some(parent.to_string());
        self
    }

    /// Set details.
    pub fn with_details(mut self, details: &str) -> Self {
        self.details = Some(details.to_string());
        self
    }

    /// Set signatures.
    pub fn with_signatures(mut self, old: Option<String>, new: Option<String>) -> Self {
        self.old_signature = old;
        self.new_signature = new;
        self
    }

    /// Mark as breaking change.
    pub fn mark_breaking(mut self) -> Self {
        self.is_breaking = true;
        self
    }
}

/// Summary statistics for a diff.
#[pyclass]
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct DiffSummary {
    #[pyo3(get)]
    pub modules_added: u32,
    #[pyo3(get)]
    pub modules_removed: u32,
    #[pyo3(get)]
    pub modules_modified: u32,

    #[pyo3(get)]
    pub functions_added: u32,
    #[pyo3(get)]
    pub functions_removed: u32,
    #[pyo3(get)]
    pub functions_modified: u32,

    #[pyo3(get)]
    pub classes_added: u32,
    #[pyo3(get)]
    pub classes_removed: u32,
    #[pyo3(get)]
    pub classes_modified: u32,

    #[pyo3(get)]
    pub methods_added: u32,
    #[pyo3(get)]
    pub methods_removed: u32,
    #[pyo3(get)]
    pub methods_modified: u32,

    #[pyo3(get)]
    pub parameters_added: u32,
    #[pyo3(get)]
    pub parameters_removed: u32,
    #[pyo3(get)]
    pub parameters_modified: u32,

    #[pyo3(get)]
    pub imports_added: u32,
    #[pyo3(get)]
    pub imports_removed: u32,

    #[pyo3(get)]
    pub breaking_changes: u32,
}

#[pymethods]
impl DiffSummary {
    #[new]
    fn new() -> Self {
        Self::default()
    }

    /// Convert to Python dict.
    fn to_dict(&self, py: Python<'_>) -> PyResult<PyObject> {
        let dict = PyDict::new_bound(py);
        dict.set_item("modules_added", self.modules_added)?;
        dict.set_item("modules_removed", self.modules_removed)?;
        dict.set_item("modules_modified", self.modules_modified)?;
        dict.set_item("functions_added", self.functions_added)?;
        dict.set_item("functions_removed", self.functions_removed)?;
        dict.set_item("functions_modified", self.functions_modified)?;
        dict.set_item("classes_added", self.classes_added)?;
        dict.set_item("classes_removed", self.classes_removed)?;
        dict.set_item("classes_modified", self.classes_modified)?;
        dict.set_item("methods_added", self.methods_added)?;
        dict.set_item("methods_removed", self.methods_removed)?;
        dict.set_item("methods_modified", self.methods_modified)?;
        dict.set_item("parameters_added", self.parameters_added)?;
        dict.set_item("parameters_removed", self.parameters_removed)?;
        dict.set_item("parameters_modified", self.parameters_modified)?;
        dict.set_item("imports_added", self.imports_added)?;
        dict.set_item("imports_removed", self.imports_removed)?;
        dict.set_item("breaking_changes", self.breaking_changes)?;
        Ok(dict.into())
    }

    /// Generate human-readable summary string.
    fn text(&self) -> String {
        let mut parts = Vec::new();

        // Modules
        if self.modules_added > 0 || self.modules_removed > 0 || self.modules_modified > 0 {
            let mut module_parts = Vec::new();
            if self.modules_added > 0 {
                module_parts.push(format!("{} added", self.modules_added));
            }
            if self.modules_removed > 0 {
                module_parts.push(format!("{} removed", self.modules_removed));
            }
            if self.modules_modified > 0 {
                module_parts.push(format!("{} modified", self.modules_modified));
            }
            parts.push(format!("modules: {}", module_parts.join(", ")));
        }

        // Functions
        if self.functions_added > 0 || self.functions_removed > 0 || self.functions_modified > 0 {
            let mut func_parts = Vec::new();
            if self.functions_added > 0 {
                func_parts.push(format!("{} added", self.functions_added));
            }
            if self.functions_removed > 0 {
                func_parts.push(format!("{} removed", self.functions_removed));
            }
            if self.functions_modified > 0 {
                func_parts.push(format!("{} modified", self.functions_modified));
            }
            parts.push(format!("functions: {}", func_parts.join(", ")));
        }

        // Classes
        if self.classes_added > 0 || self.classes_removed > 0 || self.classes_modified > 0 {
            let mut class_parts = Vec::new();
            if self.classes_added > 0 {
                class_parts.push(format!("{} added", self.classes_added));
            }
            if self.classes_removed > 0 {
                class_parts.push(format!("{} removed", self.classes_removed));
            }
            if self.classes_modified > 0 {
                class_parts.push(format!("{} modified", self.classes_modified));
            }
            parts.push(format!("classes: {}", class_parts.join(", ")));
        }

        // Methods
        if self.methods_added > 0 || self.methods_removed > 0 || self.methods_modified > 0 {
            let mut method_parts = Vec::new();
            if self.methods_added > 0 {
                method_parts.push(format!("{} added", self.methods_added));
            }
            if self.methods_removed > 0 {
                method_parts.push(format!("{} removed", self.methods_removed));
            }
            if self.methods_modified > 0 {
                method_parts.push(format!("{} modified", self.methods_modified));
            }
            parts.push(format!("methods: {}", method_parts.join(", ")));
        }

        if parts.is_empty() {
            "No changes".to_string()
        } else {
            parts.join("; ")
        }
    }

    fn __repr__(&self) -> String {
        format!("DiffSummary({})", self.text())
    }
}

impl DiffSummary {
    /// Increment counter based on entity and change type.
    pub fn record(&mut self, entity_type: &str, change_type: &str, is_breaking: bool) {
        match entity_type {
            "module" => match change_type {
                "added" => self.modules_added += 1,
                "removed" => self.modules_removed += 1,
                "modified" => self.modules_modified += 1,
                _ => {}
            },
            "function" => match change_type {
                "added" => self.functions_added += 1,
                "removed" => self.functions_removed += 1,
                "modified" => self.functions_modified += 1,
                _ => {}
            },
            "class" => match change_type {
                "added" => self.classes_added += 1,
                "removed" => self.classes_removed += 1,
                "modified" => self.classes_modified += 1,
                _ => {}
            },
            "method" => match change_type {
                "added" => self.methods_added += 1,
                "removed" => self.methods_removed += 1,
                "modified" => self.methods_modified += 1,
                _ => {}
            },
            "parameter" => match change_type {
                "added" => self.parameters_added += 1,
                "removed" => self.parameters_removed += 1,
                "modified" => self.parameters_modified += 1,
                _ => {}
            },
            "import" => match change_type {
                "added" => self.imports_added += 1,
                "removed" => self.imports_removed += 1,
                _ => {}
            },
            _ => {}
        }

        if is_breaking {
            self.breaking_changes += 1;
        }
    }
}

/// Complete result of a semantic diff operation.
#[pyclass]
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct SemanticDiffResult {
    /// All changes detected
    #[pyo3(get)]
    pub changes: Vec<EntityChange>,

    /// Breaking changes only
    #[pyo3(get)]
    pub breaking_changes: Vec<EntityChange>,

    /// Summary statistics
    #[pyo3(get)]
    pub summary: DiffSummary,

    /// Human-readable summary text
    #[pyo3(get)]
    pub summary_text: String,

    /// Duration of diff operation in milliseconds
    #[pyo3(get)]
    pub duration_ms: f64,
}

#[pymethods]
impl SemanticDiffResult {
    #[new]
    fn new() -> Self {
        Self::default()
    }

    /// Check if there are any changes.
    fn has_changes(&self) -> bool {
        !self.changes.is_empty()
    }

    /// Check if there are breaking changes.
    fn has_breaking_changes(&self) -> bool {
        !self.breaking_changes.is_empty()
    }

    /// Get change count.
    fn change_count(&self) -> usize {
        self.changes.len()
    }

    /// Filter changes by entity type.
    fn filter_by_type(&self, entity_type: &str) -> Vec<EntityChange> {
        self.changes
            .iter()
            .filter(|c| c.entity_type == entity_type)
            .cloned()
            .collect()
    }

    /// Filter changes by file path.
    fn filter_by_path(&self, file_path: &str) -> Vec<EntityChange> {
        self.changes
            .iter()
            .filter(|c| c.file_path == file_path)
            .cloned()
            .collect()
    }

    /// Convert to Python dict.
    fn to_dict(&self, py: Python<'_>) -> PyResult<PyObject> {
        let dict = PyDict::new_bound(py);

        let changes: Vec<PyObject> = self
            .changes
            .iter()
            .map(|c| c.to_dict(py))
            .collect::<PyResult<Vec<_>>>()?;
        dict.set_item("changes", changes)?;

        let breaking: Vec<PyObject> = self
            .breaking_changes
            .iter()
            .map(|c| c.to_dict(py))
            .collect::<PyResult<Vec<_>>>()?;
        dict.set_item("breaking_changes", breaking)?;

        dict.set_item("summary", self.summary.to_dict(py)?)?;
        dict.set_item("summary_text", &self.summary_text)?;
        dict.set_item("duration_ms", self.duration_ms)?;
        dict.set_item("has_changes", self.has_changes())?;
        dict.set_item("has_breaking_changes", self.has_breaking_changes())?;

        Ok(dict.into())
    }

    fn __len__(&self) -> usize {
        self.changes.len()
    }

    fn __repr__(&self) -> String {
        format!(
            "SemanticDiffResult({} changes, {} breaking)",
            self.changes.len(),
            self.breaking_changes.len()
        )
    }
}

impl SemanticDiffResult {
    /// Add a change and update summary.
    pub fn add_change(&mut self, change: EntityChange) {
        self.summary
            .record(&change.entity_type, &change.change_type, change.is_breaking);

        if change.is_breaking {
            self.breaking_changes.push(change.clone());
        }

        self.changes.push(change);
    }

    /// Finalize the result with timing and summary text.
    pub fn finalize(&mut self, duration_ms: f64) {
        self.duration_ms = duration_ms;
        self.summary_text = self.summary.text();
    }

    /// Check if there are any changes (Rust API).
    pub fn is_changed(&self) -> bool {
        !self.changes.is_empty()
    }

    /// Check if there are breaking changes (Rust API).
    pub fn is_breaking(&self) -> bool {
        !self.breaking_changes.is_empty()
    }

    /// Filter changes by entity type (Rust API).
    pub fn filter_entity_type(&self, entity_type: &str) -> Vec<EntityChange> {
        self.changes
            .iter()
            .filter(|c| c.entity_type == entity_type)
            .cloned()
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_change_type_as_str() {
        assert_eq!(ChangeType::Added.as_str(), "added");
        assert_eq!(ChangeType::Removed.as_str(), "removed");
        assert_eq!(ChangeType::Modified.as_str(), "modified");
        assert_eq!(ChangeType::Renamed.as_str(), "renamed");
    }

    #[test]
    fn test_entity_type_as_str() {
        assert_eq!(EntityType::Function.as_str(), "function");
        assert_eq!(EntityType::Class.as_str(), "class");
        assert_eq!(EntityType::Method.as_str(), "method");
    }

    #[test]
    fn test_entity_change_create() {
        let change = EntityChange::create(
            ChangeType::Added,
            EntityType::Function,
            "my_func".to_string(),
            "src/lib.rs".to_string(),
        );

        assert_eq!(change.change_type, "added");
        assert_eq!(change.entity_type, "function");
        assert_eq!(change.entity_name, "my_func");
        assert!(!change.is_breaking);
    }

    #[test]
    fn test_entity_change_removed_is_breaking() {
        let change = EntityChange::create(
            ChangeType::Removed,
            EntityType::Function,
            "my_func".to_string(),
            "src/lib.rs".to_string(),
        );

        assert!(change.is_breaking);
    }

    #[test]
    fn test_entity_change_with_parent() {
        let change = EntityChange::create(
            ChangeType::Added,
            EntityType::Method,
            "my_method".to_string(),
            "src/lib.rs".to_string(),
        )
        .with_parent("MyClass");

        assert_eq!(change.parent_name, Some("MyClass".to_string()));
    }

    #[test]
    fn test_diff_summary_record() {
        let mut summary = DiffSummary::default();

        summary.record("function", "added", false);
        assert_eq!(summary.functions_added, 1);

        summary.record("class", "removed", true);
        assert_eq!(summary.classes_removed, 1);
        assert_eq!(summary.breaking_changes, 1);
    }

    #[test]
    fn test_diff_summary_text() {
        let summary = DiffSummary {
            functions_added: 2,
            classes_modified: 1,
            ..Default::default()
        };

        let text = summary.text();
        assert!(text.contains("functions: 2 added"));
        assert!(text.contains("classes: 1 modified"));
    }

    #[test]
    fn test_diff_summary_text_no_changes() {
        let summary = DiffSummary::default();
        assert_eq!(summary.text(), "No changes");
    }

    #[test]
    fn test_semantic_diff_result_add_change() {
        let mut result = SemanticDiffResult::default();

        let change = EntityChange::create(
            ChangeType::Added,
            EntityType::Function,
            "new_func".to_string(),
            "src/main.py".to_string(),
        );

        result.add_change(change);

        assert!(result.has_changes());
        assert!(!result.has_breaking_changes());
        assert_eq!(result.summary.functions_added, 1);
    }

    #[test]
    fn test_semantic_diff_result_breaking() {
        let mut result = SemanticDiffResult::default();

        let change = EntityChange::create(
            ChangeType::Removed,
            EntityType::Function,
            "old_func".to_string(),
            "src/main.py".to_string(),
        );

        result.add_change(change);

        assert!(result.has_changes());
        assert!(result.has_breaking_changes());
        assert_eq!(result.breaking_changes.len(), 1);
    }

    #[test]
    fn test_semantic_diff_result_finalize() {
        let mut result = SemanticDiffResult::default();
        result.summary.functions_added = 1;

        result.finalize(42.5);

        assert_eq!(result.duration_ms, 42.5);
        assert!(!result.summary_text.is_empty());
    }
}
