//! Comparator logic for diffing ModuleDef structures.

use pyo3::prelude::*;
use rayon::prelude::*;
use std::collections::{HashMap, HashSet};
use std::time::Instant;

use crate::differ::changes::{ChangeType, EntityChange, EntityType, SemanticDiffResult};
use crate::types::{ClassDef, FunctionDef, ModuleDef, ParameterDef};

/// Generate a signature string for a function.
fn generate_signature(func: &FunctionDef) -> String {
    let params: Vec<String> = func
        .parameters
        .iter()
        .map(|p| {
            let mut s = p.name.clone();
            if let Some(ref t) = p.type_annotation {
                s.push_str(": ");
                s.push_str(t);
            }
            if let Some(ref d) = p.default_value {
                s.push_str(" = ");
                s.push_str(d);
            }
            s
        })
        .collect();

    let ret = func
        .return_type
        .as_ref()
        .map(|t| format!(" -> {}", t))
        .unwrap_or_default();

    let async_prefix = if func.is_async { "async " } else { "" };

    format!(
        "{}{}({}){}",
        async_prefix,
        func.name,
        params.join(", "),
        ret
    )
}

/// Diff function parameters and return changes.
fn diff_parameters(
    base: &[ParameterDef],
    head: &[ParameterDef],
    func_name: &str,
    file_path: &str,
    class_name: Option<&str>,
) -> Vec<EntityChange> {
    let mut changes = Vec::new();

    let base_by_name: HashMap<&str, &ParameterDef> =
        base.iter().map(|p| (p.name.as_str(), p)).collect();
    let head_by_name: HashMap<&str, &ParameterDef> =
        head.iter().map(|p| (p.name.as_str(), p)).collect();

    let base_names: HashSet<&str> = base_by_name.keys().copied().collect();
    let head_names: HashSet<&str> = head_by_name.keys().copied().collect();

    // Added parameters
    for name in head_names.difference(&base_names) {
        let param = head_by_name[*name];
        let mut change = EntityChange::create(
            ChangeType::Added,
            EntityType::Parameter,
            (*name).to_string(),
            file_path.to_string(),
        )
        .with_parent(func_name);

        if let Some(class) = class_name {
            change.parent_name = Some(format!("{}.{}", class, func_name));
        }

        let details = match (&param.type_annotation, &param.default_value) {
            (Some(t), Some(d)) => format!("type: {}, default: {}", t, d),
            (Some(t), None) => format!("type: {}", t),
            (None, Some(d)) => format!("default: {}", d),
            (None, None) => String::new(),
        };
        if !details.is_empty() {
            change.details = Some(details);
        }

        changes.push(change);
    }

    // Removed parameters (breaking)
    for name in base_names.difference(&head_names) {
        let mut change = EntityChange::create(
            ChangeType::Removed,
            EntityType::Parameter,
            (*name).to_string(),
            file_path.to_string(),
        )
        .with_parent(func_name)
        .mark_breaking();

        if let Some(class) = class_name {
            change.parent_name = Some(format!("{}.{}", class, func_name));
        }

        changes.push(change);
    }

    // Modified parameters
    for name in base_names.intersection(&head_names) {
        let base_param = base_by_name[*name];
        let head_param = head_by_name[*name];

        let type_changed = base_param.type_annotation != head_param.type_annotation;
        let default_changed = base_param.default_value != head_param.default_value;

        if type_changed || default_changed {
            let mut change = EntityChange::create(
                ChangeType::Modified,
                EntityType::Parameter,
                (*name).to_string(),
                file_path.to_string(),
            )
            .with_parent(func_name);

            if let Some(class) = class_name {
                change.parent_name = Some(format!("{}.{}", class, func_name));
            }

            let mut details_parts = Vec::new();
            if type_changed {
                details_parts.push(format!(
                    "type: {} -> {}",
                    base_param.type_annotation.as_deref().unwrap_or("none"),
                    head_param.type_annotation.as_deref().unwrap_or("none")
                ));
                // Type changes are potentially breaking
                change.is_breaking = true;
            }
            if default_changed {
                details_parts.push(format!(
                    "default: {} -> {}",
                    base_param.default_value.as_deref().unwrap_or("none"),
                    head_param.default_value.as_deref().unwrap_or("none")
                ));
            }
            change.details = Some(details_parts.join(", "));

            changes.push(change);
        }
    }

    changes
}

