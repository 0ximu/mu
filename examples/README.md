# MU Examples

This directory contains sample MU output files to help you understand the format.

## Files

### `sample-output.mu`

A synthetic example showing MU output for a typical e-commerce API with:
- 5 modules (auth, order, product, notification, user services)
- 45 classes
- 23 standalone functions + 89 methods
- External dependencies (Stripe, SendGrid, Twilio, Firebase, Elasticsearch, Redis)

This example demonstrates:
- Module dependency declarations (`!module`, `@deps`)
- Class definitions with inheritance (`$User < Base`)
- Function signatures with types (`#async create_order(...) -> Order`)
- Metadata annotations (`:: guard:`, `:: transaction:`, `:: external:`)
- Conditional logic notation (`? PAID -> ...`)
- State mutation operator (`=>`)

## Real-World Results

MU has been tested on production codebases:

| Codebase | Original | MU Output | Compression |
|----------|----------|-----------|-------------|
| Python Backend | 66k lines | 5k lines | 92% |
| TypeScript Gateway | 407k lines | 6.7k lines | 98% |

## Supported Languages

MU supports semantic compression for:
- Python (.py)
- TypeScript (.ts, .tsx)
- JavaScript (.js, .jsx)
- C# (.cs)
- Go (.go)
- Rust (.rs)
- Java (.java)

## Generating Your Own

```bash
# Navigate to your project
cd /path/to/your/project

# Generate MU output
mu compress ./src --output my-system.mu

# Or output to stdout
mu compress ./src

# With LLM-enhanced summarization
mu compress ./src --llm --output my-system.mu

# View with syntax highlighting
mu view my-system.mu

# Export to HTML
mu view my-system.mu -f html -o my-system.html
```

## Semantic Diff

Compare changes between git refs:

```bash
# Compare branches
mu diff main feature-branch

# Compare commits
mu diff HEAD~5 HEAD
```
