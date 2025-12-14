# Operators - Data Flow & Relationships

Operators in MU show how data moves and transforms through your system.

## Flow Operators

### `->` Pure Data Flow

The arrow shows pure transformation - data in, data out, no side effects.

```mu
#transform(input:str) -> Output
  input -> validate -> parse -> enrich -> Output

#pipeline(data:list)
  data -> filter(active) -> map(transform) -> sort(by_date) -> list
```

**When you see `->`, think:**
- No database writes
- No external API calls
- No state mutation
- Deterministic output for same input

### `=>` State Mutation

The fat arrow marks side effects - state changes, I/O, the dangerous stuff.

```mu
#save_user(user:User) => void
  db.insert(user) => persisted
  cache.invalidate("users") => cleared

#process_payment(tx:Transaction) => Result
  stripe.charge(tx) => charged
  tx.status => "complete"
  notify(tx.user) => notified
```

**When you see `=>`, think:**
- Database operations
- External API calls
- File I/O
- State that changes
- Things that can fail

## Relationship Operators

### `<` Inheritance

Shows type hierarchies and implementations.

```mu
$Admin < $User              # Admin extends User
$User < $Entity             # User extends Entity
$PaymentService < IPaymentService  # implements interface
```

Multiple inheritance:
```mu
$PowerUser < [$Admin, $Subscriber]
```

### `|` Match / Switch

Shows branching possibilities.

```mu
?status | pending -> process
       | complete -> skip
       | failed -> retry
       | -> error("Unknown status")  # default case
```

Type matching:
```mu
?event | UserCreated -> handleCreate
      | UserDeleted -> handleDelete
      | _ -> log("Unknown event")
```

### `~` Iteration

Shows collection processing and loops.

```mu
#notify_all(users:list[User])
  ~users -> sendNotification

#process_batch(items:list)
  ~items | valid -> process
         | invalid -> log_error
```

## Combining Operators

Operators compose naturally:

```mu
!OrderService
  #process_orders(orders:list[Order]) => list[Result]
    ~orders                           # iterate
      -> validate                     # pure transform
      -> enrich_with_customer_data    # pure transform
      | valid -> charge_payment =>    # branch, then mutate
      | invalid -> reject             # branch, pure

#data_pipeline(raw:Stream)
  raw -> parse                        # pure
      ~> transform_batch              # iterate
      -> aggregate                    # pure
      => persist                      # mutate
```

## Real-World Example

Here's a complete service showing operators in action:

```mu
!PaymentService @requires:[Stripe, Database, EventBus]

  $PaymentIntent { id, amount:Decimal, status:Status, customer_id:str }

  #create_intent(customer_id:str, amount:Decimal) -> PaymentIntent
    :: creates Stripe PaymentIntent, stores locally
    validate_amount(amount) -> ok
    stripe.create_intent(amount) -> intent
    -> PaymentIntent(intent.id, amount, "pending", customer_id)

  #confirm_payment(intent_id:str) => Result
    :: confirms payment, updates status, emits event
    db.get(intent_id) -> intent
    ?intent.status | "pending" ->
      stripe.confirm(intent_id) => confirmed
      intent.status => "complete"
      db.save(intent) => persisted
      events.emit(PaymentComplete(intent)) => notified
      -> Success
    | "complete" -> AlreadyComplete
    | -> InvalidState

  #refund(intent_id:str, reason:str) => Result
    :: processes refund, requires audit trail
    ?intent.amount > 10000 -> require_approval
    stripe.refund(intent_id) => refunded
    intent.status => "refunded"
    audit.log(intent_id, reason) => logged
```

---

*Press [n] for MUbase Queries, [p] for previous, [q] to quit*