/// Diff two functions and return changes.
fn diff_functions(
    base: &FunctionDef,
    head: &FunctionDef,
    file_path: &str,
    class_name: Option<&str>,
) -> Vec<EntityChange> {
    let mut changes = Vec::new();

    let entity_type = if class_name.is_some() {
        EntityType::Method
    } else {
        EntityType::Function
    };

    // Check if signature changed
    let old_sig = generate_signature(base);
    let new_sig = generate_signature(head);

    let return_type_changed = base.return_type != head.return_type;
    let async_changed = base.is_async != head.is_async;
    let static_changed = base.is_static != head.is_static;
    let complexity_changed = base.body_complexity != head.body_complexity;

    // Diff parameters
    let param_changes = diff_parameters(
        &base.parameters,
        &head.parameters,
        &head.name,
        file_path,
        class_name,
    );

    let has_signature_change =
        return_type_changed || async_changed || static_changed || !param_changes.is_empty();

    if has_signature_change || complexity_changed {
        let mut details_parts = Vec::new();

        if return_type_changed {
            details_parts.push(format!(
                "return: {} -> {}",
                base.return_type.as_deref().unwrap_or("none"),
                head.return_type.as_deref().unwrap_or("none")
            ));
        }
        if async_changed {
            details_parts.push(format!("async: {} -> {}", base.is_async, head.is_async));
        }
        if static_changed {
            details_parts.push(format!("static: {} -> {}", base.is_static, head.is_static));
        }
        if complexity_changed {
            details_parts.push(format!(
                "complexity: {} -> {}",
                base.body_complexity, head.body_complexity
            ));
        }
        if !param_changes.is_empty() {
            details_parts.push(format!("{} param changes", param_changes.len()));
        }

        let mut change = EntityChange::create(
            ChangeType::Modified,
            entity_type,
            head.name.clone(),
            file_path.to_string(),
        )
        .with_signatures(Some(old_sig), Some(new_sig));

        if let Some(class) = class_name {
            change = change.with_parent(class);
        }

        if !details_parts.is_empty() {
            change.details = Some(details_parts.join(", "));
        }

        // Return type changes are breaking
        if return_type_changed {
            change.is_breaking = true;
        }

        changes.push(change);
    }

    // Add parameter changes
    changes.extend(param_changes);

    changes
}

