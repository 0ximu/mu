# Epic 3: Smart Context

**Priority**: P1 - Key differentiator for AI-assisted coding
**Dependencies**: Vector Layer (Epic 1), Kernel (complete)
**Estimated Complexity**: Medium-High
**PRD Reference**: Section 0.4 (get_context_for_question)

---

## Overview

Smart Context extracts the optimal subgraph from MUbase to answer a specific question. It combines entity extraction, vector similarity, and graph traversal to select the most relevant code, then exports it within a token budget.

This is the **killer feature** - it enables AI coding assistants to receive perfect context for any question.

## Goals

1. Extract semantically relevant code for natural language questions
2. Balance relevance with token budget constraints
3. Combine multiple signals: named entities, vector similarity, structural proximity
4. Export as token-efficient MU format for LLM consumption

---

## User Stories

### Story 3.1: Entity Extraction
**As a** developer
**I want** mentioned code entities detected
**So that** explicitly referenced code is always included

**Acceptance Criteria**:
- [ ] Extract code names from natural language (e.g., "AuthService", "login")
- [ ] Match against node names in graph
- [ ] Handle partial matches and aliases
- [ ] Support qualified names (e.g., "auth.service.login")

### Story 3.2: Relevance Scoring
**As a** developer
**I want** code ranked by relevance to my question
**So that** the most important code fits in the context

**Acceptance Criteria**:
- [ ] Score based on: named mention, vector similarity, structural proximity
- [ ] Configurable weights for each signal
- [ ] Higher scores for exact matches
- [ ] Decay for distant neighbors

### Story 3.3: Token Budgeting
**As a** developer
**I want** context that fits my token limit
**So that** I don't exceed LLM context windows

**Acceptance Criteria**:
- [ ] Respect `max_tokens` parameter
- [ ] Prioritize high-relevance nodes
- [ ] Include necessary context (e.g., parent class for method)
- [ ] Accurate token counting (tiktoken)

### Story 3.4: Context Export
**As a** developer
**I want** context as optimized MU text
**So that** tokens are used efficiently

**Acceptance Criteria**:
- [ ] Export selected nodes as MU format
- [ ] Preserve structural relationships
- [ ] Include import context
- [ ] Add relevance annotations (optional)

### Story 3.5: CLI & API
**As a** developer
**I want** to get context from CLI and Python
**So that** I can integrate with my workflow

**Acceptance Criteria**:
- [ ] `mu context "<question>"` CLI command
- [ ] `MUbase.get_context_for_question()` API
- [ ] `--max-tokens` flag
- [ ] `--format` option (mu, json)

---

## Technical Design

### Algorithm Overview

```
Question → Entity Extraction → Seed Nodes
                ↓
         Vector Search → Candidate Nodes
                ↓
         Graph Expansion → Extended Nodes
                ↓
         Relevance Ranking → Sorted Nodes
                ↓
         Token Budgeting → Selected Nodes
                ↓
         MU Export → Context String
```

### File Structure

```
src/mu/kernel/
├── context/
│   ├── __init__.py          # Public API
│   ├── extractor.py         # Entity extraction
│   ├── scorer.py            # Relevance scoring
│   ├── budgeter.py          # Token budget fitting
│   └── models.py            # ContextResult, etc.
```

### Core Classes

