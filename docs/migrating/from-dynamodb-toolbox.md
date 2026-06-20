# Migrating from DynamoDB-Toolbox

[DynamoDB-Toolbox](https://www.dynamodbtoolbox.com/) is a popular JavaScript single-table
toolkit built around a `Table` plus `Entity` definitions and command objects.
`pydynantic` offers the same model in Python on Pydantic v2.

## Concept mapping

| DynamoDB-Toolbox | pydynantic |
| --- | --- |
| `new Table({ name, partitionKey, sortKey, indexes })` | [`Table`][pydynantic.Table] |
| `new Entity({ schema, ... })` | subclass [`Entity`][pydynantic.Entity] |
| `schema({ attr: string() })` | Pydantic fields |
| `.key()` computed partition/sort | `key(pk="...", sk="...")` templates |
| `PutItemCommand` / `entity.build(PutItem).send()` | [`Entity.put(...)`][pydynantic.Entity.put] |
| `GetItemCommand` | [`Entity.get(...)`][pydynantic.Entity.get] |
| `UpdateItemCommand` (`$add`, `$remove`) | [`Entity.update(add=..., remove=...)`][pydynantic.Entity.update] |
| `QueryCommand` (`{ index, ... }`) | named `Entity.query.<pattern>(...)` |
| `condition: { attr, eq }` | `condition=F("attr") == ...` |
| `BatchGetCommand` / `BatchWriteCommand` | [`batch_get`][pydynantic.Entity.batch_get] / [`batch_write`][pydynantic.Entity.batch_write] |
| `executeTransactWrite([...])` | [`transaction(table)`][pydynantic.transaction] |

## Table & entity

=== "DynamoDB-Toolbox (JS)"

    ```javascript
    import { Table, Entity, schema, string, number } from "dynamodb-toolbox";

    const table = new Table({
      name: "app-prod",
      partitionKey: { name: "PK", type: "string" },
      sortKey: { name: "SK", type: "string" },
      indexes: { GSI1: { type: "global", partitionKey: { name: "GSI1PK", type: "string" },
                         sortKey: { name: "GSI1SK", type: "string" } } },
      documentClient,
    });

    const User = new Entity({
      name: "user",
      table,
      schema: schema({
        userId: string().key(),
        orgId:  string().key(),
        email:  string(),
        name:   string(),
        status: string().default("active"),
        loginCount: number().default(0),
      }),
      computeKey: ({ orgId, userId }) => ({ PK: `ORG#${orgId}`, SK: `USER#${userId}` }),
    });
    ```

=== "pydynantic (Python)"

    ```python
    import boto3
    from pydynantic import Table, Entity, key

    table = Table(
        name="app-prod",
        pk="PK", sk="SK",
        indexes={"GSI1": {"pk": "GSI1PK", "sk": "GSI1SK"}},
        client=boto3.client("dynamodb"),
    )

    class User(Entity, table=table, name="user"):
        user_id: str
        org_id: str
        email: str
        name: str
        status: str = "active"
        login_count: int = 0

        class Meta:
            primary = key(pk="ORG#{org_id}", sk="USER#{user_id}")
            by_email = key(index="GSI1", pk="EMAIL#{email}", sk="USER#{user_id}")
    ```

## CRUD

=== "DynamoDB-Toolbox (JS)"

    ```javascript
    await User.build(PutItemCommand)
      .item({ userId: "u1", orgId: "acme", email: "a@x.com", name: "Ana" })
      .send();

    const { Item } = await User.build(GetItemCommand)
      .key({ orgId: "acme", userId: "u1" }).send();

    await User.build(UpdateItemCommand)
      .item({ orgId: "acme", userId: "u1", name: "Ana B.", loginCount: $add(1) })
      .send();

    await User.build(DeleteItemCommand)
      .key({ orgId: "acme", userId: "u1" }).send();
    ```

=== "pydynantic (Python)"

    ```python
    User.put(User(user_id="u1", org_id="acme", email="a@x.com", name="Ana"))

    user = User.get(org_id="acme", user_id="u1")

    User.update(
        org_id="acme", user_id="u1",
        set={"name": "Ana B."},
        add={"login_count": 1},
    )

    User.delete(org_id="acme", user_id="u1")
    ```

## Queries & transactions

=== "DynamoDB-Toolbox (JS)"

    ```javascript
    const { Items } = await table.build(QueryCommand)
      .query({ partition: "ORG#acme", range: { beginsWith: "USER#" } })
      .entities(User)
      .send();

    await table.build(TransactWriteCommand)
      .commands([
        User.build(UpdateTransaction).item({ orgId: "acme", userId: "u1", orders: $add(1) }),
        Order.build(PutTransaction).item({ ... }),
      ])
      .send();
    ```

=== "pydynantic (Python)"

    ```python
    users = User.query.primary(org_id="acme").begins_with("USER#").all()

    from pydynantic import transaction
    with transaction(table) as tx:
        tx.update(User, key=("acme", "u1"), add={"orders": 1})
        tx.put(Order(order_id="o1", customer_id="acme", total=10.0))
    ```

## What's different

- **No command builders.** Where DynamoDB-Toolbox builds a `*Command` and calls `.send()`,
  `pydynantic` exposes plain classmethods (`put`, `get`, `update`, `delete`) and a query
  builder whose terminals run immediately.
- **Synchronous.** No promises/`await`; results return directly.
- **Pydantic schema.** Field types, defaults and nested models are standard Pydantic v2.
- **Named access patterns.** Instead of passing `{ index }` to a `QueryCommand`, each key
  in `Meta` becomes a typed method on `Entity.query` (see [Queries](../guide/queries.md)).
- **Cross-entity reads** use a [`Collection`][pydynantic.Collection]
  ([Collections](../guide/collections.md)) rather than `.entities(A, B)` on a query.
