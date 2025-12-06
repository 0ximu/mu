# Common Workflows

Real-world patterns for using MU effectively.

## AI-Assisted Development

### Context for Conversations

```bash
# Generate MU and copy to clipboard
mu compress ./src -o context.mu

# Then in your AI chat:
# "Here's my codebase in MU format: [paste context.mu]
#  How should I implement feature X?"
```

### Focused Context

```bash
# Just the authentication module
mu compress ./src/auth -o auth.mu

# Just a specific file's context
mu compress ./src/services/payment.py -o payment.mu
```

### With LLM Summaries

```bash
# For complex codebases, add semantic summaries
mu compress . --llm -o codebase.mu

# Review what got summarized
grep "^  ::" codebase.mu
```

## Code Review

### Semantic Diff

```bash
# What changed semantically between branches?
mu diff main feature-branch

# Between commits
mu diff HEAD~5 HEAD

# Output as JSON for tooling
mu diff main develop -f json

# As markdown for PR descriptions
mu diff main feature-branch -f markdown > changes.md
```

### Review a PR

```bash
# 1. Checkout PR branch
git checkout feature-branch

# 2. Generate semantic diff
mu diff main HEAD

# 3. Ask AI about the changes
mu diff main HEAD -f markdown | pbcopy
# "Review these changes for security issues: [paste]"
```

## Documentation

### Generate Module Overview

```bash
mu compress ./src/core -f markdown > docs/core-overview.md
```

### Dependency Documentation

```bash
mu kernel build .
mu kernel deps CoreService --depth 2 --json | \
  jq -r '"## " + .[].name' > deps.md
```

## Refactoring

### Find Complexity Hotspots

```bash
# Top 10 most complex functions
mu kernel query --complexity 20 --limit 10

# Find functions with too many dependencies
mu kernel query --type function --json | \
  jq '.[] | select(.complexity > 30)' | \
  jq -r '.name'
```

### Impact Analysis

```bash
# What would break if I change UserService?
mu kernel deps UserService --reverse --depth 3
```

### Safe Refactoring

```bash
# Before refactoring
mu compress . -o before.mu

# After refactoring
mu compress . -o after.mu

# Compare
diff before.mu after.mu
# Or semantic diff:
mu diff before.mu after.mu
```

## CI/CD Integration

### Codebase Metrics

```bash
# Add to CI pipeline
mu kernel build .
mu kernel stats --json > metrics.json

# Track complexity over time
mu kernel query --complexity 50 --json | jq length
# Alert if > threshold
```

### PR Size Check

```bash
# In PR pipeline
mu diff main HEAD --json | jq '.total_changes'
# Alert if too large
```

## Security

### Secret Detection

```bash
# MU automatically redacts secrets
mu compress . | grep "REDACTED"

# Verify nothing leaked
mu compress . --no-redact | grep -E "(api_key|password|secret)"
```

### Sensitive Code Review

```bash
# Focus AI review on security-critical code
mu compress ./src/auth ./src/payment -o security-critical.mu
# "Review this code for OWASP Top 10 vulnerabilities: [paste]"
```

## Team Onboarding

### Codebase Overview for New Developers

```bash
# Generate human-readable overview
mu compress . -f markdown -o ARCHITECTURE.md

# Generate graph for visualization
mu kernel build .
mu kernel query --json > codebase-graph.json
```

### "How does X work?" Documentation

```bash
# Generate focused context
mu compress ./src/feature-x -o feature-x.mu

# Ask AI to explain
# "Explain how feature X works based on this: [paste feature-x.mu]"
```

---

*Press [n] for Philosophy, [p] for previous, [q] to quit*
