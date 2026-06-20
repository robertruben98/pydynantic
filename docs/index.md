# pydynantic

**Single-table design for DynamoDB in Python, with typed entities on top of Pydantic v2.**

`pydynantic` is the Pythonic answer to JavaScript's [ElectroDB](https://electrodb.dev/)
and [DynamoDB-Toolbox](https://www.dynamodbtoolbox.com/): model many entities in a
single DynamoDB table, compose keys from attributes, declare named & typed access
patterns, and never hand-write an `UpdateExpression` again.

- **Declarative entities** built on Pydantic v2 (validation, defaults, nested models).
- **Automatic key composition** from templates like `"ORG#{org_id}"` — primary keys and GSIs.
- **Typed, named access patterns** instead of raw expressions.
- **Transparent marshalling** for `str`, `int`, `float`, `Decimal`, `bool`, `bytes`,
  `datetime`, `date`, `UUID`, `Enum`, `list`, `dict`, `set`, and nested Pydantic models.
- **Single-table primitives**: collections, batch get/write, transactions, optimistic locking, cursor pagination.
- **Type-safe**: ships `py.typed`, passes `mypy --strict`.

!!! note
    The library never opens its own connections — you inject a boto3 client, which keeps
    credentials, region, endpoint, and testing fully in your control.

## Installation

```bash
pip install pydynantic
```

Requires Python 3.10+ and `boto3` / `pydantic>=2`.

## Quick start

```python
import boto3
from datetime import datetime, timezone
from pydynantic import Table, Entity, Field, key, F

# 1. Describe the physical table (one instance per real table).
table = Table(
    name="app-prod",
    pk="PK",
    sk="SK",
    indexes={"GSI1": {"pk": "GSI1PK", "sk": "GSI1SK"}},
    client=boto3.client("dynamodb"),   # injected; testable
)

# 2. Declare entities. Attributes use plain Pydantic syntax; keys are templates.
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

# 3. CRUD — no expressions by hand.
User.put(User(user_id="u1", org_id="acme", email="a@x.com", name="Ana"))

user = User.get(org_id="acme", user_id="u1")          # -> User | None

User.update(
    org_id="acme", user_id="u1",
    set={"name": "Ana B.", "status": "inactive"},
    add={"login_count": 1},
)

User.delete(org_id="acme", user_id="u1")
```

## Where to go next

- New to single-table modelling? Start with [Single-table design](concepts/single-table-design.md).
- Ready to model? See [Entities & keys](guide/entities-and-keys.md), then [CRUD](guide/crud.md)
  and [Queries](guide/queries.md).
- Need patterns? Browse the [Recipes](recipes.md) cookbook.
- Coming from JavaScript? See [Migrating from ElectroDB](migrating/from-electrodb.md) or
  [Migrating from DynamoDB-Toolbox](migrating/from-dynamodb-toolbox.md).
- The exhaustive symbol list lives in the [API reference](reference/api.md).

## Scope

In scope (v1): single-table modelling, keys, CRUD, queries, filters/conditions,
pagination, batch, transactions, collections, optimistic locking. Synchronous only.

Out of scope: table/infra provisioning (use CDK/Terraform), data migrations,
multi-table joins, async (planned for v2 on `aioboto3`).
