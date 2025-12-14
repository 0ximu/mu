# Sigils - The Building Blocks

MU uses **sigils** - single-character prefixes that instantly convey meaning.
Each sigil is a semantic marker that tells the AI what it's looking at.

## The Core Six

```
!  MODULE      Containers. Services. Boundaries. The big boxes.
$  ENTITY      Data shapes. Your nouns. Structs, classes, types.
#  FUNCTION    Actions. Verbs. Things that happen.
@  METADATA    Config, deps, decorators. The stuff around the stuff.
?  CONDITION   Branching. Guards. The forks in the road.
:: ANNOTATION  Invariants. Summaries. Semantic metadata.
```

## Module Sigil: `!`

Marks a service, file, or logical boundary.

```mu
!AuthService @requires:[Database, JWT]
!payment/stripe.py
!module:core.utils
```

**Use for:**
- Service classes
- Module declarations
- Logical groupings

## Entity Sigil: `$`

Marks data structures - the "nouns" of your system.

```mu
$User { id:str, email:str, role:Role }
$Transaction { id, amount:Decimal, status:Status }
$Config < BaseSettings    # < means inheritance
```

**Use for:**
- Data classes / DTOs
- Domain models
- Type definitions
- Enums

## Function Sigil: `#`

Marks operations - the "verbs" of your system.

```mu
#authenticate(creds:Credentials) -> Token
#process_payment(tx:Transaction) => void   # => means side effect
#calculate_total(items:list) -> Decimal
```

**Use for:**
- Methods
- Functions
- Handlers
- Operations

## Metadata Sigil: `@`

Marks configuration, dependencies, and decorators.

```mu
@requires: [Database, Cache, Logger]
@env: API_KEY, DATABASE_URL
@route: POST /api/users
@async
@cached(ttl=3600)
```

**Use for:**
- Dependencies
- Environment variables
- Route definitions
- Decorators/attributes

## Conditional Sigil: `?`

Marks branching logic and guards.

```mu
?amount > 1000 -> requireApproval
?user.role | admin -> fullAccess | user -> limitedAccess
?valid -> proceed | -> error("Invalid input")
```

**Use for:**
- If/else logic
- Pattern matching
- Guard clauses
- Validation branches

## Annotation Sigil: `::`

Marks semantic metadata and summaries.

```mu
:: complexity:45
:: cache-first with 1h TTL
:: REDACTED:api_key
:: guard: amount > 0
```

**Use for:**
- Complexity scores
- LLM-generated summaries
- Redacted secrets
- Invariants and preconditions

---

## Operators

Beyond sigils, MU uses operators to show relationships:

```
->   PURE FLOW     Data in, data out. No side effects.
=>   MUTATION      State changes. Side effects. Dragons here.
<    INHERITANCE   Extends, implements, inherits from.
|    MATCH         Pattern matching, switch cases.
~    ITERATION     Loops, map operations, collection processing.
```

### Examples

```mu
# Pure transformation
input -> validate -> transform -> output

# State mutation
user.balance => decreased

# Inheritance
$Admin < $User < $Entity

# Pattern matching
?status | pending -> process | complete -> skip | -> error

# Iteration
~users -> sendEmail
```

---

*Press [n] for Operators Deep Dive, [p] for previous, [q] to quit*