```python
from dataclasses import dataclass

@dataclass
class ContextResult:
    """Result of smart context extraction."""
    mu_text: str
    nodes: list[Node]
    token_count: int
    relevance_scores: dict[str, float]  # node_id -> score
    extraction_stats: dict


@dataclass
class ExtractionConfig:
    """Configuration for context extraction."""
    max_tokens: int = 8000
    include_imports: bool = True
    include_parent: bool = True  # Include class for methods
    expand_depth: int = 1        # Neighbor expansion

    # Scoring weights
    entity_weight: float = 1.0
    vector_weight: float = 0.7
    proximity_weight: float = 0.3

    # Filtering
    min_relevance: float = 0.1
    exclude_tests: bool = False


class SmartContextExtractor:
    """Extract optimal context for a question."""

    def __init__(self, mubase: MUbase, config: ExtractionConfig | None = None):
        self.mubase = mubase
        self.config = config or ExtractionConfig()
        self.tokenizer = tiktoken.get_encoding("cl100k_base")

    def extract(self, question: str) -> ContextResult:
        """Extract context for a natural language question."""

        # 1. Entity extraction
        entities = self._extract_entities(question)
        named_nodes = self._find_nodes_by_name(entities)

        # 2. Vector search (if embeddings available)
        similar_nodes = []
        if self.mubase.has_embeddings():
            similar_nodes = self.mubase.semantic_search(
                question,
                limit=20
            )

        # 3. Combine seed nodes
        seed_nodes = self._merge_seeds(named_nodes, similar_nodes)

        # 4. Graph expansion
        expanded = self._expand_graph(seed_nodes)

        # 5. Score all candidates
        scored = self._score_nodes(expanded, question, entities)

        # 6. Fit to token budget
        selected = self._fit_to_budget(scored)

        # 7. Export as MU
        mu_text = self._export_mu(selected)

        return ContextResult(
            mu_text=mu_text,
            nodes=[s.node for s in selected],
            token_count=self._count_tokens(mu_text),
            relevance_scores={s.node.id: s.score for s in selected},
            extraction_stats=self._get_stats(entities, seed_nodes, expanded, selected)
        )

    def _extract_entities(self, text: str) -> list[str]:
        """Extract potential code entity names from text."""
        # Strategy 1: CamelCase and snake_case patterns
        patterns = [
            r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b',  # CamelCase
            r'\b[a-z]+(?:_[a-z]+)+\b',            # snake_case
            r'\b[A-Z][A-Z_]+\b',                  # CONSTANTS
        ]

        # Strategy 2: Quoted strings
        # Strategy 3: Known node names (fast lookup)

        return extracted

    def _find_nodes_by_name(self, names: list[str]) -> list[Node]:
        """Find nodes matching extracted names."""
        results = []
        for name in names:
            # Exact match
            node = self.mubase.find_node_by_name(name)
            if node:
                results.append(node)
                continue

            # Partial match (suffix)
            nodes = self.mubase.find_nodes_by_suffix(name)
            results.extend(nodes[:3])  # Top 3 matches

        return results

    def _expand_graph(self, seeds: list[Node]) -> list[Node]:
        """Expand seed nodes with structural context."""
        expanded = set(n.id for n in seeds)

        for node in seeds:
            # Add parent (class for method)
            if self.config.include_parent:
                parent = self.mubase.get_parent(node.id)
                if parent:
                    expanded.add(parent.id)

            # Add neighbors
            neighbors = self.mubase.get_neighbors(
                node.id,
                direction="both"
            )
            for n in neighbors[:self.config.expand_depth * 5]:
                expanded.add(n.id)

        return [self.mubase.get_node(nid) for nid in expanded]

    def _score_nodes(
        self,
        nodes: list[Node],
        question: str,
        entities: list[str]
    ) -> list[ScoredNode]:
        """Score nodes by relevance to question."""
        scored = []

        for node in nodes:
            score = 0.0

            # Entity match score
            if node.name in entities:
                score += self.config.entity_weight * 1.0
            elif any(e in node.name for e in entities):
                score += self.config.entity_weight * 0.5

            # Vector similarity (if available)
            if self.mubase.has_embeddings():
                similarity = self.mubase.get_similarity(node.id, question)
                score += self.config.vector_weight * similarity

            # Structural proximity to named entities
            proximity = self._calculate_proximity(node, entities)
            score += self.config.proximity_weight * proximity

            if score >= self.config.min_relevance:
                scored.append(ScoredNode(node, score))

        return sorted(scored, key=lambda x: -x.score)

    def _fit_to_budget(self, scored: list[ScoredNode]) -> list[ScoredNode]:
        """Select nodes that fit within token budget."""
        selected = []
        current_tokens = 0

        for item in scored:
            node_tokens = self._estimate_node_tokens(item.node)

            if current_tokens + node_tokens <= self.config.max_tokens:
                selected.append(item)
                current_tokens += node_tokens
            elif current_tokens >= self.config.max_tokens * 0.9:
                break  # Close enough to budget

        return selected

    def _estimate_node_tokens(self, node: Node) -> int:
        """Estimate tokens needed to represent node in MU format."""
        # Rough estimation based on node type
        base = 20  # Sigils, name, basic metadata

        if node.type == NodeType.FUNCTION:
            base += len(node.properties.get("parameters", [])) * 10
            base += 50  # Return type, docstring summary
        elif node.type == NodeType.CLASS:
            base += len(node.properties.get("methods", [])) * 30

        return base

    def _export_mu(self, selected: list[ScoredNode]) -> str:
        """Export selected nodes as MU format."""
        # Group by module for coherent output
        by_module = {}
        for item in selected:
            module = item.node.properties.get("module", "unknown")
            if module not in by_module:
                by_module[module] = []
            by_module[module].append(item.node)

        # Use existing MU exporter
        return self.mubase.export_mu(
            node_ids=[s.node.id for s in selected]
        )
```

