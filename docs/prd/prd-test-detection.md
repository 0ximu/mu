# PRD: Language-Agnostic Test Detection

## Business Context

### Problem Statement
MU's `mu warn` command incorrectly reports "No test file found" for files that have corresponding tests in non-Python project structures. This was observed on the Dominaite codebase where `mu warn PayoutService.cs` claimed no tests existed, but `PayoutServiceTests.cs` exists in the `.Tests` project directory.

**Root Cause**: MU's test detection heuristic is Python-centric, looking for patterns like `test_*.py` and `*_test.py`. It doesn't recognize test conventions for other languages:
- .NET: `*Tests.cs` in `*.Tests/` or `*.Test/` projects
- Java: `*Test.java` in `src/test/`
- Go: `*_test.go` in same directory
- TypeScript/JavaScript: `*.test.ts`, `*.spec.ts` in `__tests__/` or alongside source

### Outcome
When `mu warn` analyzes a file, it should correctly identify whether tests exist using language-appropriate patterns. This eliminates false positives that erode user trust in MU's analysis capabilities.

### Users
- AI agents (Claude Code) using MU for code analysis
- Developers running `mu warn` for code health checks
- CI/CD pipelines using MU for automated analysis

---

## Discovery Phase

**IMPORTANT**: Before implementing, the agent MUST first explore the codebase to understand:

1. **Where test detection currently lives**
   ```
   mu query "SELECT file_path, name FROM functions WHERE name LIKE '%test%' AND file_path LIKE '%warn%'"
   ```
   
2. **How warnings are structured**
   ```
   mu context "how does mu warn detect missing tests"
   ```

3. **What language detection already exists**
   - Check `mu-core/src/parser/mod.rs` for language detection
   - Check `src/mu/scanner/__init__.py` for file classification

### Expected Discovery Locations

| Component | Likely Location | What to Look For |
|-----------|-----------------|------------------|
| Test detection heuristic | `src/mu/intelligence/warnings.py` | Functions checking for test files |
| Warning generation | `mu-daemon/src/server/http.rs` (analyze_warnings) | Rust warning analysis |
| Language detection | `mu-core/src/parser/mod.rs` | `parse_source()` language parameter |
| File scanning | `src/mu/scanner/__init__.py` | Language classification from extensions |

---

## Existing Patterns Found

From codebase.mu analysis:

| Pattern | File | Relevance |
|---------|------|-----------|
| `WarningInfo` struct | `mu-daemon/src/server/http.rs` | Warning model with category, level, message, details |
| `WarnResponse` struct | `mu-daemon/src/server/http.rs` | Response includes target_type, warnings array |
| `analyze_warnings()` | `mu-daemon/src/server/http.rs` | Main warning analysis function (complexity: 24) |
| Language parsers | `mu-core/src/parser/{python,csharp,java,go,typescript}.rs` | Per-language parsing exists |
| `FileInfo` dataclass | `src/mu/scanner/__init__.py` | Has `language` field |

---

## Task Breakdown

### Task 1: Create Language-Aware Test Pattern Registry

**File(s)**: `src/mu/intelligence/test_patterns.py` (new file)

**Description**: Create a registry of test file patterns per language. This centralizes test detection logic and makes it easy to add new languages.

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TestPattern:
    """Pattern for detecting test files in a specific language."""
    language: str
    file_patterns: list[str]        # Glob patterns: ["*Tests.cs", "*_test.go"]
    dir_patterns: list[str]         # Directory patterns: ["*.Tests", "src/test"]
    test_suffix_patterns: list[str] # For matching source->test: ["Tests", "Test", "_test"]


