# CRUD

All CRUD operations are classmethods on your entity. You never hand-write an
`UpdateExpression`, and key attributes are composed from your templates automatically.

The examples below assume the `User` entity from [Entities & keys](entities-and-keys.md).

## Put (create or replace)

[`put()`][pydynantic.Entity.put] writes a whole item, creating or replacing it. It
returns the written object (so `User.put(x) is x`).

```python
user = User(user_id="u1", org_id="acme", email="a@x.com", name="Ana")
User.put(user)
```

Pass a `condition` to guard the write — for example, a create-only put that fails if the
item already exists:

```python
from pydynantic import attr_not_exists

User.put(user, condition=attr_not_exists("PK"))
```

A failed condition raises [`ConditionCheckFailedError`][pydynantic.ConditionCheckFailedError].
See [Filters & conditions](filters-and-conditions.md).

## Get

[`get()`][pydynantic.Entity.get] fetches by primary key and returns the typed entity, or
`None` if it does not exist.

```python
user = User.get(org_id="acme", user_id="u1")     # -> User | None
```

Need it to raise instead of returning `None`? Use
[`get_or_raise()`][pydynantic.Entity.get_or_raise], which raises
[`ItemNotFoundError`][pydynantic.ItemNotFoundError].

For a strongly consistent read, pass `consistent=True`. To fetch only some attributes,
pass a projection (omitted fields fall back to their model defaults, so include
everything the entity needs to construct):

```python
user = User.get(org_id="acme", user_id="u1", attributes=["user_id", "name"])
```

## Update (partial)

[`update()`][pydynantic.Entity.update] applies a partial change via a generated
`UpdateExpression`. It returns the new state (`ReturnValues="ALL_NEW"` by default).

```python
User.update(
    org_id="acme", user_id="u1",
    set={"name": "Ana B.", "status": "inactive"},  # assign attributes
    add={"login_count": 1},                         # atomic numeric/set add
    remove=["nickname"],                            # delete attributes
)
```

| Clause | Meaning |
| --- | --- |
| `set` | Assign attribute values. |
| `remove` | Delete attributes entirely. |
| `add` | Atomic numeric increment, or add elements to a set. |
| `delete` | Remove elements from a set. |

!!! note "GSI keys are kept consistent"
    If `set` changes an attribute that feeds a GSI key template, `pydynantic` recomputes
    that index key automatically. If it can't (because a co-dependent attribute wasn't
    supplied), it raises [`PydynanticError`][pydynantic.PydynanticError] telling you which
    attributes to also pass in `set=`.

You can also pass a `condition`; a failed guard raises
[`ConditionCheckFailedError`][pydynantic.ConditionCheckFailedError].

## Delete

[`delete()`][pydynantic.Entity.delete] removes an item by primary key.

```python
User.delete(org_id="acme", user_id="u1")
```

With `return_values="ALL_OLD"` it returns the deleted item (or `None` if it didn't
exist); otherwise it returns `None`. A `condition` guards the delete.

## Next

- Read many items by key pattern: [Queries](queries.md).
- Read/write many at once: [Batch](batch.md).
- Atomic multi-item changes: [Transactions](transactions.md).
