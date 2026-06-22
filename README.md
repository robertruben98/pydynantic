# pydynantic

[![PyPI version](https://img.shields.io/pypi/v/pydynantic.svg)](https://pypi.org/project/pydynantic/)
[![Docs](https://img.shields.io/badge/docs-online-blue)](https://robertruben98.github.io/pydynantic/)
[![Python versions](https://img.shields.io/pypi/pyversions/pydynantic.svg)](https://pypi.org/project/pydynantic/)
[![CI](https://github.com/robertruben98/pydynantic/actions/workflows/ci.yml/badge.svg)](https://github.com/robertruben98/pydynantic/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/robertruben98/pydynantic/branch/main/graph/badge.svg)](https://codecov.io/gh/robertruben98/pydynantic)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/robertruben98/pydynantic/blob/main/LICENSE)
[![Typed](https://img.shields.io/badge/typed-mypy%20strict-blue.svg)](https://mypy.readthedocs.io/)

**Single-table design for DynamoDB in Python, with typed entities on top of Pydantic v2.**

`pydynantic` is the Pythonic answer to JavaScript's [ElectroDB](https://electrodb.dev/)
and [DynamoDB-Toolbox](https://www.dynamodbtoolbox.com/): model many entities in a
single DynamoDB table, compose keys from attributes, declare named & typed access
patterns, and never hand-write an `UpdateExpression` again.

- 🧩 **Declarative entities** built on Pydantic v2 (validation, defaults, nested models).
- 🔑 **Automatic key composition** from templates like `"ORG#{org_id}"` — primary keys and GSIs.
- 🔎 **Typed, named access patterns** instead of raw expressions.
- 🔁 **Transparent marshalling** for `str`, `int`, `float`, `Decimal`, `bool`, `bytes`,
  `datetime`, `date`, `UUID`, `Enum`, `list`, `dict`, `set`, and nested Pydantic models.
- 🧱 **Single-table primitives**: collections, batch get/write, transactions, optimistic locking, cursor pagination.
- ✅ **Type-safe**: ships `py.typed`, passes `mypy --strict`.

> The library never opens its own connections — you inject a boto3 client, which keeps
> credentials, region, endpoint, and testing fully in your control.

---

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

### Queries & access patterns

```python
# Partition + begins_with on the sort key:
users = (User.query.primary(org_id="acme")
                   .begins_with("USER#")
                   .limit(50)
                   .all())                              # -> list[User]

# Access by GSI:
user = User.query.by_email(email="a@x.com").one_or_none()  # -> User | None

# Sort-key operators: .eq .begins_with .between .gt .gte .lt .lte
# Terminals: .all() .one() .one_or_none() .first() .iter() .page(cursor=...) .count()

# Count server-side (no items materialised):
active = User.query.primary(org_id="acme").filter(F("status") == "active").count()

# Projection — fetch only some attributes (omitted ones fall back to defaults):
User.query.primary(org_id="acme").attributes(["user_id", "name"]).all()
User.get(org_id="acme", user_id="u1", attributes=["user_id", "name"])
```

### Scan

```python
# Full-table scan, automatically restricted to this entity's items:
all_users = User.scan().all()
User.scan().filter(F("status") == "active").count()
# Same builder surface as query: .filter .limit .attributes .all .first .iter .page .count
```

### Filters & conditions

```python
User.query.primary(org_id="acme").filter(
    (F("status") == "active") & (F("login_count") > 0)
).all()

# Create-only put:
from pydynantic import attr_not_exists
User.put(user, condition=attr_not_exists("PK"))
```

Operators: `== != < <= > >=`, `.between()`, `.begins_with()`, `.contains()`,
`.exists()`, `.not_exists()`, `.is_in([...])`, combined with `&`, `|`, `~`.
`ExpressionAttributeNames`/`Values` are managed for you with no placeholder collisions.

### Pagination

```python
page = User.query.primary(org_id="acme").limit(25).page()
page.items        # list[User]
page.cursor       # opaque, JSON/HTTP-safe token (None when exhausted)

next_page = User.query.primary(org_id="acme").limit(25).page(cursor=page.cursor)
```

### Batch

```python
# Chunks of 25 (write) / 100 (get) and UnprocessedItems/Keys retried with backoff.
users = User.batch_get([("acme", "u1"), ("acme", "u2")])
User.batch_write(puts=[...], deletes=[("acme", "u3")])
```

### Transactions

```python
from pydynantic import transaction

with transaction(table) as tx:
    tx.put(Order(...))
    tx.update(User, key=("acme", "u1"), add={"orders": 1})
    tx.condition_check(Account, key=("acme",), condition=F("balance") >= 100)
# Commits on a clean exit; a failed condition cancels everything atomically.
```

### Collections (several entities, one partition)

```python
from pydynantic import Collection

class OrgData(Collection):
    members = [User, Membership, Invoice]   # share PK = ORG#{org_id}

result = OrgData.query(org_id="acme").all()
result.users        # list[User]
result.invoices     # list[Invoice]
```

Items are discriminated by a reserved `__entity__` attribute written on every item.

### Optimistic locking

```python
from pydynantic import version_attr

class Order(Entity, table=table, name="order"):
    order_id: str
    customer_id: str
    total: float = 0.0
    version: int = version_attr()        # marks the version field

    class Meta:
        primary = key(pk="CUSTOMER#{customer_id}", sk="ORDER#{order_id}")
```

A versioned `put` guards on the previous value automatically; a versioned `update` guards
when you pass `expected_version=` (the value you last read). Either way `version` is
incremented, and a lost race raises `OptimisticLockError`.

## Error handling

All errors derive from `PydynanticError` (raw `ClientError` is never leaked):

```
PydynanticError
├── ItemNotFoundError
├── ConditionCheckFailedError
│   └── OptimisticLockError
├── ValidationError
├── TransactionCanceledError    (.reasons per action)
├── KeyTemplateError
└── MultipleResultsError
```

## Marshalling notes

- Numbers are stored as `Decimal` to avoid floating-point drift.
- `datetime`/`date` are stored as ISO-8601 strings.
- `None` values and empty sets are omitted from items (DynamoDB cannot store them).

## Development

```bash
pip install -e ".[dev]"
pytest                 # unit tests on moto (in-memory DynamoDB)
pytest --cov=pydynantic --cov-report=term-missing
mypy                   # strict
ruff check .
```

## Scope

In scope (v1): single-table modelling, keys, CRUD, queries, filters/conditions,
pagination, batch, transactions, collections, optimistic locking. Synchronous only.

Out of scope: table/infra provisioning (use CDK/Terraform), data migrations,
multi-table joins, async (planned for v2 on `aioboto3`).

## License

MIT © Robert Ruben
