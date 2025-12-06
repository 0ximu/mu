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
