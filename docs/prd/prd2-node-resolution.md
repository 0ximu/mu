# PRD: Node Resolution & Disambiguation UX

## Business Context

### Problem Statement
When users reference a node by name (e.g., `mu deps PayoutService`), MU often resolves to the wrong node when multiple matches exist. Observed behaviors:

1. **Silent wrong choice**: `mu deps PayoutService` silently picked `PayoutServiceTests` instead of `PayoutService`
2. **Alphabetical bias**: Resolution appears to use alphabetical sorting, causing test files to win over source files (T < t in some cases, or longer paths winning)
3. **No user choice**: Message says "Multiple matches found" but doesn't let user select
4. **Inconsistent interfaces**: Some commands accept class names, others require file paths, with no clear pattern

**User Impact**: Users lose trust in MU when it analyzes the wrong code. They have to guess the exact node ID format, leading to frustration and workarounds like copying full paths.

### Outcome
When multiple nodes match a user's query, MU should:
1. **Prefer source over tests** by default
2. **Prompt for disambiguation** when ambiguous
3. **Provide consistent resolution** across all commands
4. **Show helpful context** (file path, type, line count) to help users choose

### Users
- AI agents (Claude Code) that need deterministic node resolution
- Developers running CLI commands interactively
- Scripts that need predictable behavior

---

## Discovery Phase

**IMPORTANT**: Before implementing, the agent MUST first explore:

1. **Where node resolution currently lives**
   ```
   mu context "how does mu resolve node names to node IDs"
   ```

2. **Which commands use node resolution**
   ```
   mu query "SELECT file_path, name FROM functions WHERE name LIKE '%resolve%node%'"
   ```

3. **How the Rust daemon resolves nodes**
   ```bash
   grep -rn "resolve_node" mu-daemon/src/
   ```

### Expected Discovery Locations

| Component | Likely Location | What to Look For |
|-----------|-----------------|------------------|
| Python node resolution | `src/mu/kernel/mubase.py` | `find_node()`, `get_node_by_name()` |
| Rust node resolution | `mu-daemon/src/muql/executor.rs` | `resolve_node_id()` function |
| CLI commands | `src/mu/commands/*.py` | How commands parse node arguments |
| MUQL executor | `src/mu/kernel/muql/executor.py` | `_resolve_node_id()` method |

---

## Existing Patterns Found

From codebase.mu analysis:

| Pattern | File | Relevance |
|---------|------|-----------|
| `resolve_node_id()` | `mu-daemon/src/muql/executor.rs` | Rust async node resolution |
| `_resolve_node_id()` | `src/mu/kernel/muql/executor.py` | Python node resolution in MUQL |
| `NodeFilter.by_names()` | `src/mu/kernel/export/filters.py` | Fuzzy name matching with `fuzzy` param |
| `find_nodes_by_suffix()` | Test file reference | Suffix-based matching exists |
| `QueryExecutor` | `src/mu/kernel/muql/executor.py` | Main query execution with node resolution |

---

## Task Breakdown

### Task 1: Create NodeResolver with Disambiguation Logic

**File(s)**: `src/mu/kernel/resolver.py` (new file)

**Description**: Centralized node resolution with smart disambiguation and preference ordering.

