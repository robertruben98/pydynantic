# Optimistic locking

Optimistic locking prevents lost updates without holding a lock: each write checks that
the item hasn't changed since you read it, and bumps a version number. A lost race fails
loudly instead of silently overwriting.

## Marking the version field

Declare an integer field with [`version_attr()`][pydynantic.version_attr]:

```python
from pydynantic import Entity, key, version_attr

class Order(Entity, table=table, name="order"):
    order_id: str
    customer_id: str
    total: float = 0.0
    version: int = version_attr()        # starts at 0

    class Meta:
        primary = key(pk="CUSTOMER#{customer_id}", sk="ORDER#{order_id}")
```

## How it works

Once a version field is present, `pydynantic` makes every `put` and `update` conditional:

- The write **increments** `version`.
- It guards on the **previous** value — "the stored version must still be what I last
  saw" (a first create is allowed because the item doesn't yet exist).
- If the guard fails (someone else wrote in between), it raises
  [`OptimisticLockError`][pydynantic.OptimisticLockError] (a subclass of
  [`ConditionCheckFailedError`][pydynantic.ConditionCheckFailedError]).

```python
order = Order(order_id="o1", customer_id="acme", total=120.0)
Order.put(order)          # version 0 -> 1; the returned object carries version 1

order.total = 130.0
Order.put(order)          # guards on version 1; succeeds, now version 2
```

On a failed `put`, the in-memory version bump is rolled back so the object still reflects
the stored version and the call can be retried after re-reading.

## Handling conflicts

```python
from pydynantic import OptimisticLockError

try:
    Order.update(customer_id="acme", order_id="o1", set={"total": 99.0})
except OptimisticLockError:
    fresh = Order.get_or_raise(customer_id="acme", order_id="o1")
    # re-apply the change against the fresh version, then retry
```

!!! warning
    Optimistic locking guards `put` and `update` only. A
    [batch write](batch.md) replaces items unconditionally and **bypasses** the version
    guard — use [transactions](transactions.md) when you need conditional multi-item
    writes.
