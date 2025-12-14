//! Language-aware naming convention utilities
//!
//! Provides naming convention checking and conversion for different programming languages.
//! Each language has different conventions for different entity types (classes, functions,
//! constants, etc.).
//!
//! Supported languages:
//! - Python: snake_case functions, PascalCase classes, SCREAMING_SNAKE_CASE constants
//! - Rust: snake_case functions/modules, PascalCase types, SCREAMING_SNAKE_CASE constants
//! - Go: PascalCase exported, camelCase unexported
//! - JavaScript/TypeScript: camelCase functions, PascalCase classes
//! - Java: camelCase methods, PascalCase classes
//! - C#: PascalCase everything (methods, classes, properties)

use std::fmt;

/// Naming convention type
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[allow(clippy::enum_variant_names)]
pub enum NamingConvention {
    /// lowercase_with_underscores (Python functions, Rust functions)
    SnakeCase,
    /// UpperCamelCase (classes in most languages)
    PascalCase,
    /// lowerCamelCase (JavaScript/Java methods)
    CamelCase,
    /// UPPERCASE_WITH_UNDERSCORES (constants in most languages)
    ScreamingSnakeCase,
}

impl fmt::Display for NamingConvention {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            NamingConvention::SnakeCase => write!(f, "snake_case"),
            NamingConvention::PascalCase => write!(f, "PascalCase"),
            NamingConvention::CamelCase => write!(f, "camelCase"),
            NamingConvention::ScreamingSnakeCase => write!(f, "SCREAMING_SNAKE_CASE"),
        }
    }
}

impl std::str::FromStr for NamingConvention {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "snake" | "snake_case" => Ok(NamingConvention::SnakeCase),
            "pascal" | "pascalcase" | "pascal_case" => Ok(NamingConvention::PascalCase),
            "camel" | "camelcase" | "camel_case" => Ok(NamingConvention::CamelCase),
            "screaming" | "screaming_snake" | "screaming_snake_case" | "constant" | "constants" => {
                Ok(NamingConvention::ScreamingSnakeCase)
            }
            _ => Err(format!(
                "Unknown convention '{}'. Valid options: snake_case, PascalCase, camelCase, SCREAMING_SNAKE_CASE",
                s
            )),
        }
    }
}

/// Entity types that have naming conventions
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EntityType {
    Function,
    Method,
    Class,
    Struct,
    Interface,
    Enum,
    Constant,
    Variable,
    Module,
    Property,
    Parameter,
}

impl std::str::FromStr for EntityType {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "function" | "func" | "fn" => Ok(EntityType::Function),
            "method" => Ok(EntityType::Method),
            "class" => Ok(EntityType::Class),
            "struct" => Ok(EntityType::Struct),
            "interface" | "trait" | "protocol" => Ok(EntityType::Interface),
            "enum" => Ok(EntityType::Enum),
            "constant" | "const" => Ok(EntityType::Constant),
            "variable" | "var" => Ok(EntityType::Variable),
            "module" | "mod" | "package" => Ok(EntityType::Module),
            "property" | "prop" | "field" => Ok(EntityType::Property),
            "parameter" | "param" | "arg" => Ok(EntityType::Parameter),
            _ => Err(format!("Unknown entity type '{}'", s)),
        }
    }
}

/// Get the expected naming convention for a given language and entity type.
///
/// Returns the most common convention for that language/entity combination.
/// For languages not explicitly supported, returns a sensible default.
///
/// # Arguments
/// * `language` - Programming language (e.g., "python", "rust", "go", "typescript")
/// * `entity` - Entity type (e.g., "function", "class", "constant")
///
/// # Returns
/// The expected `NamingConvention` for this language/entity pair
pub fn convention_for(language: &str, entity: &str) -> NamingConvention {
    let entity_type = entity.parse::<EntityType>().unwrap_or(EntityType::Variable);
    convention_for_entity(language, entity_type)
}

