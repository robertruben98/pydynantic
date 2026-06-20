# Collections

A **collection** retrieves several *distinct* entity types that share one partition, in a
single query. This is the payoff of [single-table design](../concepts/single-table-design.md):
one read returns an item collection, and `pydynantic` buckets it back into typed lists.

## Declaring a collection

Subclass [`Collection`][pydynantic.Collection] and list its `members`. Every member must
compose the **same** partition key.

```python
from pydynantic import Collection

class OrgData(Collection):
    members = [User, Membership, Invoice]   # all share PK = ORG#{org_id}
```

## Querying a partition

[`Collection.query()`][pydynantic.Collection.query] takes the partition-key attributes
and returns a query you terminate with `.all()` or `.page()`:

```python
result = OrgData.query(org_id="acme").all()    # -> CollectionResult

result.users        # list[User]
result.memberships  # list[Membership]
result.invoices     # list[Invoice]
result.all()        # every item across buckets, in DynamoDB return order
```

Each bucket is exposed as the entity's `name` **pluralised** (`name="user"` →
`result.users`). The result object is a [`CollectionResult`][pydynantic.CollectionResult].

## How discrimination works

Every item carries the reserved `__entity__` attribute (set from the entity's
`name=`). The collection query reads the whole partition, then routes each item to the
member whose discriminator matches — that is how three entity types come back as three
typed lists from one query.

## Pagination and projection

```python
# Cursor pagination over a collection:
page = OrgData.query(org_id="acme").limit(50).page()
page.result.users   # list[User] in this page (page.result is a CollectionResult)
page.has_more       # bool
next_page = OrgData.query(org_id="acme").limit(50).page(cursor=page.cursor)

# Projection — fetch only some attributes (the discriminator is always included):
OrgData.query(org_id="acme", attributes=["user_id", "name"]).all()
```

`.page()` returns a [`CollectionPage`][pydynantic.CollectionPage]; its `.result` is a
`CollectionResult` (the per-entity buckets), alongside `cursor` / `has_more`.

!!! tip
    Reach for a collection when an access pattern needs several entity types from the same
    partition at once (e.g. "load everything about this org"). For a single entity type,
    a plain [query](queries.md) is simpler.