```python
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from mu.kernel.models import Node
from mu.kernel.schema import NodeType


class ResolutionStrategy(Enum):
    """How to handle multiple matches."""
    INTERACTIVE = "interactive"  # Prompt user to choose
    PREFER_SOURCE = "prefer_source"  # Auto-select source over test
    FIRST_MATCH = "first_match"  # Legacy behavior
    STRICT = "strict"  # Error on ambiguity


@dataclass
class ResolvedNode:
    """Result of node resolution."""
    node: Node
    alternatives: list[Node]  # Other matches that weren't selected
    resolution_method: str  # How the node was selected
    was_ambiguous: bool


@dataclass
class NodeCandidate:
    """A potential node match with scoring metadata."""
    node: Node
    score: float
    is_test: bool
    is_exact_match: bool
    match_type: str  # "exact", "suffix", "fuzzy", "qualified"


class NodeResolver:
    """Resolves user-provided node references to actual Node objects.
    
    Handles ambiguity through configurable strategies:
    - INTERACTIVE: Prompt user to choose (CLI default)
    - PREFER_SOURCE: Auto-select source files over tests (API/MCP default)
    - FIRST_MATCH: Legacy alphabetical selection
    - STRICT: Error on any ambiguity
    """
    
    def __init__(
        self, 
        mubase: "MUbase",
        strategy: ResolutionStrategy = ResolutionStrategy.PREFER_SOURCE,
        interactive_callback: callable = None,
    ):
        self.mubase = mubase
        self.strategy = strategy
        self.interactive_callback = interactive_callback
    
    def resolve(self, reference: str) -> ResolvedNode:
        """Resolve a node reference to a Node object.
        
        Args:
            reference: User-provided reference. Can be:
                - Full node ID: "func:src/services/payout.py:PayoutService.process"
                - Class name: "PayoutService"
                - Function name: "process_payout"
                - File path: "src/services/payout.py"
                - Qualified name: "PayoutService.process"
        
        Returns:
            ResolvedNode with the selected node and alternatives
            
        Raises:
            NodeNotFoundError: If no nodes match
            AmbiguousNodeError: If STRICT strategy and multiple matches
        """
        candidates = self._find_candidates(reference)
        
        if not candidates:
            raise NodeNotFoundError(f"No node found matching '{reference}'")
        
        if len(candidates) == 1:
            return ResolvedNode(
                node=candidates[0].node,
                alternatives=[],
                resolution_method="unique_match",
                was_ambiguous=False,
            )
        
        # Multiple matches - apply strategy
        return self._disambiguate(reference, candidates)
    
    def _find_candidates(self, reference: str) -> list[NodeCandidate]:
        """Find all nodes that could match the reference."""
        candidates = []
        
        # Strategy 1: Exact ID match
        exact = self.mubase.get_node(reference)
        if exact:
            return [NodeCandidate(
                node=exact,
                score=1.0,
                is_test=self._is_test_node(exact),
                is_exact_match=True,
                match_type="exact_id",
            )]
        
        # Strategy 2: Exact name match
        by_name = self.mubase.query(
            f"SELECT * FROM nodes WHERE name = '{_escape_sql(reference)}'"
        )
        for row in by_name.rows:
            node = Node.from_row(row)
            candidates.append(NodeCandidate(
                node=node,
                score=0.9,
                is_test=self._is_test_node(node),
                is_exact_match=True,
                match_type="exact_name",
            ))
        
        if candidates:
            return candidates
        
        # Strategy 3: Suffix match (e.g., "PayoutService" matches "src/.../PayoutService")
        suffix_query = f"SELECT * FROM nodes WHERE name LIKE '%{_escape_sql(reference)}'"
        for row in self.mubase.query(suffix_query).rows:
            node = Node.from_row(row)
            candidates.append(NodeCandidate(
                node=node,
                score=0.7,
                is_test=self._is_test_node(node),
                is_exact_match=False,
                match_type="suffix",
            ))
        
        if candidates:
            return candidates
        
        # Strategy 4: Fuzzy match (case-insensitive, partial)
        fuzzy_query = f"SELECT * FROM nodes WHERE LOWER(name) LIKE LOWER('%{_escape_sql(reference)}%')"
        for row in self.mubase.query(fuzzy_query).rows:
            node = Node.from_row(row)
            candidates.append(NodeCandidate(
                node=node,
                score=0.5,
                is_test=self._is_test_node(node),
                is_exact_match=False,
                match_type="fuzzy",
            ))
        
        return candidates
    
    def _disambiguate(
        self, 
        reference: str, 
        candidates: list[NodeCandidate]
    ) -> ResolvedNode:
        """Select from multiple candidates based on strategy."""
        
        if self.strategy == ResolutionStrategy.STRICT:
            raise AmbiguousNodeError(
                f"Multiple nodes match '{reference}': {[c.node.name for c in candidates]}"
            )
        
        if self.strategy == ResolutionStrategy.PREFER_SOURCE:
            return self._prefer_source(candidates)
        
        if self.strategy == ResolutionStrategy.INTERACTIVE:
            if self.interactive_callback:
                selected_idx = self.interactive_callback(reference, candidates)
                selected = candidates[selected_idx]
                others = [c.node for i, c in enumerate(candidates) if i != selected_idx]
                return ResolvedNode(
                    node=selected.node,
                    alternatives=others,
                    resolution_method="user_selected",
                    was_ambiguous=True,
                )
            else:
                # Fall back to prefer_source if no callback
                return self._prefer_source(candidates)
        
        # FIRST_MATCH - legacy behavior
        candidates.sort(key=lambda c: c.node.id)
        return ResolvedNode(
            node=candidates[0].node,
            alternatives=[c.node for c in candidates[1:]],
            resolution_method="first_match",
            was_ambiguous=True,
        )
    
    def _prefer_source(self, candidates: list[NodeCandidate]) -> ResolvedNode:
        """Select source files over test files."""
        # Sort by: source > test, then by score, then by path length (shorter = better)
        def sort_key(c: NodeCandidate) -> tuple:
            return (
                c.is_test,  # False (source) sorts before True (test)
                -c.score,   # Higher score first
                len(c.node.file_path or ""),  # Shorter paths first
            )
        
        sorted_candidates = sorted(candidates, key=sort_key)
        selected = sorted_candidates[0]
        others = [c.node for c in sorted_candidates[1:]]
        
        return ResolvedNode(
            node=selected.node,
            alternatives=others,
            resolution_method="prefer_source",
            was_ambiguous=True,
        )
    
    def _is_test_node(self, node: Node) -> bool:
        """Check if a node is from a test file."""
        if not node.file_path:
            return False
        
        path = node.file_path.lower()
        test_indicators = [
            "/test", "/tests", "test_", "_test.", ".test.", ".spec.",
            "tests.cs", "test.cs", "test.java", "_test.go", "__tests__",
        ]
        return any(indicator in path for indicator in test_indicators)


class NodeNotFoundError(Exception):
    """Raised when no node matches the reference."""
    pass


class AmbiguousNodeError(Exception):
    """Raised when multiple nodes match and strategy is STRICT."""
    pass


def _escape_sql(value: str) -> str:
    """Escape single quotes for SQL."""
    return value.replace("'", "''")
```