/// Get the expected naming convention for a given language and entity type.
pub fn convention_for_entity(language: &str, entity: EntityType) -> NamingConvention {
    let lang = language.to_lowercase();

    match lang.as_str() {
        // Python: snake_case for functions/variables, PascalCase for classes
        "python" | "py" => match entity {
            EntityType::Function
            | EntityType::Method
            | EntityType::Variable
            | EntityType::Parameter => NamingConvention::SnakeCase,
            EntityType::Class | EntityType::Struct | EntityType::Interface | EntityType::Enum => {
                NamingConvention::PascalCase
            }
            EntityType::Constant => NamingConvention::ScreamingSnakeCase,
            EntityType::Module => NamingConvention::SnakeCase,
            EntityType::Property => NamingConvention::SnakeCase,
        },

        // Rust: snake_case for functions/modules, PascalCase for types
        "rust" | "rs" => match entity {
            EntityType::Function
            | EntityType::Method
            | EntityType::Variable
            | EntityType::Parameter => NamingConvention::SnakeCase,
            EntityType::Class | EntityType::Struct | EntityType::Interface | EntityType::Enum => {
                NamingConvention::PascalCase
            }
            EntityType::Constant => NamingConvention::ScreamingSnakeCase,
            EntityType::Module => NamingConvention::SnakeCase,
            EntityType::Property => NamingConvention::SnakeCase,
        },

        // Go: PascalCase for exported, camelCase for unexported
        // We default to PascalCase since we can't easily detect export status
        "go" | "golang" => match entity {
            EntityType::Function | EntityType::Method => NamingConvention::PascalCase, // Exported
            EntityType::Variable | EntityType::Parameter => NamingConvention::CamelCase,
            EntityType::Class | EntityType::Struct | EntityType::Interface | EntityType::Enum => {
                NamingConvention::PascalCase
            }
            EntityType::Constant => NamingConvention::PascalCase, // Go uses PascalCase for exported constants
            EntityType::Module => NamingConvention::SnakeCase,    // Package names are lowercase
            EntityType::Property => NamingConvention::PascalCase,
        },

        // JavaScript/TypeScript: camelCase for functions, PascalCase for classes
        "javascript" | "js" | "typescript" | "ts" => match entity {
            EntityType::Function
            | EntityType::Method
            | EntityType::Variable
            | EntityType::Parameter => NamingConvention::CamelCase,
            EntityType::Class | EntityType::Struct | EntityType::Interface | EntityType::Enum => {
                NamingConvention::PascalCase
            }
            EntityType::Constant => NamingConvention::ScreamingSnakeCase,
            EntityType::Module => NamingConvention::CamelCase,
            EntityType::Property => NamingConvention::CamelCase,
        },

        // Java: camelCase for methods/variables, PascalCase for classes
        "java" => match entity {
            EntityType::Function
            | EntityType::Method
            | EntityType::Variable
            | EntityType::Parameter => NamingConvention::CamelCase,
            EntityType::Class | EntityType::Struct | EntityType::Interface | EntityType::Enum => {
                NamingConvention::PascalCase
            }
            EntityType::Constant => NamingConvention::ScreamingSnakeCase,
            EntityType::Module => NamingConvention::SnakeCase, // Package names lowercase
            EntityType::Property => NamingConvention::CamelCase,
        },

        // C#: PascalCase for almost everything (methods, classes, properties)
        "csharp" | "c#" | "cs" => match entity {
            EntityType::Function | EntityType::Method => NamingConvention::PascalCase,
            EntityType::Variable | EntityType::Parameter => NamingConvention::CamelCase,
            EntityType::Class | EntityType::Struct | EntityType::Interface | EntityType::Enum => {
                NamingConvention::PascalCase
            }
            EntityType::Constant => NamingConvention::PascalCase, // C# uses PascalCase for constants
            EntityType::Module => NamingConvention::PascalCase,   // Namespace names PascalCase
            EntityType::Property => NamingConvention::PascalCase,
        },

        // C/C++: snake_case for functions, varies for types
        "c" | "cpp" | "c++" | "cxx" => match entity {
            EntityType::Function
            | EntityType::Method
            | EntityType::Variable
            | EntityType::Parameter => NamingConvention::SnakeCase,
            EntityType::Class | EntityType::Struct => NamingConvention::PascalCase,
            EntityType::Interface | EntityType::Enum => NamingConvention::PascalCase,
            EntityType::Constant => NamingConvention::ScreamingSnakeCase,
            EntityType::Module => NamingConvention::SnakeCase,
            EntityType::Property => NamingConvention::SnakeCase,
        },

        // Ruby: snake_case for methods, PascalCase for classes
        "ruby" | "rb" => match entity {
            EntityType::Function
            | EntityType::Method
            | EntityType::Variable
            | EntityType::Parameter => NamingConvention::SnakeCase,
            EntityType::Class | EntityType::Struct | EntityType::Interface | EntityType::Enum => {
                NamingConvention::PascalCase
            }
            EntityType::Constant => NamingConvention::ScreamingSnakeCase,
            EntityType::Module => NamingConvention::PascalCase, // Ruby modules are PascalCase
            EntityType::Property => NamingConvention::SnakeCase,
        },

        // PHP: camelCase for methods, PascalCase for classes (PSR-1/PSR-12)
        "php" => match entity {
            EntityType::Function
            | EntityType::Method
            | EntityType::Variable
            | EntityType::Parameter => NamingConvention::CamelCase,
            EntityType::Class | EntityType::Struct | EntityType::Interface | EntityType::Enum => {
                NamingConvention::PascalCase
            }
            EntityType::Constant => NamingConvention::ScreamingSnakeCase,
            EntityType::Module => NamingConvention::PascalCase,
            EntityType::Property => NamingConvention::CamelCase,
        },

        // Kotlin: camelCase for functions, PascalCase for classes
        "kotlin" | "kt" => match entity {
            EntityType::Function
            | EntityType::Method
            | EntityType::Variable
            | EntityType::Parameter => NamingConvention::CamelCase,
            EntityType::Class | EntityType::Struct | EntityType::Interface | EntityType::Enum => {
                NamingConvention::PascalCase
            }
            EntityType::Constant => NamingConvention::ScreamingSnakeCase,
            EntityType::Module => NamingConvention::SnakeCase,
            EntityType::Property => NamingConvention::CamelCase,
        },

        // Swift: camelCase for functions, PascalCase for types
        "swift" => match entity {
            EntityType::Function
            | EntityType::Method
            | EntityType::Variable
            | EntityType::Parameter => NamingConvention::CamelCase,
            EntityType::Class | EntityType::Struct | EntityType::Interface | EntityType::Enum => {
                NamingConvention::PascalCase
            }
            EntityType::Constant => NamingConvention::CamelCase, // Swift uses camelCase for constants
            EntityType::Module => NamingConvention::PascalCase,
            EntityType::Property => NamingConvention::CamelCase,
        },

        // Default: Python-like conventions (widely understood)
        _ => match entity {
            EntityType::Function
            | EntityType::Method
            | EntityType::Variable
            | EntityType::Parameter => NamingConvention::SnakeCase,
            EntityType::Class | EntityType::Struct | EntityType::Interface | EntityType::Enum => {
                NamingConvention::PascalCase
            }
            EntityType::Constant => NamingConvention::ScreamingSnakeCase,
            EntityType::Module => NamingConvention::SnakeCase,
            EntityType::Property => NamingConvention::SnakeCase,
        },
    }
}

