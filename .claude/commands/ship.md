---
description: "Commit changes and create draft PR to dev branch."
---

# /ship - Commit and Draft PR Workflow

## Steps

1. **Review changes**
   ```bash
   git status
   git diff
   ```

2. **Commit with conventional message**
   ```bash
   git add -A
   git commit -m "feat: [description]

   [skip ci]"
   ```

3. **Push to remote**
   ```bash
   git push -u origin HEAD
   ```

4. **Create draft PR to dev**
   ```bash
   gh pr create --draft --base dev --title "feat: {Feature Name}" --body "$(cat <<'EOF'
   ## Summary
   [1-2 sentence overview]

   ## Changes
   - [Key change 1]
   - [Key change 2]

   ## Test Plan
   - [ ] Unit tests pass
   - [ ] Coverage thresholds met
   - [ ] Manual verification completed

   ---
   🔍 Review Status: **PENDING FINAL REVIEW**
   EOF
   )"
   ```

5. **Add PR comment with detailed summary**
   ```bash
   gh pr comment --body "[Detailed implementation notes]"
   ```

## Commit Message Format

Use conventional commits:

| Type | Description |
|------|-------------|
| `feat:` | New feature |
| `fix:` | Bug fix |
| `refactor:` | Code refactoring |
| `docs:` | Documentation only |
| `test:` | Adding/updating tests |
| `chore:` | Maintenance tasks |

Example:
```
feat: add Rust parser support

- Implement RustExtractor following Python pattern
- Add language registration
- Include 15 unit tests

[skip ci]
```

## Draft PR Guidelines

- **Always create as draft** (`--draft` flag)
- **Always target dev branch** (`--base dev`)
- Include summary in PR description
- Link related issues if applicable
- Add detailed PR comment after creation

## Branch Strategy

| Branch | Purpose |
|--------|---------|
| `dev` | Default branch, all PRs target here |
| `feature/*` | Feature development |
| `fix/*` | Bug fixes |
| `main` | Production releases only |

## Banana Agent Protocol

**MANDATORY FOR MORALE**: Sign off every ship with a creative, absurd banana alias.

Format: `— 🍌 [Your Absurd Banana Agent Alias]`

Examples:
- Agent Potassium Thunderpeel
- Banana Splitzkrieg
- Sir Peels-a-Lot
- The Unpeelable One
- Captain Cavendish
- Baron Von Bananington
- The Yellow Avenger
- Professor Peel McLongbottom
- The Unappealable Judge

Be creative. Be absurd. Be banana.

## Example Output

```
✅ Changes committed: feat: add semantic search
✅ Pushed to origin/feature/semantic-search
✅ Draft PR #42 created → dev
✅ PR comment added

— 🍌 The Magnificent Musa Paradisiaca
```