/// Diff two classes and return changes.
fn diff_classes(base: &ClassDef, head: &ClassDef, file_path: &str) -> Vec<EntityChange> {
    let mut changes = Vec::new();

    let class_name = &head.name;

    // Check inheritance changes
    let base_bases: HashSet<&str> = base.bases.iter().map(|s| s.as_str()).collect();
    let head_bases: HashSet<&str> = head.bases.iter().map(|s| s.as_str()).collect();

    if base_bases != head_bases {
        let mut change = EntityChange::create(
            ChangeType::Modified,
            EntityType::Class,
            class_name.clone(),
            file_path.to_string(),
        );

        let added: Vec<_> = head_bases.difference(&base_bases).collect();
        let removed: Vec<_> = base_bases.difference(&head_bases).collect();

        let mut details_parts = Vec::new();
        if !added.is_empty() {
            let added_str: Vec<&str> = added.iter().map(|s| **s).collect();
            details_parts.push(format!("+bases: {}", added_str.join(", ")));
        }
        if !removed.is_empty() {
            let removed_str: Vec<&str> = removed.iter().map(|s| **s).collect();
            details_parts.push(format!("-bases: {}", removed_str.join(", ")));
            change.is_breaking = true; // Removing inheritance is breaking
        }
        change.details = Some(details_parts.join("; "));

        changes.push(change);
    }

    // Diff methods
    let base_methods: HashMap<&str, &FunctionDef> =
        base.methods.iter().map(|m| (m.name.as_str(), m)).collect();
    let head_methods: HashMap<&str, &FunctionDef> =
        head.methods.iter().map(|m| (m.name.as_str(), m)).collect();

    let base_method_names: HashSet<&str> = base_methods.keys().copied().collect();
    let head_method_names: HashSet<&str> = head_methods.keys().copied().collect();

    // Added methods
    for name in head_method_names.difference(&base_method_names) {
        let method = head_methods[*name];
        let change = EntityChange::create(
            ChangeType::Added,
            EntityType::Method,
            (*name).to_string(),
            file_path.to_string(),
        )
        .with_parent(class_name)
        .with_signatures(None, Some(generate_signature(method)));

        changes.push(change);
    }

    // Removed methods (breaking)
    for name in base_method_names.difference(&head_method_names) {
        let method = base_methods[*name];
        let change = EntityChange::create(
            ChangeType::Removed,
            EntityType::Method,
            (*name).to_string(),
            file_path.to_string(),
        )
        .with_parent(class_name)
        .with_signatures(Some(generate_signature(method)), None)
        .mark_breaking();

        changes.push(change);
    }

    // Modified methods
    for name in base_method_names.intersection(&head_method_names) {
        let base_method = base_methods[*name];
        let head_method = head_methods[*name];

        let method_changes = diff_functions(base_method, head_method, file_path, Some(class_name));
        changes.extend(method_changes);
    }

    // Diff attributes
    let base_attrs: HashSet<&str> = base.attributes.iter().map(|s| s.as_str()).collect();
    let head_attrs: HashSet<&str> = head.attributes.iter().map(|s| s.as_str()).collect();

    // Added attributes
    for name in head_attrs.difference(&base_attrs) {
        let change = EntityChange::create(
            ChangeType::Added,
            EntityType::Attribute,
            (*name).to_string(),
            file_path.to_string(),
        )
        .with_parent(class_name);

        changes.push(change);
    }

    // Removed attributes (potentially breaking)
    for name in base_attrs.difference(&head_attrs) {
        let change = EntityChange::create(
            ChangeType::Removed,
            EntityType::Attribute,
            (*name).to_string(),
            file_path.to_string(),
        )
        .with_parent(class_name)
        .mark_breaking();

        changes.push(change);
    }

    changes
}

/// Diff two modules and return changes.
fn diff_single_module(base: &ModuleDef, head: &ModuleDef) -> Vec<EntityChange> {
    let mut changes = Vec::new();
    let file_path = &head.path;

    // Diff functions
    let base_funcs: HashMap<&str, &FunctionDef> = base
        .functions
        .iter()
        .map(|f| (f.name.as_str(), f))
        .collect();
    let head_funcs: HashMap<&str, &FunctionDef> = head
        .functions
        .iter()
        .map(|f| (f.name.as_str(), f))
        .collect();

    let base_func_names: HashSet<&str> = base_funcs.keys().copied().collect();
    let head_func_names: HashSet<&str> = head_funcs.keys().copied().collect();

    // Added functions
    for name in head_func_names.difference(&base_func_names) {
        let func = head_funcs[*name];
        let change = EntityChange::create(
            ChangeType::Added,
            EntityType::Function,
            (*name).to_string(),
            file_path.to_string(),
        )
        .with_signatures(None, Some(generate_signature(func)));

        changes.push(change);
    }

    // Removed functions (breaking)
    for name in base_func_names.difference(&head_func_names) {
        let func = base_funcs[*name];
        let change = EntityChange::create(
            ChangeType::Removed,
            EntityType::Function,
            (*name).to_string(),
            file_path.to_string(),
        )
        .with_signatures(Some(generate_signature(func)), None)
        .mark_breaking();

        changes.push(change);
    }

    // Modified functions
    for name in base_func_names.intersection(&head_func_names) {
        let base_func = base_funcs[*name];
        let head_func = head_funcs[*name];

        let func_changes = diff_functions(base_func, head_func, file_path, None);
        changes.extend(func_changes);
    }

    // Diff classes
    let base_classes: HashMap<&str, &ClassDef> =
        base.classes.iter().map(|c| (c.name.as_str(), c)).collect();
    let head_classes: HashMap<&str, &ClassDef> =
        head.classes.iter().map(|c| (c.name.as_str(), c)).collect();

    let base_class_names: HashSet<&str> = base_classes.keys().copied().collect();
    let head_class_names: HashSet<&str> = head_classes.keys().copied().collect();

    // Added classes
    for name in head_class_names.difference(&base_class_names) {
        let class = head_classes[*name];
        let mut change = EntityChange::create(
            ChangeType::Added,
            EntityType::Class,
            (*name).to_string(),
            file_path.to_string(),
        );

        if !class.bases.is_empty() {
            change.details = Some(format!("bases: {}", class.bases.join(", ")));
        }

        changes.push(change);
    }

    // Removed classes (breaking)
    for name in base_class_names.difference(&head_class_names) {
        let change = EntityChange::create(
            ChangeType::Removed,
            EntityType::Class,
            (*name).to_string(),
            file_path.to_string(),
        )
        .mark_breaking();

        changes.push(change);
    }

    // Modified classes
    for name in base_class_names.intersection(&head_class_names) {
        let base_class = base_classes[*name];
        let head_class = head_classes[*name];

        let class_changes = diff_classes(base_class, head_class, file_path);
        changes.extend(class_changes);
    }

    // Diff imports
    let base_imports: HashSet<&str> = base.imports.iter().map(|i| i.module.as_str()).collect();
    let head_imports: HashSet<&str> = head.imports.iter().map(|i| i.module.as_str()).collect();

    // Added imports
    for module in head_imports.difference(&base_imports) {
        let change = EntityChange::create(
            ChangeType::Added,
            EntityType::Import,
            (*module).to_string(),
            file_path.to_string(),
        );
        changes.push(change);
    }

    // Removed imports
    for module in base_imports.difference(&head_imports) {
        let change = EntityChange::create(
            ChangeType::Removed,
            EntityType::Import,
            (*module).to_string(),
            file_path.to_string(),
        );
        changes.push(change);
    }

    changes
}