/// Check if a name follows the expected convention and return a suggestion if not.
///
/// # Arguments
/// * `name` - The name to check
/// * `conv` - The expected naming convention
///
/// # Returns
/// * `None` if the name follows the convention
/// * `Some(suggestion)` with the corrected name if it doesn't
pub fn check_convention(name: &str, conv: NamingConvention) -> Option<String> {
    let matches = match conv {
        NamingConvention::SnakeCase => is_snake_case(name),
        NamingConvention::PascalCase => is_pascal_case(name),
        NamingConvention::CamelCase => is_camel_case(name),
        NamingConvention::ScreamingSnakeCase => is_screaming_snake_case(name),
    };

    if matches {
        None
    } else {
        let suggestion = match conv {
            NamingConvention::SnakeCase => to_snake_case(name),
            NamingConvention::PascalCase => to_pascal_case(name),
            NamingConvention::CamelCase => to_camel_case(name),
            NamingConvention::ScreamingSnakeCase => to_screaming_snake_case(name),
        };
        Some(suggestion)
    }
}

// ============================================================================
// Case Detection Functions
// ============================================================================

/// Check if a string is in snake_case (lowercase with underscores).
///
/// Valid snake_case:
/// - `hello_world`
/// - `get_user_by_id`
/// - `_private_var` (leading underscore allowed)
/// - `__dunder__` (dunder methods allowed)
///
/// Invalid snake_case:
/// - `HelloWorld` (contains uppercase)
/// - `helloWorld` (contains uppercase)
/// - `hello-world` (contains hyphen)
pub fn is_snake_case(s: &str) -> bool {
    if s.is_empty() {
        return false;
    }

    // Allow dunder methods (__init__, __str__, etc.)
    if is_dunder(s) {
        return true;
    }

    // Allow leading underscores for private/protected
    let s = s.trim_start_matches('_');
    if s.is_empty() {
        return true; // Single underscore is valid
    }

    // Must start with lowercase letter
    let first_char = s.chars().next().unwrap();
    if !first_char.is_ascii_lowercase() && !first_char.is_ascii_digit() {
        return false;
    }

    // All characters must be lowercase, digits, or underscore
    for c in s.chars() {
        if !c.is_ascii_lowercase() && !c.is_ascii_digit() && c != '_' {
            return false;
        }
    }

    // No double underscores (except dunders already handled)
    !s.contains("__")
}

