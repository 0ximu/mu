## MCP Bootstrap Flow

When an agent enters a new codebase:

```
mu_status() → "next_action": "mu_init"
     ↓
mu_init(".") → creates .murc.toml
     ↓
mu_build(".") → builds .mubase
     ↓
mu_context("How does auth work?") → works!
     ↓
mu_semantic_diff("main", "HEAD") → PR review
```

## MCP Tools Reference

### Bootstrap Tools (P0)

| Tool | Args | Returns |
|------|------|---------|
| `mu_init(path, force)` | path=".", force=False | `InitResult` |
| `mu_build(path, force)` | path=".", force=False | `BuildResult` |
| `mu_semantic_diff(base_ref, head_ref, path)` | base="main", head="HEAD" | `SemanticDiffOutput` |

### Discovery Tools (P1)

| Tool | Args | Returns |
|------|------|---------|
| `mu_scan(path, extensions)` | extensions=["py","ts"] | `ScanOutput` |
| `mu_compress(path, format)` | format="mu"/"json"/"markdown" | `CompressOutput` |

### Query Tools

| Tool | Args | Returns |
|------|------|---------|
| `mu_status()` | - | `dict` with `next_action` |
| `mu_query(query)` | MUQL query string | `QueryResult` |
| `mu_context(question, max_tokens)` | max_tokens=8000 | `ContextResult` |
| `mu_search(pattern, node_type, limit)` | pattern="%auth%" | `QueryResult` |
| `mu_deps(node_name, depth, direction)` | direction="outgoing"/"incoming" | `DepsResult` |
| `mu_node(node_id)` | e.g. "mod:src/auth.py" | `NodeInfo` |

### Graph Reasoning Tools

| Tool | Args | Algorithm |
|------|------|-----------|
| `mu_impact(node_id, edge_types)` | edge_types=["imports","calls"] | BFS O(V+E) |
| `mu_ancestors(node_id, edge_types)` | edge_types=["imports","calls"] | BFS O(V+E) |
| `mu_cycles(edge_types)` | edge_types=["imports"] | Kosaraju's SCC |

## Response Schemas

### mu_status Response

```json
{
  "daemon_running": bool,
  "config_exists": bool,
  "mubase_exists": bool,
  "embeddings_exist": bool,
  "next_action": "mu_init" | "mu_build" | "mu_embed" | null,
  "message": "..."
}
```

### SemanticDiffOutput

```json
{
  "base_ref": "main",
  "head_ref": "HEAD",
  "changes": [{"entity_type": "function", "entity_name": "...", "change_type": "added/removed/modified", "is_breaking": bool}],
  "breaking_changes": [...],
  "summary_text": "functions: 2 added, 1 removed",
  "has_breaking_changes": true,
  "total_changes": 5
}
```

### BuildResult

```json
{
  "success": true,
  "mubase_path": "/path/.mubase",
  "stats": {"nodes": 150, "edges": 320, "nodes_by_type": {...}},
  "duration_ms": 1234.5
}
```

## Performance Notes

- **Rust Scanner**: 6.9x faster than Python, respects .gitignore/.muignore
- **Incremental Parser**: <5ms updates for daemon mode
- **Graph Algorithms**: O(V+E) via petgraph (impact, ancestors, cycles)

---

## MU Sigils
! = module/service boundary
$ = entity/data shape (class, struct, type)
# = function/method
@ = metadata (deps, decorators, config)
? = conditional/branch
:: = annotation/semantic note

## Operators
-> = pure data flow (no side effects)
=> = state mutation (side effects)
< = inheritance/implements
| = match/switch case
~ = iteration/loop

## Syntax Patterns

### Modules
!ModuleName
!ModuleName @requires:[Dep1, Dep2]
!path/to/module.py

### Entities
$EntityName { field1:Type, field2:Type }
$EntityName { field1, field2, field3 }  # types omitted if obvious
$Child < $Parent                         # inheritance
$Impl < IInterface                       # implements

### Functions
#func_name() -> ReturnType               # no args
#func_name(arg:Type) -> ReturnType       # with args
#func_name(a:T, b:T) -> T                # multiple args
#mutating(x:T) => ReturnType             # has side effects
#void_mutator(x:T) => void               # mutates, returns nothing

### Conditionals
?condition -> result
?value | case1 -> result1 | case2 -> result2 | -> default
?guard: precondition

### Annotations
:: complexity:N                          # AST complexity score
:: REDACTED:TYPE                         # secret was here
:: guard: condition                      # precondition
:: free text summary                     # semantic description

### Metadata
@requires: [Dep1, Dep2]                  # dependencies
@env: VAR1, VAR2                         # environment vars
@route: METHOD /path                     # HTTP route
@async                                   # async function
@cached(ttl=N)                           # caching decorator
@deprecated                              # deprecation marker

## Type Conventions
str, int, float, bool                    # primitives
list[T], dict[K,V], set[T]              # collections
T?                                       # Optional[T] / nullable
T | U                                    # Union type
Any                                      # dynamic/unknown

## Flow Patterns

### Pure transformation
input -> step1 -> step2 -> output

### Mutation chain
source => step1 => step2 => persisted

### Iteration
~items -> process
~items | valid -> handle | invalid -> skip

### Conditional flow
?check -> proceed
?status | ok -> success | error -> fail | -> unknown

## Complete Example

!UserService @requires:[Database, Cache, EventBus]
  @env: DATABASE_URL, REDIS_URL

  $User { id:str, email:str, role:Role, created_at:datetime }
  $CreateUserRequest { email:str, name:str, password:str }
  $Role < Enum { ADMIN, USER, GUEST }

  #get_user(id:str) -> User?
    :: cache-first lookup, 1h TTL
    ?cached -> return
    db.get(id) -> user
    cache.set(user) => cached

  #create_user(req:CreateUserRequest) => User :: complexity:34
    :: validates email uniqueness, hashes password, emits event
    ?existing_email -> raise DuplicateError
    hash(req.password) -> hashed
    User(req, hashed) -> user
    db.insert(user) => persisted
    events.emit(UserCreated(user)) => notified
    -> user

  #delete_user(id:str) => void
    :: soft delete with audit trail
    db.soft_delete(id) => deleted
    cache.invalidate(id) => cleared
    audit.log("delete", id) => logged

  #list_users(filters:Filters) -> list[User] :: complexity:28
    ~filters -> build_query -> execute -> list[User]

## Anti-Patterns (What NOT to do)
- Don't include import statements (stdlib is assumed known)
- Don't include trivial getters/setters
- Don't include __init__ that just assigns
- Don't include full implementation of simple functions
- Don't include comments that restate code
- Don't use natural language where sigils suffice
