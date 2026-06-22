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

Once a version field is present, every write **increments** `version`. Whether the write
is also **guarded** (raises instead of overwriting a concurrent change) depends on the call:

- **`put`** guards automatically. It carries the full item — including the `version` you
  read — so it guards on the **previous** value: "the stored version must still be what I
  last saw" (a first create is allowed because the item doesn't yet exist).
- **`update`** is a blind, keyed partial write with no item in hand, so it cannot know the
  expected version. Pass `expected_version=` to opt into the guard (see below). Without it,
  `update` still increments `version` but does **not** guard — concurrent updates can lose
  each other's writes.

When a guard fails (someone else wrote in between), the write raises
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

## Guarding an `update`

Read the item, then pass the version you saw as `expected_version=`. If the stored version
moved in between, the write raises instead of clobbering it:

```python
from pydynantic import OptimisticLockError

order = Order.get_or_raise(customer_id="acme", order_id="o1")
try:
    Order.update(
        customer_id="acme",
        order_id="o1",
        set={"total": 99.0},
        expected_version=order.version,   # guard on what we read
    )
except OptimisticLockError:
    fresh = Order.get_or_raise(customer_id="acme", order_id="o1")
    # re-apply the change against the fresh version, then retry
```

Passing `expected_version=` to an entity without a `version_attr()` field raises
`ValueError` — there is nothing to guard on.

!!! warning
    An `update` **without** `expected_version=` increments `version` but does not guard, so
    it can silently lose a concurrent write. A [batch write](batch.md) replaces items
    unconditionally and bypasses the guard entirely — use
    [transactions](transactions.md) when you need conditional multi-item writes.