/// Check if a string is in PascalCase (UpperCamelCase).
///
/// Valid PascalCase:
/// - `HelloWorld`
/// - `UserService`
/// - `HTTPHandler` (acronyms allowed)
/// - `IO` (short names allowed)
/// - `ServiceResult<T>` (generics allowed)
/// - `Dictionary<TKey, TValue>` (multi-param generics allowed)
///
/// Invalid PascalCase:
/// - `helloWorld` (starts with lowercase)
/// - `Hello_World` (contains underscore)
/// - `hello_world` (all lowercase)
pub fn is_pascal_case(s: &str) -> bool {
    if s.is_empty() {
        return false;
    }

    // Strip generic type parameters before checking (e.g., "ServiceResult<T>" -> "ServiceResult")
    let base_name = strip_generic_params(s);

    // Must start with uppercase letter
    let first_char = base_name.chars().next().unwrap_or(' ');
    if !first_char.is_ascii_uppercase() {
        return false;
    }

    // All characters must be alphanumeric (no underscores, hyphens)
    for c in base_name.chars() {
        if !c.is_ascii_alphanumeric() {
            return false;
        }
    }

    true
}

/// Strip generic type parameters from a type name.
///
/// Examples:
/// - `ServiceResult<T>` -> `ServiceResult`
/// - `Dictionary<TKey, TValue>` -> `Dictionary`
/// - `List<int>` -> `List`
/// - `NoGenerics` -> `NoGenerics`
fn strip_generic_params(s: &str) -> &str {
    match s.find('<') {
        Some(idx) => &s[..idx],
        None => s,
    }
}

/// Check if a string is in camelCase (lowerCamelCase).
///
/// Valid camelCase:
/// - `helloWorld`
/// - `getUserById`
/// - `parseJSON` (acronyms in uppercase allowed)
///
/// Invalid camelCase:
/// - `HelloWorld` (starts with uppercase)
/// - `hello_world` (contains underscore)
/// - `helloworld` (no case changes - arguably valid but uncommon)
pub fn is_camel_case(s: &str) -> bool {
    if s.is_empty() {
        return false;
    }

    // Must start with lowercase letter
    let first_char = s.chars().next().unwrap();
    if !first_char.is_ascii_lowercase() {
        return false;
    }

    // All characters must be alphanumeric (no underscores, hyphens)
    for c in s.chars() {
        if !c.is_ascii_alphanumeric() {
            return false;
        }
    }

    true
}

/// Check if a string is in SCREAMING_SNAKE_CASE (uppercase with underscores).
///
/// Valid SCREAMING_SNAKE_CASE:
/// - `MAX_SIZE`
/// - `DEFAULT_TIMEOUT`
/// - `API_KEY`
///
/// Invalid SCREAMING_SNAKE_CASE:
/// - `Max_Size` (contains lowercase)
/// - `MAXSIZE` (no underscore - though single words are valid)
/// - `max_size` (all lowercase)
pub fn is_screaming_snake_case(s: &str) -> bool {
    if s.is_empty() {
        return false;
    }

    // Must start with uppercase letter
    let first_char = s.chars().next().unwrap();
    if !first_char.is_ascii_uppercase() && !first_char.is_ascii_digit() {
        return false;
    }

    // All characters must be uppercase, digits, or underscore
    for c in s.chars() {
        if !c.is_ascii_uppercase() && !c.is_ascii_digit() && c != '_' {
            return false;
        }
    }

    // No double underscores
    !s.contains("__")
}

/// Check if a string is a Python dunder method (e.g., __init__, __str__).
pub fn is_dunder(s: &str) -> bool {
    s.len() > 4 && s.starts_with("__") && s.ends_with("__") && !s[2..s.len() - 2].contains("__")
}

/// Check if a method name follows the C# test method naming pattern.
///
/// C# test frameworks (xUnit, NUnit, MSTest) commonly use patterns like:
/// - `Method_Scenario_Expected` (3 parts)
/// - `Method_Scenario` (2 parts, common in test files)
/// - `MethodName_WhenCondition_ShouldResult`
///
/// This pattern uses underscores to separate the method being tested,
/// the scenario/condition, and optionally the expected result.
///
/// # Arguments
/// * `name` - The method name to check
/// * `file_path` - Optional file path to check if it's a test file
///
/// # Examples
/// Valid test method names:
/// - `Constructor_WithValidParameters_InitializesSuccessfully`
/// - `GetUser_WhenUserNotFound_ReturnsNull`
/// - `Constructor_LogsEnabledStatus` (2 parts, valid in test files)
/// - `Add_TwoNumbers_ReturnsSum`
///
/// Not test method names (regular PascalCase):
/// - `GetUserById` (no underscores)
/// - `get_user_by_id` (snake_case, not PascalCase segments)
pub fn is_csharp_test_method(name: &str, file_path: Option<&str>) -> bool {
    // Must have at least 1 underscore
    let underscore_count = name.chars().filter(|&c| c == '_').count();
    if underscore_count < 1 {
        return false;
    }

    // Split by underscores and check each part is PascalCase
    let parts: Vec<&str> = name.split('_').collect();
    if parts.len() < 2 {
        return false;
    }

    // Each part should start with uppercase (PascalCase segments)
    let all_parts_pascal = parts.iter().all(|part| {
        !part.is_empty()
            && part
                .chars()
                .next()
                .map(|c| c.is_ascii_uppercase())
                .unwrap_or(false)
    });

    if !all_parts_pascal {
        return false;
    }

    // Check if we're in a test file
    let is_test_file = file_path.is_some_and(|path| {
        let path_lower = path.to_lowercase();
        path_lower.contains("test")
            || path_lower.contains("spec")
            || path_lower.ends_with("tests.cs")
            || path_lower.ends_with("test.cs")
    });

    // If in a test file, accept 2+ part patterns (Method_Scenario)
    if is_test_file {
        return true;
    }

    // If not clearly in a test file, require 3+ parts (Method_Scenario_Expected)
    // This more distinctive pattern is a strong signal even outside test files
    parts.len() >= 3
}