**Acceptance Criteria**:
- [ ] `NodeResolver` handles exact, suffix, and fuzzy matching
- [ ] `PREFER_SOURCE` correctly ranks source files above test files
- [ ] `INTERACTIVE` strategy calls callback for user selection
- [ ] `STRICT` strategy raises error on ambiguity
- [ ] Unit tests cover all strategies and match types

---

### Task 2: Add Interactive Disambiguation to CLI

**File(s)**: `src/mu/commands/_utils.py` or similar shared CLI utilities

**Discovery First**:
```bash
grep -rn "click" src/mu/commands/ | head -20
```

**Description**: Create a reusable prompt for CLI commands when node resolution is ambiguous.

```python
import click
from mu.kernel.resolver import NodeCandidate, NodeResolver, ResolutionStrategy


def resolve_node_interactive(
    mubase: "MUbase",
    reference: str,
    allow_ambiguous: bool = True,
) -> "Node":
    """Resolve a node reference with interactive disambiguation.
    
    For use in CLI commands. Shows a selection menu when multiple matches exist.
    """
    
    def prompt_selection(ref: str, candidates: list[NodeCandidate]) -> int:
        """Display selection menu and return chosen index."""
        click.echo(f"\nMultiple nodes match '{ref}':\n")
        
        for i, candidate in enumerate(candidates, 1):
            node = candidate.node
            test_marker = " [TEST]" if candidate.is_test else ""
            type_str = node.type.value if hasattr(node.type, 'value') else str(node.type)
            
            # Format: 1. PayoutService (class) - src/Services/PayoutService.cs:15-120
            location = ""
            if node.file_path:
                short_path = _shorten_path(node.file_path)
                location = f" - {short_path}"
                if node.line_start:
                    location += f":{node.line_start}"
                    if node.line_end and node.line_end != node.line_start:
                        location += f"-{node.line_end}"
            
            click.echo(f"  {i}. {node.name} ({type_str}){location}{test_marker}")
        
        click.echo()
        
        while True:
            choice = click.prompt(
                "Select",
                type=int,
                default=1,
                show_default=True,
            )
            if 1 <= choice <= len(candidates):
                return choice - 1
            click.echo(f"Please enter a number between 1 and {len(candidates)}")
    
    resolver = NodeResolver(
        mubase=mubase,
        strategy=ResolutionStrategy.INTERACTIVE,
        interactive_callback=prompt_selection,
    )
    
    result = resolver.resolve(reference)
    
    if result.was_ambiguous and result.alternatives:
        click.secho(
            f"Selected: {result.node.name} ({result.resolution_method})",
            fg="green",
        )
    
    return result.node


def resolve_node_auto(
    mubase: "MUbase",
    reference: str,
    prefer_source: bool = True,
) -> "Node":
    """Resolve a node reference automatically (non-interactive).
    
    For use in scripts, APIs, and MCP. Prefers source files over tests.
    """
    strategy = (
        ResolutionStrategy.PREFER_SOURCE 
        if prefer_source 
        else ResolutionStrategy.FIRST_MATCH
    )
    
    resolver = NodeResolver(mubase=mubase, strategy=strategy)
    result = resolver.resolve(reference)
    
    return result.node


def _shorten_path(path: str, max_length: int = 50) -> str:
    """Shorten a file path for display."""
    if len(path) <= max_length:
        return path
    
    parts = path.split("/")
    if len(parts) <= 2:
        return path
    
    # Keep first and last parts, abbreviate middle
    return f"{parts[0]}/.../{'/'.join(parts[-2:])}"
```

