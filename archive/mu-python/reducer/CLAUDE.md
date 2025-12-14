# Reducer Module - Semantic Compression

The reducer transforms parsed `ModuleDef` structures into token-efficient representations, stripping boilerplate while preserving semantic signal.

## Architecture

```
ModuleDef -> TransformationRules -> ReducedModule -> ReducedCodebase
                    |                     |
            Strip/Keep decisions    needs_llm markers
```

### Files

| File | Purpose |
|------|---------|
| `rules.py` | `TransformationRules` - configurable strip/keep decisions |
| `generator.py` | `ReducedModule`, `ReducedCodebase`, transformation application |

## Compression Philosophy

Based on MU spec, achieve 92-98% compression by:

**STRIP** (remove):
- Stdlib imports
- Boilerplate code (simple getters, `__str__`, `__repr__`)
- Defensive code (null checks on internal data)
- Verbose logging statements
- Object mapping code
- Syntax keywords (reconstructed by LLM)

**KEEP** (preserve):
- Function signatures
- Dependencies (external packages)
- State mutations
- Control flow structure
- External I/O operations
- Business logic
- Transactions

## TransformationRules

```python
@dataclass
class TransformationRules:
    # Import filtering
    strip_stdlib_imports: bool = True
    strip_relative_imports: bool = False
    keep_external_deps: bool = True

    # Method filtering
    strip_dunder_methods: bool = True
    keep_dunder_methods: list[str] = ["__init__", "__call__", ...]
    strip_property_getters: bool = True
    strip_empty_methods: bool = True

    # Parameter filtering
    strip_self_parameter: bool = True
    strip_cls_parameter: bool = True

    # Complexity thresholds
    complexity_threshold_for_llm: int = 20  # Suggest LLM summary
    min_method_complexity: int = 3          # Skip trivial methods

    # Annotations
    include_docstrings: bool = False
    include_decorators: bool = True
    include_type_annotations: bool = True
```

## Predefined Rule Sets

```python
# Maximum compression (aggressive stripping)
AGGRESSIVE_RULES = TransformationRules(
    strip_stdlib_imports=True,
    strip_relative_imports=True,
    strip_dunder_methods=True,
    min_method_complexity=5,
)

# Minimal compression (preserve everything)
CONSERVATIVE_RULES = TransformationRules(
    strip_stdlib_imports=False,
    strip_relative_imports=False,
    include_docstrings=True,
    min_method_complexity=1,
)

# Balanced (default)
DEFAULT_RULES = TransformationRules()
```

## LLM Summary Markers

Functions with `body_complexity >= complexity_threshold_for_llm` are marked for LLM summarization:

```python
def needs_llm_summary(self, func: FunctionDef) -> bool:
    return func.body_complexity >= self.complexity_threshold_for_llm
```

In `ReducedModule`:
```python
@dataclass
class ReducedModule:
    # ...
    needs_llm: list[str]  # Function names needing LLM summary
```

The CLI uses this to batch LLM calls for complex functions.

## Reduction Process

```python
from mu.reducer.generator import reduce_codebase
from mu.reducer.rules import DEFAULT_RULES

reduced = reduce_codebase(
    modules=parsed_modules,
    source_path="/path/to/codebase",
    rules=DEFAULT_RULES,
)

# Results
print(f"Modules: {len(reduced.modules)}")
print(f"Total functions: {reduced.stats['total_functions']}")
print(f"Stripped: {reduced.stats['stripped_functions']}")
print(f"Need LLM: {sum(len(m.needs_llm) for m in reduced.modules)}")
```

## What Gets Stripped

### Import Filtering
```python
# Stripped (stdlib)
import os
from typing import Optional

# Kept (external)
from click import command
import litellm
```

### Method Filtering
```python
class User:
    def __str__(self):           # Stripped (dunder)
        return self.name

    def __init__(self, name):    # Kept (in keep_dunder_methods)
        self.name = name

    @property
    def display_name(self):       # Stripped (simple property)
        return self.name

    def save(self):               # Kept (has side effects)
        db.save(self)
```

### Complexity-Based
```python
def simple():      # body_complexity=2, STRIPPED
    return True

def medium():      # body_complexity=15, KEPT
    # some logic
    pass

def complex():     # body_complexity=25, KEPT + needs_llm=True
    # lots of logic
    pass
```

## ReducedCodebase Output

```python
@dataclass
class ReducedCodebase:
    source: str                       # Source path
    modules: list[ReducedModule]      # Reduced modules
    stats: dict[str, int]             # Compression statistics
    dependency_graph: dict            # Populated by assembler
    external_packages: list[str]      # Populated by assembler
    dynamic_dependencies: list        # Populated by assembler
```

## Statistics Tracked

```python
stats = {
    "total_modules": 42,
    "total_functions": 256,
    "total_classes": 35,
    "stripped_functions": 89,       # Removed by rules
    "stripped_methods": 45,
    "functions_needing_llm": 12,    # Complex enough for summary
    "internal_dependencies": 0,     # Populated by assembler
    "external_packages": 0,
    "dynamic_imports": 0,
}
```

## Anti-Patterns

1. **Never** strip functions without checking `body_complexity` first
2. **Never** remove `__init__` - it defines class structure
3. **Never** strip imports without checking if they're external dependencies
4. **Never** modify `FunctionDef.body_source` - LLM needs original
5. **Never** ignore `needs_llm` markers - complex functions need summarization

## Customizing Rules

For project-specific needs:

```python
custom_rules = TransformationRules(
    # Keep docstrings for API documentation
    include_docstrings=True,

    # Keep all dunder methods for special classes
    strip_dunder_methods=False,

    # Higher threshold for LLM (save API costs)
    complexity_threshold_for_llm=50,

    # More aggressive stripping
    min_method_complexity=10,
)
```

## Testing

```bash
pytest tests/unit/test_reducer.py -v
```

Key test scenarios:
- Stdlib import stripping
- Dunder method filtering
- Complexity threshold behavior
- Parameter filtering (self/cls)
- Rule set comparison