TEST_PATTERNS: dict[str, TestPattern] = {
    "python": TestPattern(
        language="python",
        file_patterns=["test_*.py", "*_test.py"],
        dir_patterns=["tests/", "test/"],
        test_suffix_patterns=["_test", "test_"],
    ),
    "csharp": TestPattern(
        language="csharp",
        file_patterns=["*Tests.cs", "*Test.cs"],
        dir_patterns=["*.Tests/", "*.Test/", "Tests/"],
        test_suffix_patterns=["Tests", "Test"],
    ),
    "java": TestPattern(
        language="java",
        file_patterns=["*Test.java", "*Tests.java"],
        dir_patterns=["src/test/", "test/"],
        test_suffix_patterns=["Test", "Tests"],
    ),
    "go": TestPattern(
        language="go",
        file_patterns=["*_test.go"],
        dir_patterns=[],  # Go tests live alongside source
        test_suffix_patterns=["_test"],
    ),
    "typescript": TestPattern(
        language="typescript",
        file_patterns=["*.test.ts", "*.spec.ts", "*.test.tsx", "*.spec.tsx"],
        dir_patterns=["__tests__/", "test/", "tests/"],
        test_suffix_patterns=[".test", ".spec"],
    ),
    "javascript": TestPattern(
        language="javascript",
        file_patterns=["*.test.js", "*.spec.js", "*.test.jsx", "*.spec.jsx"],
        dir_patterns=["__tests__/", "test/", "tests/"],
        test_suffix_patterns=[".test", ".spec"],
    ),
    "rust": TestPattern(
        language="rust",
        file_patterns=[],  # Rust tests are inline or in tests/ dir
        dir_patterns=["tests/"],
        test_suffix_patterns=["_test"],
    ),
}


def find_test_file(source_path: Path, language: str, project_root: Path) -> Path | None:
    """Find the test file corresponding to a source file.
    
    Args:
        source_path: Path to the source file
        language: Programming language of the source file
        project_root: Root directory of the project
        
    Returns:
        Path to the test file if found, None otherwise
    """
    pattern = TEST_PATTERNS.get(language)
    if not pattern:
        return None
    
    source_name = source_path.stem  # e.g., "PayoutService" from "PayoutService.cs"
    
    # Strategy 1: Look for test file with matching name pattern
    for suffix in pattern.test_suffix_patterns:
        # Try same directory first
        test_name = f"{source_name}{suffix}{source_path.suffix}"
        test_path = source_path.parent / test_name
        if test_path.exists():
            return test_path
    
    # Strategy 2: Look in test directories
    for dir_pattern in pattern.dir_patterns:
        # Handle project-relative test directories (e.g., *.Tests for .NET)
        if dir_pattern.startswith("*"):
            # Find directories matching pattern
            for test_dir in project_root.glob(dir_pattern):
                if test_dir.is_dir():
                    for suffix in pattern.test_suffix_patterns:
                        for test_file in test_dir.rglob(f"{source_name}{suffix}.*"):
                            if test_file.suffix == source_path.suffix:
                                return test_file
        else:
            # Absolute test directory
            test_dir = project_root / dir_pattern
            if test_dir.exists():
                for suffix in pattern.test_suffix_patterns:
                    for test_file in test_dir.rglob(f"{source_name}{suffix}.*"):
                        if test_file.suffix == source_path.suffix:
                            return test_file
    
    return None


def is_test_file(file_path: Path, language: str) -> bool:
    """Check if a file is a test file based on language conventions.
    
    Args:
        file_path: Path to check
        language: Programming language
        
    Returns:
        True if the file appears to be a test file
    """
    pattern = TEST_PATTERNS.get(language)
    if not pattern:
        return False
    
    file_name = file_path.name
    
    # Check file patterns
    for file_pattern in pattern.file_patterns:
        if _matches_glob(file_name, file_pattern):
            return True
    
    # Check if in test directory
    path_str = str(file_path)
    for dir_pattern in pattern.dir_patterns:
        clean_pattern = dir_pattern.rstrip("/").replace("*", "")
        if clean_pattern in path_str:
            return True
    
    return False


def _matches_glob(filename: str, pattern: str) -> bool:
    """Simple glob matching for filenames."""
    import fnmatch
    return fnmatch.fnmatch(filename, pattern)
```

**Acceptance Criteria**:
- [ ] `TEST_PATTERNS` registry covers Python, C#, Java, Go, TypeScript, JavaScript, Rust
- [ ] `find_test_file()` correctly locates tests for each language
- [ ] `is_test_file()` correctly identifies test files
- [ ] Unit tests cover all supported languages

---

### Task 2: Integrate Test Patterns into Python Warning Analysis

**File(s)**: `src/mu/intelligence/warnings.py`

**Discovery First**: 
```bash
grep -n "test" src/mu/intelligence/warnings.py
```

**Description**: Update the existing warning analysis to use the new language-aware test detection.

**Pattern to Follow**: Look at how other warnings are generated in the same file.

**Changes**:
```python
from mu.intelligence.test_patterns import find_test_file, is_test_file

