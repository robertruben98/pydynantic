# Marshalling

DynamoDB only understands its own attribute-value types. `pydynantic` marshals your
Pydantic fields to and from those types transparently, so you model with native Python
types and never touch a raw `{"S": ...}` / `{"N": ...}` map.

## Supported types

| Python type | DynamoDB representation |
| --- | --- |
| `str` | `S` |
| `int`, `float`, `Decimal` | `N` (stored as `Decimal`) |
| `bool` | `BOOL` |
| `bytes` | `B` |
| `datetime`, `date` | `S` (ISO-8601 string) |
| `UUID` | `S` |
| `Enum` | underlying value's type |
| `list` | `L` |
| `dict` | `M` |
| `set` (of str/number/bytes) | `SS` / `NS` / `BS` |
| nested Pydantic model | `M` |

```python
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID
from pydantic import BaseModel
from pydynantic import Entity, key

class Tier(str, Enum):
    free = "free"
    pro = "pro"

class Address(BaseModel):
    city: str
    zip: str

class Account(Entity, table=table, name="account"):
    account_id: UUID
    org_id: str
    balance: Decimal = Decimal("0")
    tier: Tier = Tier.free
    tags: set[str] = set()
    address: Address | None = None
    created_at: datetime = datetime(2024, 1, 1, tzinfo=timezone.utc)

    class Meta:
        primary = key(pk="ORG#{org_id}", sk="ACCOUNT#{account_id}")
```

## Important behaviours

- **Numbers are stored as `Decimal`.** Floats are converted to `Decimal` on write to
  avoid floating-point drift. Read back, a field typed `float` is coerced by Pydantic;
  prefer `Decimal` directly for money.
- **`datetime` / `date` are ISO-8601 strings.** Because they sort lexicographically, they
  work naturally in sort keys and `between` ranges.
- **`None` values are omitted.** DynamoDB can't store a true null in a typed item, so
  `None` fields are dropped — and re-materialise from the field's default on read.
- **Empty sets are omitted.** DynamoDB rejects empty `SS`/`NS`/`BS`, so an empty set is
  dropped and comes back as the field default.

!!! warning "Projections and defaults"
    A projected read ([`get(..., attributes=...)`][pydynantic.Entity.get], `.attributes([...])`)
    returns only the requested attributes; every omitted field falls back to its model
    default. Include everything a required field needs, or validation will fail when the
    entity is reconstructed.

## Round-trip helpers

The marshalling is exercised by `Entity.to_dynamo()` (model → DynamoDB item) and
`Entity.from_dynamo(item)` (item → model). You rarely call these directly — every CRUD,
query, batch and transaction path uses them — but they're useful when integrating with
raw boto3 calls.
