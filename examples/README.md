# pydynantic examples

Runnable, end-to-end examples of using `pydynantic` to model many entities in a
single DynamoDB table.

## `saas_app.py` — a multi-tenant SaaS data model

A self-contained walkthrough that models four entities (`Org`, `User`,
`Project`, `Membership`) in one physical table and exercises the whole public
API:

- a `Table` + entities defined with **key templates** and a **GSI**;
- **CRUD** — `put` / `get` / `update` / `delete`;
- a **query by primary key** and a **query by GSI** (`by_email`);
- a **filter expression** with `F(...)`;
- **cursor pagination** with `.page(cursor=...)`;
- **batch** write + batch get;
- an atomic **transaction** (`with transaction(table) as tx: ...`);
- a **collection query** over a single org partition;
- **optimistic locking** with `version_attr()` plus **auto-timestamps**
  (`created_at_attr` / `updated_at_attr`);
- a **conditional, create-only put** with `attr_not_exists`.

It needs **no AWS credentials**: everything runs against
[`moto`](https://github.com/getmoto/moto)'s in-memory DynamoDB (`mock_aws`),
which ships as a dev dependency.

### Run it

From the repository root:

```bash
pip install -e ".[dev]"
python examples/saas_app.py
```

The script prints what it does at each step and finishes with a success line.
