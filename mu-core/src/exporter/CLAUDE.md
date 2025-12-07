# Exporter Module - Claude Code Instructions

Multi-format export of `ModuleDef` to MU sigil format, JSON, and Markdown.

## Module Structure

```
exporter/
├── mod.rs          # Module exports
├── mu_format.rs    # MU sigil-based format (primary)
├── json.rs         # JSON via Serde
└── markdown.rs     # Structured Markdown
```

## MU Sigil Format

The primary output format, optimized for LLM consumption. Uses sigils for semantic compression.

### Sigil Reference

| Sigil | Meaning | Example |
|-------|---------|---------|
| `!` | Module/Service | `! auth [python]` |
| `$` | Entity/Class | `$ UserService < BaseService` |
| `#` | Function/Method | `# authenticate(user, password) -> bool` |
| `@` | Metadata/Dependencies | `@ flask, sqlalchemy` |
| `::` | Annotation/Docstring | `:: Handles user authentication` |
| `->` | Return type/flow | `-> Optional[User]` |
| `=>` | State mutation | `=> self.cache` |
| `<` | Inheritance | `$ Admin < User` |

### Output Structure

```
! module_name [language]
  :: Module docstring (truncated)
  @ import1, import2.{name1, name2}
  $ ClassName < BaseClass
    @ @decorator
    :: Class docstring
    # method_name(params) -> return_type
      :: method docstring
  # function_name(params) -> return_type
    :: function docstring
```

### ExportConfig Options

```rust
pub struct ExportConfig {
    pub shell_safe: bool,      // Escape sigils for shell output
    pub include_source: bool,  // Include body_source in output
    pub pretty_print: bool,    // Format JSON/markdown nicely
}
```

When `shell_safe = true`, sigils are escaped: `\!`, `\$`, `\#`, `\@`

### Usage

```rust
use crate::exporter::mu_format;

// Single module with defaults
let output = mu_format::export(&module);

// Multiple modules with config
let config = ExportConfig {
    shell_safe: true,
    include_source: false,
    pretty_print: false,
};
let output = mu_format::export_all(&modules, &config);
```

## JSON Format

Direct serialization via Serde. All types derive `Serialize`.

```rust
use crate::exporter::json;

// Compact JSON
let output = json::export(&modules, &ExportConfig::default())?;

// Pretty-printed
let config = ExportConfig { pretty_print: true, ..Default::default() };
let output = json::export(&modules, &config)?;
```

Output mirrors the `ModuleDef` structure exactly.

## Markdown Format

Human-readable documentation format with headers, code blocks, and tables.

```rust
use crate::exporter::markdown;

let output = markdown::export(&module);
```

### Output Structure

```markdown
# module_name

**Language:** python
**Lines:** 150

## Imports

- `flask`
- `sqlalchemy.{Column, String}`

## Classes

### ClassName

**Bases:** BaseClass

**Docstring:** Class description here

#### Methods

##### method_name

```python
def method_name(self, param: str) -> bool:
```

**Complexity:** 5

## Functions

### function_name

...
```

## Adding a New Export Format

### 1. Create Exporter Module

Create `src/exporter/newformat.rs`:

```rust
//! NewFormat exporter.

use crate::types::{ModuleDef, ExportConfig};

/// Export single module to NewFormat.
pub fn export(module: &ModuleDef) -> String {
    export_with_config(module, &ExportConfig::default())
}

/// Export with configuration.
pub fn export_with_config(module: &ModuleDef, config: &ExportConfig) -> String {
    let mut output = String::new();

    // Format module header
    output.push_str(&format_header(module));

    // Format imports
    for import in &module.imports {
        output.push_str(&format_import(import));
    }

    // Format classes
    for class in &module.classes {
        output.push_str(&format_class(class, config));
    }

    // Format functions
    for func in &module.functions {
        output.push_str(&format_function(func, config));
    }

    output
}

// Private formatting helpers...
fn format_header(module: &ModuleDef) -> String { /* ... */ }
fn format_import(import: &ImportDef) -> String { /* ... */ }
fn format_class(class: &ClassDef, config: &ExportConfig) -> String { /* ... */ }
fn format_function(func: &FunctionDef, config: &ExportConfig) -> String { /* ... */ }
```

### 2. Register in mod.rs

```rust
pub mod mu_format;
pub mod json;
pub mod markdown;
pub mod newformat;  // Add this
```

### 3. Expose via PyO3 (if needed)

In `lib.rs`:

```rust
#[pyfunction]
fn export_newformat(module: &ModuleDef) -> PyResult<String> {
    Ok(exporter::newformat::export(module))
}

// In _core module init:
m.add_function(wrap_pyfunction!(export_newformat, m)?)?;
```

## Formatting Conventions

### Docstring Truncation

Long docstrings are truncated to first line + ellipsis:

```rust
fn truncate_docstring(doc: &str) -> String {
    let first_line = doc.lines().next().unwrap_or("");
    if first_line.len() > 80 || doc.lines().count() > 1 {
        format!("{}...", &first_line[..first_line.len().min(77)])
    } else {
        first_line.to_string()
    }
}
```

### Parameter Formatting

```rust
fn format_parameters(params: &[ParameterDef]) -> String {
    params.iter()
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
        .collect::<Vec<_>>()
        .join(", ")
}
```

### Indentation

MU format uses 2-space indentation per level:
- Level 0: Module header
- Level 1: Imports, classes, top-level functions
- Level 2: Class members, decorators
- Level 3: Method details

## Testing

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::*;

    #[test]
    fn test_export_simple_module() {
        let module = ModuleDef {
            name: "test".to_string(),
            language: "python".to_string(),
            ..Default::default()
        };

        let output = export(&module);
        assert!(output.contains("! test [python]"));
    }

    #[test]
    fn test_export_with_class() {
        let module = ModuleDef {
            name: "test".to_string(),
            language: "python".to_string(),
            classes: vec![ClassDef {
                name: "MyClass".to_string(),
                bases: vec!["BaseClass".to_string()],
                ..Default::default()
            }],
            ..Default::default()
        };

        let output = export(&module);
        assert!(output.contains("$ MyClass < BaseClass"));
    }
}
```

## Performance Notes

- String building uses `Vec<String>` + `.join()` for efficiency
- No allocations for empty collections (early returns)
- Docstring truncation avoids full string copies when possible
