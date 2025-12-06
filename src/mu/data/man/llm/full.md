## Sigils
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
