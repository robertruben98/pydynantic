# Single-table design

If you come from relational databases, the natural instinct is one table per entity:
a `users` table, an `orders` table, a `memberships` table. DynamoDB rewards the
opposite instinct. **Single-table design (STD)** puts many entity types in *one*
physical table and uses the key schema to keep related items physically close, so a
single `Query` returns everything an access pattern needs without joins.

`pydynantic` exists to make STD ergonomic in Python: you keep modelling typed entities,
and the library handles the key gymnastics underneath.

## One table, generic keys

A DynamoDB table has a **partition key** (PK) and an optional **sort key** (SK). In STD
these are deliberately *generic* — usually named `PK` and `SK` — because they will hold
composed string values for many different entity types, not a single natural id.

```text
PK                     SK                  __entity__   attributes...
ORG#acme               USER#u1             user         email=a@x.com, name=Ana
ORG#acme               USER#u2             user         email=b@x.com, name=Bob
ORG#acme               INVOICE#2024-001    invoice      total=120.00
ORG#acme               MEMBERSHIP#u1       membership   role=admin
```

Three different entity types share the partition `ORG#acme`. One query on that
partition returns the org's users, invoices, and memberships together — an **item
collection**.

In `pydynantic`, those composed values are never typed by hand. You declare *templates*
and the library renders them:

```python
class Meta:
    primary = key(pk="ORG#{org_id}", sk="USER#{user_id}")
```

`org_id="acme"`, `user_id="u1"` → `PK="ORG#acme"`, `SK="USER#u1"`.

## Item collections

An **item collection** is the set of items that share the same partition key. Because
DynamoDB stores them together and a `Query` reads a contiguous slice of one partition,
fetching a collection is a single, cheap, sorted read.

The sort key gives you range power within a collection:

- `begins_with("USER#")` — only the users in the org.
- `between("INVOICE#2024-01", "INVOICE#2024-12")` — a date range, because ISO strings
  sort lexicographically.

See the [Collections guide](../guide/collections.md) for retrieving several entity types
from one partition in one call.

## GSI overloading

A **Global Secondary Index (GSI)** is a second key schema over the same items, letting
you query by attributes that are not the primary key. In STD, GSIs are *overloaded*:
the same physical index (e.g. `GSI1PK` / `GSI1SK`) serves different access patterns for
different entities.

```python
class User(Entity, table=table, name="user"):
    user_id: str
    org_id: str
    email: str

    class Meta:
        primary = key(pk="ORG#{org_id}", sk="USER#{user_id}")
        by_email = key(index="GSI1", pk="EMAIL#{email}", sk="USER#{user_id}")
```

`by_email` writes `GSI1PK="EMAIL#a@x.com"`, so you can look a user up by email without
knowing their org. A different entity can reuse `GSI1` with a totally different template
(for instance `STATUS#{status}`), and each entity's items only appear under the patterns
it defines.

!!! tip "Sparse indexes"
    If an entity doesn't define a key for a given index, its items simply don't carry that
    index's attributes — so they never show up in that index. Overloading plus sparseness
    is how one GSI cleanly serves many unrelated queries.

## Access-pattern-first modelling

The relational workflow is: model the entities, normalize, then write whatever queries
you need. DynamoDB inverts this. You **list the access patterns first**, then design keys
that satisfy them with single-partition reads.

A typical worksheet:

| Access pattern | Key shape |
| --- | --- |
| Get a user by id within an org | PK `ORG#{org_id}`, SK `USER#{user_id}` |
| List all users in an org | PK `ORG#{org_id}`, SK `begins_with("USER#")` |
| Find a user by email | GSI1 PK `EMAIL#{email}` |
| List active users | GSI1 PK `STATUS#{status}` |

`pydynantic` maps each row to a named `key(...)` in `Meta`, and each becomes a typed
query like `User.query.by_email(email=...)`. The query surface *is* your access-pattern
list, in code.

## How pydynantic supports STD

- **Templates** ([Entities & keys](../guide/entities-and-keys.md)) compose PK/SK/GSI values.
- **`__entity__` discriminator** is written on every item so reads route back to the
  right typed class — the backbone of overloading and collections.
- **Named access patterns** ([Queries](../guide/queries.md)) replace raw expressions.
- **Collections** ([Collections](../guide/collections.md)) read multiple entity types from
  one partition.
- **Transactions** ([Transactions](../guide/transactions.md)) keep multi-item invariants
  atomic — important when one logical change touches several items.

With those primitives, the awkward parts of STD become declarations, and you can keep
thinking in entities.
