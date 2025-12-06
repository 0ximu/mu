# What is MU?

**MU** (Machine Understanding) is a semantic compression format that translates
your codebase into a token-efficient representation optimized for LLM comprehension.

Think of it as a **lingua franca** between your code and AI assistants.

```
Your 400,000 token codebase  ->  MU  ->  ~6,000 tokens
                              (98.5% compression)
```

## The Problem

You're working with Claude, GPT, or Copilot. You want to ask about your codebase.
But here's the thing:

- Your codebase is **400K tokens**
- Your context window is **128K tokens** (if you're lucky)
- You paste in files... and hit the limit
- You try RAG... and get fragmented, context-free snippets
- The AI hallucinates because it can't see the full picture

## The Solution

MU compresses your code semantically - not just syntactically. It preserves:

- **Structure**: What modules exist, how they connect
- **Contracts**: Function signatures, types, interfaces
- **Intent**: What things DO, not how they do it
- **Dependencies**: What talks to what

And strips away:

- Boilerplate (getters, setters, `__init__` that just assigns)
- Standard library imports (the AI knows what `json.loads` does)
- Implementation details of simple functions
- Comments that restate the obvious

The result? An AI that can **actually understand your codebase** in one shot.

## Quick Example

**Before** (Python, 847 tokens):
```python
class UserService:
    """Service for managing users in the system."""

    def __init__(self, db: Database, cache: RedisCache, logger: Logger):
        self.db = db
        self.cache = cache
        self.logger = logger
        self._initialized = False

    def get_user(self, user_id: str) -> Optional[User]:
        """Get a user by their ID, checking cache first."""
        cached = self.cache.get(f"user:{user_id}")
        if cached:
            return User.from_dict(cached)

        user = self.db.query(User).filter(User.id == user_id).first()
        if user:
            self.cache.set(f"user:{user_id}", user.to_dict(), ttl=3600)
        return user
    # ... 200 more lines
```

**After** (MU, 89 tokens):
```mu
!UserService @requires:[Database, RedisCache, Logger]
  #get_user(user_id:str) -> User?
    :: cache-first lookup with 1h TTL
  #create_user(email:str, name:str) -> User
    :: validates email, hashes password, persists
  #delete_user(user_id:str) => void
    :: soft delete, invalidates cache
```

Same semantic information. **10x fewer tokens.**

---

*Press [n] for Quick Start, [q] to quit*