### MUbase Extension

```python
# Add to mubase.py

def get_context_for_question(
    self,
    question: str,
    max_tokens: int = 8000,
    **kwargs
) -> ContextResult:
    """Extract optimal context for answering a question."""
    config = ExtractionConfig(max_tokens=max_tokens, **kwargs)
    extractor = SmartContextExtractor(self, config)
    return extractor.extract(question)

def has_embeddings(self) -> bool:
    """Check if embeddings are available."""
    count = self.conn.execute(
        "SELECT COUNT(*) FROM embeddings"
    ).fetchone()[0]
    return count > 0

def get_similarity(self, node_id: str, query: str) -> float:
    """Get similarity score between node and query."""
    # Requires vector layer
    ...
```

---

## Implementation Plan

### Phase 1: Entity Extraction (Day 1)
1. Implement regex-based entity extraction
2. Add node name lookup methods to MUbase
3. Handle partial and fuzzy matches
4. Test with various question formats

### Phase 2: Scoring System (Day 1-2)
1. Implement `_score_nodes()` with configurable weights
2. Add entity match scoring
3. Add proximity calculation
4. Test scoring accuracy

### Phase 3: Graph Expansion (Day 2)
1. Implement `_expand_graph()`
2. Add parent inclusion logic
3. Add neighbor traversal
4. Limit expansion to prevent explosion

### Phase 4: Token Budgeting (Day 2-3)
1. Implement token estimation
2. Add tiktoken integration
3. Implement greedy selection algorithm
4. Add essential context inclusion (imports, parents)

### Phase 5: MU Export (Day 3)
1. Integrate with existing MU exporter
2. Add relevance annotations (optional)
3. Ensure coherent module grouping
4. Test output quality

### Phase 6: CLI Integration (Day 3-4)
1. Add `mu context` command
2. Add `--max-tokens` and `--format` flags
3. Add relevance score display option
4. Test with real questions

### Phase 7: Vector Integration (Day 4)
1. Connect to Vector Layer (Epic 1)
2. Add semantic search to seed nodes
3. Add vector similarity to scoring
4. Test improvement over entity-only

### Phase 8: Testing (Day 4-5)
1. Unit tests for each component
2. Integration tests with sample codebase
3. Quality tests: verify relevant code included
4. Performance tests: ensure < 500ms extraction

---

## CLI Interface

