## MCP Bootstrap Flow

When entering a new codebase:
1. `mu_status()` - Check status, get `next_action`
2. `mu_init(".")` - Create config (if needed)
3. `mu_build(".")` - Build code graph
4. Now `mu_context`, `mu_query`, etc. work

## MCP Tools

| Tool | Purpose |
|------|---------|
| `mu_status` | Health check + `next_action` guidance |
| `mu_init` | Create .murc.toml config |
| `mu_build` | Build .mubase graph |
| `mu_query` | MUQL queries (supports terse syntax) |
| `mu_context` | Smart context for questions |
| `mu_semantic_diff` | PR review with breaking changes |
| `mu_scan` | Fast file discovery (Rust, 6.9x faster) |
| `mu_compress` | Generate MU output |
| `mu_impact` | "If I change X, what breaks?" |
| `mu_ancestors` | "What does X depend on?" |
| `mu_cycles` | Detect circular dependencies |

## MUQL Terse Syntax (Token-Optimized)

Use terse syntax for 60-85% token reduction:

| Verbose | Terse | Example |
|---------|-------|---------|
| `SELECT * FROM functions WHERE` | `fn` | `fn c>50` |
| `SELECT * FROM classes WHERE` | `cls` | `cls n~'Service'` |
| `SELECT * FROM modules` | `mod` | `mod fp~'src/'` |
| `complexity` | `c` | `fn c>50` |
| `name LIKE` | `n~` | `fn n~'auth'` |
| `file_path` | `fp` | `fn fp~'test'` |
| `SHOW DEPENDENCIES OF X DEPTH N` | `deps X dN` | `deps Auth d2` |
| `SHOW DEPENDENTS OF X` | `rdeps X` | `rdeps User` |
| `SHOW CALLERS OF X` | `callers X` | `callers main` |
| `SHOW CALLEES OF X` | `callees X` | `callees process` |
| `SHOW IMPACT OF X` | `impact X` | `impact Service` |
| `ORDER BY X DESC` | `sort x-` | `fn sort c-` |
| `ORDER BY X ASC` | `sort x+` | `fn sort n+` |
| `LIMIT N` | `N` (at end) | `fn c>50 10` |

### Examples
```
fn c>50 sort c- 10      # Top 10 complex functions
deps AuthService d2     # Auth dependencies, 2 levels
fn n~'parse' fp~'src/'  # Functions named *parse* in src/
callers main d3         # What calls main, 3 levels up
```

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

## Syntax
!ModuleName @requires:[Dep1, Dep2]
$EntityName { field1:Type, field2:Type }
$Child < $Parent
#func_name(arg:Type) -> ReturnType
#mutating_func(arg:Type) => ReturnType
?condition -> result
?value | case1 -> result1 | case2 -> result2
:: complexity:N
:: summary text

## Annotations
:: complexity:N = AST node count (high = complex)
:: REDACTED:TYPE = secret removed (api_key, password, etc.)
:: guard: COND = precondition
:: summary text = LLM-generated semantic summary

## Example
!PaymentService @requires:[Stripe, Database]
  $Transaction { id:str, amount:Decimal, status:Status }
  #process(tx:Transaction) => Result :: complexity:42
    :: validates amount, charges via Stripe, persists to DB
    ?tx.amount > 1000 -> requireApproval
    stripe.charge(tx) => tx.status = COMPLETE
