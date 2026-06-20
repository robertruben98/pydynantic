# Batch

Batch operations read or write many items in as few round-trips as DynamoDB allows.
`pydynantic` chunks your input to the service limits (100 per `BatchGetItem`, 25 per
`BatchWriteItem`) and retries `UnprocessedItems` / `UnprocessedKeys` with backoff, so you
hand it a flat list and get a clean result.

## Batch get

[`batch_get()`][pydynantic.Entity.batch_get] fetches many items by key. Keys are passed
positionally in primary-key order (here `(org_id, user_id)`):

```python
users = User.batch_get([("acme", "u1"), ("acme", "u2")])   # -> list[User]
```

For a strongly consistent read or a projection:

```python
users = User.batch_get(
    [("acme", "u1"), ("acme", "u2")],
    consistent=True,
    attributes=["user_id", "name"],   # omitted fields fall back to model defaults
)
```

!!! note
    A batch get does not guarantee order and silently omits keys that don't exist — the
    result may be shorter than the input. Match by id if you need to align results.

## Batch write

[`batch_write()`][pydynantic.Entity.batch_write] puts and/or deletes many items in one
call. `puts` takes entity instances; `deletes` takes keys:

```python
User.batch_write(
    puts=[
        User(user_id="u4", org_id="acme", email="d@x.com", name="Dan"),
        User(user_id="u5", org_id="acme", email="e@x.com", name="Eve"),
    ],
    deletes=[("acme", "u3")],
)
```

!!! warning "Batch writes are not transactional and not conditional"
    `BatchWriteItem` cannot carry conditions and does not roll back as a unit — each item
    is applied independently. When you need atomicity or conditional guards across items,
    use [Transactions](transactions.md). Also note a batch put **replaces** the whole item
    (like [`put()`][pydynantic.Entity.put]), so it bypasses optimistic-locking guards.
