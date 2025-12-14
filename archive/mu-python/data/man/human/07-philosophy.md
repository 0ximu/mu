# Philosophy

The ideas behind MU's design.

## Divorce Authoring from Reading

Code is written for humans. It has whitespace, comments, verbose names,
error messages, type hints - all valuable when **writing**.

But when an AI **reads** code, it doesn't need:
- Indentation (it understands structure)
- Comments explaining `i += 1` is "incrementing i"
- Verbose error messages (it knows what ValueError means)
- Standard library imports (it knows `json.loads` exists)

MU is a **reading format**, not a writing format.

You author in Python/TypeScript/Go. MU translates for the machine.

## Semantic Compression, Not Syntactic

ZIP compresses bytes. MU compresses **meaning**.

```python
def get_user(self, user_id: str) -> Optional[User]:
    """Get user by ID, checking cache first."""
    cached = self.cache.get(f"user:{user_id}")
    if cached:
        return User.from_dict(cached)
    user = self.db.query(User).filter_by(id=user_id).first()
    if user:
        self.cache.set(f"user:{user_id}", user.to_dict())
    return user
```

A human reading this learns:
1. It gets a user by ID
2. It checks cache first
3. It falls back to database
4. It populates cache on miss

MU preserves exactly that:
```mu
#get_user(user_id:str) -> User?
  :: cache-first lookup with DB fallback
```

The **what** survives. The **how** is implied by the summary.

## Convention Over Configuration

MU makes opinionated choices:

- Standard library imports are always stripped (every language has them)
- `__init__` methods that just assign are noise
- Property getters are noise
- Empty methods are noise
- Type annotations are kept (contracts matter)
- Decorators are kept (behavior modifiers matter)

You can override these, but defaults work for 90% of codebases.

## Sigils Are Semantic

Each sigil carries meaning:

```
!  "This is a container/boundary"
$  "This is data/a noun"
#  "This is an action/a verb"
@  "This is metadata/config"
?  "This is a decision point"
:: "This is a semantic note"
```

An LLM seeing `!PaymentService` instantly knows:
- It's a service (not a utility function)
- It's a boundary (has dependencies, owns behavior)
- It's likely a class or module

Compare to seeing `class PaymentService:` - same info, more tokens.

## Preserve Contracts, Summarize Implementation

Function signatures are contracts:
```mu
#process(input:str, options:Options) -> Result
```

This tells you:
- What goes in (str, Options)
- What comes out (Result)
- The name hints at purpose

The implementation? If it's simple, omit it. If it's complex,
summarize it:
```mu
#process(input:str, options:Options) -> Result
  :: validates input, applies transformations based on options,
  :: handles retries with exponential backoff, returns Result or throws
```

The AI doesn't need to see the retry loop code. It needs to know
retries happen.

## Trust the Reader

MU trusts that LLMs know:
- What standard libraries do
- Common patterns (cache-aside, repository, factory)
- Language idioms

So we don't explain them. We just signal them:
```mu
@cached(ttl=3600)
#get_data() -> Data
```

An LLM knows `@cached(ttl=3600)` means "result cached for 1 hour."
We don't need to show the cache implementation.

## The 92-98% Rule

MU achieves 92-98% compression on most codebases. The remaining 2-8%
is pure signal:

- Service boundaries
- Data contracts
- Function signatures
- Dependency graphs
- Complex logic summaries

This fits in a context window. This gives the AI the full picture.

This is the point.

---

## Easter Egg

If you've read this far, you deserve to know: MU stands for Machine
Understanding, but it's also a reference to the Zen koan "Mu" (無).

When asked "Does a dog have Buddha-nature?", Zhaozhou answered "Mu."

When asked "What does this codebase do?", MU answers with exactly
what matters - no more, no less.

🐕 Woof.

---

*Press [p] for previous, [q] to quit*