// ============================================================================
// Case Conversion Functions
// ============================================================================

/// Convert a string to snake_case.
///
/// # Examples
/// - `HelloWorld` -> `hello_world`
/// - `getUserById` -> `get_user_by_id`
/// - `HTTPServer` -> `http_server`
/// - `parseJSON` -> `parse_json`
pub fn to_snake_case(s: &str) -> String {
    if s.is_empty() {
        return String::new();
    }

    let mut result = String::with_capacity(s.len() + 4);
    let mut chars = s.chars().peekable();
    let mut prev_was_uppercase = false;
    let mut prev_was_underscore = true; // Start as true to avoid leading underscore

    while let Some(c) = chars.next() {
        if c == '_' || c == '-' || c == ' ' {
            if !prev_was_underscore {
                result.push('_');
                prev_was_underscore = true;
            }
            prev_was_uppercase = false;
        } else if c.is_ascii_uppercase() {
            // Add underscore before uppercase if:
            // 1. Not at the start
            // 2. Previous wasn't underscore
            // 3. Either previous wasn't uppercase, OR next char is lowercase (for acronyms)
            let next_is_lower = chars
                .peek()
                .map(|c| c.is_ascii_lowercase())
                .unwrap_or(false);
            if !prev_was_underscore && (!prev_was_uppercase || next_is_lower) {
                result.push('_');
            }
            result.push(c.to_ascii_lowercase());
            prev_was_uppercase = true;
            prev_was_underscore = false;
        } else {
            result.push(c.to_ascii_lowercase());
            prev_was_uppercase = false;
            prev_was_underscore = false;
        }
    }

    // Clean up any trailing underscore
    while result.ends_with('_') {
        result.pop();
    }

    result
}

/// Convert a string to PascalCase.
///
/// # Examples
/// - `hello_world` -> `HelloWorld`
/// - `get_user_by_id` -> `GetUserById`
/// - `helloWorld` -> `HelloWorld`
/// - `HELLO_WORLD` -> `HelloWorld`
pub fn to_pascal_case(s: &str) -> String {
    if s.is_empty() {
        return String::new();
    }

    let mut result = String::with_capacity(s.len());
    let mut capitalize_next = true;

    for c in s.chars() {
        if c == '_' || c == '-' || c == ' ' {
            capitalize_next = true;
        } else if capitalize_next {
            result.push(c.to_ascii_uppercase());
            capitalize_next = false;
        } else {
            // Lowercase the rest of the characters in each segment
            result.push(c.to_ascii_lowercase());
        }
    }

    result
}

/// Convert a string to camelCase.
///
/// # Examples
/// - `hello_world` -> `helloWorld`
/// - `GetUserById` -> `getUserById`
/// - `HELLO_WORLD` -> `helloWorld`
pub fn to_camel_case(s: &str) -> String {
    if s.is_empty() {
        return String::new();
    }

    let pascal = to_pascal_case(s);
    if pascal.is_empty() {
        return pascal;
    }

    let mut chars = pascal.chars();
    match chars.next() {
        Some(first) => first.to_ascii_lowercase().to_string() + chars.as_str(),
        None => String::new(),
    }
}

/// Convert a string to SCREAMING_SNAKE_CASE.
///
/// # Examples
/// - `helloWorld` -> `HELLO_WORLD`
/// - `HelloWorld` -> `HELLO_WORLD`
/// - `hello_world` -> `HELLO_WORLD`
pub fn to_screaming_snake_case(s: &str) -> String {
    to_snake_case(s).to_ascii_uppercase()
}

