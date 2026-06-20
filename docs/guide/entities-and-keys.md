# Entities & keys

An **entity** is a Pydantic v2 model that carries single-table metadata: which table it
lives in, a discriminator name, and the key templates that compose its DynamoDB keys.

## The table

Create one [`Table`][pydynantic.Table] per physical DynamoDB table. The boto3 client is
**injected**, so credentials, region, endpoint and testing stay in your control.

```python
import boto3
from pydynantic import Table

table = Table(
    name="app-prod",
    pk="PK",                       # physical partition-key attribute name
    sk="SK",                       # physical sort-key attribute name (or None)
    indexes={"GSI1": {"pk": "GSI1PK", "sk": "GSI1SK"}},
    client=boto3.client("dynamodb"),
)
```

`pk` defaults to `"PK"` and `sk` to `"SK"`. Each index maps a logical name to its
physical key attribute names.

## Declaring an entity

Subclass [`Entity`][pydynantic.Entity], pass `table=` and a `name=` discriminator, and
declare attributes with normal Pydantic syntax. Key templates go on an inner `Meta`
class via [`key()`][pydynantic.key].

```python
from datetime import datetime, timezone
from pydynantic import Entity, Field, key

class User(Entity, table=table, name="user"):
    user_id: str
    org_id: str
    email: str
    name: str
    status: str = "active"
    login_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Meta:
        primary = key(pk="ORG#{org_id}", sk="USER#{user_id}")
        by_email = key(index="GSI1", pk="EMAIL#{email}", sk="USER#{user_id}")
```

The `name="user"` discriminator is written to a reserved `__entity__` attribute on every
item, which is how reads (and [collections](collections.md)) route an item back to the
right typed class.

## Key templates

A template is a string with `{placeholder}` fields that reference entity attributes.
Placeholders are resolved against the attribute values when an item is written or a key
is built:

| Template | Attributes | Rendered key |
| --- | --- | --- |
| `"ORG#{org_id}"` | `org_id="acme"` | `ORG#acme` |
| `"USER#{user_id}"` | `user_id="u1"` | `USER#u1` |
| `"EMAIL#{email}"` | `email="a@x.com"` | `EMAIL#a@x.com` |

Templates support literal prefixes/suffixes and multiple placeholders in a single key
(e.g. `"TENANT#{tenant}#USER#{user_id}"`). Values are rendered deterministically:
`datetime`/`date` use ISO-8601, `Enum` uses its value, `bool` is lowercased.

!!! warning
    If a template references an attribute you don't supply when building a key,
    `pydynantic` raises [`KeyTemplateError`][pydynantic.KeyTemplateError]. Pass every
    attribute the relevant template needs.

## The `primary` key and GSIs

- The `Meta` attribute named **`primary`** is the entity's primary key (no `index=`).
- Any other `key(..., index="GSI1", ...)` declares a named access pattern over that GSI.

Each named key becomes a typed query — `User.query.primary(...)`,
`User.query.by_email(...)` — covered in [Queries](queries.md). When an `update()` changes
an attribute that feeds a GSI key, `pydynantic` recomputes that index key automatically
(see [CRUD](crud.md)).

## Special attribute markers

`pydynantic` ships field markers that opt an attribute into managed behaviour. Each is a
drop-in replacement for a Pydantic default:

```python
from pydynantic import version_attr, ttl_attr, created_at_attr, updated_at_attr

class Order(Entity, table=table, name="order"):
    order_id: str
    customer_id: str
    version: int = version_attr()         # optimistic locking
    created_at: datetime | None = created_at_attr()
    updated_at: datetime | None = updated_at_attr()
    expires_at: datetime | None = ttl_attr()

    class Meta:
        primary = key(pk="CUSTOMER#{customer_id}", sk="ORDER#{order_id}")
```

- [`version_attr()`][pydynantic.version_attr] — see [Optimistic locking](optimistic-locking.md).
- [`ttl_attr()`][pydynantic.ttl_attr], [`created_at_attr()`][pydynantic.created_at_attr],
  [`updated_at_attr()`][pydynantic.updated_at_attr] — see [TTL & timestamps](ttl-and-timestamps.md).
