# Parser Module - Multi-Language AST Extraction

The parser module converts source code into language-agnostic `ModuleDef` structures using Tree-sitter for AST parsing.

## Architecture

```
Source File -> Tree-sitter Parser -> Language Extractor -> ModuleDef
                    |                       |
              Language Grammar       Protocol Implementation
```

### Files

| File | Purpose |
|------|---------|
| `base.py` | `LanguageExtractor` protocol, parser routing, helper functions |
| `models.py` | Data models: `ModuleDef`, `ClassDef`, `FunctionDef`, `ImportDef`, `ParameterDef` |
| `python_extractor.py` | Python-specific extraction |
| `typescript_extractor.py` | TypeScript/JavaScript extraction |
| `go_extractor.py` | Go extraction |
| `java_extractor.py` | Java extraction |
| `rust_extractor.py` | Rust extraction |
| `csharp_extractor.py` | C# extraction |

## LanguageExtractor Protocol

All extractors must implement this protocol from `base.py`:

```python
class LanguageExtractor(Protocol):
    def extract(self, root: Node, source: bytes, file_path: str) -> ModuleDef:
        """Extract module definition from AST root node."""
        ...
```

### Adding a New Language Extractor

1. Create `{language}_extractor.py` in this directory
2. Implement `LanguageExtractor` protocol
3. Register in `base.py`:
   - Add to `_get_language()` function (Tree-sitter grammar)
   - Add to `_get_extractor()` function (extractor instance)
4. Add tests in `tests/unit/test_parser.py`
5. Update stdlib list in `assembler/__init__.py`

## Key Patterns

### Extracting Functions

```python
def _extract_function(self, node: Node, source: bytes) -> FunctionDef:
    name = get_node_text(find_child_by_type(node, "identifier"), source)
    params = self._extract_parameters(node, source)
    return_type = self._extract_return_type(node, source)
    body = find_child_by_type(node, "block")

    return FunctionDef(
        name=name,
        parameters=params,
        return_type=return_type,
        body_complexity=count_nodes(body) if body else 0,
        body_source=get_node_text(body, source) if body else None,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
    )
```

### Extracting Imports

Handle both static and dynamic imports:

```python
# Static import
ImportDef(
    module="os.path",
    names=["join", "dirname"],
    is_from=True,
)

# Dynamic import (Python importlib, JS dynamic import())
ImportDef(
    module="<dynamic>",  # Or actual module if known
    is_dynamic=True,
    dynamic_pattern="f'plugins.{name}'",
    dynamic_source="importlib",  # or "__import__", "import()", "require()"
    line_number=42,
)
```

### Body Complexity

Use `count_nodes()` from `base.py` to measure AST complexity:
- Complexity < 3: Trivial (just return/pass)
- Complexity >= 20: Suggest LLM summarization

## Language-Specific Quirks

### Python
- Decorators parsed separately (`@decorator` nodes)
- `async def` has `is_async=True`
- f-strings in dynamic imports need pattern extraction
- Type hints in function signatures and variable annotations

### TypeScript/JavaScript
- Same extractor handles both (minor AST differences)
- `export` keyword affects visibility
- Arrow functions treated as function expressions
- JSX/TSX supported through tree-sitter-typescript

### Go
- Package name extracted from `package` declaration
- Exported symbols start with uppercase
- Multiple return values supported
- Method receivers handled specially

### Java
- Package and class structure mapped to module name
- Annotations parsed as decorators
- Generic types preserved in signatures
- Inner classes tracked as nested ClassDef

### Rust
- `mod` declarations create implicit imports
- `pub` visibility tracked
- Trait implementations handled as class methods
- Macros (`macro_rules!`) extracted as functions

### C#
- Namespaces map to module structure
- Properties extracted with `is_property=True`
- Async methods with `async` keyword
- Generic types preserved

## Helper Functions (base.py)

```python
# Get text content of a node
get_node_text(node: Node, source: bytes) -> str

# Count AST nodes for complexity
count_nodes(node: Node) -> int

# Find child nodes by type
find_child_by_type(node: Node, type_name: str) -> Node | None
find_children_by_type(node: Node, type_name: str) -> list[Node]
find_descendants_by_type(node: Node, type_name: str) -> list[Node]
```

## Anti-Patterns

1. **Never** expose Tree-sitter `Node` types outside this module
2. **Never** raise exceptions for parse errors - set `ParsedFile.error` instead
3. **Never** assume UTF-8 encoding - use `errors="replace"` in decode
4. **Never** hardcode language keywords - use Tree-sitter node types
5. **Never** skip `body_source` for complex functions - reducer needs it for LLM

## Testing

Tests in `tests/unit/test_parser.py` organized by language class:

```python
class TestPythonParser:
    def test_parse_function(self): ...
    def test_parse_class_with_inheritance(self): ...
    def test_dynamic_imports(self): ...

class TestGoParser:
    def test_parse_interface(self): ...
    ...
```

Run language-specific tests:
```bash
pytest tests/unit/test_parser.py::TestPythonParser -v
pytest tests/unit/test_parser.py::TestGoParser -v
```