/// Compute semantic diff between two sets of modules.
pub fn semantic_diff_modules(
    base_modules: &[ModuleDef],
    head_modules: &[ModuleDef],
) -> SemanticDiffResult {
    let start = Instant::now();
    let mut result = SemanticDiffResult::default();

    // Build indexes
    let base_by_path: HashMap<&str, &ModuleDef> =
        base_modules.iter().map(|m| (m.path.as_str(), m)).collect();
    let head_by_path: HashMap<&str, &ModuleDef> =
        head_modules.iter().map(|m| (m.path.as_str(), m)).collect();

    let base_paths: HashSet<&str> = base_by_path.keys().copied().collect();
    let head_paths: HashSet<&str> = head_by_path.keys().copied().collect();

    // Added modules
    for path in head_paths.difference(&base_paths) {
        let module = head_by_path[*path];
        let mut change = EntityChange::create(
            ChangeType::Added,
            EntityType::Module,
            module.name.clone(),
            (*path).to_string(),
        );

        let func_count = module.functions.len();
        let class_count = module.classes.len();
        if func_count > 0 || class_count > 0 {
            change.details = Some(format!("{} functions, {} classes", func_count, class_count));
        }

        result.add_change(change);
    }

    // Removed modules (breaking)
    for path in base_paths.difference(&head_paths) {
        let module = base_by_path[*path];
        let change = EntityChange::create(
            ChangeType::Removed,
            EntityType::Module,
            module.name.clone(),
            (*path).to_string(),
        )
        .mark_breaking();

        result.add_change(change);
    }

    // Common modules - diff in parallel
    let common_paths: Vec<&str> = base_paths.intersection(&head_paths).copied().collect();

    let module_changes: Vec<Vec<EntityChange>> = common_paths
        .par_iter()
        .map(|path| {
            let base = base_by_path[*path];
            let head = head_by_path[*path];
            diff_single_module(base, head)
        })
        .collect();

    // Collect changes from modified modules
    for (path, changes) in common_paths.iter().zip(module_changes.into_iter()) {
        if !changes.is_empty() {
            // Add module-level modified change
            let base = base_by_path[*path];
            let mut module_change = EntityChange::create(
                ChangeType::Modified,
                EntityType::Module,
                base.name.clone(),
                (*path).to_string(),
            );
            module_change.details = Some(format!("{} entity changes", changes.len()));
            result.add_change(module_change);

            // Add all entity changes
            for change in changes {
                result.add_change(change);
            }
        }
    }

    result.finalize(start.elapsed().as_secs_f64() * 1000.0);
    result
}

