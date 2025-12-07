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
| `mu_query` | MUQL queries |
| `mu_context` | Smart context for questions |
| `mu_semantic_diff` | PR review with breaking changes |
| `mu_scan` | Fast file discovery (Rust, 6.9x faster) |
| `mu_compress` | Generate MU output |
| `mu_impact` | "If I change X, what breaks?" |
| `mu_ancestors` | "What does X depend on?" |
| `mu_cycles` | Detect circular dependencies |

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
