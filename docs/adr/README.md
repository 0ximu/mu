# Architecture Decision Records (ADR)

This directory contains Architecture Decision Records for the MU project.

## What is an ADR?

An ADR is a document that captures an important architectural decision made along with its context and consequences.

## ADR Index

| ID | Title | Status | Date |
|----|-------|--------|------|
| [0001](0001-use-tree-sitter-for-parsing.md) | Use Tree-sitter for AST Parsing | Accepted | 2025-01 |
| [0002](0002-sigil-based-output-format.md) | Sigil-based MU Output Format | Accepted | 2025-01 |
| [0003](0003-litellm-for-llm-integration.md) | Use LiteLLM for Multi-Provider LLM | Accepted | 2025-01 |

## ADR Template

Use this template when creating new ADRs:

```markdown
# ADR-XXXX: [Title]

## Status

[Proposed | Accepted | Deprecated | Superseded by ADR-XXXX]

## Date

YYYY-MM-DD

## Context

[Describe the issue motivating this decision and any context that influences it.]

## Decision

[Describe the decision that was made.]

## Consequences

### Positive
- [List positive consequences]

### Negative
- [List negative consequences]

### Neutral
- [List neutral consequences]

## Alternatives Considered

### Alternative 1: [Name]
- Pros: [list]
- Cons: [list]
- Why rejected: [reason]

## References

- [Links to relevant resources, issues, or discussions]
```

## Creating a New ADR

1. Copy the template above
2. Create a new file: `XXXX-short-title.md` (use next available number)
3. Fill in all sections
4. Update the index table in this README
5. Submit for review with your PR

## When to Create an ADR

Create an ADR when:
- Choosing between technologies (libraries, frameworks, tools)
- Defining data formats or protocols
- Establishing patterns that will be used throughout the codebase
- Making decisions that are hard to reverse
- Changing a previous architectural decision

## ADR Lifecycle

1. **Proposed**: Under discussion, not yet accepted
2. **Accepted**: Decision has been made and is in effect
3. **Deprecated**: No longer applies but kept for historical context
4. **Superseded**: Replaced by a newer ADR (link to the new one)
