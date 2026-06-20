# Transactions

A transaction applies up to 100 writes as a single, atomic `TransactWriteItems` call:
either every action succeeds or none do. Use it to keep multi-item invariants consistent.

## The context manager

[`transaction()`][pydynantic.transaction] yields a [`Transaction`][pydynantic.Transaction]
to queue actions. It commits on a clean exit; if the `with` block raises, `commit` is
never reached, so nothing is sent (rollback).

```python
from pydynantic import transaction, F

with transaction(table) as tx:
    tx.put(Order(order_id="o1", customer_id="acme", total=120.0))
    tx.update(User, key=("acme", "u1"), add={"orders": 1})
    tx.condition_check(Account, key=("acme",), condition=F("balance") >= 100)
# Commits here. A failed condition cancels everything atomically.
```

## Actions

| Method | Purpose |
| --- | --- |
| `tx.put(item, condition=...)` | queue a `Put` |
| `tx.update(Entity, key=..., set=..., add=..., remove=..., delete=..., condition=...)` | queue an `Update` |
| `tx.delete(Entity, key=..., condition=...)` | queue a `Delete` |
| `tx.condition_check(Entity, key=..., condition=...)` | guard with no write |

`key=` accepts the primary-key attributes (a tuple in primary-key order, e.g.
`("acme", "u1")`). The `set` / `add` / `remove` / `delete` clauses mirror
[`update()`][pydynantic.Entity.update].

## Atomicity and failures

If any queued condition fails at commit time, DynamoDB cancels the **whole** transaction
and `pydynantic` raises [`TransactionCanceledError`][pydynantic.TransactionCanceledError].
Its `.reasons` lists a cancellation reason per action, in order, so you can tell which
guard failed.

```python
from pydynantic import transaction, TransactionCanceledError, F

try:
    with transaction(table) as tx:
        tx.update(Account, key=("acme",), add={"balance": -100},
                  condition=F("balance") >= 100)
        tx.put(Order(order_id="o1", customer_id="acme", total=100.0))
except TransactionCanceledError as exc:
    print(exc.reasons)   # per-action reasons; e.g. ConditionalCheckFailed on the guard
```

!!! note "`condition_check` is a read-only guard"
    Use `tx.condition_check(...)` to assert a fact about an item you are **not** writing —
    for example "the account still exists and is active" — so the transaction fails if the
    assumption no longer holds.
