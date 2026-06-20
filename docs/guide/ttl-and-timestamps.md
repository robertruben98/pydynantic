# TTL & timestamps

`pydynantic` ships field markers that manage common metadata for you: a DynamoDB TTL
attribute and auto-stamped created/updated timestamps. Each is a drop-in replacement for
a Pydantic field default.

```python
from datetime import datetime
from pydynantic import Entity, key, ttl_attr, created_at_attr, updated_at_attr

class Session(Entity, table=table, name="session"):
    session_id: str
    user_id: str
    created_at: datetime | None = created_at_attr()
    updated_at: datetime | None = updated_at_attr()
    expires_at: datetime | None = ttl_attr()

    class Meta:
        primary = key(pk="USER#{user_id}", sk="SESSION#{session_id}")
```

## `created_at_attr()`

[`created_at_attr()`][pydynantic.created_at_attr] marks a `datetime | None` field as the
creation timestamp. On the **first** `put` (while the field is still `None`) it is stamped
with `datetime.now(timezone.utc)`. Later puts leave it untouched, and `update` never
modifies it.

## `updated_at_attr()`

[`updated_at_attr()`][pydynantic.updated_at_attr] marks a `datetime | None` field as the
modification timestamp. It is stamped on **every** `put`, and on every `update` — unless
the caller explicitly supplies it in `set=`, in which case the caller's value wins.

## `ttl_attr()`

[`ttl_attr()`][pydynantic.ttl_attr] marks the DynamoDB Time-To-Live attribute. DynamoDB
requires the TTL attribute to be a Number holding a Unix epoch timestamp in **seconds**.
You usually declare the field as `datetime | None` (the common case) or `int`:

- On every `put`, the stored value is written as epoch-seconds, regardless of the model's
  normal ISO datetime encoding.
- Reading back coerces the epoch into a UTC `datetime`, so sub-second precision is dropped.
- The default is `None` (TTL is optional); when `None`, the attribute is omitted entirely.

```python
from datetime import datetime, timedelta, timezone

session = Session(
    session_id="s1",
    user_id="u1",
    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
)
Session.put(session)   # expires_at stored as epoch-seconds; DynamoDB expires it later
```

!!! warning "Use timezone-aware datetimes for TTL"
    TTL `datetime` values should be timezone-aware. A naive datetime is passed to
    `.timestamp()` unchanged (Python interprets it in the local timezone); `pydynantic`
    does not reinterpret it, so prefer tz-aware values to avoid surprises.

!!! note "Enable TTL on the table"
    These markers control how `pydynantic` *writes* the attribute. Actual expiry requires
    TimeToLive to be enabled on the table itself (via the console, CDK, or Terraform) —
    `pydynantic` does not provision infrastructure. DynamoDB also deletes expired items
    lazily (typically within 48 hours), so don't rely on TTL for precise timing; pair it
    with a filter on `expires_at` if you need exactness (see the
    [soft-delete recipe](../recipes.md)).