**Example Output**:
```
$ mu deps PayoutService

Multiple nodes match 'PayoutService':

  1. PayoutService (class) - src/Services/PayoutService.cs:15-120
  2. PayoutServiceTests (class) - src/Services.Tests/PayoutServiceTests.cs:10-85 [TEST]
  3. PayoutServiceMock (class) - src/Services.Tests/Mocks/PayoutServiceMock.cs:5-30 [TEST]

Select [1]: 1
Selected: PayoutService (user_selected)

Dependencies for PayoutService:
...
```

**Acceptance Criteria**:
- [ ] Interactive prompt shows all candidates with helpful context
- [ ] Test files are clearly marked with `[TEST]`
- [ ] Default selection is the most likely source file
- [ ] User can type number to select
- [ ] Non-interactive mode works for scripts

---

### Task 3: Update CLI Commands to Use NodeResolver

**File(s)**: 
- `src/mu/commands/deps.py`
- `src/mu/commands/impact.py`
- `src/mu/commands/related.py`
- Other commands that accept node references

**Discovery First**:
```bash
grep -rn "node" src/mu/commands/*.py | grep -i "argument\|option"
```

**Description**: Update commands to use the new `resolve_node_interactive()` helper.

**Before**:
```python
@click.command()
@click.argument("node")
def deps(node: str):
    # ... current resolution logic
    result = mubase.get_node(node)  # or similar
```

**After**:
```python
from mu.commands._utils import resolve_node_interactive

@click.command()
@click.argument("node")
@click.option("--no-interactive", is_flag=True, help="Disable interactive selection")
def deps(node: str, no_interactive: bool):
    with get_mubase() as mubase:
        if no_interactive:
            resolved = resolve_node_auto(mubase, node)
        else:
            resolved = resolve_node_interactive(mubase, node)
        
        # ... rest of command using resolved.id
```

**Acceptance Criteria**:
- [ ] `mu deps` uses new resolver
- [ ] `mu impact` uses new resolver
- [ ] `mu related` uses new resolver (and accepts class names, not just file paths)
- [ ] `--no-interactive` flag available for scripting
- [ ] Backward compatible with full node IDs

---

### Task 4: Update Rust Daemon Node Resolution

**File(s)**: `mu-daemon/src/muql/executor.rs`

**Discovery First**:
```bash
grep -n "resolve_node_id" mu-daemon/src/muql/executor.rs
```

**Description**: Update the Rust `resolve_node_id()` to prefer source over test files.