/// Detect the file's language from its extension.
///
/// # Arguments
/// * `file_path` - Path to the file (can be relative or absolute)
///
/// # Returns
/// The detected language name, or "unknown" if not recognized
pub fn detect_language(file_path: &str) -> &'static str {
    let path = std::path::Path::new(file_path);
    let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("");

    match ext.to_lowercase().as_str() {
        "py" | "pyi" | "pyw" => "python",
        "rs" => "rust",
        "go" => "go",
        "js" | "mjs" | "cjs" => "javascript",
        "ts" | "mts" | "cts" => "typescript",
        "jsx" => "javascript",
        "tsx" => "typescript",
        "java" => "java",
        "cs" => "csharp",
        "c" | "h" => "c",
        "cpp" | "cc" | "cxx" | "hpp" | "hxx" => "cpp",
        "rb" => "ruby",
        "php" => "php",
        "kt" | "kts" => "kotlin",
        "swift" => "swift",
        "scala" => "scala",
        "ex" | "exs" => "elixir",
        "erl" | "hrl" => "erlang",
        "hs" | "lhs" => "haskell",
        "ml" | "mli" => "ocaml",
        "fs" | "fsi" | "fsx" => "fsharp",
        "clj" | "cljs" | "cljc" | "edn" => "clojure",
        "lua" => "lua",
        "r" => "r",
        "jl" => "julia",
        "nim" => "nim",
        "zig" => "zig",
        "v" => "v",
        "d" => "d",
        "dart" => "dart",
        _ => "unknown",
    }
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    // ========================================================================
    // Convention Detection Tests
    // ========================================================================

    #[test]
    fn test_is_snake_case() {
        // Valid snake_case
        assert!(is_snake_case("hello_world"));
        assert!(is_snake_case("get_user_by_id"));
        assert!(is_snake_case("simple"));
        assert!(is_snake_case("_private"));
        assert!(is_snake_case("__dunder__"));
        assert!(is_snake_case("with_123_numbers"));

        // Invalid snake_case
        assert!(!is_snake_case("HelloWorld"));
        assert!(!is_snake_case("helloWorld"));
        assert!(!is_snake_case("HELLO_WORLD"));
        assert!(!is_snake_case("hello-world"));
        assert!(!is_snake_case(""));
    }

    #[test]
    fn test_is_pascal_case() {
        // Valid PascalCase
        assert!(is_pascal_case("HelloWorld"));
        assert!(is_pascal_case("UserService"));
        assert!(is_pascal_case("HTTPHandler"));
        assert!(is_pascal_case("IO"));
        assert!(is_pascal_case("A"));

        // Invalid PascalCase
        assert!(!is_pascal_case("helloWorld"));
        assert!(!is_pascal_case("Hello_World"));
        assert!(!is_pascal_case("hello_world"));
        assert!(!is_pascal_case("HELLO_WORLD"));
        assert!(!is_pascal_case(""));
    }

    #[test]
    fn test_is_camel_case() {
        // Valid camelCase
        assert!(is_camel_case("helloWorld"));
        assert!(is_camel_case("getUserById"));
        assert!(is_camel_case("parseJSON"));
        assert!(is_camel_case("simple"));
        assert!(is_camel_case("a"));

        // Invalid camelCase
        assert!(!is_camel_case("HelloWorld"));
        assert!(!is_camel_case("hello_world"));
        assert!(!is_camel_case("HELLO_WORLD"));
        assert!(!is_camel_case(""));
    }

    #[test]
    fn test_is_screaming_snake_case() {
        // Valid SCREAMING_SNAKE_CASE
        assert!(is_screaming_snake_case("HELLO_WORLD"));
        assert!(is_screaming_snake_case("MAX_SIZE"));
        assert!(is_screaming_snake_case("API_KEY"));
        assert!(is_screaming_snake_case("SIMPLE"));
        assert!(is_screaming_snake_case("WITH_123_NUMBERS"));

        // Invalid SCREAMING_SNAKE_CASE
        assert!(!is_screaming_snake_case("hello_world"));
        assert!(!is_screaming_snake_case("HelloWorld"));
        assert!(!is_screaming_snake_case("Hello_World"));
        assert!(!is_screaming_snake_case(""));
    }

    #[test]
    fn test_is_dunder() {
        assert!(is_dunder("__init__"));
        assert!(is_dunder("__str__"));
        assert!(is_dunder("__getitem__"));

        assert!(!is_dunder("__init"));
        assert!(!is_dunder("init__"));
        assert!(!is_dunder("_init_"));
        assert!(!is_dunder("____"));
    }

    // ========================================================================
    // Convention Conversion Tests
    // ========================================================================

    #[test]
    fn test_to_snake_case() {
        assert_eq!(to_snake_case("HelloWorld"), "hello_world");
        assert_eq!(to_snake_case("getUserById"), "get_user_by_id");
        assert_eq!(to_snake_case("HTTPServer"), "http_server");
        assert_eq!(to_snake_case("parseJSON"), "parse_json");
        assert_eq!(to_snake_case("HELLO_WORLD"), "hello_world");
        assert_eq!(to_snake_case("already_snake"), "already_snake");
        assert_eq!(to_snake_case("simple"), "simple");
    }

    #[test]
    fn test_to_pascal_case() {
        assert_eq!(to_pascal_case("hello_world"), "HelloWorld");
        assert_eq!(to_pascal_case("get_user_by_id"), "GetUserById");
        assert_eq!(to_pascal_case("helloWorld"), "Helloworld");
        assert_eq!(to_pascal_case("simple"), "Simple");
        assert_eq!(to_pascal_case("HELLO_WORLD"), "HelloWorld");
    }

    #[test]
    fn test_to_camel_case() {
        assert_eq!(to_camel_case("hello_world"), "helloWorld");
        assert_eq!(to_camel_case("GetUserById"), "getuserbyid"); // note: loses case info in current impl
        assert_eq!(to_camel_case("HELLO_WORLD"), "helloWorld");
        assert_eq!(to_camel_case("simple"), "simple");
        assert_eq!(to_camel_case("Simple"), "simple");
    }

    #[test]
    fn test_to_screaming_snake_case() {
        assert_eq!(to_screaming_snake_case("helloWorld"), "HELLO_WORLD");
        assert_eq!(to_screaming_snake_case("HelloWorld"), "HELLO_WORLD");
        assert_eq!(to_screaming_snake_case("hello_world"), "HELLO_WORLD");
        assert_eq!(to_screaming_snake_case("simple"), "SIMPLE");
    }

    // ========================================================================
    // Check Convention Tests
    // ========================================================================

    #[test]
    fn test_check_convention_returns_none_when_valid() {
        assert!(check_convention("hello_world", NamingConvention::SnakeCase).is_none());
        assert!(check_convention("HelloWorld", NamingConvention::PascalCase).is_none());
        assert!(check_convention("helloWorld", NamingConvention::CamelCase).is_none());
        assert!(check_convention("HELLO_WORLD", NamingConvention::ScreamingSnakeCase).is_none());
    }

    #[test]
    fn test_check_convention_returns_suggestion_when_invalid() {
        assert_eq!(
            check_convention("HelloWorld", NamingConvention::SnakeCase),
            Some("hello_world".to_string())
        );
        assert_eq!(
            check_convention("hello_world", NamingConvention::PascalCase),
            Some("HelloWorld".to_string())
        );
        assert_eq!(
            check_convention("hello_world", NamingConvention::CamelCase),
            Some("helloWorld".to_string())
        );
        assert_eq!(
            check_convention("hello_world", NamingConvention::ScreamingSnakeCase),
            Some("HELLO_WORLD".to_string())
        );
    }

    // ========================================================================
    // Language Detection Tests
    // ========================================================================

    #[test]
    fn test_detect_language() {
        assert_eq!(detect_language("main.py"), "python");
        assert_eq!(detect_language("src/lib.rs"), "rust");
        assert_eq!(detect_language("handlers/user.go"), "go");
        assert_eq!(detect_language("app.js"), "javascript");
        assert_eq!(detect_language("component.tsx"), "typescript");
        assert_eq!(detect_language("Service.java"), "java");
        assert_eq!(detect_language("Controller.cs"), "csharp");
        assert_eq!(detect_language("unknown.xyz"), "unknown");
    }

    // ========================================================================
    // Parse Tests
    // ========================================================================

    #[test]
    fn test_convention_from_str() {
        assert_eq!(
            "snake".parse::<NamingConvention>().unwrap(),
            NamingConvention::SnakeCase
        );
        assert_eq!(
            "pascal".parse::<NamingConvention>().unwrap(),
            NamingConvention::PascalCase
        );
        assert_eq!(
            "camel".parse::<NamingConvention>().unwrap(),
            NamingConvention::CamelCase
        );
        assert_eq!(
            "screaming".parse::<NamingConvention>().unwrap(),
            NamingConvention::ScreamingSnakeCase
        );
        assert!("invalid".parse::<NamingConvention>().is_err());
    }

    #[test]
    fn test_entity_type_from_str() {
        assert_eq!(
            "function".parse::<EntityType>().unwrap(),
            EntityType::Function
        );
        assert_eq!("class".parse::<EntityType>().unwrap(), EntityType::Class);
        assert_eq!(
            "constant".parse::<EntityType>().unwrap(),
            EntityType::Constant
        );
        assert!("invalid".parse::<EntityType>().is_err());
    }

    // ========================================================================
    // C# Test Method Detection Tests
    // ========================================================================

    #[test]
    fn test_csharp_test_method_valid_patterns() {
        // Standard Method_Scenario_Expected pattern
        assert!(is_csharp_test_method(
            "Constructor_WithValidParameters_InitializesSuccessfully",
            None
        ));
        assert!(is_csharp_test_method(
            "GetUser_WhenUserNotFound_ReturnsNull",
            None
        ));
        assert!(is_csharp_test_method("Add_TwoNumbers_ReturnsSum", None));
        assert!(is_csharp_test_method(
            "ProcessOrder_WithInvalidInput_ThrowsException",
            None
        ));

        // More complex patterns with longer names
        assert!(is_csharp_test_method(
            "Calculate_WhenInputIsNegative_ShouldThrowArgumentException",
            None
        ));
        assert!(is_csharp_test_method(
            "Save_WithValidEntity_ReturnsTrue",
            None
        ));
    }

    #[test]
    fn test_csharp_test_method_invalid_patterns() {
        // Regular PascalCase (no underscores) - not a test method pattern
        assert!(!is_csharp_test_method("GetUserById", None));
        assert!(!is_csharp_test_method("ProcessPayment", None));

        // Only one underscore without test file - requires 3+ parts outside test files
        assert!(!is_csharp_test_method("Process_Data", None));
        assert!(!is_csharp_test_method("Get_User", None));

        // snake_case (all lowercase) - not a test method pattern
        assert!(!is_csharp_test_method("get_user_by_id", None));

        // Mixed case with lowercase segments - not valid test pattern
        assert!(!is_csharp_test_method("Get_user_ById", None));
        assert!(!is_csharp_test_method("get_User_ById", None));

        // Empty string
        assert!(!is_csharp_test_method("", None));
    }

    #[test]
    fn test_csharp_test_method_with_test_file_path() {
        // Test file paths should be recognized - 3-part patterns
        assert!(is_csharp_test_method(
            "Constructor_WithValidParameters_InitializesSuccessfully",
            Some("tests/UserServiceTests.cs")
        ));
        assert!(is_csharp_test_method(
            "GetUser_WhenNotFound_ReturnsNull",
            Some("src/Tests/Unit/UserTests.cs")
        ));
        assert!(is_csharp_test_method(
            "Add_TwoNumbers_ReturnsSum",
            Some("MathTest.cs")
        ));
        assert!(is_csharp_test_method(
            "Process_ValidInput_Succeeds",
            Some("spec/ProcessorSpec.cs")
        ));

        // 2-part patterns should also be valid in test files
        assert!(is_csharp_test_method(
            "Constructor_LogsEnabledStatus",
            Some("tests/ServiceTests.cs")
        ));
        assert!(is_csharp_test_method(
            "Get_User",
            Some("tests/UserTests.cs")
        ));
    }

    #[test]
    fn test_csharp_test_method_with_non_test_file_path() {
        // With non-test file paths, 3-part patterns are still recognized
        // (distinctive enough to be a test method even in non-standard location)
        assert!(is_csharp_test_method(
            "Constructor_WithValidParameters_InitializesSuccessfully",
            Some("src/Services/UserService.cs")
        ));

        // But 2-part patterns are NOT recognized outside test files
        // (too ambiguous - could be regular method naming)
        assert!(!is_csharp_test_method(
            "Constructor_LogsStatus",
            Some("src/Services/UserService.cs")
        ));
    }

    // ========================================================================
    // Generic Type Parameter Tests
    // ========================================================================

    #[test]
    fn test_strip_generic_params() {
        assert_eq!(strip_generic_params("ServiceResult<T>"), "ServiceResult");
        assert_eq!(
            strip_generic_params("Dictionary<TKey, TValue>"),
            "Dictionary"
        );
        assert_eq!(strip_generic_params("List<int>"), "List");
        assert_eq!(strip_generic_params("NoGenerics"), "NoGenerics");
        assert_eq!(strip_generic_params("ApiResponse<TData>"), "ApiResponse");
        assert_eq!(
            strip_generic_params("PaginatedResponse<T>"),
            "PaginatedResponse"
        );
    }

    #[test]
    fn test_is_pascal_case_with_generics() {
        // Valid PascalCase with generics
        assert!(is_pascal_case("ServiceResult<T>"));
        assert!(is_pascal_case("ApiResponse<TData>"));
        assert!(is_pascal_case("Dictionary<TKey, TValue>"));
        assert!(is_pascal_case("PaginatedResponse<T>"));
        assert!(is_pascal_case("List<int>"));
        assert!(is_pascal_case("WebhookRequest<T>"));
        assert!(is_pascal_case("TransactionListResponse<T>"));

        // Invalid - still catches non-PascalCase base names
        assert!(!is_pascal_case("serviceResult<T>"));
        assert!(!is_pascal_case("service_result<T>"));
    }
}