def check_missing_tests(
    node: Node, 
    mubase: MUbase, 
    project_root: Path
) -> WarningInfo | None:
    """Check if a source file has corresponding tests.
    
    Uses language-aware patterns to find test files.
    """
    if not node.file_path:
        return None
    
    source_path = Path(node.file_path)
    
    # Detect language from file extension or node properties
    language = _detect_language(source_path)
    
    # Skip if already a test file
    if is_test_file(source_path, language):
        return None
    
    # Look for corresponding test file
    test_file = find_test_file(source_path, language, project_root)
    
    if test_file is None:
        return WarningInfo(
            category="testing",
            level="warning",
            message=f"No test file found for {source_path.name}",
            details={
                "source_file": str(source_path),
                "language": language,
                "expected_patterns": _get_expected_test_names(source_path, language),
            }
        )
    
    return None


def _detect_language(path: Path) -> str:
    """Detect language from file extension."""
    ext_to_lang = {
        ".py": "python",
        ".cs": "csharp",
        ".java": "java",
        ".go": "go",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".rs": "rust",
    }
    return ext_to_lang.get(path.suffix.lower(), "unknown")


def _get_expected_test_names(source_path: Path, language: str) -> list[str]:
    """Generate list of expected test file names for helpful error messages."""
    from mu.intelligence.test_patterns import TEST_PATTERNS
    
    pattern = TEST_PATTERNS.get(language)
    if not pattern:
        return []
    
    source_name = source_path.stem
    expected = []
    for suffix in pattern.test_suffix_patterns:
        expected.append(f"{source_name}{suffix}{source_path.suffix}")
    return expected
```

**Acceptance Criteria**:
- [ ] Warning analysis uses language-aware test detection
- [ ] False positive eliminated for .NET projects with `*Tests.cs` pattern
- [ ] Warning message includes helpful details (expected patterns)
- [ ] Existing Python test detection still works

---

### Task 3: Update Rust Daemon Warning Analysis

**File(s)**: `mu-daemon/src/server/http.rs`

**Discovery First**:
```bash
grep -n "test" mu-daemon/src/server/http.rs | head -30
```

**Description**: The Rust daemon has its own `analyze_warnings()` function that needs the same language-aware test detection.

**Pattern**: Follow how `analyze_warnings()` currently generates warnings.

**Changes** (conceptual - adapt to actual code structure):
```rust
// In mu-daemon/src/server/http.rs

struct TestPattern {
    language: String,
    file_patterns: Vec<String>,
    dir_patterns: Vec<String>,
    test_suffix_patterns: Vec<String>,
}

lazy_static! {
    static ref TEST_PATTERNS: HashMap<String, TestPattern> = {
        let mut m = HashMap::new();
        m.insert("csharp".to_string(), TestPattern {
            language: "csharp".to_string(),
            file_patterns: vec!["*Tests.cs".to_string(), "*Test.cs".to_string()],
            dir_patterns: vec!["*.Tests".to_string(), "Tests".to_string()],
            test_suffix_patterns: vec!["Tests".to_string(), "Test".to_string()],
        });
        // ... other languages
        m
    };
}

fn find_test_file(source_path: &Path, language: &str, project_root: &Path) -> Option<PathBuf> {
    let pattern = TEST_PATTERNS.get(language)?;
    let source_stem = source_path.file_stem()?.to_str()?;
    let source_ext = source_path.extension()?.to_str()?;
    
    // Strategy 1: Same directory with test suffix
    for suffix in &pattern.test_suffix_patterns {
        let test_name = format!("{}{}.{}", source_stem, suffix, source_ext);
        let test_path = source_path.parent()?.join(&test_name);
        if test_path.exists() {
            return Some(test_path);
        }
    }
    
    // Strategy 2: Test directories
    for dir_pattern in &pattern.dir_patterns {
        if dir_pattern.starts_with("*") {
            // Glob for matching directories
            let clean_pattern = dir_pattern.trim_start_matches('*');
            for entry in walkdir::WalkDir::new(project_root).max_depth(2) {
                if let Ok(entry) = entry {
                    if entry.path().is_dir() && 
                       entry.path().to_str().map_or(false, |s| s.ends_with(clean_pattern)) {
                        for suffix in &pattern.test_suffix_patterns {
                            let test_name = format!("{}{}.{}", source_stem, suffix, source_ext);
                            let test_path = entry.path().join(&test_name);
                            if test_path.exists() {
                                return Some(test_path);
                            }
                        }
                    }
                }
            }
        }
    }
    
    None
}
```

**Acceptance Criteria**:
- [ ] Rust daemon uses same language-aware patterns as Python
- [ ] `analyze_warnings()` correctly finds .NET tests
- [ ] Performance acceptable (< 100ms for typical project)

---

### Task 4: Add Language Detection to Warning Pipeline

**File(s)**: 
- `src/mu/intelligence/warnings.py`
- `mu-daemon/src/server/http.rs`

**Description**: Ensure the warning analysis has access to the file's language when analyzing nodes.

**Discovery First**:
```
mu query "SELECT name, file_path FROM nodes WHERE file_path LIKE '%.cs' LIMIT 5"
```

Check if nodes already have language info in properties.

**Changes**: If language is not in node properties, derive it from file extension.

**Acceptance Criteria**:
- [ ] Language available during warning analysis
- [ ] Works for all supported languages
- [ ] Fallback to extension-based detection if not in node properties

---

### Task 5: Unit Tests for Test Detection

**File(s)**: `tests/unit/test_test_patterns.py` (new file)

**Description**: Comprehensive tests for the test pattern matching logic.

```python
import pytest
from pathlib import Path
from mu.intelligence.test_patterns import (
    find_test_file,
    is_test_file,
    TEST_PATTERNS,
)