**Current** (likely):
```rust
async fn resolve_node_id(input: &str, state: &AppState) -> String {
    // Probably does simple lookup and returns first match
}
```

**Updated**:
```rust
async fn resolve_node_id(input: &str, state: &AppState) -> String {
    let mubase = state.mubase.read().await;
    
    // Try exact ID match first
    if let Ok(result) = mubase.query(&format!(
        "SELECT id FROM nodes WHERE id = '{}'", 
        input.replace("'", "''")
    )) {
        if !result.rows.is_empty() {
            return input.to_string();
        }
    }
    
    // Find all name matches
    let query = format!(
        "SELECT id, name, file_path, type FROM nodes WHERE name = '{}' OR name LIKE '%{}'",
        input.replace("'", "''"),
        input.replace("'", "''")
    );
    
    if let Ok(result) = mubase.query(&query) {
        if result.rows.is_empty() {
            return input.to_string();
        }
        
        if result.rows.len() == 1 {
            return result.rows[0][0].clone(); // Return ID
        }
        
        // Multiple matches - prefer source over test
        let mut candidates: Vec<_> = result.rows.iter().map(|row| {
            let id = &row[0];
            let file_path = row.get(2).map(|s| s.as_str()).unwrap_or("");
            let is_test = is_test_path(file_path);
            (id.clone(), is_test, file_path.len())
        }).collect();
        
        // Sort: source first, then shorter paths
        candidates.sort_by(|a, b| {
            match (a.1, b.1) {
                (false, true) => std::cmp::Ordering::Less,    // source < test
                (true, false) => std::cmp::Ordering::Greater, // test > source
                _ => a.2.cmp(&b.2),                           // shorter path first
            }
        });
        
        return candidates[0].0.clone();
    }
    
    input.to_string()
}

fn is_test_path(path: &str) -> bool {
    let lower = path.to_lowercase();
    lower.contains("/test") || 
    lower.contains("_test.") || 
    lower.contains(".test.") ||
    lower.contains(".spec.") ||
    lower.contains("tests.cs") ||
    lower.contains("__tests__")
}
```

**Acceptance Criteria**:
- [ ] Rust daemon prefers source files over test files
- [ ] Exact ID matches still work
- [ ] MUQL queries benefit from improved resolution
- [ ] Performance acceptable (< 10ms for resolution)

---

### Task 5: Add Resolution Info to CLI Output

**File(s)**: Various command output formatters

**Description**: When disambiguation happens, show users what was resolved.

**Example Output Enhancement**:
```
$ mu deps PayoutService

ℹ Resolved 'PayoutService' → class:src/Services/PayoutService.cs:PayoutService
  (2 other matches: PayoutServiceTests, PayoutServiceMock)

Dependencies:
  → IPaymentGateway
  → ILogger<PayoutService>
  → PayoutConfig
```

**Acceptance Criteria**:
- [ ] Resolution info shown when ambiguous
- [ ] Can be suppressed with `--quiet`
- [ ] JSON output includes resolution metadata

---

### Task 6: Unit Tests for Node Resolution

**File(s)**: `tests/unit/test_resolver.py` (new file)

