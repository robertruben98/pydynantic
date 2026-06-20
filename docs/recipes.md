# Recipes

A cookbook of patterns built from the primitives in the guide. Each recipe assumes a
configured `table` and the imports it shows.

## Status-index overloading

Serve "list by status" from an overloaded GSI without a separate table. The GSI partition
is the status value, so a query returns just that status's items — and the index is
**sparse**: only entities defining the key appear in it.

```python
from pydynantic import Entity, Field, key

class Ticket(Entity, table=table, name="ticket"):
    ticket_id: str
    project_id: str
    status: str = "open"           # open | in_progress | closed
    priority: int = 3

    class Meta:
        primary = key(pk="PROJECT#{project_id}", sk="TICKET#{ticket_id}")
        by_status = key(index="GSI1", pk="STATUS#{status}", sk="TICKET#{ticket_id}")

# All open tickets across every project, one query:
open_tickets = Ticket.query.by_status(status="open").all()
```

When a ticket's status changes, update it through `set=` and `pydynantic` recomputes the
GSI key automatically:

```python
Ticket.update(project_id="p1", ticket_id="t1", set={"status": "closed"})
```

## Pagination in an HTTP handler

Return one page per request and pass the opaque cursor through the query string. The
cursor is URL-safe, so no encoding gymnastics.

```python
def list_users(org_id: str, cursor: str | None = None):
    page = User.query.primary(org_id=org_id).limit(25).page(cursor=cursor)
    return {
        "items": [u.model_dump() for u in page.items],
        "next_cursor": page.cursor,    # None when exhausted; echo back to fetch more
    }
```

A stale or tampered cursor raises [`PydynanticError`][pydynantic.PydynanticError]; map it
to a `400 Bad Request`.

## Idempotent create

Make "create if absent" safe to retry by guarding on the primary key's absence. A retry
that loses the race fails with a typed error instead of overwriting.

```python
from pydynantic import attr_not_exists, ConditionCheckFailedError

def create_user_once(user: User) -> bool:
    try:
        User.put(user, condition=attr_not_exists("PK"))
        return True            # we created it
    except ConditionCheckFailedError:
        return False           # already existed; safe no-op
```

## Atomic counters

Use `add=` for server-side, race-free numeric increments — no read-modify-write.

```python
# Bump a login counter atomically and read back the new total:
updated = User.update(org_id="acme", user_id="u1", add={"login_count": 1})
print(updated.login_count)

# Decrement (negative delta), guarded so it never goes below zero:
from pydynantic import F
User.update(
    org_id="acme", user_id="u1",
    add={"credits": -1},
    condition=F("credits") >= 1,
)
```

## Soft-delete via TTL

Mark an item for expiry instead of deleting it, and hide it immediately with a filter
(DynamoDB removes expired items lazily, typically within 48 hours).

```python
from datetime import datetime, timedelta, timezone
from pydynantic import Entity, key, ttl_attr, F

class Note(Entity, table=table, name="note"):
    note_id: str
    user_id: str
    body: str
    expires_at: datetime | None = ttl_attr()

    class Meta:
        primary = key(pk="USER#{user_id}", sk="NOTE#{note_id}")

# Soft-delete: schedule expiry 30 days out.
Note.update(
    user_id="u1", note_id="n1",
    set={"expires_at": datetime.now(timezone.utc) + timedelta(days=30)},
)

# Hide soft-deleted notes right away (don't wait for DynamoDB's sweep):
now = datetime.now(timezone.utc)
live = (Note.query.primary(user_id="u1")
            .filter(F("expires_at").not_exists() | (F("expires_at") > now))
            .all())
```

## Multi-entity partition reads

Load several entity types from one partition in a single query with a
[collection](guide/collections.md).

```python
from pydynantic import Collection

class OrgData(Collection):
    members = [User, Membership, Invoice]   # all keyed PK = ORG#{org_id}

result = OrgData.query(org_id="acme").all()
dashboard = {
    "users": result.users,
    "memberships": result.memberships,
    "invoices": result.invoices,
}
```
