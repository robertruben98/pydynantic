# Migrating from ElectroDB

[ElectroDB](https://electrodb.dev/) is the JavaScript/TypeScript single-table library
many teams reach for. `pydynantic` covers the same ground in Python on Pydantic v2. The
concepts map closely; the syntax is Pythonic.

## Concept mapping

| ElectroDB | pydynantic |
| --- | --- |
| `new Entity({...})` | subclass [`Entity`][pydynantic.Entity] |
| `new Service({...})` | a [`Collection`][pydynantic.Collection] (multi-entity partition reads) |
| `attributes: { ... }` | Pydantic fields on the class |
| `indexes: { primary: {...} }` | `key(...)` in inner `Meta` |
| composite `pk`/`sk` `template` | `key(pk="...", sk="...")` templates |
| secondary `index: "gsi1pk-..."` | `key(index="GSI1", ...)` |
| `entity.get({...}).go()` | [`Entity.get(...)`][pydynantic.Entity.get] |
| `entity.put({...}).go()` | [`Entity.put(...)`][pydynantic.Entity.put] |
| `entity.update({...}).set({...}).go()` | [`Entity.update(set=...)`][pydynantic.Entity.update] |
| `entity.query.byX({...}).go()` | `Entity.query.by_x(...)` |
| `.where(({attr}, {eq}) => ...)` | `.filter(F("attr") == ...)` |
| `{ cursor }` on `.go()` | [`.page(cursor=...)`][pydynantic.Page] |
| `add`/`subtract` in update | `add={...}` (negative delta to subtract) |

## Defining an entity

=== "ElectroDB (JS)"

    ```javascript
    import { Entity } from "electrodb";

    const User = new Entity({
      model: { entity: "user", version: "1", service: "app" },
      attributes: {
        userId: { type: "string" },
        orgId:  { type: "string" },
        email:  { type: "string" },
        name:   { type: "string" },
        status: { type: "string", default: "active" },
      },
      indexes: {
        primary: {
          pk: { field: "PK", composite: ["orgId"], template: "ORG#${orgId}" },
          sk: { field: "SK", composite: ["userId"], template: "USER#${userId}" },
        },
        byEmail: {
          index: "GSI1",
          pk: { field: "GSI1PK", composite: ["email"], template: "EMAIL#${email}" },
          sk: { field: "GSI1SK", composite: ["userId"], template: "USER#${userId}" },
        },
      },
    }, { client, table: "app-prod" });
    ```

=== "pydynantic (Python)"

    ```python
    from pydynantic import Entity, key

    class User(Entity, table=table, name="user"):
        user_id: str
        org_id: str
        email: str
        name: str
        status: str = "active"

        class Meta:
            primary = key(pk="ORG#{org_id}", sk="USER#{user_id}")
            by_email = key(index="GSI1", pk="EMAIL#{email}", sk="USER#{user_id}")
    ```

## CRUD

=== "ElectroDB (JS)"

    ```javascript
    await User.put({ userId: "u1", orgId: "acme", email: "a@x.com", name: "Ana" }).go();

    const { data } = await User.get({ orgId: "acme", userId: "u1" }).go();

    await User.update({ orgId: "acme", userId: "u1" })
      .set({ name: "Ana B.", status: "inactive" })
      .add({ loginCount: 1 })
      .go();

    await User.delete({ orgId: "acme", userId: "u1" }).go();
    ```

=== "pydynantic (Python)"

    ```python
    User.put(User(user_id="u1", org_id="acme", email="a@x.com", name="Ana"))

    user = User.get(org_id="acme", user_id="u1")     # -> User | None

    User.update(
        org_id="acme", user_id="u1",
        set={"name": "Ana B.", "status": "inactive"},
        add={"login_count": 1},
    )

    User.delete(org_id="acme", user_id="u1")
    ```

## Queries & filters

=== "ElectroDB (JS)"

    ```javascript
    const { data } = await User.query
      .primary({ orgId: "acme" })
      .where(({ status }, { eq }) => eq(status, "active"))
      .go({ limit: 50 });

    const { data: byEmail } = await User.query.byEmail({ email: "a@x.com" }).go();
    ```

=== "pydynantic (Python)"

    ```python
    from pydynantic import F

    users = (User.query.primary(org_id="acme")
                       .filter(F("status") == "active")
                       .limit(50)
                       .all())

    user = User.query.by_email(email="a@x.com").one_or_none()
    ```

## What's different

- **No `.go()` / no async.** `pydynantic` is synchronous; terminals like `.all()`,
  `.one()`, `.page()` execute immediately. (Async is planned for a future major version.)
- **Validation is Pydantic.** Types, defaults, and nested models come from Pydantic v2
  instead of ElectroDB's attribute schema.
- **You inject the boto3 client** on the [`Table`][pydynantic.Table]; the library never
  opens connections.
- **Services → Collections.** ElectroDB's `Service` for cross-entity queries maps to a
  [`Collection`][pydynantic.Collection]. See [Collections](../guide/collections.md).
- **No infra provisioning.** Like ElectroDB, table creation is out of scope — use
  CDK/Terraform.