```python
import pytest
from mu.kernel.models import Node
from mu.kernel.schema import NodeType
from mu.kernel.resolver import (
    NodeResolver,
    ResolutionStrategy,
    NodeNotFoundError,
    AmbiguousNodeError,
)


@pytest.fixture
def mock_mubase_with_duplicates(mock_mubase):
    """MUbase with PayoutService and PayoutServiceTests."""
    # Add source node
    mock_mubase.add_node(Node(
        id="class:src/Services/PayoutService.cs:PayoutService",
        type=NodeType.CLASS,
        name="PayoutService",
        qualified_name="Services.PayoutService",
        file_path="src/Services/PayoutService.cs",
        line_start=15,
        line_end=120,
        complexity=25,
        properties={},
    ))
    
    # Add test node
    mock_mubase.add_node(Node(
        id="class:src/Services.Tests/PayoutServiceTests.cs:PayoutServiceTests",
        type=NodeType.CLASS,
        name="PayoutServiceTests",
        qualified_name="Services.Tests.PayoutServiceTests",
        file_path="src/Services.Tests/PayoutServiceTests.cs",
        line_start=10,
        line_end=85,
        complexity=15,
        properties={},
    ))
    
    return mock_mubase


class TestNodeResolver:
    """Tests for NodeResolver class."""
    
    def test_exact_id_match(self, mock_mubase_with_duplicates):
        """Exact ID should return immediately without ambiguity."""
        resolver = NodeResolver(mock_mubase_with_duplicates)
        result = resolver.resolve("class:src/Services/PayoutService.cs:PayoutService")
        
        assert result.node.name == "PayoutService"
        assert not result.was_ambiguous
        assert result.resolution_method == "unique_match"
    
    def test_prefer_source_over_test(self, mock_mubase_with_duplicates):
        """PREFER_SOURCE should select source file when name is ambiguous."""
        resolver = NodeResolver(
            mock_mubase_with_duplicates,
            strategy=ResolutionStrategy.PREFER_SOURCE,
        )
        
        # "PayoutService" matches both PayoutService and PayoutServiceTests
        result = resolver.resolve("PayoutService")
        
        assert result.node.name == "PayoutService"
        assert "Tests" not in result.node.file_path
        assert result.was_ambiguous
        assert result.resolution_method == "prefer_source"
        assert len(result.alternatives) == 1
    
    def test_strict_raises_on_ambiguity(self, mock_mubase_with_duplicates):
        """STRICT strategy should raise error when ambiguous."""
        resolver = NodeResolver(
            mock_mubase_with_duplicates,
            strategy=ResolutionStrategy.STRICT,
        )
        
        with pytest.raises(AmbiguousNodeError) as exc_info:
            resolver.resolve("PayoutService")
        
        assert "Multiple nodes match" in str(exc_info.value)
    
    def test_interactive_calls_callback(self, mock_mubase_with_duplicates):
        """INTERACTIVE strategy should call the callback."""
        selected_index = [None]
        
        def mock_callback(ref, candidates):
            selected_index[0] = len(candidates)  # Track that it was called
            return 1  # Select second option
        
        resolver = NodeResolver(
            mock_mubase_with_duplicates,
            strategy=ResolutionStrategy.INTERACTIVE,
            interactive_callback=mock_callback,
        )
        
        result = resolver.resolve("PayoutService")
        
        assert selected_index[0] is not None  # Callback was called
        assert result.resolution_method == "user_selected"
    
    def test_not_found_raises_error(self, mock_mubase_with_duplicates):
        """Should raise NodeNotFoundError when no matches."""
        resolver = NodeResolver(mock_mubase_with_duplicates)
        
        with pytest.raises(NodeNotFoundError) as exc_info:
            resolver.resolve("NonExistentClass")
        
        assert "No node found" in str(exc_info.value)
    
    def test_fuzzy_match_fallback(self, mock_mubase_with_duplicates):
        """Should fall back to fuzzy matching when exact fails."""
        resolver = NodeResolver(mock_mubase_with_duplicates)
        
        # "payout" should fuzzy match "PayoutService"
        result = resolver.resolve("payout")
        
        assert "Payout" in result.node.name


class TestIsTestNode:
    """Tests for test file detection in resolver."""
    
    @pytest.mark.parametrize("path,expected", [
        ("src/Services/PayoutService.cs", False),
        ("src/Services.Tests/PayoutServiceTests.cs", True),
        ("tests/unit/test_service.py", True),
        ("src/app/service_test.go", True),
        ("src/app/__tests__/service.test.ts", True),
        ("src/app/service.spec.ts", True),
        ("src/main/java/Service.java", False),
        ("src/test/java/ServiceTest.java", True),
    ])
    def test_is_test_node(self, path: str, expected: bool):
        node = Node(
            id=f"class:{path}:Test",
            type=NodeType.CLASS,
            name="Test",
            qualified_name="Test",
            file_path=path,
            line_start=1,
            line_end=10,
            complexity=5,
            properties={},
        )
        
        resolver = NodeResolver(None)
        assert resolver._is_test_node(node) == expected
```

**Acceptance Criteria**:
- [ ] Tests cover all resolution strategies
- [ ] Tests cover source vs test preference
- [ ] Tests cover error cases
- [ ] Tests pass in CI

