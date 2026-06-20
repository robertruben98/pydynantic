# Queries

A query reads a slice of one partition by key condition. In `pydynantic`, every named
key in `Meta` becomes a **typed access pattern** on `Entity.query`, so you call the
pattern by name instead of writing a `KeyConditionExpression`.

```python
class User(Entity, table=table, name="user"):
    ...
    class Meta:
        primary = key(pk="ORG#{org_id}", sk="USER#{user_id}")
        by_email = key(index="GSI1", pk="EMAIL#{email}", sk="USER#{user_id}")
```

## Querying a partition

Start from the access pattern, supplying the attributes its **partition key** needs:

```python
# All users in an org (partition + begins_with on the sort key):
users = (User.query.primary(org_id="acme")
                   .begins_with("USER#")
                   .limit(50)
                   .all())                      # -> list[User]
```

Query a GSI exactly the same way:

```python
user = User.query.by_email(email="a@x.com").one_or_none()   # -> User | None
```

## Sort-key conditions

After choosing a pattern, narrow the sort key with one of:

| Method | Meaning |
| --- | --- |
| `.eq(v)` | exact match |
| `.begins_with(prefix)` | prefix match |
| `.between(low, high)` | inclusive range |
| `.gt(v)` / `.gte(v)` | greater (or equal) |
| `.lt(v)` / `.lte(v)` | less (or equal) |

Because sort keys sort lexicographically, ISO-8601 timestamp prefixes give you natural
date ranges:

```python
User.query.primary(org_id="acme").between("USER#a", "USER#m").all()
```

## Ordering, limits, projection, consistency

```python
(User.query.primary(org_id="acme")
     .descending()                  # newest-first; .ascending() is the default
     .limit(25)                     # cap the page size
     .attributes(["user_id", "name"])  # projection; omitted fields use defaults
     .consistent()                  # strongly consistent read (not valid on a GSI)
     .all())
```

## Terminals

A builder does nothing until you call a terminal:

| Terminal | Returns |
| --- | --- |
| `.all()` | `list[E]` — every matching item (paginates internally) |
| `.iter()` | `Iterator[E]` — lazy, streams pages |
| `.first()` | `E \| None` — the first item, or `None` |
| `.one()` | `E` — exactly one; raises otherwise |
| `.one_or_none()` | `E \| None` — at most one; raises if more |
| `.page(cursor=...)` | a [`Page`][pydynantic.Page] for cursor pagination |
| `.count()` | `int` — server-side count, no items materialised |

```python
# Exactly one (raises ItemNotFoundError / MultipleResultsError otherwise):
user = User.query.by_email(email="a@x.com").one()

# Server-side count with a filter, nothing materialised:
active = User.query.primary(org_id="acme").filter(F("status") == "active").count()
```

`.one()` raises [`ItemNotFoundError`][pydynantic.ItemNotFoundError] when empty and
[`MultipleResultsError`][pydynantic.MultipleResultsError] when more than one matches.

## Filters

`.filter(...)` applies a server-side `FilterExpression` *after* the key condition (it
narrows results but is billed on items read). See [Filters & conditions](filters-and-conditions.md).

## Scan

When no key condition applies, [`scan()`][pydynantic.Entity.scan] reads the whole table.
It automatically filters on the `__entity__` discriminator so only this entity's items
come back, and exposes the same builder surface
([`ScanBuilder`][pydynantic.ScanBuilder]): `.filter`, `.limit`, `.attributes`, `.all`,
`.first`, `.iter`, `.page`, `.count`.

```python
all_users = User.scan().all()
User.scan().filter(F("status") == "active").count()
```

!!! tip
    Prefer `query` whenever a key condition applies — a scan reads every item in the
    table and is far more expensive than a partition query.