class TestIsTestFile:
    """Tests for is_test_file() function."""
    
    @pytest.mark.parametrize("path,language,expected", [
        # Python
        (Path("test_service.py"), "python", True),
        (Path("service_test.py"), "python", True),
        (Path("service.py"), "python", False),
        (Path("tests/test_foo.py"), "python", True),
        
        # C#
        (Path("PayoutServiceTests.cs"), "csharp", True),
        (Path("PayoutServiceTest.cs"), "csharp", True),
        (Path("PayoutService.cs"), "csharp", False),
        (Path("Project.Tests/ServiceTests.cs"), "csharp", True),
        
        # Java
        (Path("PayoutServiceTest.java"), "java", True),
        (Path("src/test/java/ServiceTest.java"), "java", True),
        (Path("PayoutService.java"), "java", False),
        
        # Go
        (Path("service_test.go"), "go", True),
        (Path("service.go"), "go", False),
        
        # TypeScript
        (Path("service.test.ts"), "typescript", True),
        (Path("service.spec.ts"), "typescript", True),
        (Path("__tests__/service.test.ts"), "typescript", True),
        (Path("service.ts"), "typescript", False),
    ])
    def test_is_test_file(self, path: Path, language: str, expected: bool):
        assert is_test_file(path, language) == expected


class TestFindTestFile:
    """Tests for find_test_file() function."""
    
    def test_csharp_finds_tests_in_test_project(self, tmp_path: Path):
        """Test that .NET *.Tests project structure is recognized."""
        # Setup
        src_dir = tmp_path / "src" / "Services"
        test_dir = tmp_path / "src" / "Services.Tests"
        src_dir.mkdir(parents=True)
        test_dir.mkdir(parents=True)
        
        source_file = src_dir / "PayoutService.cs"
        test_file = test_dir / "PayoutServiceTests.cs"
        source_file.touch()
        test_file.touch()
        
        # Test
        result = find_test_file(source_file, "csharp", tmp_path)
        assert result == test_file
    
    def test_python_finds_test_prefix(self, tmp_path: Path):
        """Test that Python test_*.py pattern is recognized."""
        source_file = tmp_path / "service.py"
        test_file = tmp_path / "test_service.py"
        source_file.touch()
        test_file.touch()
        
        result = find_test_file(source_file, "python", tmp_path)
        assert result == test_file
    
    def test_go_finds_adjacent_test(self, tmp_path: Path):
        """Test that Go *_test.go in same directory is recognized."""
        source_file = tmp_path / "service.go"
        test_file = tmp_path / "service_test.go"
        source_file.touch()
        test_file.touch()
        
        result = find_test_file(source_file, "go", tmp_path)
        assert result == test_file
    
    def test_returns_none_when_no_test(self, tmp_path: Path):
        """Test that None is returned when no test file exists."""
        source_file = tmp_path / "service.py"
        source_file.touch()
        
        result = find_test_file(source_file, "python", tmp_path)
        assert result is None


class TestPatternRegistry:
    """Tests for TEST_PATTERNS registry."""
    
    def test_all_languages_have_patterns(self):
        """Verify all expected languages are covered."""
        expected_languages = {"python", "csharp", "java", "go", "typescript", "javascript", "rust"}
        assert expected_languages.issubset(set(TEST_PATTERNS.keys()))
    
    def test_patterns_have_required_fields(self):
        """Verify all patterns have the required fields."""
        for lang, pattern in TEST_PATTERNS.items():
            assert pattern.language == lang
            assert isinstance(pattern.file_patterns, list)
            assert isinstance(pattern.dir_patterns, list)
            assert isinstance(pattern.test_suffix_patterns, list)
