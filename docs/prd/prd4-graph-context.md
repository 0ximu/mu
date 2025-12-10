# PRD: Graph-Based Context Extraction (Without Embeddings)

## Business Context

### Problem Statement
When embeddings are not available (the default state), MU's context extraction falls back to keyword matching, which produces noisy, irrelevant results. Observed on Dominaite:

```
Query: "How does payout service work?"

Expected: PayoutService.cs, IPayoutService.cs, PayoutConfig.cs
Actual: 104 nodes including chat agent Python code, random services with "service" in the name
```

**Root Cause**: Without embeddings, `SmartContextExtractor` uses naive keyword matching:
1. Extracts keywords: "payout", "service", "work"
2. Searches all nodes where name contains any keyword
3. Returns nodes sorted by keyword match count

This fails because:
- "service" matches hundreds of unrelated services
- No understanding of code relationships (imports, calls, inheritance)
- No domain boundary awareness (Python chat agent vs C# payment services)
- No preference for structurally related code

### Outcome
Context extraction without embeddings should leverage the **graph structure** that MU already has:
1. Find exact/fuzzy name matches first
2. Expand via graph relationships (imports, calls, inheritance)
3. Stay within domain boundaries (same language, same module hierarchy)
4. Score by graph proximity, not just keyword overlap

### Users
- AI agents (Claude Code) using MU MCP without OpenAI API key
- Developers who haven't run `mu bootstrap --embed`
- CI/CD systems where embedding generation is impractical

---

## Discovery Phase

**IMPORTANT**: Before implementing, the agent MUST first explore:

1. **How context extraction currently works**
   ```
   mu context "how does SmartContextExtractor find relevant nodes"
   ```

2. **What graph traversal already exists**
   ```
   mu query "SELECT file_path, name FROM functions WHERE name LIKE '%_expand%' OR name LIKE '%traverse%'"
   ```

3. **How embeddings are used when available**
   ```bash
   grep -rn "vector_search\|embedding" src/mu/kernel/context/
   ```

### Expected Discovery Locations

| Component | Likely Location | What to Look For |
|-----------|-----------------|------------------|
| Context extraction | `src/mu/kernel/context/smart.py` | `SmartContextExtractor`, `_expand_graph()` |
| Entity extraction | `src/mu/kernel/context/extractor.py` | `EntityExtractor`, keyword patterns |
| Scoring | `src/mu/kernel/context/scorer.py` | `RelevanceScorer`, scoring logic |
| Graph traversal | `src/mu/kernel/mubase.py` | `get_dependencies()`, `get_dependents()` |
| Strategies | `src/mu/kernel/context/strategies.py` | Different extraction strategies |

---

## Existing Patterns Found

From codebase.mu analysis:

| Pattern | File | Relevance |
|---------|------|-----------|
| `SmartContextExtractor` | `src/mu/kernel/context/smart.py` | Main extraction class |
| `_expand_graph()` | `src/mu/kernel/context/smart.py` | Graph expansion exists but underused |
| `_vector_search()` | `src/mu/kernel/context/smart.py` | Embedding-based search |
| `_find_seed_nodes()` | `src/mu/kernel/context/smart.py` | Initial node discovery |
| `EntityExtractor` | `src/mu/kernel/context/extractor.py` | Keyword/pattern extraction |
| `RelevanceScorer` | `src/mu/kernel/context/scorer.py` | Node scoring logic |
| `get_dependencies()` | `src/mu/kernel/mubase.py` | Graph traversal available |
| `get_dependents()` | `src/mu/kernel/mubase.py` | Reverse graph traversal |
| `EdgeType.CALLS` | `src/mu/kernel/schema.py` | Call graph edges exist |
| `EdgeType.IMPORTS` | `src/mu/kernel/schema.py` | Import edges exist |
| `EdgeType.INHERITS` | `src/mu/kernel/schema.py` | Inheritance edges exist |

**Key Finding**: The graph infrastructure exists! `_expand_graph()` is already in `SmartContextExtractor` but it's not being used effectively when embeddings are unavailable.

---

## Task Breakdown

### Task 1: Create Graph-First Seed Discovery

**File(s)**: `src/mu/kernel/context/smart.py`

**Discovery First**:
```bash
grep -n "def _find_seed" src/mu/kernel/context/smart.py
```

**Description**: Improve `_find_seed_nodes()` to use graph-aware matching instead of pure keyword search.

**Current Flow** (likely):
```
Query → Extract keywords → Search by keyword → Return all matches
```

**New Flow**:
```
Query → Extract entities → Exact name match → Qualified name match → 
       → File path match → Fuzzy match (same language only) → Return ranked seeds
```

```python
def _find_seed_nodes_graph_aware(
    self,
    entities: list[ExtractedEntity],
    question: str,
) -> tuple[list[Node], set[str], dict[str, float]]:
    """Find seed nodes using graph-aware matching.
    
    Returns:
        - List of seed nodes
        - Set of seed node IDs
        - Dict of node_id -> match_score
    
    Matching priority:
    1. Exact name match (score: 1.0)
    2. Qualified name match (score: 0.95)
    3. File path contains entity (score: 0.8)
    4. Suffix match, same language (score: 0.7)
    5. Fuzzy match, same language (score: 0.5)
    """
    seed_nodes = []
    seed_ids = set()
    scores = {}
    
    # Detect primary language from question context
    primary_language = self._detect_query_language(question, entities)
    
    for entity in entities:
        name = entity.name
        
        # Strategy 1: Exact name match
        exact_matches = self._query_nodes(
            f"SELECT * FROM nodes WHERE name = '{_escape(name)}'"
        )
        for node in exact_matches:
            if node.id not in seed_ids:
                seed_nodes.append(node)
                seed_ids.add(node.id)
                scores[node.id] = 1.0
        
        if exact_matches:
            continue  # Found exact match, skip fuzzy for this entity
        
        # Strategy 2: Qualified name match
        qualified_matches = self._query_nodes(
            f"SELECT * FROM nodes WHERE qualified_name LIKE '%{_escape(name)}'"
        )
        for node in qualified_matches:
            if node.id not in seed_ids:
                seed_nodes.append(node)
                seed_ids.add(node.id)
                scores[node.id] = 0.95
        
        if qualified_matches:
            continue
        
        # Strategy 3: File path contains entity
        path_matches = self._query_nodes(
            f"SELECT * FROM nodes WHERE file_path LIKE '%{_escape(name)}%'"
        )
        for node in path_matches:
            if node.id not in seed_ids:
                # Prefer same language
                node_lang = self._get_node_language(node)
                if primary_language and node_lang != primary_language:
                    continue
                seed_nodes.append(node)
                seed_ids.add(node.id)
                scores[node.id] = 0.8
        
        # Strategy 4: Suffix/prefix match (same language only)
        if primary_language:
            suffix_matches = self._query_nodes(
                f"""SELECT * FROM nodes 
                    WHERE (name LIKE '%{_escape(name)}' OR name LIKE '{_escape(name)}%')
                    AND file_path LIKE '%.{self._lang_to_ext(primary_language)}'"""
            )
            for node in suffix_matches:
                if node.id not in seed_ids:
                    seed_nodes.append(node)
                    seed_ids.add(node.id)
                    scores[node.id] = 0.7
    
    return seed_nodes, seed_ids, scores


def _detect_query_language(
    self, 
    question: str, 
    entities: list[ExtractedEntity]
) -> str | None:
    """Detect the likely target language from the query.
    
    Looks for:
    - Explicit language mentions: "C#", "Python", ".NET"
    - File extension mentions: ".cs", ".py"
    - Framework mentions: "ASP.NET", "Django", "React"
    """
    question_lower = question.lower()
    
    language_indicators = {
        "csharp": ["c#", ".net", "asp.net", ".cs", "csharp"],
        "python": ["python", "django", "flask", ".py", "fastapi"],
        "typescript": ["typescript", "react", "angular", ".ts", ".tsx"],
        "javascript": ["javascript", "node", "express", ".js", ".jsx"],
        "java": ["java", "spring", "maven", ".java"],
        "go": ["golang", "go ", ".go"],
        "rust": ["rust", "cargo", ".rs"],
    }
    
    for lang, indicators in language_indicators.items():
        if any(ind in question_lower for ind in indicators):
            return lang
    
    # Check entity file extensions
    for entity in entities:
        if "." in entity.name:
            ext = entity.name.split(".")[-1].lower()
            ext_to_lang = {
                "cs": "csharp", "py": "python", "ts": "typescript",
                "js": "javascript", "java": "java", "go": "go", "rs": "rust",
            }
            if ext in ext_to_lang:
                return ext_to_lang[ext]
    
    return None


def _lang_to_ext(self, language: str) -> str:
    """Convert language name to file extension."""
    return {
        "csharp": "cs", "python": "py", "typescript": "ts",
        "javascript": "js", "java": "java", "go": "go", "rust": "rs",
    }.get(language, "*")
```

**Acceptance Criteria**:
- [ ] Exact name matches prioritized over fuzzy
- [ ] Language detection prevents cross-language noise
- [ ] File path matching works for module-level queries
- [ ] Scores reflect match quality

---

### Task 2: Enhance Graph Expansion with Relationship Scoring

**File(s)**: `src/mu/kernel/context/smart.py`

**Discovery First**:
```bash
grep -n "_expand_graph" src/mu/kernel/context/smart.py
```

**Description**: Make `_expand_graph()` smarter by scoring nodes based on relationship type and distance.

```python
@dataclass
class GraphExpansionConfig:
    """Configuration for graph expansion."""
    max_depth: int = 2
    max_nodes_per_depth: int = 10
    
    # Relationship weights (how much to decay score)
    weights: dict[str, float] = field(default_factory=lambda: {
        "CALLS": 0.9,      # Called functions are very relevant
        "IMPORTS": 0.7,    # Imported modules are relevant
        "INHERITS": 0.85,  # Parent/child classes are relevant
        "CONTAINS": 0.95,  # Same module/class is very relevant
        "USES": 0.6,       # Used types are somewhat relevant
    })
    
    # Decay factor per depth level
    depth_decay: float = 0.7


def _expand_graph_scored(
    self,
    seed_nodes: list[Node],
    seed_scores: dict[str, float],
    config: GraphExpansionConfig | None = None,
) -> dict[str, tuple[Node, float]]:
    """Expand seed nodes via graph relationships with scored results.
    
    Args:
        seed_nodes: Initial nodes to expand from
        seed_scores: Scores for seed nodes
        config: Expansion configuration
        
    Returns:
        Dict of node_id -> (Node, score)
    """
    if config is None:
        config = GraphExpansionConfig()
    
    results: dict[str, tuple[Node, float]] = {}
    
    # Add seeds with their scores
    for node in seed_nodes:
        results[node.id] = (node, seed_scores.get(node.id, 1.0))
    
    # BFS expansion with score decay
    frontier = [(node.id, seed_scores.get(node.id, 1.0), 0) for node in seed_nodes]
    visited = set(results.keys())
    
    while frontier:
        current_id, current_score, depth = frontier.pop(0)
        
        if depth >= config.max_depth:
            continue
        
        # Get all edges from current node
        edges = self._get_edges_for_node(current_id)
        
        # Group by relationship type
        for edge in edges:
            # Determine neighbor
            if edge.source_id == current_id:
                neighbor_id = edge.target_id
                direction = "outgoing"
            else:
                neighbor_id = edge.source_id
                direction = "incoming"
            
            if neighbor_id in visited:
                continue
            
            # Calculate score for neighbor
            edge_weight = config.weights.get(edge.type.value, 0.5)
            depth_factor = config.depth_decay ** (depth + 1)
            neighbor_score = current_score * edge_weight * depth_factor
            
            # Skip if score too low
            if neighbor_score < 0.1:
                continue
            
            # Get neighbor node
            neighbor = self.mubase.get_node(neighbor_id)
            if neighbor is None:
                continue
            
            # Add to results
            if neighbor_id in results:
                # Keep higher score
                if neighbor_score > results[neighbor_id][1]:
                    results[neighbor_id] = (neighbor, neighbor_score)
            else:
                results[neighbor_id] = (neighbor, neighbor_score)
                visited.add(neighbor_id)
                
                # Add to frontier for further expansion
                if depth + 1 < config.max_depth:
                    frontier.append((neighbor_id, neighbor_score, depth + 1))
    
    return results


def _get_edges_for_node(self, node_id: str) -> list[Edge]:
    """Get all edges connected to a node."""
    return self.mubase.get_edges(
        source_id=node_id,
    ) + self.mubase.get_edges(
        target_id=node_id,
    )
```

**Acceptance Criteria**:
- [ ] Graph expansion uses relationship-type weights
- [ ] Score decays with distance from seed
- [ ] CALLS edges weighted higher than IMPORTS
- [ ] Maximum depth prevents runaway expansion

---

### Task 3: Add Domain Boundary Detection

**File(s)**: `src/mu/kernel/context/smart.py`

**Description**: Prevent context from crossing domain boundaries (e.g., Python chat agent vs C# payment services).

```python
@dataclass
class DomainBoundary:
    """Represents a code domain boundary."""
    root_path: str
    language: str
    name: str  # e.g., "payment-services", "chat-agent"


def _detect_domains(self) -> list[DomainBoundary]:
    """Detect domain boundaries in the codebase.
    
    Domains are detected by:
    1. Language clusters (all .cs files vs all .py files)
    2. Top-level directories
    3. Package/namespace patterns
    """
    domains = []
    
    # Query for distinct root paths and languages
    result = self.mubase.query("""
        SELECT 
            SPLIT_PART(file_path, '/', 2) as root_dir,
            CASE 
                WHEN file_path LIKE '%.cs' THEN 'csharp'
                WHEN file_path LIKE '%.py' THEN 'python'
                WHEN file_path LIKE '%.ts' THEN 'typescript'
                WHEN file_path LIKE '%.js' THEN 'javascript'
                WHEN file_path LIKE '%.java' THEN 'java'
                WHEN file_path LIKE '%.go' THEN 'go'
                ELSE 'other'
            END as language,
            COUNT(*) as node_count
        FROM nodes
        WHERE file_path IS NOT NULL
        GROUP BY root_dir, language
        HAVING COUNT(*) > 5
        ORDER BY node_count DESC
    """)
    
    for row in result.rows:
        root_dir, language, count = row
        domains.append(DomainBoundary(
            root_path=root_dir,
            language=language,
            name=f"{root_dir}-{language}",
        ))
    
    return domains


def _get_node_domain(self, node: Node, domains: list[DomainBoundary]) -> DomainBoundary | None:
    """Determine which domain a node belongs to."""
    if not node.file_path:
        return None
    
    for domain in domains:
        if node.file_path.startswith(domain.root_path):
            node_lang = self._get_node_language(node)
            if node_lang == domain.language:
                return domain
    
    return None


def _filter_by_domain(
    self,
    candidates: dict[str, tuple[Node, float]],
    seed_domains: set[str],
) -> dict[str, tuple[Node, float]]:
    """Filter candidates to prefer nodes in the same domain as seeds.
    
    Doesn't remove cross-domain nodes entirely, but penalizes them.
    """
    domains = self._detect_domains()
    filtered = {}
    
    for node_id, (node, score) in candidates.items():
        node_domain = self._get_node_domain(node, domains)
        
        if node_domain is None:
            # Unknown domain - keep with slight penalty
            filtered[node_id] = (node, score * 0.8)
        elif node_domain.name in seed_domains:
            # Same domain - keep full score
            filtered[node_id] = (node, score)
        else:
            # Different domain - significant penalty
            filtered[node_id] = (node, score * 0.3)
    
    return filtered
```

**Acceptance Criteria**:
- [ ] Domains detected from directory structure and language
- [ ] Cross-domain nodes penalized but not excluded
- [ ] Same-domain nodes preferred
- [ ] Works for monorepo structures

---

### Task 4: Integrate Graph-Based Extraction into SmartContextExtractor

**File(s)**: `src/mu/kernel/context/smart.py`

**Discovery First**:
```bash
grep -n "def extract" src/mu/kernel/context/smart.py
```

**Description**: Update the main `extract()` method to use graph-based extraction when embeddings unavailable.

```python
def extract(self, question: str) -> ContextResult:
    """Extract relevant context for a question.
    
    Uses embeddings if available, otherwise falls back to graph-based extraction.
    """
    start_time = time.time()
    
    # Extract entities from question
    entities = self.entity_extractor.extract(question)
    
    # Check if embeddings are available
    has_embeddings = self._check_embeddings_available()
    
    if has_embeddings:
        # Use vector search (existing behavior)
        return self._extract_with_embeddings(question, entities)
    else:
        # Use graph-based extraction (new behavior)
        return self._extract_with_graph(question, entities)


def _extract_with_graph(
    self,
    question: str,
    entities: list[ExtractedEntity],
) -> ContextResult:
    """Extract context using graph relationships instead of embeddings.
    
    Strategy:
    1. Find seed nodes with graph-aware matching
    2. Expand via graph relationships with scored traversal
    3. Apply domain filtering
    4. Apply call-site inclusion (from PRD 1)
    5. Score and rank results
    6. Export to MU format
    """
    # Step 1: Find seed nodes
    seed_nodes, seed_ids, seed_scores = self._find_seed_nodes_graph_aware(
        entities, question
    )
    
    if not seed_nodes:
        return ContextResult(
            nodes=[],
            mu_text="# No relevant nodes found\n",
            token_count=0,
            extraction_stats={"method": "graph", "seeds": 0},
            warnings=["No nodes matched the query. Try more specific terms."],
        )
    
    # Detect seed domains for filtering
    domains = self._detect_domains()
    seed_domains = set()
    for node in seed_nodes:
        domain = self._get_node_domain(node, domains)
        if domain:
            seed_domains.add(domain.name)
    
    # Step 2: Expand via graph
    expansion_config = GraphExpansionConfig(
        max_depth=2,
        max_nodes_per_depth=15,
    )
    expanded = self._expand_graph_scored(seed_nodes, seed_scores, expansion_config)
    
    # Step 3: Apply domain filtering
    filtered = self._filter_by_domain(expanded, seed_domains)
    
    # Step 4: Include call sites for functions (from call-site PRD)
    with_call_sites = self._include_call_sites(filtered)
    
    # Step 5: Score and rank
    scored_nodes = [
        ScoredNode(
            node=node,
            score=score,
            relevance_scores={"graph_score": score},
        )
        for node_id, (node, score) in with_call_sites.items()
    ]
    
    # Sort by score descending
    scored_nodes.sort(key=lambda x: x.score, reverse=True)
    
    # Step 6: Apply budget and export
    budgeted = self.budgeter.fit_to_budget(scored_nodes)
    mu_text = self.exporter.export(budgeted)
    token_count = self._count_tokens(mu_text)
    
    return ContextResult(
        nodes=[sn.node for sn in budgeted],
        mu_text=mu_text,
        token_count=token_count,
        extraction_stats={
            "method": "graph",
            "seeds": len(seed_nodes),
            "expanded": len(expanded),
            "after_domain_filter": len(filtered),
            "final": len(budgeted),
        },
        warnings=self._generate_warnings(seed_nodes, budgeted),
    )


def _include_call_sites(
    self,
    candidates: dict[str, tuple[Node, float]],
) -> dict[str, tuple[Node, float]]:
    """Include call sites for function nodes.
    
    For each function in candidates, also include nodes that call it
    (with reduced score) to show how the function is used.
    """
    result = dict(candidates)
    
    for node_id, (node, score) in candidates.items():
        if node.type.value != "function":
            continue
        
        # Get callers
        caller_edges = self.mubase.get_edges(
            target_id=node_id,
            edge_type=EdgeType.CALLS,
        )
        
        for edge in caller_edges[:3]:  # Limit to top 3 callers
            caller_id = edge.source_id
            if caller_id in result:
                continue
            
            caller = self.mubase.get_node(caller_id)
            if caller:
                # Callers get 0.7x score
                result[caller_id] = (caller, score * 0.7)
    
    return result


def _generate_warnings(
    self,
    seed_nodes: list[Node],
    final_nodes: list[ScoredNode],
) -> list[str]:
    """Generate warnings about potential context quality issues."""
    warnings = []
    
    # Check if we lost too many seeds
    seed_ids = {n.id for n in seed_nodes}
    final_ids = {sn.node.id for sn in final_nodes}
    lost_seeds = seed_ids - final_ids
    
    if len(lost_seeds) > len(seed_ids) * 0.5:
        warnings.append(
            f"Warning: {len(lost_seeds)} seed nodes excluded due to budget. "
            "Results may be incomplete."
        )
    
    # Check for multi-language results
    languages = set()
    for sn in final_nodes:
        lang = self._get_node_language(sn.node)
        if lang:
            languages.add(lang)
    
    if len(languages) > 1:
        warnings.append(
            f"Note: Results span multiple languages ({', '.join(languages)}). "
            "Consider specifying the target language."
        )
    
    return warnings
```

**Acceptance Criteria**:
- [ ] Graph-based extraction used when embeddings unavailable
- [ ] Results stay within domain boundaries
- [ ] Call sites included for functions
- [ ] Warnings generated for quality issues
- [ ] Stats include extraction method

---

### Task 5: Add Fallback Indicator to Output

**File(s)**: 
- `src/mu/kernel/context/models.py`
- `src/mu/commands/context.py`

**Description**: Let users know when graph-based fallback is being used.

```python
# In models.py
@dataclass
class ContextResult:
    nodes: list[Node]
    mu_text: str
    token_count: int
    extraction_stats: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    
    # New field
    extraction_method: str = "unknown"  # "embeddings" or "graph"


# In context.py command
@click.command()
@click.argument("question")
@click.pass_context
def context(ctx, question: str):
    """Extract relevant context for a question."""
    with get_mubase() as mubase:
        extractor = SmartContextExtractor(mubase, config)
        result = extractor.extract(question)
        
        # Show extraction method
        if result.extraction_method == "graph":
            click.secho(
                "ℹ Using graph-based extraction (embeddings not available)",
                fg="yellow",
            )
            click.secho(
                "  Tip: Run 'mu embed' for better semantic search",
                fg="yellow",
                dim=True,
            )
        
        # Show warnings
        for warning in result.warnings:
            click.secho(f"⚠ {warning}", fg="yellow")
        
        # Output results
        click.echo(result.mu_text)
```

**Acceptance Criteria**:
- [ ] Extraction method visible in output
- [ ] Helpful tip to run embeddings shown
- [ ] Warnings displayed
- [ ] No noise when embeddings ARE available

---

### Task 6: Unit Tests for Graph-Based Extraction

**File(s)**: `tests/unit/test_context_graph.py` (new file)

```python
import pytest
from mu.kernel.context.smart import (
    SmartContextExtractor,
    GraphExpansionConfig,
    DomainBoundary,
)
from mu.kernel.context.models import ExtractionConfig
from mu.kernel.models import Node
from mu.kernel.schema import NodeType, EdgeType


class TestGraphBasedExtraction:
    """Tests for graph-based context extraction (no embeddings)."""
    
    @pytest.fixture
    def mixed_language_mubase(self, tmp_path):
        """MUbase with both Python and C# code."""
        from mu.kernel import MUbase
        
        db = MUbase(tmp_path / ".mu" / "mubase")
        
        # C# Payment Service
        db.add_node(Node(
            id="class:src/Services/PayoutService.cs:PayoutService",
            type=NodeType.CLASS,
            name="PayoutService",
            qualified_name="Services.PayoutService",
            file_path="src/Services/PayoutService.cs",
            line_start=10,
            line_end=100,
            complexity=25,
            properties={},
        ))
        
        # C# Payment Service Test
        db.add_node(Node(
            id="class:src/Services.Tests/PayoutServiceTests.cs:PayoutServiceTests",
            type=NodeType.CLASS,
            name="PayoutServiceTests",
            qualified_name="Services.Tests.PayoutServiceTests",
            file_path="src/Services.Tests/PayoutServiceTests.cs",
            line_start=10,
            line_end=50,
            complexity=10,
            properties={},
        ))
        
        # Python Chat Agent Service (different domain)
        db.add_node(Node(
            id="class:chat/services/agent_service.py:AgentService",
            type=NodeType.CLASS,
            name="AgentService",
            qualified_name="chat.services.AgentService",
            file_path="chat/services/agent_service.py",
            line_start=5,
            line_end=80,
            complexity=20,
            properties={},
        ))
        
        # Add CALLS edge (PayoutServiceTests calls PayoutService)
        db.add_edge({
            "id": "edge:calls:1",
            "source_id": "class:src/Services.Tests/PayoutServiceTests.cs:PayoutServiceTests",
            "target_id": "class:src/Services/PayoutService.cs:PayoutService",
            "type": EdgeType.CALLS.value,
            "properties": {},
        })
        
        return db
    
    def test_language_filtering(self, mixed_language_mubase):
        """C# query should not return Python code."""
        extractor = SmartContextExtractor(
            mixed_language_mubase,
            ExtractionConfig(max_tokens=2000),
        )
        
        # Query specifically about C# service
        result = extractor.extract("How does the C# PayoutService work?")
        
        # Should include PayoutService
        node_names = [n.name for n in result.nodes]
        assert "PayoutService" in node_names
        
        # Should NOT include Python AgentService
        assert "AgentService" not in node_names
    
    def test_graph_expansion_includes_callers(self, mixed_language_mubase):
        """Graph expansion should include nodes connected by edges."""
        extractor = SmartContextExtractor(
            mixed_language_mubase,
            ExtractionConfig(max_tokens=2000),
        )
        
        result = extractor.extract("PayoutService")
        
        node_names = [n.name for n in result.nodes]
        
        # Should include the service
        assert "PayoutService" in node_names
        
        # Should also include test (connected via CALLS edge)
        # but with lower score than the service itself
        assert "PayoutServiceTests" in node_names
    
    def test_exact_match_prioritized(self, mixed_language_mubase):
        """Exact name matches should be prioritized over fuzzy."""
        extractor = SmartContextExtractor(
            mixed_language_mubase,
            ExtractionConfig(max_tokens=2000),
        )
        
        result = extractor.extract("PayoutService")
        
        # PayoutService should be ranked higher than PayoutServiceTests
        node_names = [n.name for n in result.nodes]
        payout_idx = node_names.index("PayoutService")
        tests_idx = node_names.index("PayoutServiceTests")
        
        assert payout_idx < tests_idx, "Exact match should rank higher"
    
    def test_extraction_method_reported(self, mixed_language_mubase):
        """Should report that graph-based extraction was used."""
        extractor = SmartContextExtractor(
            mixed_language_mubase,
            ExtractionConfig(max_tokens=2000),
        )
        
        result = extractor.extract("PayoutService")
        
        assert result.extraction_stats.get("method") == "graph"


class TestDomainBoundaryDetection:
    """Tests for domain boundary detection."""
    
    def test_detect_language_from_query(self):
        """Should detect language from query text."""
        extractor = SmartContextExtractor.__new__(SmartContextExtractor)
        
        assert extractor._detect_query_language("How does the C# service work?", []) == "csharp"
        assert extractor._detect_query_language("Python API endpoint", []) == "python"
        assert extractor._detect_query_language("React component rendering", []) == "typescript"
    
    def test_domain_filtering_reduces_noise(self, mixed_language_mubase):
        """Domain filtering should reduce cross-language noise."""
        extractor = SmartContextExtractor(
            mixed_language_mubase,
            ExtractionConfig(max_tokens=2000),
        )
        
        # Generic "service" query could match both languages
        result = extractor.extract("How does the payment service work?")
        
        # Should have filtered out Python chat agent
        file_paths = [n.file_path for n in result.nodes]
        python_files = [f for f in file_paths if f and f.endswith(".py")]
        csharp_files = [f for f in file_paths if f and f.endswith(".cs")]
        
        # Expecting mostly C# files since "payment" matches PayoutService
        assert len(csharp_files) >= len(python_files)


class TestGraphExpansionConfig:
    """Tests for GraphExpansionConfig."""
    
    def test_default_weights(self):
        """Default weights should prioritize CALLS over IMPORTS."""
        config = GraphExpansionConfig()
        
        assert config.weights["CALLS"] > config.weights["IMPORTS"]
        assert config.weights["CONTAINS"] > config.weights["CALLS"]
    
    def test_depth_decay(self):
        """Score should decay with depth."""
        config = GraphExpansionConfig(depth_decay=0.5)
        
        # At depth 1, score should be 0.5x
        # At depth 2, score should be 0.25x
        assert config.depth_decay ** 1 == 0.5
        assert config.depth_decay ** 2 == 0.25
```

**Acceptance Criteria**:
- [ ] Tests verify language filtering works
- [ ] Tests verify graph expansion includes connected nodes
- [ ] Tests verify exact matches prioritized
- [ ] Tests verify domain boundaries respected
- [ ] Tests pass in CI

---

### Task 7: Integration Test - Dominaite Regression

**File(s)**: `tests/integration/test_context_accuracy.py`

```python
import pytest
from pathlib import Path


class TestDominaiteContextRegression:
    """Regression test for the Dominaite context extraction failure.
    
    On Dominaite, asking 'How does payout service work?' returned Python
    chat agent code instead of the C# PayoutService class.
    """
    
    def test_payout_service_query_returns_correct_domain(self, tmp_path: Path):
        """Query about payout service should return payment code, not chat code."""
        from mu.kernel import MUbase
        from mu.kernel.context.smart import SmartContextExtractor
        from mu.kernel.context.models import ExtractionConfig
        from mu.kernel.models import Node
        from mu.kernel.schema import NodeType
        
        # Setup: Simulate Dominaite structure
        db_path = tmp_path / ".mu" / "mubase"
        db_path.parent.mkdir(parents=True)
        mubase = MUbase(db_path)
        
        # C# PayoutService (what we WANT)
        mubase.add_node(Node(
            id="class:src/Dominaite.Services/PayoutService.cs:PayoutService",
            type=NodeType.CLASS,
            name="PayoutService",
            qualified_name="Dominaite.Services.PayoutService",
            file_path="src/Dominaite.Services/PayoutService.cs",
            line_start=15,
            line_end=200,
            complexity=35,
            properties={},
        ))
        
        # Python ChatAgentService (what we DON'T want)
        mubase.add_node(Node(
            id="class:src/chat_agent/services/chat_service.py:ChatService",
            type=NodeType.CLASS,
            name="ChatService",
            qualified_name="chat_agent.services.ChatService",
            file_path="src/chat_agent/services/chat_service.py",
            line_start=10,
            line_end=150,
            complexity=25,
            properties={},
        ))
        
        # Python AgentPayoutHandler (has "payout" in name but wrong domain)
        mubase.add_node(Node(
            id="class:src/chat_agent/handlers/payout_handler.py:PayoutHandler",
            type=NodeType.CLASS,
            name="PayoutHandler",
            qualified_name="chat_agent.handlers.PayoutHandler",
            file_path="src/chat_agent/handlers/payout_handler.py",
            line_start=5,
            line_end=50,
            complexity=10,
            properties={},
        ))
        
        # Extract context
        extractor = SmartContextExtractor(
            mubase,
            ExtractionConfig(max_tokens=2000),
        )
        
        result = extractor.extract("How does the payout service work?")
        
        # Primary result should be C# PayoutService
        top_nodes = result.nodes[:3]  # Top 3 results
        top_names = [n.name for n in top_nodes]
        top_paths = [n.file_path for n in top_nodes]
        
        # PayoutService.cs should be in top results
        assert "PayoutService" in top_names, (
            f"PayoutService should be in top results. Got: {top_names}"
        )
        
        # Should have C# files ranked higher than Python
        csharp_in_top = any(".cs" in p for p in top_paths if p)
        assert csharp_in_top, (
            f"C# files should be prioritized. Top paths: {top_paths}"
        )
        
        # Verify extraction method
        assert result.extraction_stats.get("method") == "graph", (
            "Should use graph-based extraction when embeddings unavailable"
        )
```

**Acceptance Criteria**:
- [ ] Test recreates exact Dominaite scenario
- [ ] C# PayoutService ranked above Python services
- [ ] Graph-based extraction confirmed
- [ ] Test is marked as regression test

---

## Dependencies

```
Task 1 (Seed Discovery)
    ↓
Task 2 (Graph Expansion) ←─── Depends on seed scores
    ↓
Task 3 (Domain Detection) ←── Filters expanded results
    ↓
Task 4 (Integration) ←──────── Combines all components
    ↓
Task 5 (Output Indicator)
    ↓
Task 6 (Unit Tests)
    ↓
Task 7 (Integration Test)
```

---

## Implementation Order

| Priority | Task | Effort | Risk |
|----------|------|--------|------|
| P0 | Task 1: Graph-First Seed Discovery | Medium (2h) | Medium - modifying core search |
| P0 | Task 2: Graph Expansion with Scoring | Medium (2h) | Medium |
| P1 | Task 3: Domain Boundary Detection | Medium (1.5h) | Low |
| P1 | Task 4: Integration | Medium (2h) | Medium - wiring everything together |
| P2 | Task 5: Output Indicator | Small (30m) | Low |
| P2 | Task 6: Unit Tests | Medium (1.5h) | Low |
| P2 | Task 7: Integration Test | Small (30m) | Low |

---

## Success Metrics

1. **Precision**: Top 5 results should be from correct domain 90%+ of the time
2. **Recall**: Relevant nodes should appear in top 10 results
3. **No Cross-Language Noise**: C# query returns < 10% Python nodes
4. **Performance**: Graph-based extraction < 500ms for typical query

---

## Edge Cases

| Scenario | Expected Behavior |
|----------|-------------------|
| No seed nodes found | Return empty result with helpful warning |
| Query spans multiple languages | Include both but warn user |
| Very generic query ("how does it work") | Use most connected nodes as proxy |
| Monorepo with 10+ languages | Detect language from explicit mentions |
| All seeds are tests | Expand to find source files |

---

## Comparison: Before vs After

### Before (Keyword Matching)
```
Query: "How does payout service work?"

Results (104 nodes, 2911 tokens):
1. chat_agent/services/__init__.py (has "service")
2. chat_agent/services/agent_service.py (has "service")
3. chat_agent/handlers/payout_handler.py (has "payout")
4. utils/service_registry.py (has "service")
5. ... more Python code ...
45. PayoutService.cs (finally!)
```

### After (Graph-Based)
```
Query: "How does payout service work?"

Results (12 nodes, 450 tokens):
1. PayoutService.cs (exact match, C# domain)
2. IPayoutService.cs (inherits from, same domain)
3. PayoutConfig.cs (imported by PayoutService)
4. PayoutServiceTests.cs (calls PayoutService)
5. TransactionProcessor.cs (called by PayoutService)
```

---

## Rollback Plan

If issues arise:
1. Feature flag: `MU_GRAPH_CONTEXT=0` to disable
2. Keep keyword matching as fallback
3. A/B test with select users before full rollout