/// PyO3 function to compute semantic diff.
#[pyfunction]
#[pyo3(signature = (base_modules, head_modules))]
pub fn semantic_diff(
    py: Python<'_>,
    base_modules: Vec<ModuleDef>,
    head_modules: Vec<ModuleDef>,
) -> PyResult<SemanticDiffResult> {
    // Release GIL during computation
    Ok(py.allow_threads(|| semantic_diff_modules(&base_modules, &head_modules)))
}

/// PyO3 function to diff two files directly.
///
/// Reads, parses, and diffs two source files in one call.
/// When `normalize_paths` is true, uses the head file path for both modules
/// so they are compared as the same module (useful for comparing file versions).
#[pyfunction]
#[pyo3(signature = (base_path, head_path, language, normalize_paths=true))]
pub fn semantic_diff_files(
    py: Python<'_>,
    base_path: &str,
    head_path: &str,
    language: &str,
    normalize_paths: bool,
) -> PyResult<SemanticDiffResult> {
    use std::fs;

    // Read files
    let base_source = fs::read_to_string(base_path).map_err(|e| {
        pyo3::exceptions::PyIOError::new_err(format!("Failed to read base file: {}", e))
    })?;
    let head_source = fs::read_to_string(head_path).map_err(|e| {
        pyo3::exceptions::PyIOError::new_err(format!("Failed to read head file: {}", e))
    })?;

    // Use normalized path if requested (default: true for CLI usage)
    let effective_base_path = if normalize_paths {
        head_path
    } else {
        base_path
    };

    // Parse files
    let base_result = crate::parser::parse_source(&base_source, effective_base_path, language);
    let head_result = crate::parser::parse_source(&head_source, head_path, language);

    // Handle parse errors
    let base_module = base_result.module.ok_or_else(|| {
        pyo3::exceptions::PyValueError::new_err(format!(
            "Failed to parse base file: {}",
            base_result
                .error
                .unwrap_or_else(|| "Unknown error".to_string())
        ))
    })?;
    let head_module = head_result.module.ok_or_else(|| {
        pyo3::exceptions::PyValueError::new_err(format!(
            "Failed to parse head file: {}",
            head_result
                .error
                .unwrap_or_else(|| "Unknown error".to_string())
        ))
    })?;

    // Diff
    Ok(py.allow_threads(|| semantic_diff_modules(&[base_module], &[head_module])))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_param(name: &str, type_ann: Option<&str>, default: Option<&str>) -> ParameterDef {
        ParameterDef {
            name: name.to_string(),
            type_annotation: type_ann.map(|s| s.to_string()),
            default_value: default.map(|s| s.to_string()),
            is_variadic: false,
            is_keyword: false,
        }
    }

    fn make_function(
        name: &str,
        params: Vec<ParameterDef>,
        return_type: Option<&str>,
    ) -> FunctionDef {
        FunctionDef {
            name: name.to_string(),
            parameters: params,
            return_type: return_type.map(|s| s.to_string()),
            decorators: vec![],
            is_async: false,
            is_method: false,
            is_static: false,
            is_classmethod: false,
            is_property: false,
            docstring: None,
            body_complexity: 1,
            body_source: None,
            call_sites: vec![],
            start_line: 0,
            end_line: 0,
        }
    }

    fn make_class(name: &str, bases: Vec<&str>, methods: Vec<FunctionDef>) -> ClassDef {
        ClassDef {
            name: name.to_string(),
            bases: bases.into_iter().map(|s| s.to_string()).collect(),
            decorators: vec![],
            methods,
            attributes: vec![],
            docstring: None,
            start_line: 0,
            end_line: 0,
            referenced_types: vec![],
        }
    }

    fn make_module(
        name: &str,
        path: &str,
        functions: Vec<FunctionDef>,
        classes: Vec<ClassDef>,
    ) -> ModuleDef {
        ModuleDef {
            name: name.to_string(),
            path: path.to_string(),
            language: "python".to_string(),
            imports: vec![],
            classes,
            functions,
            module_docstring: None,
            total_lines: 0,
        }
    }

    #[test]
    fn test_generate_signature_simple() {
        let func = make_function("foo", vec![], None);
        assert_eq!(generate_signature(&func), "foo()");
    }

    #[test]
    fn test_generate_signature_with_params() {
        let func = make_function(
            "foo",
            vec![
                make_param("a", Some("int"), None),
                make_param("b", Some("str"), Some("\"default\"")),
            ],
            Some("bool"),
        );
        assert_eq!(
            generate_signature(&func),
            "foo(a: int, b: str = \"default\") -> bool"
        );
    }

    #[test]
    fn test_generate_signature_async() {
        let mut func = make_function("foo", vec![], None);
        func.is_async = true;
        assert_eq!(generate_signature(&func), "async foo()");
    }

    #[test]
    fn test_diff_modules_added() {
        let base = vec![];
        let head = vec![make_module("new_mod", "src/new.py", vec![], vec![])];

        let result = semantic_diff_modules(&base, &head);

        assert!(result.is_changed());
        assert_eq!(result.summary.modules_added, 1);

        let module_changes: Vec<_> = result
            .changes
            .iter()
            .filter(|c| c.entity_type == "module" && c.change_type == "added")
            .collect();
        assert_eq!(module_changes.len(), 1);
        assert_eq!(module_changes[0].file_path, "src/new.py");
    }

    #[test]
    fn test_diff_modules_removed() {
        let base = vec![make_module("old_mod", "src/old.py", vec![], vec![])];
        let head = vec![];

        let result = semantic_diff_modules(&base, &head);

        assert!(result.is_changed());
        assert!(result.is_breaking());
        assert_eq!(result.summary.modules_removed, 1);
    }

    #[test]
    fn test_diff_function_added() {
        let base = vec![make_module("mod", "src/mod.py", vec![], vec![])];
        let head = vec![make_module(
            "mod",
            "src/mod.py",
            vec![make_function("new_func", vec![], None)],
            vec![],
        )];

        let result = semantic_diff_modules(&base, &head);

        assert!(result.is_changed());
        assert_eq!(result.summary.functions_added, 1);
    }

    #[test]
    fn test_diff_function_removed_is_breaking() {
        let base = vec![make_module(
            "mod",
            "src/mod.py",
            vec![make_function("old_func", vec![], None)],
            vec![],
        )];
        let head = vec![make_module("mod", "src/mod.py", vec![], vec![])];

        let result = semantic_diff_modules(&base, &head);

        assert!(result.is_changed());
        assert!(result.is_breaking());
        assert_eq!(result.summary.functions_removed, 1);
    }

    #[test]
    fn test_diff_function_modified_return_type() {
        let base = vec![make_module(
            "mod",
            "src/mod.py",
            vec![make_function("func", vec![], Some("str"))],
            vec![],
        )];
        let head = vec![make_module(
            "mod",
            "src/mod.py",
            vec![make_function("func", vec![], Some("int"))],
            vec![],
        )];

        let result = semantic_diff_modules(&base, &head);

        assert!(result.is_changed());
        assert_eq!(result.summary.functions_modified, 1);

        // Return type changes are breaking
        assert!(result.is_breaking());
    }

    #[test]
    fn test_diff_function_modified_params() {
        let base = vec![make_module(
            "mod",
            "src/mod.py",
            vec![make_function(
                "func",
                vec![make_param("a", Some("int"), None)],
                None,
            )],
            vec![],
        )];
        let head = vec![make_module(
            "mod",
            "src/mod.py",
            vec![make_function(
                "func",
                vec![
                    make_param("a", Some("int"), None),
                    make_param("b", Some("str"), None),
                ],
                None,
            )],
            vec![],
        )];

        let result = semantic_diff_modules(&base, &head);

        assert!(result.is_changed());
        assert_eq!(result.summary.parameters_added, 1);
    }

    #[test]
    fn test_diff_parameter_removed_is_breaking() {
        let base = vec![make_module(
            "mod",
            "src/mod.py",
            vec![make_function(
                "func",
                vec![make_param("a", Some("int"), None)],
                None,
            )],
            vec![],
        )];
        let head = vec![make_module(
            "mod",
            "src/mod.py",
            vec![make_function("func", vec![], None)],
            vec![],
        )];

        let result = semantic_diff_modules(&base, &head);

        assert!(result.is_changed());
        assert!(result.is_breaking());
        assert_eq!(result.summary.parameters_removed, 1);
    }

    #[test]
    fn test_diff_class_added() {
        let base = vec![make_module("mod", "src/mod.py", vec![], vec![])];
        let head = vec![make_module(
            "mod",
            "src/mod.py",
            vec![],
            vec![make_class("NewClass", vec![], vec![])],
        )];

        let result = semantic_diff_modules(&base, &head);

        assert!(result.is_changed());
        assert_eq!(result.summary.classes_added, 1);
    }

    #[test]
    fn test_diff_class_removed_is_breaking() {
        let base = vec![make_module(
            "mod",
            "src/mod.py",
            vec![],
            vec![make_class("OldClass", vec![], vec![])],
        )];
        let head = vec![make_module("mod", "src/mod.py", vec![], vec![])];

        let result = semantic_diff_modules(&base, &head);

        assert!(result.is_changed());
        assert!(result.is_breaking());
        assert_eq!(result.summary.classes_removed, 1);
    }

    #[test]
    fn test_diff_class_inheritance_change() {
        let base = vec![make_module(
            "mod",
            "src/mod.py",
            vec![],
            vec![make_class("MyClass", vec!["Base"], vec![])],
        )];
        let head = vec![make_module(
            "mod",
            "src/mod.py",
            vec![],
            vec![make_class("MyClass", vec!["Base", "Mixin"], vec![])],
        )];

        let result = semantic_diff_modules(&base, &head);

        assert!(result.is_changed());
        assert_eq!(result.summary.classes_modified, 1);
    }

    #[test]
    fn test_diff_method_added() {
        let base = vec![make_module(
            "mod",
            "src/mod.py",
            vec![],
            vec![make_class("MyClass", vec![], vec![])],
        )];
        let head = vec![make_module(
            "mod",
            "src/mod.py",
            vec![],
            vec![make_class(
                "MyClass",
                vec![],
                vec![make_function("new_method", vec![], None)],
            )],
        )];

        let result = semantic_diff_modules(&base, &head);

        assert!(result.is_changed());
        assert_eq!(result.summary.methods_added, 1);
    }

    #[test]
    fn test_diff_method_removed_is_breaking() {
        let base = vec![make_module(
            "mod",
            "src/mod.py",
            vec![],
            vec![make_class(
                "MyClass",
                vec![],
                vec![make_function("old_method", vec![], None)],
            )],
        )];
        let head = vec![make_module(
            "mod",
            "src/mod.py",
            vec![],
            vec![make_class("MyClass", vec![], vec![])],
        )];

        let result = semantic_diff_modules(&base, &head);

        assert!(result.is_changed());
        assert!(result.is_breaking());
        assert_eq!(result.summary.methods_removed, 1);
    }

    #[test]
    fn test_diff_no_changes() {
        let module = make_module(
            "mod",
            "src/mod.py",
            vec![make_function("func", vec![], None)],
            vec![],
        );
        let base = vec![module.clone()];
        let head = vec![module];

        let result = semantic_diff_modules(&base, &head);

        assert!(!result.is_changed());
        assert!(!result.is_breaking());
    }

    #[test]
    fn test_diff_result_filter_by_type() {
        let base = vec![make_module("mod", "src/mod.py", vec![], vec![])];
        let head = vec![make_module(
            "mod",
            "src/mod.py",
            vec![make_function("func", vec![], None)],
            vec![make_class("Class", vec![], vec![])],
        )];

        let result = semantic_diff_modules(&base, &head);

        let func_changes = result.filter_entity_type("function");
        assert_eq!(func_changes.len(), 1);

        let class_changes = result.filter_entity_type("class");
        assert_eq!(class_changes.len(), 1);
    }
}