---

### Task 7: Integration Test - Dominaite Regression

**File(s)**: `tests/integration/test_node_resolution.py`

```python
import pytest
from pathlib import Path


class TestDominaiteResolutionRegression:
    """Regression test for mu deps PayoutService picking wrong node.
    
    On Dominaite, `mu deps PayoutService` resolved to PayoutServiceTests
    instead of PayoutService because of alphabetical sorting.
    """
    
    def test_deps_prefers_source_over_test(self, tmp_path: Path):
        """mu deps PayoutService should select the source class, not tests."""
        # This test should use the actual CLI or resolver
        # to ensure the full pipeline works correctly
        
        from mu.kernel.resolver import NodeResolver, ResolutionStrategy
        from mu.kernel import MUbase
        
        # Setup: Create a mubase with both nodes
        db_path = tmp_path / ".mu" / "mubase"
        db_path.parent.mkdir(parents=True)
        
        mubase = MUbase(db_path)
        
        # Add source class
        mubase.add_node({
            "id": "class:src/Services/PayoutService.cs:PayoutService",
            "type": "class",
            "name": "PayoutService",
            "file_path": "src/Services/PayoutService.cs",
            "line_start": 15,
        })
        
        # Add test class (would win alphabetically in old system)
        mubase.add_node({
            "id": "class:src/Services.Tests/PayoutServiceTests.cs:PayoutServiceTests",
            "type": "class",
            "name": "PayoutServiceTests", 
            "file_path": "src/Services.Tests/PayoutServiceTests.cs",
            "line_start": 10,
        })
        
        # Resolve with PREFER_SOURCE (the new default)
        resolver = NodeResolver(mubase, strategy=ResolutionStrategy.PREFER_SOURCE)
        result = resolver.resolve("PayoutService")
        
        # Should get the source file, not the test
        assert result.node.name == "PayoutService"
        assert "Tests" not in result.node.file_path
        assert result.was_ambiguous  # Confirms disambiguation happened
```

**Acceptance Criteria**:
- [ ] Test recreates exact Dominaite scenario
- [ ] Source file wins over test file
- [ ] Test is marked as regression test

---

## Dependencies

```
Task 1 (NodeResolver) 
    ↓
Task 2 (CLI Disambiguation) ←─── Uses NodeResolver
    ↓
Task 3 (Update Commands) ←────── Uses CLI helpers
    
Task 4 (Rust Daemon) ──────────── Independent, parallel track
    
Task 5 (Output Enhancement) ←─── After Task 3
    
Task 6 (Unit Tests) ←──────────── After Task 1
    
Task 7 (Integration Test) ←────── After Task 3
```

---

## Implementation Order

| Priority | Task | Effort | Risk |
|----------|------|--------|------|
| P0 | Task 1: NodeResolver | Medium (2h) | Low - new file |
| P0 | Task 6: Unit Tests | Medium (1h) | Low |
| P1 | Task 2: CLI Disambiguation | Medium (1.5h) | Low |
| P1 | Task 3: Update Commands | Medium (2h) | Medium - touching multiple files |
| P1 | Task 4: Rust Daemon | Medium (1.5h) | Medium - Rust changes |
| P2 | Task 5: Output Enhancement | Small (1h) | Low |
| P2 | Task 7: Integration Test | Small (30m) | Low |

---

## Success Metrics

1. **Correct Resolution Rate**: 100% of `mu deps ClassName` commands resolve to source file when tests exist
2. **User Experience**: Interactive prompt shown < 100ms after detecting ambiguity
3. **Backward Compatibility**: Full node IDs still work without disambiguation

---

## Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| Only test files match | Return test file (it's the only option) |
| Multiple source files match | Prefer shorter path, then alphabetical |
| Node name is substring of another | Exact match wins over suffix match |
| Same name in different modules | Show module path in disambiguation |
| Piped input (non-TTY) | Use PREFER_SOURCE, no interactive prompt |

---

## Rollback Plan

If issues arise:
1. Add `--legacy-resolution` flag to commands
2. Environment variable `MU_LEGACY_RESOLUTION=1`
3. Gradually migrate users to new behavior
