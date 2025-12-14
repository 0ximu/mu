## MCP Tool Examples

### Bootstrap a New Codebase

```python
# Check what needs to be done
status = mu_status()

# Follow the guidance
if status["next_action"] == "mu_init":
    mu_init(".")

if status["next_action"] == "mu_build":
    result = mu_build(".")
    print(f"Built graph: {result.stats}")

# Now query works
context = mu_context("How does authentication work?")
```

### PR Review with Semantic Diff

```python
# Compare main to current branch
diff = mu_semantic_diff("main", "HEAD")

# Check for breaking changes
if diff.has_breaking_changes:
    print("Breaking changes detected:")
    for change in diff.breaking_changes:
        print(f"  - {change['change_type']}: {change['entity_name']}")

# Human-readable summary
print(diff.summary_text)
# "functions: 2 added, 1 modified; classes: 1 removed"
```

### Impact Analysis

```python
# What breaks if I change auth.py?
impact = mu_impact("mod:src/auth.py")
print(f"{impact.count} nodes affected")

# Find circular dependencies
cycles = mu_cycles(["imports"])
if cycles.cycle_count > 0:
    print(f"Found {cycles.cycle_count} import cycles")
    for cycle in cycles.cycles:
        print(f"  {' -> '.join(cycle)}")

# What does cli.py depend on?
deps = mu_ancestors("mod:src/cli.py")
print(f"cli.py has {deps.count} upstream dependencies")
```

### Fast Codebase Scan

```python
# Quick file discovery (uses Rust scanner)
scan = mu_scan(".", extensions=["py", "ts"])
print(f"Found {scan.total_files} files, {scan.total_lines} lines")
print(f"Languages: {scan.by_language}")

# Generate compressed output
compressed = mu_compress("src/auth", format="mu")
print(f"Compressed to {compressed.token_count} tokens ({compressed.compression_ratio:.0%} reduction)")
```

---

## MU Format Examples

### Python Class -> MU

**Input:**
```python
class UserRepository:
    def __init__(self, db: Database, cache: Cache):
        self.db = db
        self.cache = cache

    def get(self, user_id: str) -> Optional[User]:
        cached = self.cache.get(f"user:{user_id}")
        if cached:
            return cached
        user = self.db.query(User).get(user_id)
        if user:
            self.cache.set(f"user:{user_id}", user, ttl=3600)
        return user

    def save(self, user: User) -> User:
        self.db.add(user)
        self.db.commit()
        self.cache.delete(f"user:{user.id}")
        return user
```

**Output:**
```mu
!UserRepository @requires:[Database, Cache]
  #get(user_id:str) -> User?
    :: cache-first with 1h TTL, DB fallback
  #save(user:User) => User
    :: persists to DB, invalidates cache
```

### TypeScript Service -> MU

**Input:**
```typescript
export class PaymentService {
  constructor(
    private stripe: StripeClient,
    private db: Database,
    private events: EventEmitter
  ) {}

  async processPayment(
    amount: number,
    customerId: string
  ): Promise<PaymentResult> {
    if (amount <= 0) {
      throw new ValidationError("Amount must be positive");
    }

    const intent = await this.stripe.createPaymentIntent({
      amount,
      customer: customerId,
    });

    const payment = await this.db.payments.create({
      intentId: intent.id,
      amount,
      customerId,
      status: "pending",
    });

    this.events.emit("payment:created", payment);

    return { paymentId: payment.id, clientSecret: intent.clientSecret };
  }
}
```

**Output:**
```mu
!PaymentService @requires:[StripeClient, Database, EventEmitter]
  #processPayment(amount:number, customerId:str) => PaymentResult @async
    :: validates amount, creates Stripe intent, persists payment, emits event
    ?amount <= 0 -> ValidationError
    stripe.createPaymentIntent => intent
    db.payments.create => payment
    events.emit("payment:created") => notified
```

### Go Struct -> MU

**Input:**
```go
type OrderService struct {
    repo    OrderRepository
    payment PaymentClient
    notify  NotificationService
}

func (s *OrderService) CreateOrder(ctx context.Context, req CreateOrderRequest) (*Order, error) {
    if err := req.Validate(); err != nil {
        return nil, fmt.Errorf("validation: %w", err)
    }

    order := &Order{
        ID:        uuid.New(),
        Items:     req.Items,
        Total:     calculateTotal(req.Items),
        Status:    StatusPending,
        CreatedAt: time.Now(),
    }

    if err := s.repo.Save(ctx, order); err != nil {
        return nil, fmt.Errorf("save order: %w", err)
    }

    if req.AutoCharge {
        if err := s.payment.Charge(ctx, order.Total); err != nil {
            order.Status = StatusFailed
            s.repo.Save(ctx, order)
            return nil, fmt.Errorf("payment: %w", err)
        }
        order.Status = StatusPaid
    }

    s.notify.SendConfirmation(ctx, order)

    return order, nil
}
```

**Output:**
```mu
!OrderService @requires:[OrderRepository, PaymentClient, NotificationService]

  $Order { ID:UUID, Items:list, Total:Decimal, Status, CreatedAt:time }
  $CreateOrderRequest { Items:list, AutoCharge:bool }

  #CreateOrder(ctx, req:CreateOrderRequest) => Order? :: complexity:35
    :: validates, persists order, optionally charges, sends confirmation
    ?req.Validate() -> error
    Order(req.Items, calculateTotal) -> order
    repo.Save(order) => persisted
    ?req.AutoCharge ->
      payment.Charge(order.Total) => charged
      ?error -> order.Status => Failed
    notify.SendConfirmation(order) => notified
```

### Complex Function -> MU with Summary

**Input:**
```python
def resolve_dependencies(
    modules: list[Module],
    external_packages: set[str],
    stdlib: set[str]
) -> DependencyGraph:
    graph = DependencyGraph()

    # First pass: register all modules
    for module in modules:
        node = graph.add_node(module.name, NodeType.MODULE)
        node.metadata["path"] = module.path

    # Second pass: resolve imports
    for module in modules:
        for imp in module.imports:
            if imp.module in stdlib:
                continue  # Skip stdlib

            if imp.module in external_packages:
                ext_node = graph.get_or_create(imp.module, NodeType.EXTERNAL)
                graph.add_edge(module.name, imp.module, EdgeType.IMPORTS)
            else:
                # Try to resolve as internal
                resolved = resolve_internal(imp, modules)
                if resolved:
                    graph.add_edge(module.name, resolved, EdgeType.IMPORTS)
                else:
                    # Unresolved - might be dynamic import
                    graph.add_unresolved(module.name, imp.module)

    # Third pass: detect cycles
    cycles = graph.find_cycles()
    if cycles:
        for cycle in cycles:
            graph.mark_cycle(cycle)

    return graph
```

**Output:**
```mu
#resolve_dependencies(modules:list[Module], external_packages:set, stdlib:set) -> DependencyGraph :: complexity:52
  :: Three-pass algorithm: (1) register modules, (2) resolve imports distinguishing
  :: stdlib/external/internal, (3) detect and mark circular dependencies.
  :: Unresolved imports tracked separately for dynamic import handling.
```
