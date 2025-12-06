# MU Semantic Diff GitHub Action

Automatically run MU semantic diff on pull requests and post the results as PR comments.

## Features

- Runs `mu diff` between PR base and head commits
- Posts semantic diff as a formatted PR comment
- Updates existing comments instead of creating duplicates
- Handles large diffs with automatic truncation
- Uploads full diff as workflow artifact (optional)
- Writes job summary for workflow overview
- Graceful error handling with partial results

## Quick Start

Add this workflow to your repository at `.github/workflows/mu-diff.yml`:

```yaml
name: MU Semantic Diff

on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  mu-diff:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: YOUR_ORG/mu-action@v1
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
```

## Inputs

| Input | Description | Default |
|-------|-------------|---------|
| `base` | Base ref to compare against | PR base SHA |
| `head` | Head ref to compare | PR head SHA |
| `github-token` | GitHub token for posting comments | `${{ github.token }}` |
| `comment` | Post diff as PR comment | `true` |
| `artifact` | Upload full diff as artifact | `false` |
| `artifact-name` | Name of the artifact | `mu-diff` |
| `max-comment-size` | Max comment size before truncating | `60000` |
| `working-directory` | Directory for running mu diff | `.` |
| `fail-on-error` | Fail action if mu diff errors | `false` |
| `update-comment` | Update existing comment vs. create new | `true` |

## Outputs

| Output | Description |
|--------|-------------|
| `diff-output` | Full diff output in markdown format |
| `has-changes` | Whether semantic changes were detected (`true`/`false`) |
| `comment-url` | URL of the posted/updated comment |
| `artifact-url` | URL of uploaded artifact (if enabled) |

## Examples

### Basic Usage

```yaml
- uses: YOUR_ORG/mu-action@v1
  with:
    github-token: ${{ secrets.GITHUB_TOKEN }}
```

### With Artifact Upload

```yaml
- uses: YOUR_ORG/mu-action@v1
  id: mu-diff
  with:
    github-token: ${{ secrets.GITHUB_TOKEN }}
    artifact: true

- uses: actions/upload-artifact@v4
  if: always()
  with:
    name: mu-diff
    path: .mu-diff-artifact/
```

### Compare Specific Refs

```yaml
- uses: YOUR_ORG/mu-action@v1
  with:
    github-token: ${{ secrets.GITHUB_TOKEN }}
    base: main
    head: ${{ github.sha }}
```

### Conditional Execution

```yaml
- uses: YOUR_ORG/mu-action@v1
  id: mu-diff
  with:
    github-token: ${{ secrets.GITHUB_TOKEN }}

- name: Check for semantic changes
  if: steps.mu-diff.outputs.has-changes == 'true'
  run: echo "Semantic changes detected!"
```

### Custom Working Directory

For monorepos or subdirectory projects:

```yaml
- uses: YOUR_ORG/mu-action@v1
  with:
    github-token: ${{ secrets.GITHUB_TOKEN }}
    working-directory: packages/my-package
```

### Fail on Error

Make the workflow fail if MU encounters an error:

```yaml
- uses: YOUR_ORG/mu-action@v1
  with:
    github-token: ${{ secrets.GITHUB_TOKEN }}
    fail-on-error: true
```

## PR Comment Format

The action posts a formatted comment like this:

```markdown
## MU Semantic Diff

**Base:** `abc1234` → **Head:** `def5678`

## Summary

| Category | Added | Removed | Modified |
|----------|-------|---------|----------|
| Modules | 1 | 0 | 2 |
| Functions | 5 | 1 | 3 |
| Classes | 0 | 0 | 1 |

## Changes

### `src/auth/service.py`
- **Added functions:** `validate_token`, `refresh_token`
- **Modified functions:** `login`, `logout`

### `src/api/routes.py`
- **Added functions:** `health_check`
- **Removed functions:** `deprecated_endpoint`
```

## Handling Large Diffs

When a diff exceeds `max-comment-size` (default: 60,000 characters):

1. The comment is truncated at a section boundary
2. A notice is added explaining the truncation
3. Enable `artifact: true` to upload the full diff

## Permissions

The action requires:

- `contents: read` - To checkout and read repository code
- `pull-requests: write` - To post comments on PRs

```yaml
permissions:
  contents: read
  pull-requests: write
```

## Requirements

- Python 3.11+ (handled by Docker image)
- Git repository with accessible history
- Use `fetch-depth: 0` in checkout for full history

## Troubleshooting

### Shallow Clone Errors

If you see errors about missing refs:

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0  # Required for full git history
```

### Permission Errors

Ensure your workflow has the required permissions:

```yaml
permissions:
  contents: read
  pull-requests: write
```

### Large Repository Performance

For very large repositories, consider:

1. Using a `.murc.toml` config to ignore unnecessary directories
2. Limiting the `working-directory` to relevant subdirectories
3. Using GitHub Actions caching for the MU cache directory

## Development

### Local Testing

You can test the action locally using [act](https://github.com/nektos/act):

```bash
act pull_request -W .github/workflows/mu-diff.yml
```

### Building the Docker Image

```bash
cd tools/action-mu
docker build -t mu-action -f Dockerfile ../..
```

## License

MIT License - see the [LICENSE](../../LICENSE) file for details.