```

**Acceptance Criteria**:
- [ ] Tests cover all supported languages
- [ ] Tests cover edge cases (no test, test in subdirectory, etc.)
- [ ] Tests pass in CI

---

### Task 6: Integration Test - Dominaite Regression

**File(s)**: `tests/integration/test_warn_multiplatform.py` (new file)

**Description**: End-to-end test that simulates the Dominaite scenario.

```python
import pytest
from pathlib import Path
from mu.intelligence.warnings import check_missing_tests
from mu.kernel.models import Node
from mu.kernel.schema import NodeType


class TestDominaiteRegression:
    """Regression test for the Dominaite false positive.
    
    This test ensures that `mu warn PayoutService.cs` correctly finds
    PayoutServiceTests.cs in the .Tests project directory.
    """
    
    def test_csharp_test_detection_in_test_project(self, tmp_path: Path):
        """The exact scenario that failed on Dominaite."""
        # Setup: Simulate .NET project structure
        # src/Dominaite.Services/PayoutService.cs
        # src/Dominaite.Services.Tests/PayoutServiceTests.cs
        
        services_dir = tmp_path / "src" / "Dominaite.Services"
        tests_dir = tmp_path / "src" / "Dominaite.Services.Tests"
        services_dir.mkdir(parents=True)
        tests_dir.mkdir(parents=True)
        
        source_file = services_dir / "PayoutService.cs"
        test_file = tests_dir / "PayoutServiceTests.cs"
        source_file.write_text("public class PayoutService { }")
        test_file.write_text("public class PayoutServiceTests { }")
        
        # Create a node representing PayoutService
        node = Node(
            id="class:PayoutService",
            type=NodeType.CLASS,
            name="PayoutService",
            qualified_name="Dominaite.Services.PayoutService",
            file_path=str(source_file),
            line_start=1,
            line_end=1,
            complexity=5,
            properties={},
        )
        
        # This should NOT return a warning
        warning = check_missing_tests(node, mubase=None, project_root=tmp_path)
        
        assert warning is None, (
            f"Should not warn about missing tests when {test_file} exists. "
            f"Got warning: {warning}"
        )
```

**Acceptance Criteria**:
- [ ] Test simulates exact Dominaite directory structure
- [ ] No false positive for PayoutService.cs
- [ ] Test is marked as regression test in CI

---

## Dependencies

```
Task 1 (Pattern Registry) 
    ↓
Task 2 (Python Integration) ←─── Task 4 (Language Detection)
    ↓
Task 3 (Rust Integration) ←───── Task 4 (Language Detection)
    ↓
Task 5 (Unit Tests)
    ↓
Task 6 (Integration Test)
```

---

## Implementation Order

| Priority | Task | Effort | Risk |
|----------|------|--------|------|
| P0 | Task 1: Pattern Registry | Small (1h) | Low - new file, no existing code changes |
| P0 | Task 2: Python Integration | Medium (2h) | Medium - modifying existing warning logic |
| P1 | Task 4: Language Detection | Small (30m) | Low |
| P1 | Task 5: Unit Tests | Medium (1h) | Low |
| P2 | Task 3: Rust Integration | Medium (2h) | Medium - Rust code changes |
| P2 | Task 6: Integration Test | Small (30m) | Low |

---

## Success Metrics

1. **False Positive Rate**: 0 false "no test file" warnings for projects with proper test structure
2. **Language Coverage**: Correctly detects tests for Python, C#, Java, Go, TypeScript, JavaScript
3. **Regression Prevention**: Dominaite scenario test passes

---

## Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| Multiple test files for one source | Return first match, no warning |
| Test file with different extension | No match (e.g., `.cs` source won't match `.vb` test) |
| Nested test directories | Search recursively within test directories |
| Monorepo with multiple projects | Use closest ancestor project root |
| No recognized language | Skip test detection, no warning |

---

## Security Considerations

- No sensitive data involved
- File system access limited to project root
- No user input used in glob patterns (prevents injection)

---

## Rollback Plan

If issues arise:
1. Revert to Python-only test detection
2. Add feature flag: `MU_LEGACY_TEST_DETECTION=1`
3. Gradually re-enable per language
