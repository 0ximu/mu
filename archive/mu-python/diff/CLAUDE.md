# Diff Module - Semantic Code Comparison

The diff module computes semantic differences between two versions of a codebase, focusing on structural changes rather than text.

## Architecture

```
AssembledOutput (base) + AssembledOutput (target) -> SemanticDiffer -> DiffResult
                                                            |
                                                    Module/Class/Function diffs
```

### Files

| File | Purpose |
|------|---------|
| `differ.py` | `SemanticDiffer` class, core diff logic |
| `models.py` | Data models: `DiffResult`, `ModuleDiff`, `ClassDiff`, `FunctionDiff` |
| `formatters.py` | Output formatting (JSON, Markdown, table) |
| `git_utils.py` | Git operations for fetching versions |

## Change Types

```python
class ChangeType(Enum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
```

## Diff Hierarchy

```
DiffResult
├── module_diffs: list[ModuleDiff]
│   ├── added/removed_functions: list[str]
│   ├── added/removed_classes: list[str]
│   ├── modified_functions: list[FunctionDiff]
│   │   ├── parameter_changes: list[ParameterChange]
│   │   ├── return_type changes
│   │   └── complexity changes
│   └── modified_classes: list[ClassDiff]
│       ├── inheritance changes
│       ├── added/removed_methods
│       └── modified_methods: list[FunctionDiff]
└── dependency_diff: DependencyDiff
    ├── added/removed_internal
    └── added/removed_external
```

## Usage

### Computing a Diff

```python
from mu.diff.differ import SemanticDiffer, compute_diff

# Using class directly
differ = SemanticDiffer(
    base=base_assembled,
    target=target_assembled,
    base_ref="main",
    target_ref="feature-branch",
)
result = differ.diff()

# Or convenience function
result = compute_diff(base, target, "main", "feature-branch")
```

### Accessing Results

```python
# Module-level changes
for mod_diff in result.module_diffs:
    print(f"{mod_diff.path}: {mod_diff.change_type.value}")

    # Function changes
    for func_name in mod_diff.added_functions:
        print(f"  + {func_name}")
    for func_diff in mod_diff.modified_functions:
        print(f"  ~ {func_diff.name}")
        if func_diff.parameter_changes:
            for p in func_diff.parameter_changes:
                print(f"    param {p.name}: {p.change_type.value}")

# Dependency changes
print(f"New packages: {result.dependency_diff.added_external}")
print(f"Removed packages: {result.dependency_diff.removed_external}")

# Statistics
print(f"Modules: +{result.stats.modules_added} -{result.stats.modules_removed}")
print(f"Functions: +{result.stats.functions_added} ~{result.stats.functions_modified}")
```

## Semantic vs Text Diff

| Semantic Diff | Text Diff |
|---------------|-----------|
| "Function `foo` added parameter `bar: int`" | `+    bar: int,` |
| "Class `User` now inherits from `BaseModel`" | `- class User:` / `+ class User(BaseModel):` |
| "Return type changed `str` -> `Optional[str]`" | (lost in whitespace) |
| Tracks complexity changes | N/A |

## FunctionDiff Details

```python
@dataclass
class FunctionDiff:
    name: str
    change_type: ChangeType
    module_path: str
    class_name: str | None  # If method

    # What changed
    parameter_changes: list[ParameterChange]
    old_return_type: str | None
    new_return_type: str | None
    async_changed: bool      # sync <-> async
    static_changed: bool     # instance <-> static
    old_complexity: int
    new_complexity: int
```

## Git Integration

```python
from mu.diff.git_utils import checkout_ref, get_files_at_ref

# Get file contents at specific ref
files = get_files_at_ref(repo_path, "main", ["src/cli.py", "src/parser/base.py"])

# Diff between refs (full workflow in CLI)
mu diff main feature-branch --format markdown
```

## Output Formats

### JSON
```json
{
  "base_ref": "main",
  "target_ref": "feature",
  "module_diffs": [...],
  "stats": {"modules_added": 1, ...}
}
```

### Markdown
```markdown
## Changes: main -> feature

### Added Modules
- `src/new_feature.py`

### Modified: src/cli.py
- **Functions**:
  - `+` `new_command`
  - `~` `main`: return type `None` -> `int`
```

### Table (Terminal)
```
| Module          | +Func | -Func | ~Func |
|-----------------|-------|-------|-------|
| src/cli.py      | 1     | 0     | 2     |
| src/parser/...  | 0     | 1     | 0     |
```

## What's NOT Diffed

- **Docstrings**: Content changes ignored (structure changes tracked)
- **Comments**: Not part of AST
- **Formatting**: Whitespace-only changes ignored
- **Import order**: Set comparison, order doesn't matter
- **Variable values**: Only declarations tracked

## Anti-Patterns

1. **Never** compare `body_source` directly - use `body_complexity` for change detection
2. **Never** assume modules exist in both versions - check for ADDED/REMOVED first
3. **Never** diff unassembled output - requires `AssembledOutput` for dependency tracking
4. **Never** use text diff for semantic changes - loses structural context

## Testing

```bash
pytest tests/unit/test_diff.py -v
```

Key test scenarios:
- Module added/removed/modified
- Function signature changes
- Parameter changes (add/remove/type change)
- Class inheritance changes
- Method changes within classes
- Dependency graph changes