```bash
# Basic usage
$ mu context "How does authentication work?"
! auth.service
  Authentication service module
  $ AuthService < BaseService
    # login(email: str, password: str) -> Result[User]
      Authenticate user with credentials
      @validate, @log_call
    # logout(user_id: UUID) -> None
    # refresh_token(token: str) -> Token
  @ UserRepository, TokenService, CacheService

# With token limit
$ mu context "Where is Redis used?" --max-tokens 2000

# JSON output with scores
$ mu context "How do payments work?" --format json
{
  "question": "How do payments work?",
  "token_count": 1847,
  "nodes": [
    {"id": "PaymentService", "score": 0.95, "type": "CLASS"},
    {"id": "process_payment", "score": 0.88, "type": "FUNCTION"}
  ],
  "mu_text": "..."
}

# Verbose mode
$ mu context "User validation logic" --verbose
Extracted entities: ['User', 'validation']
Named nodes found: 2
Vector similar nodes: 15
After expansion: 34
After scoring: 28
Selected (token fit): 12
Token count: 3,421 / 8,000
```

---

## Scoring Details

### Signal Weights (Default)

| Signal | Weight | Description |
|--------|--------|-------------|
| Entity Match (exact) | 1.0 | Node name matches extracted entity |
| Entity Match (partial) | 0.5 | Entity is substring of node name |
| Vector Similarity | 0.7 | Cosine similarity with question |
| Proximity (depth 1) | 0.3 | Direct neighbor of matched node |
| Proximity (depth 2) | 0.15 | 2 hops from matched node |

### Relevance Score Formula

```
score = entity_weight * entity_score
      + vector_weight * vector_similarity
      + proximity_weight * proximity_score

where:
  entity_score ∈ {0, 0.5, 1.0}
  vector_similarity ∈ [0, 1]
  proximity_score = 1 / (1 + distance)
```

---

## Testing Strategy

### Unit Tests
```python
def test_extract_entities_camelcase():
    entities = extractor._extract_entities("How does AuthService handle login?")
    assert "AuthService" in entities
    assert "login" in entities

def test_score_exact_match():
    node = Node(name="AuthService", ...)
    score = extractor._score_nodes([node], "AuthService usage", ["AuthService"])
    assert score[0].score >= 1.0
```

### Integration Tests
```python
def test_context_includes_mentioned_class(populated_mubase):
    result = populated_mubase.get_context_for_question("How does AuthService work?")
    node_names = [n.name for n in result.nodes]
    assert "AuthService" in node_names

def test_context_fits_token_budget(populated_mubase):
    result = populated_mubase.get_context_for_question(
        "Explain the payment flow",
        max_tokens=2000
    )
    assert result.token_count <= 2000
```

### Quality Tests
```python
def test_context_quality_auth_question():
    """Verify that auth-related code is included for auth question."""
    result = db.get_context_for_question("How does authentication work?")

    # Must include
    assert any("auth" in n.name.lower() for n in result.nodes)
    assert any("login" in n.name.lower() for n in result.nodes)

    # Should not include
    assert not any("payment" in n.name.lower() for n in result.nodes)
```

---

## Success Criteria

- [ ] Mentioned entities always included in context
- [ ] Context fits within token budget
- [ ] Extraction time < 500ms for typical questions
- [ ] Manual quality review: 90% of contexts are useful
- [ ] Works without embeddings (entity + structure only)
- [ ] Improves with embeddings

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Entity extraction misses names | High | Multiple extraction strategies, fuzzy matching |
| Token estimation inaccurate | Medium | Use tiktoken for accurate counting |
| Too much irrelevant code | High | Tune scoring weights, add exclusion filters |
| Slow extraction | Medium | Cache entity lookups, limit expansion |

---

## Future Enhancements

1. **Query understanding**: Use LLM to better understand question intent
2. **Conversation context**: Include previous questions/answers
3. **Code snippets**: Include relevant code lines, not just signatures
4. **Cross-repo**: Search across multiple mubase files
5. **Learning**: Improve weights based on user feedback
